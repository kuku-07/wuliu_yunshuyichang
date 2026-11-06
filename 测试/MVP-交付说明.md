# MVP 交付说明

> 对应交付要求：① 问答助手归档；② MVP 项目需包含工程架构、Agent 框架、知识库，以及至少 3 处人工确认 / 审核点。
> 本文给出每一项的落点、代码路径与演示方式。

---

## 一、交付物清单

| 交付物 | 位置 | 说明 |
| --- | --- | --- |
| 问答助手（归档） | `archive/qa_assistant/` | 阶段 1 单文件 CLI，冻结但可运行；被 `agent_core` 复用检索/闸门/护栏 |
| MVP 工程 | `admin_app/` | FastAPI + Jinja2 + SQLite，含员工端、管理端、客户门户、机器接入 |
| Agent 框架 | `admin_app/agent/framework.py` | Tool / Registry / Context / Trace / Pipeline |
| 知识库 | `admin_app/routers/kb.py`、`admin_app/services/agent_core.py` | 文档版本、审批发布、切片、线路隔离检索、引用 |
| 人工确认点 | 见第五节 | 5 处，其中 Agent 流水线内 3 处 |
| 演示脚本 | `scripts/agent_demo.py` | 打印 Agent 每一步工具、耗时、是否需要人工确认 |

---

## 二、工程架构

### 2.1 四层

| 层 | 组成 | 职责 |
| --- | --- | --- |
| 入口层 | `/agent` 员工端、`/admin` 管理端、`/portal` 客户/承运商 | 页面、SSE 流、登录与跳转 |
| 服务层 | `admin_app/routers/` + `deps.py` + `security.py` | HTTP 接口、鉴权、CSRF、限流、审计 |
| Agent 编排层 | `admin_app/agent/` + `services/draft.py` + `services/chat_service.py` | 工具流水线、证据、生成、护栏 |
| 数据层 | `admin_app/db.py`（SQLite，29 张表）+ 规则切片 + 审计 | 持久化、版本、快照、引用 |

### 2.2 目录（节选）

```
wuliu_yunshuyichang/
├── admin_app/
│   ├── main.py                 # FastAPI 入口
│   ├── agent/
│   │   └── framework.py        # ★ Agent 框架：Tool / Pipeline / Trace
│   ├── routers/                # 接口层：auth/chat/kb/exceptions/workbench/audit...
│   ├── services/
│   │   ├── agent_core.py       # 检索、红线闸门、护栏（复用归档 CLI）
│   │   ├── draft.py            # ★ 草稿 Agent：7 步流水线
│   │   ├── chat_service.py     # 问答 SSE 编排
│   │   ├── kb.py / tms.py / alerts.py / metrics.py ...
│   ├── templates/              # Jinja2 页面
│   └── static/
├── archive/qa_assistant/       # 归档：阶段 1 问答助手
├── samples/tms/                # 脱敏查单与异常样本
├── scripts/                    # 冒烟测试、Agent 演示
└── docs/
```

### 2.3 请求链路

```
浏览器/CLI
  → 入口层（登录态 + CSRF）
  → 服务层（角色权限 + 线路/运单授权）
  → Agent 编排层（闸门 → 检索/证据 → 模型 → 护栏）
  → 数据层（落库 + 审计 + 引用）
  → SSE：meta → status → delta → citations → done/error
```

---

## 三、Agent 框架

### 3.1 组件

| 组件 | 作用 |
| --- | --- |
| `Tool` | 一个可执行步骤，带名称、说明、`requires_human` 标记 |
| `ToolRegistry` | 工具注册表，按名字取用，便于替换与测试 |
| `AgentContext` | 一次运行的状态：连接、用户、入参、中间结果、trace、blocked |
| `AgentPipeline` | 按固定顺序执行工具；遇 `block()` 立即停止 |
| `trace` | 每步记录工具名、耗时、是否人工确认、是否中断 |

设计取舍：**不把工具暴露给模型自由调用**。顺序固定、每步可审计，模型只负责生成，不掌握权限；出现红线或需要人工时立即停止。

### 3.2 已接入的生产路径：查单草稿

`admin_app/services/draft.py::generate_with_trace()` 用框架跑 7 步：

| 步骤 | 工具 | 人工确认 | 说明 |
| --- | --- | --- | --- |
| 1 | `validate` | - | 校验处理场景（查单 / 催单） |
| 2 | `circuit` | - | 误报率熔断检查 |
| 3 | `evidence` | - | 加载运单、子单、轨迹、异常、快照 |
| 4 | `stop_guard` | ✅ | GPS 弱网 / 改地址 / 回执延迟 → 停止自动建议 |
| 5 | `redline` | ✅ | 赔付 / 危险品 / 事故 / 判责 → 转人工接管 |
| 6 | `generate` | - | 调用模型生成草稿（不承诺时效金额） |
| 7 | `persist` | ✅ | 落库为 `pending_review`，等待人工审核 |

### 3.3 演示

```powershell
python scripts/agent_demo.py YD20261030001
```

输出示例：

```
#  工具            人工确认            耗时  说明
1  validate      -             0.0ms  校验处理场景参数
2  circuit       -             0.1ms  误报率熔断检查
3  evidence      -             2.7ms  加载运单与异常证据包
4  stop_guard    是             5.1ms  停止自动建议场景检查
    └─ 在此停止：stop_guard
结果：成功　已停止自动建议（轨迹超过 2 小时未刷新），请人工接手
本次涉及人工确认点：stop_guard
```

普通运单会跑满 7 步，`persist` 产出 `pending_review` 草稿，等待人工审核。

### 3.4 扩展方式

新增一个步骤：实现 `def handler(ctx)`，注册 `Tool("name", handler, "说明", requires_human=...)`，加入 `AgentPipeline` 的 step 列表即可；不需要改框架。

---

## 四、知识库

### 4.1 数据模型

| 表 | 作用 |
| --- | --- |
| `kb_documents` | 文档主表：标题、线路、状态、当前版本 |
| `kb_document_versions` | 版本与审批记录 |
| `kb_chunks` | 切片：章节、正文、`is_active`、`embedding_ref` |

### 4.2 生命周期

```
上传（上传即脱敏 + 注入清洗）
  → 生成草稿版本（draft）
  → 提交审核（pending）
  → 批准（approved）
  → 发布（active，旧版本下线）
  → 下线（offline）
```

发布后 5 分钟内新会话引用新版本；锁定安全段不可修改。

### 4.3 检索与引用

- 只检索本线路、`is_active=1` 的切片，**不跨线回退**；
- 回答携带引用：来源文档、版本、章节、数据时间；
- 引用落 `citations`，规则更新后仍可追溯。

代码：`admin_app/services/agent_core.py`（检索/闸门/护栏）、`admin_app/routers/kb.py`（上传/审批/发布）。

---

## 五、人工确认 / 审核点（5 处）

| 编号 | 名称 | 触发 | 系统位置 | 留痕 | 演示 |
| --- | --- | --- | --- | --- | --- |
| H1 | 规则发布审批 | 规则文档提交后 | `POST /admin/kb/{id}/submit-review` → `approve` → `publish` | 版本记录 + 审计 + 发布人 | 上传规则 → 提交 → 批准 → 发布 |
| H2 | 停止建议 / 红线接管 | 改地址、GPS 弱网、回执延迟、赔付、危险品、事故、判责 | `draft.py` 的 `stop_guard` / `redline`；聊天闸门 | 草稿状态 `stopped`/`taken_over` + 接手人/原因/时间 | `agent_demo.py YD20261030001` |
| H3 | 草稿审核 | 草稿生成后 | `POST /admin/workbench/{id}/review` | 审核人、修正原因、备注、时间 | 工作台审核通过/退回 |
| H4 | 外发登记 | 审核通过后 | `POST /admin/workbench/{id}/sent` | 渠道、时间、登记人 | 审核通过 → 登记已发出 |
| H5 | 留存清理审批 | 90 天数据清理申请 | `POST /admin/metrics/retention/{id}/approve` | 申请人、审批人、清理结果 | 申请 → 合规审批 → 执行 |

其中 **H2、H3、H4 直接位于 Agent 产出链路**，满足“至少 3 处人工确认或审核点”的要求。

---

## 六、联网演示路径（约 10 分钟）

1. `archive/qa_assistant/phase1_cli.py --selftest`：证明归档的问答助手仍可运行。
2. `python scripts/agent_demo.py YD20261030001`：展示 Agent 流水线与人工确认点。
3. 员工端 `/login` → `/agent`：规则问答带引用；赔付问题转人工。
4. 管理端 `/admin/kb`：上传规则 → 提交 → 批准 → 发布；回员工端复问，引用版本变化。
5. `/admin/exceptions`：导入样本 → 自动路由 → 受理/转交/关闭。
6. `/admin/workbench`：证据包 → 生成草稿 → 审核 → 登记外发。
7. `/admin/audit` 与 `/admin/metrics`：引用、闸门、护栏、请求 ID；首响与误报指标。

---

## 七、运行与测试

```powershell
$env:PYTHONPATH="D:\Lib\site-packages;$PWD"
.\run_admin.ps1                      # http://127.0.0.1:8088
python scripts\agent_demo.py YD20261030001
python scripts\smoke_mainline.py     # 18 项
```

九套冒烟测试共 162 项，覆盖聊天契约、越权、幂等、注入、熔断、留存审批等。

---

## 八、边界

- 问答助手已归档，不再新增功能；新功能只进 `admin_app/`。
- TMS 目前为脱敏样本 + 只读 HTTP 客户端，缺真实联调。
- 15 分钟首响是业务目标，需要试点验证；系统提供计时、升级与指标。
