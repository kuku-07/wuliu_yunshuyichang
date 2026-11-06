"""生成《运输异常协作智能体系统 · 项目设计方案（阶段 0）》docx。

结构对应两份提示词：
提示词 1：需求分析（10 问 + 一页纸清单）
提示词 2：架构选型（四层架构、目录、库表、第一周验证）
内容全部套到运输异常协作项目，不写报销助手。
"""
from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

OUT = Path(r"D:\wuliu_yunshuyichang\docs\运输异常协作系统-项目设计方案.docx")

NAVY = RGBColor(0x1F, 0x38, 0x64)
GRAY = RGBColor(0x59, 0x59, 0x59)
HEAD_FILL = "E8EEF7"


def set_font(run, name="宋体", size=None, bold=None, color=None):
    run.font.name = name
    run._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), name)
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.font.bold = bold
    if color is not None:
        run.font.color.rgb = color


def apply_styles(doc):
    normal = doc.styles["Normal"]
    normal.font.name = "宋体"
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    normal.font.size = Pt(10.5)
    normal.paragraph_format.line_spacing = 1.5
    normal.paragraph_format.space_after = Pt(4)

    for name, size in (("Heading 1", 15), ("Heading 2", 12), ("Heading 3", 11)):
        style = doc.styles[name]
        style.font.name = "微软雅黑"
        style._element.rPr.rFonts.set(qn("w:eastAsia"), "微软雅黑")
        style.font.size = Pt(size)
        style.font.bold = True
        style.font.color.rgb = NAVY
        style.paragraph_format.space_before = Pt(12 if name == "Heading 1" else 9)
        style.paragraph_format.space_after = Pt(5)
        style.paragraph_format.keep_with_next = True

    section = doc.sections[0]
    section.page_width = Cm(21)
    section.page_height = Cm(29.7)
    section.top_margin = Cm(2.0)
    section.bottom_margin = Cm(1.8)
    section.left_margin = Cm(2.2)
    section.right_margin = Cm(2.0)


def add_page_number(section):
    paragraph = section.footer.paragraphs[0]
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = paragraph.add_run()
    set_font(run, "微软雅黑", 9, color=GRAY)
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = " PAGE "
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run._r.append(begin)
    run._r.append(instr)
    run._r.append(end)


def shade(cell, color):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), color)
    tc_pr.append(shd)


def cell_text(cell, text, size=8.5, bold=False, align=WD_ALIGN_PARAGRAPH.LEFT, color=None):
    cell.text = ""
    paragraph = cell.paragraphs[0]
    paragraph.alignment = align
    paragraph.paragraph_format.line_spacing = 1.08
    paragraph.paragraph_format.space_after = Pt(1)
    run = paragraph.add_run(str(text))
    set_font(run, "宋体", size, bold=bold, color=color)


def table(doc, headers, rows, widths=None, size=8.5):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False
    layout = OxmlElement("w:tblLayout")
    layout.set(qn("w:type"), "fixed")
    t._tbl.tblPr.append(layout)

    header = t.rows[0]
    tr_pr = header._tr.get_or_add_trPr()
    repeat = OxmlElement("w:tblHeader")
    repeat.set(qn("w:val"), "true")
    tr_pr.append(repeat)
    for i, text in enumerate(headers):
        cell_text(header.cells[i], text, size, bold=True,
                  align=WD_ALIGN_PARAGRAPH.CENTER, color=NAVY)
        shade(header.cells[i], HEAD_FILL)

    for row in rows:
        cells = t.add_row().cells
        for i, text in enumerate(row):
            cell_text(cells[i], text, size)

    if widths:
        total = sum(widths)
        if total > 16.4:
            widths = [w * 16.4 / total for w in widths]
        for i, width in enumerate(widths):
            t.columns[i].width = Cm(width)
        for row in t.rows:
            for i, width in enumerate(widths):
                row.cells[i].width = Cm(width)
    return t


def caption(doc, text):
    paragraph = doc.add_paragraph()
    paragraph.paragraph_format.space_before = Pt(7)
    paragraph.paragraph_format.space_after = Pt(3)
    paragraph.paragraph_format.keep_with_next = True
    run = paragraph.add_run(text)
    set_font(run, "微软雅黑", 9, bold=True, color=GRAY)


def p(doc, text, indent=True, size=10.5, bold=False, color=None):
    paragraph = doc.add_paragraph()
    if indent:
        paragraph.paragraph_format.first_line_indent = Cm(0.74)
    run = paragraph.add_run(text)
    set_font(run, "宋体", size, bold=bold, color=color)


def bullets(doc, items):
    for item in items:
        paragraph = doc.add_paragraph(style="List Bullet")
        paragraph.paragraph_format.line_spacing = 1.35
        run = paragraph.add_run(item)
        set_font(run, "宋体", 10)


def h1(doc, text):
    doc.add_heading(text, level=1)


def h2(doc, text):
    doc.add_heading(text, level=2)


QUESTIONS = [
    {
        "no": "Q1",
        "dim": "异常类型与数据来源",
        "q": "异常事件从哪里来：只接 TMS 导出，还是同时接 GPS 与 IM？是否需要人工补录？",
        "why": "决定接入层复杂度、归一规则、实时性与修复成本",
        "diff": "只接 TMS：批量导入即可；加 GPS/IM：需推送接口、去重与四要素归一；再加人工：需修复队列与权限",
        "answers": [
            ("只接 TMS 导出（每日/每小时）", "接入简单、成本低；异常发现滞后，只能做事后统计与查单"),
            ("TMS 只读 + GPS + IM 推送", "需要接入网关、幂等去重、四要素归一；可做实时预警与证据化查单"),
            ("全渠道 + 司机手工上报", "需极简上报端与修复队列；数据质量依赖现场习惯，培训成本高"),
        ],
        "pick": "一期采用「TMS 只读 + GPS/IM 推送 + 人工补录兜底」；司机端只保留安全停车后 1–2 个动作的极简入口，不做复杂表单。",
    },
    {
        "no": "Q2",
        "dim": "运输规则与时效标准",
        "q": "规则是全网一套，还是分线路/客户多版本？15 分钟和 30 分钟是什么关系？",
        "why": "决定知识库结构、检索隔离方式与指标分母",
        "diff": "单一制度：单库单版本；分线路多版本：文档带 scope + 版本 + 发布；客户自定义 SLA：需多租户与规则引擎",
        "answers": [
            ("全网一套规则", "知识库最简单；但不同线路口径冲突时会给出错误答案"),
            ("分线路多版本 + 版本化发布", "需文档 scope、版本表、审批发布与检索隔离；答案可追到版本"),
            ("客户自定义 SLA + 规则引擎", "灵活但复杂度高；需要规则配置、测试与回滚机制"),
        ],
        "pick": "一期分线路多版本：文档带线路范围与版本，检索不跨线回退；到货与回执分开统计；15 分钟是业务目标，30 分钟是超时升级的硬性时限。",
    },
    {
        "no": "Q3",
        "dim": "处置流程与权限",
        "q": "异常处置在系统内完成，还是继续在群里？谁受理、谁升级、谁关闭？",
        "why": "决定角色模型、事件状态机、通知与审计",
        "diff": "群聊人工：系统只做看板；系统内受理/转交/关闭：需状态机 + 通知 + 升级；多级审批：需审批流引擎",
        "answers": [
            ("继续群聊，系统只记录结果", "改造最小；但责任无法追溯，二次往返依旧"),
            ("系统内受理/转交/关闭 + 超时升级", "需具名责任人、状态机、通知与升级规则；可度量首响"),
            ("多级审批 + 会签", "适合高金额赔付；流程重、上线慢，不适合一期全量"),
        ],
        "pick": "一期做「受理 → 转交 → 关闭」三态 + 30 分钟未受理升级；赔付等高金额场景走人工线下审批，系统只留痕，不做多级审批引擎。",
    },
    {
        "no": "Q4",
        "dim": "员工/管理员身份源",
        "q": "账号从 HR/SSO 同步，还是本地建号？角色和线路范围怎么来？",
        "why": "决定认证方式、角色映射与线路授权模型",
        "diff": "本地账号：用户表 + JWT；HR/SSO：OIDC/SAML 对接；企业微信：扫码登录 + 通讯录同步",
        "answers": [
            ("本地账号 + 管理员维护", "上线快；离职账号需人工清理，适合试点"),
            ("对接企业 OIDC/SSO", "统一身份、自动停用；需要 IdP 配合与回调调试"),
            ("企业微信/钉钉扫码", "一线体验好；需要应用授权、通讯录权限与免登"),
        ],
        "pick": "一期本地账号 + 角色 + 线路范围，预留 OIDC 接口；账号、角色、线路范围由系统管理员维护，登录走 Cookie 会话 + CSRF。",
    },
    {
        "no": "Q5",
        "dim": "部署方案与数据合规",
        "q": "公有云 SaaS、客户私有化，还是混合部署？数据能不能出客户网络？",
        "why": "决定数据库、文件存储、密钥、备份与多租户方案",
        "diff": "SaaS：多租户 + 对象存储 + 统一运维；私有化：单机/容器 + 本地盘；混合：数据分级路由 + 双部署",
        "answers": [
            ("公有云 SaaS", "运维简单、按租户隔离；客户对运单与客户信息出网有顾虑"),
            ("客户私有化/单机", "数据不出域、易过合规；升级与运维成本由项目承担"),
            ("混合：敏感本地、非敏感云端", "兼顾成本与合规；架构复杂，需要数据分级与路由"),
        ],
        "pick": "一期私有化单机部署（SQLite WAL，可迁移 PostgreSQL），文件本地存储；敏感字段脱敏后才进模型；预留对象存储与多租户改造点。",
    },
    {
        "no": "Q6",
        "dim": "LLM 供应商与数据出境",
        "q": "用公有云大模型 API，还是本地 Ollama/vLLM？敏感数据能不能出网？",
        "why": "决定模型客户端抽象、脱敏策略、成本与合规评估",
        "diff": "公有云 API：需出境评估与脱敏；本地模型：需 GPU/显存与并发容量；混合：需路由、降级与一致性",
        "answers": [
            ("公有云 API（OpenAI 兼容）", "效果稳定、按 token 计费；需数据出境评估，敏感字段不能进提示词"),
            ("本地 Ollama/vLLM", "数据不出域；需要 GPU 资源，效果与并发受硬件限制"),
            ("混合路由", "敏感走本地、普通走云端；需要分级、路由与结果一致性校验"),
        ],
        "pick": "模型客户端统一走 OpenAI 兼容接口，默认本地/离线兜底，可配置切换到云端；只发送脱敏后的必要上下文；不做自动出境。",
    },
    {
        "no": "Q7",
        "dim": "知识库维护与更新",
        "q": "规则由谁维护、怎么发布？改了规则多久生效？",
        "why": "决定文档版本、审批流、切片与索引重建、热更新",
        "diff": "Git/Markdown 运维：无后台；后台上传-审批-发布：需版本表与角色；自动同步制度系统：需接口与冲突处理",
        "answers": [
            ("Git/Markdown + 运维发布", "可审计、成本低；业务方无法自助修改"),
            ("后台上传-提交-批准-发布", "业务可自助；需要版本、审批与回滚，发布后分钟级生效"),
            ("对接制度系统自动同步", "减少人工；接口与字段映射复杂，冲突处理难"),
        ],
        "pick": "一期后台上传 → 提交 → 批准 → 发布，发布后 5 分钟内生效；锁定安全段不可改；保留版本与下线能力，不做自动同步。",
    },
    {
        "no": "Q8",
        "dim": "对话审计与留痕",
        "q": "审计要记到什么程度？留存多久？能不能导出？",
        "why": "决定审计表结构、append-only 策略、脱敏与导出方案",
        "diff": "只存消息：无法追责；消息+引用+闸门+请求ID：可追溯；全链路+哈希+导出：可审计、可举证",
        "answers": [
            ("只存会话消息", "实现简单；无法证明答案依据与是否越权"),
            ("消息 + 引用 + 闸门 + 请求 ID", "可还原一次回答；满足大多数内部审计"),
            ("全链路 + 前后哈希 + 导出", "可举证、可追责；存储与脱敏成本更高"),
        ],
        "pick": "一期全链路留痕：消息、引用、闸门、护栏、请求 ID，关键写操作记录变更前后哈希；90 天留存，清理需合规审批；导出异步且带请求 ID。",
    },
    {
        "no": "Q9",
        "dim": "并发量与成本预算",
        "q": "试点多少人同时用？每天多少票？模型成本按什么口径核算？",
        "why": "决定部署形态、模型选型、限流、缓存与队列",
        "diff": "10–20 并发：单机足够；100 并发：多副本 + 队列；千级：多租户 + 弹性伸缩",
        "answers": [
            ("试点 10–20 并发", "单机 FastAPI + SQLite 可支撑；限流按人控制"),
            ("部门级 100 并发", "需要多副本、共享数据库、任务队列与缓存"),
            ("全公司千级", "需要多租户、弹性伸缩、模型配额与成本中心"),
        ],
        "pick": "一期按 10–20 并发设计：单机部署、单用户 10 次/分钟限流；成本按“票”核算（每票问答与草稿的 token 折算），后续再扩。",
    },
    {
        "no": "Q10",
        "dim": "失败兜底与人工介入",
        "q": "模型超时、答错、越权时怎么办？什么情况必须转人工？",
        "why": "决定错误码、降级策略、接管记录与熔断机制",
        "diff": "报错即止：体验差；降级抽取：可用但需标注；闸门+接管+熔断：可控但需产品设计",
        "answers": [
            ("出错直接报错", "实现最简单；一线会放弃使用"),
            ("降级为离线抽取并明确标注", "可用性提升；需要标注“未经模型生成”"),
            ("闸门 + 接管 + 熔断", "红线不调模型、失败可接管、误报高自动停；需要状态与审计支撑"),
        ],
        "pick": "一期采用第三种的简化版：红线闸门（赔付/危险品/事故/判责不调模型）+ 模型失败降级并标注 + 接管留接手人/原因/时间 + 误报率连续超 10% 暂停草稿生成。",
    },
]

ONE_PAGE = [
    ("目标用户与角色", "一线客服/调度（问答、查单、处置异常）、客服主管（审核草稿、处理升级）、合规审计（只读审计）、系统管理员（规则、账号、线路、数据）、客户/承运商（只读门户）。"),
    ("核心场景", "规则问答带引用；一票货查单；异常受理/转交/关闭；查单与催单草稿；异常预警；审计与指标复盘。"),
    ("功能范围", "多源接入、四要素归一、自动路由、受理/转交/关闭、超时升级、预警、规则知识库、检索与引用、红线闸门、草稿生成与审核、外发登记、审计与导出、留存审批、权限、双入口、指标。"),
    ("非功能需求", "首字 P95 ≤2 秒；SSE 心跳与 8 秒提示；单用户 10 次/分钟限流；模型故障可降级；审计可追溯；Chrome/Edge 兼容。"),
    ("技术约束", "FastAPI + Python 3.11+；SQLite 试点、可迁移 PostgreSQL；LLM 走 OpenAI 兼容接口；TMS 只读，禁止写入。"),
    ("数据与安全", "数据分三级；PII 脱敏；JWT + CSRF；线路/运单授权；append-only 审计 + 前后哈希；90 天留存需审批。"),
    ("一期不做", "自动判责/扣罚；自动对外发送；自动修改 TMS；全网跨干线；司机/客户原生 App；多语言与支付。"),
    ("验收标准", "归一率 ≥95%；缺字段 100% 进修复队列；红线模型调用 0 次；引用率 100%；路由覆盖 100%；越权用例 0 通过；误报率 ≤10%；首响指标可复算。"),
]


def part_one(doc):
    h1(doc, "第一部分  需求分析（阶段 0 · 技术选型）")
    h2(doc, "1.1 方法与边界")
    p(doc, "本部分用 10 个问题做技术选型评审。问题覆盖异常来源、规则口径、处置权限、身份、部署与合规、模型、知识库、审计、并发成本、兜底十条线；"
           "每题给出 2–3 种典型答案及其架构影响，最后给出本项目的推荐答案。")
    p(doc, "需要说明：案例材料只完成了一位现场调度员的访谈，其余角色仍是待核实假设；"
           "因此下文的“推荐答案”是基于现有材料的技术判断，不是业务方已确认的结论。")

    h2(doc, "1.2 十个关键问题总表")
    caption(doc, "表 1  关键问题与架构差异")
    table(doc,
          ["编号", "维度", "关键问题", "为什么关键", "不同答案的架构差异"],
          [[q["no"], q["dim"], q["q"], q["why"], q["diff"]] for q in QUESTIONS],
          widths=[1.1, 2.4, 5.0, 3.5, 4.4], size=8)

    h2(doc, "1.3 逐题展开")
    for q in QUESTIONS:
        h2(doc, f"{q['no']}  {q['dim']}")
        p(doc, q["q"], indent=False, bold=True)
        caption(doc, "典型答案与架构影响")
        table(doc, ["典型答案", "架构影响"], q["answers"],
              widths=[4.8, 10.8], size=8.5)
        p(doc, "本项目建议：" + q["pick"], indent=False, bold=False)

    doc.add_page_break()
    h2(doc, "1.4 一页纸需求清单（基于推荐答案，待业务确认）")
    caption(doc, "表 2  一页纸需求清单")
    table(doc, ["项目", "内容"], ONE_PAGE, widths=[3.2, 12.9], size=9)

    h2(doc, "1.5 维度覆盖检查")
    caption(doc, "表 3  十个维度与问题映射")
    table(doc,
          ["维度", "对应问题", "覆盖"],
          [
              ["发票/凭证类（本项目为异常来源）", "Q1 异常类型与数据来源", "是"],
              ["制度/标准类（本项目为运输规则与时效）", "Q2 运输规则与时效标准", "是"],
              ["审批流程与额度（本项目为处置权限与升级）", "Q3 处置流程与权限", "是"],
              ["员工/管理员身份源", "Q4 身份源", "是"],
              ["部署方案与数据合规", "Q5 部署与合规", "是"],
              ["LLM 供应商与数据出境", "Q6 模型与数据出境", "是"],
              ["知识库维护与更新", "Q7 知识库维护", "是"],
              ["对话审计与留痕", "Q8 审计与留痕", "是"],
              ["并发量与成本预算", "Q9 并发与成本", "是"],
              ["失败兜底与人工介入", "Q10 兜底与接管", "是"],
          ],
          widths=[6.2, 8.0, 2.0], size=8.5)


def part_two(doc):
    h1(doc, "第二部分  架构选型（阶段 0 · 架构方案）")
    h2(doc, "2.1 四层架构（文字版）")
    p(doc, "目标架构分四层，职责与边界如下：")
    caption(doc, "表 4  四层架构")
    table(doc,
          ["层", "组成", "职责", "边界"],
          [
              ["入口层", "员工端 /agent、管理端 /admin、客户/承运商 /portal", "页面、SSE 流、登录与跳转", "只做展示与交互，不含业务规则"],
              ["服务层", "FastAPI 路由、鉴权、CSRF、限流、审计中间件", "HTTP 接口、会话、权限、错误码", "不直接写提示词，不直接调模型"],
              ["智能体编排层", "闸门 → 检索 → 证据包 → 模型 → 护栏 → 引用", "理解、检索、生成、校验", "不掌握权限，不做裁决"],
              ["数据模型层", "SQLite/PostgreSQL、规则切片、会话与审计、文件存储", "持久化、索引、快照", "只存结果与证据，不存推断"],
          ],
          widths=[2.4, 6.4, 4.4, 4.0], size=8.5)
    p(doc, "请求链路：入口层 → 鉴权/校验 → 服务层 → 编排层（闸门先于模型）→ 数据层；"
           "返回时先发 meta/status，再发 delta 与 citations，最后 done/error。")

    h2(doc, "2.2 目标架构与第一周最小架构")
    p(doc, "第一周不实现完整编排层，只验证“规则能检索、回答有引用、红线不调模型”三件事。")
    caption(doc, "表 5  目标架构 vs 第一周最小架构")
    table(doc,
          ["能力", "目标架构", "第一周最小架构", "差异原因"],
          [
              ["入口", "员工端 + 管理端 + 门户", "命令行 CLI", "先验证价值，不做界面"],
              ["编排", "闸门 + 检索 + 证据 + 护栏", "闸门 + 检索 + 护栏", "不做证据包与草稿"],
              ["知识库", "上传/审批/发布/版本/切片", "1 份 Markdown 切片入库", "先验证检索质量"],
              ["数据源", "TMS + GPS + IM + 人工", "本地规则文件", "接口未就绪"],
              ["模型", "可切换、本地/云端", "OpenAI 兼容 + 离线兜底", "验证可替换性"],
              ["审计", "全链路 + 哈希 + 导出", "会话与引用落库", "先保证可追溯"],
          ],
          widths=[2.8, 5.4, 4.8, 3.4], size=8.5)

    doc.add_page_break()
    h2(doc, "2.3 推荐目录结构")
    p(doc, "目录按“入口/服务/编排/数据”分层，核心模块可被 CLI 与 Web 复用。")
    tree = """transport-agent/
├── admin_app/
│   ├── main.py              # FastAPI 入口、路由注册、中间件、生命周期
│   ├── config.py            # 环境变量与部署开关
│   ├── db.py                # 建表、迁移、种子数据
│   ├── security.py          # 密码、JWT、脱敏、注入清洗
│   ├── deps.py              # 登录态、角色权限、线路/运单依赖
│   ├── web.py               # 模板上下文、CSRF、错误页
│   ├── routers/             # 接口层（每个文件一个域）
│   │   ├── auth.py  agent.py  chat.py  kb.py  prompts.py
│   │   ├── exceptions.py  workbench.py  metrics.py  audit.py
│   │   ├── lanes.py  shipments.py  grants.py  users.py
│   │   └── ingest.py  todos.py  portal.py  data_admin.py
│   ├── services/            # 编排与领域服务（可复用核心）
│   │   ├── agent_core.py    # ★ 检索、闸门、护栏（CLI 与 Web 共用）
│   │   ├── chat_service.py  # ★ SSE 事件编排、会话
│   │   ├── draft.py         # 查单/催单草稿与审核
│   │   ├── tms.py  routing.py  alerts.py  metrics.py
│   │   ├── snapshots.py  links.py  retention.py  notify.py
│   │   └── users.py  lanes.py  shipments.py  grants.py
│   ├── templates/           # Jinja2 页面
│   └── static/              # CSS/JS
├── prototype/phase1_cli.py  # ★ 第一周 CLI 验证（复用 agent_core）
├── samples/tms/             # 脱敏查单与异常样本
├── scripts/                 # 冒烟测试与数据生成
└── docs/                    # 需求、架构、答辩材料
"""
    box = doc.add_table(rows=1, cols=1)
    box.style = "Table Grid"
    tr_pr = box.rows[0]._tr.get_or_add_trPr()
    cant_split = OxmlElement("w:cantSplit")
    cant_split.set(qn("w:val"), "true")
    tr_pr.append(cant_split)
    cell = box.rows[0].cells[0]
    cell.text = ""
    paragraph = cell.paragraphs[0]
    paragraph.paragraph_format.line_spacing = 1.1
    run = paragraph.add_run(tree)
    set_font(run, "等线", 8.2)

    h2(doc, "2.4 数据库表设计")
    p(doc, "核心 8 张表：用户、会话、消息、规则文档、规则切片、异常事件、查单草稿、引用。"
           "状态字段用字符串枚举，所有表带 created_at，软删除用 status 而不是物理删除。")

    tables = [
        ("表 6  用户表 users", [
            ("id", "TEXT", "是", "主键", "u_ 前缀"),
            ("employee_no", "TEXT", "是", "唯一索引", "登录账号"),
            ("name", "TEXT", "是", "—", "姓名"),
            ("role", "TEXT", "是", "索引", "五种后台角色 + 门户角色"),
            ("lane_scopes", "TEXT", "是", "—", "线路范围 JSON"),
            ("password_hash", "TEXT", "是", "—", "Argon2id"),
            ("status", "TEXT", "是", "—", "active/disabled"),
            ("failed_count", "INTEGER", "是", "—", "失败次数"),
            ("locked_until", "TEXT", "否", "—", "锁定截止"),
            ("created_at", "TEXT", "是", "—", "ISO 时间"),
        ]),
        ("表 7  会话表 sessions", [
            ("id", "TEXT", "是", "主键", "s_ 前缀"),
            ("user_id", "TEXT", "是", "索引(user_id,last_active_at)", "归属用户"),
            ("lane_scope", "TEXT", "是", "索引", "作业干线"),
            ("shipment_no", "TEXT", "否", "—", "最近关联运单"),
            ("title", "TEXT", "否", "—", "首问摘要"),
            ("status", "TEXT", "是", "—", "active/closed"),
            ("created_at", "TEXT", "是", "—", "ISO 时间"),
            ("last_active_at", "TEXT", "是", "索引", "排序用"),
        ]),
        ("表 8  消息表 messages", [
            ("id", "TEXT", "是", "主键", "m_ 前缀"),
            ("session_id", "TEXT", "是", "索引(session_id,created_at)", "所属会话"),
            ("role", "TEXT", "是", "—", "user/assistant"),
            ("content", "TEXT", "是", "—", "脱敏后内容"),
            ("status", "TEXT", "是", "—", "complete/takeover/error"),
            ("intent", "TEXT", "否", "—", "闸门原因码"),
            ("prompt_version", "TEXT", "否", "—", "提示词版本"),
            ("model", "TEXT", "否", "—", "模型标识或“未调用”"),
            ("latency_ms", "INTEGER", "否", "—", "首字/总耗时"),
            ("request_id", "TEXT", "否", "索引", "链路追踪"),
            ("created_at", "TEXT", "是", "索引", "ISO 时间"),
        ]),
        ("表 9  规则文档表 kb_documents", [
            ("id", "TEXT", "是", "主键", "doc_ 前缀"),
            ("title", "TEXT", "是", "—", "文档标题"),
            ("lane_scope", "TEXT", "是", "索引(lane_scope,status)", "适用线路"),
            ("status", "TEXT", "是", "索引", "draft/pending/active/offline"),
            ("current_version", "INTEGER", "是", "—", "当前版本号"),
            ("is_demo", "INTEGER", "是", "—", "演示数据标记"),
            ("created_at", "TEXT", "是", "—", "创建时间"),
            ("updated_at", "TEXT", "是", "—", "更新时间"),
        ]),
        ("表 10  规则切片表 kb_chunks", [
            ("id", "TEXT", "是", "主键", "chk_ 前缀"),
            ("doc_id", "TEXT", "是", "索引(doc_id,version)", "所属文档"),
            ("version", "INTEGER", "是", "索引", "文档版本"),
            ("chunk_no", "INTEGER", "是", "—", "切片序号"),
            ("section", "TEXT", "否", "—", "章节标题"),
            ("text", "TEXT", "是", "—", "切片正文"),
            ("token_count", "INTEGER", "否", "—", "长度"),
            ("is_active", "INTEGER", "是", "索引", "是否生效"),
            ("embedding_ref", "TEXT", "否", "—", "本地向量/引用位"),
            ("created_at", "TEXT", "是", "—", "创建时间"),
        ]),
        ("表 11  异常事件表 exception_events", [
            ("id", "TEXT", "是", "主键", "ev_ 前缀"),
            ("shipment_no", "TEXT", "是", "索引(shipment_no,occurred_at)", "运单号"),
            ("sub_no", "TEXT", "否", "—", "子单号"),
            ("event_type", "TEXT", "是", "索引", "延误/改地址/货损等"),
            ("reason_code", "TEXT", "否", "—", "原因码"),
            ("occurred_at", "TEXT", "是", "索引", "发生时间"),
            ("source", "TEXT", "是", "—", "TMS/GPS/IM/人工"),
            ("handler", "TEXT", "否", "索引", "具名处理人"),
            ("due_at", "TEXT", "否", "索引", "处置截止"),
            ("status", "TEXT", "是", "索引", "normalized/accepted/escalated/closed"),
            ("accepted_at", "TEXT", "否", "—", "受理时间（首响计算）"),
            ("closed_at", "TEXT", "否", "—", "关闭时间"),
            ("return_reason", "TEXT", "否", "—", "退回/拒收原因"),
            ("data_time", "TEXT", "是", "—", "数据时间"),
        ]),
        ("表 12  查单草稿表 drafts", [
            ("id", "TEXT", "是", "主键", "d_ 前缀"),
            ("shipment_no", "TEXT", "是", "索引(shipment_no,created_at)", "关联运单"),
            ("scenario", "TEXT", "是", "—", "query/expedite"),
            ("content", "TEXT", "是", "—", "草稿正文"),
            ("status", "TEXT", "是", "索引", "pending_review/approved/rejected/taken_over/stopped"),
            ("gate_reason", "TEXT", "否", "—", "闸门原因码"),
            ("guardrail", "TEXT", "否", "—", "护栏结果"),
            ("citations_json", "TEXT", "否", "—", "引用快照"),
            ("reviewer_id", "TEXT", "否", "—", "审核人"),
            ("review_reason", "TEXT", "否", "—", "修正原因枚举"),
            ("reviewed_at", "TEXT", "否", "—", "审核时间"),
            ("created_at", "TEXT", "是", "索引", "生成时间"),
        ]),
        ("表 13  引用表 citations", [
            ("id", "TEXT", "是", "主键", "c_ 前缀"),
            ("message_id", "TEXT", "否", "索引", "回答消息"),
            ("draft_id", "TEXT", "否", "索引", "草稿"),
            ("doc_id", "TEXT", "否", "—", "规则文档"),
            ("doc_title", "TEXT", "否", "—", "标题快照"),
            ("version", "TEXT", "否", "—", "规则版本"),
            ("section", "TEXT", "否", "—", "章节"),
            ("chunk_id", "TEXT", "否", "索引", "切片"),
            ("quote", "TEXT", "是", "—", "引用原文"),
            ("data_time", "TEXT", "否", "—", "数据时间"),
        ]),
    ]
    for title, rows in tables:
        caption(doc, title)
        table(doc, ["字段", "类型", "必填", "索引", "说明"], rows,
              widths=[3.4, 2.2, 1.4, 4.6, 4.4], size=8)

    h2(doc, "2.5 实体关系说明")
    caption(doc, "表 14  主要实体关系")
    table(doc,
          ["关系", "基数", "说明"],
          [
              ["会话 — 消息", "1 : N", "一个会话多条消息，按 created_at 排序；历史窗口取最近 N 条"],
              ["消息 — 引用", "1 : N", "一条回答可引用多个切片；引用存快照，规则更新后仍可追溯"],
              ["规则文档 — 切片", "1 : N", "按版本切片；只有 active 且 is_active=1 的切片可被检索"],
              ["异常事件 — 运单", "N : 1", "一票运单多条异常；运单是授权与统计的主键"],
              ["草稿 — 运单", "N : 1", "一票可多次生成草稿；每次生成保留快照与引用"],
              ["草稿 — 引用/校验", "1 : N", "草稿保存引用快照与护栏结果，审核时可复核"],
          ],
          widths=[4.0, 2.0, 10.2], size=8.5)

    h2(doc, "2.6 核心接口与错误码")
    caption(doc, "表 15  核心接口（节选）")
    table(doc,
          ["方法", "路径", "用途", "鉴权"],
          [
              ["GET", "/agent", "员工端问答页", "登录 + agent:use"],
              ["POST", "/admin/api/chat/stream", "SSE 问答（meta/status/delta/citations/takeover/error/done）", "登录 + kb:read"],
              ["GET", "/admin/exceptions", "异常列表与预警", "ops:read"],
              ["POST", "/admin/exceptions/{id}/accept", "受理事件，开始首响计时", "ops:act"],
              ["POST", "/admin/workbench/generate", "生成查单/催单草稿", "kb:edit"],
              ["POST", "/admin/kb/upload", "上传规则文档并切片", "kb:edit"],
              ["GET", "/admin/audit", "对话审计列表", "audit:read"],
              ["POST", "/admin/api/ingest/tracks", "GPS 轨迹推送", "X-Ingest-Token"],
          ],
          widths=[1.6, 6.6, 6.0, 2.6], size=8)

    caption(doc, "表 16  错误码（中文信息）")
    table(doc,
          ["错误码", "HTTP", "含义", "处理"],
          [
              ["UNAUTHENTICATED", "401", "未登录或会话过期", "跳登录页"],
              ["FORBIDDEN", "403", "角色无权访问", "提示联系管理员"],
              ["SHIPMENT_FORBIDDEN", "403", "运单未授权或跨线", "不检索、不调模型"],
              ["SESSION_BUSY", "409", "同一会话正在生成", "稍后重试"],
              ["LLM_TIMEOUT", "504", "模型响应超时", "降级或提示重试"],
              ["LLM_UPSTREAM_ERROR", "502", "模型上游异常", "记录并提示"],
              ["KB_EMPTY", "503", "本线路无可用规则", "提示先发布规则"],
              ["PROMPT_LOCKED_SECTION", "409", "提示词锁定段被修改", "还原后重试"],
          ],
          widths=[4.4, 1.6, 5.6, 4.6], size=8)

    h2(doc, "2.7 第一周最小验证目标（可验收）")
    p(doc, "第一周不追求完整系统，只验证“检索准、引用真、红线稳、模型可换、错误可读”。")
    caption(doc, "表 17  第一周验收")
    table(doc,
          ["编号", "验证项", "操作", "通过标准"],
          [
              ["W1-1", "规则入库", "上传 1 份运输规则 Markdown", "切片数 >0，active 切片可检索"],
              ["W1-2", "制度问答", "命令行问 3 个规则问题（延误定义、回执时限、改地址处理）", "3/3 返回答案，且带来源（文档/章节/版本）"],
              ["W1-3", "无依据问题", "问 1 个规则中不存在的问题", "回答“制度中未找到”，不编造"],
              ["W1-4", "红线闸门", "问赔付/危险品问题", "0 次模型调用，输出转人工提示"],
              ["W1-5", "模型可切换", "改 base_url/model 配置", "无需改代码即可切换并跑通"],
              ["W1-6", "错误可读", "断开模型/清空知识库", "返回中文错误码与可操作提示"],
          ],
          widths=[1.4, 2.8, 6.6, 5.4], size=8.5)

    h2(doc, "2.8 与当前实现的对照")
    caption(doc, "表 18  设计目标与实现状态")
    table(doc,
          ["能力", "设计目标", "当前状态"],
          [
              ["四层架构与双入口", "员工端 / 管理端 / 门户", "已实现"],
              ["规则知识库与版本", "上传→审批→发布→下线", "已实现"],
              ["检索与引用", "线路隔离、不跨线回退", "已实现"],
              ["红线与停止建议", "赔付/危险品/事故/改地址/回执", "已实现"],
              ["异常与路由", "四要素、修复队列、自动路由、升级", "已实现"],
              ["查单/催单草稿", "证据包、引用、审核、外发登记", "已实现"],
              ["审计与留存", "append-only、哈希、90 天审批", "已实现"],
              ["低负担上报", "停车确认 + 1–2 动作", "待建（当前为接口/补录）"],
          ],
          widths=[4.4, 7.2, 4.6], size=8.5)

    h2(doc, "2.9 风险与待确认")
    caption(doc, "表 19  主要风险")
    risk_table = table(doc,
          ["风险", "影响", "缓解"],
          [
              ["只有一位角色完成访谈", "需求代表性不足", "补访其余五个角色"],
              ["TMS 接口未联调", "接入不可验证", "先用脱敏样本，接口联调前置"],
              ["改地址升级责任未定", "流程无法闭环", "顾明岚、唐映秋拍板"],
              ["模型效果与成本未知", "体验与预算风险", "小范围试点 + 按票核算"],
              ["SQLite 单机瓶颈", "并发受限", "试点够用，预留 PostgreSQL 迁移"],
          ],
          widths=[4.6, 5.4, 6.2], size=8.5)
    for row in risk_table.rows[:-1]:
        for cell in row.cells:
            for paragraph in cell.paragraphs:
                paragraph.paragraph_format.keep_with_next = True


def appendix(doc):
    h1(doc, "附录  与两份提示词的对应关系")
    table(doc,
          ["提示词要求", "本方案对应位置"],
          [
              ["10 个关键问题（覆盖十个维度）", "第一部分 1.2、1.3、1.5"],
              ["问题—原因—架构差异表", "表 1、逐题“典型答案与架构影响”"],
              ["一页纸需求清单", "1.4 表 2"],
              ["四层架构图（文字版）", "2.1 表 4"],
              ["目标架构 vs 第一周最小架构", "2.2 表 5"],
              ["推荐目录结构（标注可复用模块）", "2.3 目录树，★ 为核心复用模块"],
              ["数据库表设计（字段/类型/必填/索引/状态）", "2.4 表 6–13"],
              ["会话/文档/草稿关系", "2.5 表 14"],
              ["第一周最小验证（可验收）", "2.7 表 17"],
          ],
          widths=[8.0, 8.0], size=9)


def build():
    doc = Document()
    apply_styles(doc)
    add_page_number(doc.sections[0])

    # 封面
    doc.add_paragraph().paragraph_format.space_before = Pt(70)
    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run("运输异常与签收协作智能体系统")
    set_font(run, "微软雅黑", 23, bold=True, color=NAVY)
    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = sub.add_run("项目设计方案（阶段 0）")
    set_font(run, "微软雅黑", 19, bold=True, color=NAVY)
    sub2 = doc.add_paragraph()
    sub2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = sub2.add_run("需求分析 · 架构选型 · 第一周最小验证")
    set_font(run, "微软雅黑", 11, color=GRAY)

    doc.add_paragraph().paragraph_format.space_before = Pt(36)
    meta = [
        ("文档版本", "v1.0（阶段 0 设计稿）"),
        ("编制日期", "2026-11-06"),
        ("依据材料", "案例包 logistics-01~04、访谈 turn-2/turn-4、需求分析方案"),
        ("适用对象", "评审、开发启动、试点准备"),
        ("说明", "推荐答案基于现有材料，待业务方逐条确认"),
    ]
    t = doc.add_table(rows=0, cols=2)
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for key, value in meta:
        cells = t.add_row().cells
        cell_text(cells[0], key, 9.5, bold=True, color=NAVY)
        cell_text(cells[1], value, 9.5)
        cells[0].width = Cm(3.2)
        cells[1].width = Cm(12.6)
        shade(cells[0], HEAD_FILL)

    doc.add_page_break()

    # 目录（手工）
    h1(doc, "目录")
    for line in [
        "第一部分  需求分析（阶段 0 · 技术选型）",
        "  1.1 方法与边界",
        "  1.2 十个关键问题总表",
        "  1.3 逐题展开（Q1–Q10）",
        "  1.4 一页纸需求清单",
        "  1.5 维度覆盖检查",
        "第二部分  架构选型（阶段 0 · 架构方案）",
        "  2.1 四层架构（文字版）",
        "  2.2 目标架构与第一周最小架构",
        "  2.3 推荐目录结构",
        "  2.4 数据库表设计",
        "  2.5 实体关系说明",
        "  2.6 核心接口与错误码",
        "  2.7 第一周最小验证目标",
        "  2.8 与当前实现的对照",
        "  2.9 风险与待确认",
        "附录  与两份提示词的对应关系",
    ]:
        p(doc, line, indent=False, size=10)
    doc.add_page_break()

    part_one(doc)
    doc.add_page_break()
    part_two(doc)
    appendix(doc)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUT)
    return OUT


if __name__ == "__main__":
    print("saved:", build())
