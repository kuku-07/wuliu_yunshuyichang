# 归档：阶段 1 问答助手

本目录存放项目早期的「单文件问答助手」，已被 `admin_app/` 的 MVP 取代，仅作归档保留。

## 为什么保留

`admin_app/services/agent_core.py` 仍在复用这里的检索、红线闸门与护栏实现：

- `HybridRetriever`：本地混合检索（分词 + 词频/字符相似）
- `redline_gate`：红线拦截
- `check_output`：输出护栏
- `OfflineExtractiveLLM`：无模型 Key 时的离线兜底

因此**不要删除**，它仍是 MVP 的底层依赖；但新功能不要再写进这里。

## 目录

```
archive/qa_assistant/
├── phase1_cli.py          # 单文件 CLI：切片 → 检索 → 闸门 → LLM → 护栏
└── data/policy_sample.md  # 带版本与生效日期的规则样例
```

## 运行

```powershell
$env:PYTHONPATH="D:\Lib\site-packages;$PWD"
python archive\qa_assistant\phase1_cli.py --selftest
python archive\qa_assistant\phase1_cli.py
```

## 状态

- 冻结：不再新增功能。
- 依赖：`admin_app/services/agent_core.py` 按路径加载 `phase1_cli.py`。
- 替代：员工端 `/agent`、管理端 `/admin/*`。
