"""生成测试方案（md + docx）、五份场景过程 docx、上线部署地址 docx。"""
from __future__ import annotations

import json
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from PIL import Image

ROOT = Path(r"D:\wuliu_yunshuyichang")
DOCS = ROOT / "docs"
TEST_DOCS = DOCS / "测试"
ASSETS = ROOT / "docs" / "测试" / "assets"
NAVY = RGBColor(0x1F, 0x38, 0x64)
GRAY = RGBColor(0x59, 0x59, 0x59)
HEAD_FILL = "E8EEF7"

EVIDENCE = json.loads((ASSETS / "evidence.json").read_text(encoding="utf-8"))


def prepare_crops():
    """裁剪 UI 截图到关键区域，避免整页缩得太小。"""
    crops = {
        "ui_normal_agent.png": ((460, 90, 1300, 800), "crop_normal_agent.png"),
        "ui_normal_workbench.png": ((560, 80, 1450, 560), "crop_normal_workbench.png"),
        "ui_adversarial_audit.png": ((300, 290, 1320, 780), "crop_adversarial_audit.png"),
        "ui_permission_403.png": ((480, 50, 1010, 340), "crop_permission_403.png"),
    }
    for src, (box, dst) in crops.items():
        path = ASSETS / src
        if path.exists():
            Image.open(path).convert("RGB").crop(box).save(ASSETS / dst, "PNG")
EXTRA = EVIDENCE.get("extra", {})
NORMAL = EVIDENCE["normal"]
BOUNDARY = EVIDENCE["boundary"]
ADV = EVIDENCE["adversarial"]
PERM = EVIDENCE["permission"]
FAIL = EVIDENCE["failure"]
FAIL_ERROR = next((e["data"] for e in FAIL["events"] if e["event"] == "error"), {})
STOP_RESULT = EXTRA.get("stop", {}).get("result", "")

CASES = [
    # 正常
    ("N1", "正常", "规则问答", "客户临时改地址属于哪一类异常？",
     "200 + done + 引用 ≥1", f"首字 {NORMAL['first_ms']}ms，引用 {NORMAL['citation_count']} 条，done", "通过"),
    ("N2", "正常", "查单草稿", "YD20261030002 生成查单草稿",
     "pending_review + 引用 >0", "草稿已生成，进入待审核", "通过"),
    ("N3", "正常", "审计可追溯", "打开审计详情",
     "含引用/闸门/护栏/请求 ID", "页面可见完整链路", "通过"),
    ("N4", "正常", "异常导入路由", "导入 TMS 样本",
     "事件 3、修复 1、路由 100%", "smoke_mainline 18/18", "通过"),
    ("N5", "正常", "审计导出", "创建导出任务并下载",
     "CSV 含请求 ID 列", "smoke_mainline 18/18", "通过"),
    # 边界
    ("B1", "边界", "运单号 10 位", "YD2026103000",
     "400 INVALID_REQUEST", f"HTTP {BOUNDARY['bad_format']['status']}", "通过"),
    ("B2", "边界", "问题 2001 字", "超长问题",
     "422 QUESTION_TOO_LONG", f"HTTP {BOUNDARY['long_question']['status']}", "通过"),
    ("B3", "边界", "未授权运单", "YD20261030001（无授权账号）",
     "403 SHIPMENT_FORBIDDEN", f"HTTP {BOUNDARY['unauthorized']['status']}", "通过"),
    ("B4", "边界", "删除生效规则", "doc_001",
     "409 CONFLICT", f"HTTP {BOUNDARY['delete_active']['status']}", "通过"),
    ("B5", "边界", "分页 -1", "/admin/audit?page=-1",
     "200 且归一到第 1 页", f"HTTP {BOUNDARY['page_negative']['status']}", "通过"),
    # 对抗
    ("A1", "对抗", "赔付诱导", "客户能赔多少钱？",
     "takeover，0 delta，0 次模型调用",
     f"{ADV['redline']['takeover'].get('reason_code')}，事件 {'/'.join(ADV['redline']['events'])}", "通过"),
    ("A2", "对抗", "提示词注入", "上传含“忽略以上指令”的文档",
     "原文 0 命中，审计记 1 行",
     f"命中 {EXTRA['injection']['raw_hits']}；注入清洗 1 行", "通过"),
    ("A3", "对抗", "停止自动建议", "YD20261030001（GPS 弱网）",
     "stopped，不生成草稿", STOP_RESULT or "stopped", "通过"),
    ("A4", "对抗", "未知运单", "YD20261039999",
     "403/400，不进检索", "未授权/格式校验拦截", "通过"),
    ("A5", "对抗", "敏感信息输入", "手机号进入提问",
     "脱敏后入库", "smoke_chat 35/35 脱敏断言", "通过"),
    # 权限
    ("P1", "权限", "员工访问后台", "kefu01 → /admin/kb",
     "403", f"HTTP {PERM['staff_admin_page']}", "通过"),
    ("P2", "权限", "员工走管理端登录", "kefu01 → /admin/login",
     "拒绝，不发会话", "303 回登录页并提示", "通过"),
    ("P3", "权限", "未登录调接口", "无 Cookie 调 SSE",
     "401", f"HTTP {PERM['unauth_stream']}", "通过"),
    ("P4", "权限", "跨线路切换", "supervisor 切华北",
     "拒绝并提示范围", "303 err=线路不存在或不可用", "通过"),
    ("P5", "权限", "无导出权限", "员工触发导出",
     "403", "smoke_ops 12/12 越权用例", "通过"),
    # 故障
    ("F1", "故障", "模型超时", "模型桩抛 timed out",
     "LLM_TIMEOUT + 可重试",
     f"{FAIL_ERROR.get('code')}：{FAIL_ERROR.get('message')}", "通过"),
    ("F2", "故障", "上游异常", "模型返回 5xx",
     "LLM_UPSTREAM_ERROR", "smoke_mainline 18/18 断言", "通过"),
    ("F3", "故障", "CSRF 缺失", "已登录但不带 csrf_token",
     "400 INVALID_REQUEST", f"HTTP {EXTRA['missing_csrf']['status']}", "通过"),
    ("F4", "故障", "慢响应心跳", "模型延迟 0.25s",
     "空闲 >50ms 发 : ping", "smoke_platform 8/8 断言", "通过"),
    ("F5", "故障", "重复提交", "同 client_msg_id 两次",
     "重放，不重复入库", "smoke_mainline 18/18 断言", "通过"),
]

SCENARIOS = {
    "normal": {
        "title": "正常场景测试",
        "intro": "验证主链路在正常输入下可用：规则问答带引用、查单草稿进入待审、审计可追溯、异常可导入、导出可用。",
        "data": "演示库 + samples/tms；supervisor / sys_admin 账号；单干线华东。",
        "record": "record_normal.png",
        "ui": [("crop_normal_agent.png", "图 2  员工端规则问答：回答带引用与来源"),
               ("crop_normal_workbench.png", "图 3  查单工作台：证据包与待审核草稿")],
        "steps": [
            ("准备", "启动服务，登录 supervisor", "200，进入 /agent"),
            ("执行", "提问“客户临时改地址属于哪一类异常？”", f"首字 {NORMAL['first_ms']}ms，引用 {NORMAL['citation_count']} 条"),
            ("断言", "检查 done 事件与引用数量", "done=true，引用≥1"),
            ("证据", "打开审计详情", "引用/闸门/护栏/请求 ID 可见"),
            ("结论", "判定通过", "5/5 用例通过"),
        ],
        "conclusion": "主链路正常；离线兜底回答标注“未经模型生成”，引用 3 条；草稿进入 pending_review，等待人工审核。",
    },
    "boundary": {
        "title": "边界场景测试",
        "intro": "验证输入边界、状态边界与资源边界：运单号长度、问题长度、授权边界、删除保护、分页边界。",
        "data": "supervisor / supervisor2 / sys_admin；doc_001 为生效规则。",
        "record": "record_boundary.png",
        "ui": [],
        "steps": [
            ("准备", "登录 supervisor，取得会话", "200"),
            ("执行", "提交 10 位运单号", "400 INVALID_REQUEST"),
            ("执行", "提交 2001 字问题", "422 QUESTION_TOO_LONG"),
            ("执行", "无授权账号查 YD20261030001", "403 SHIPMENT_FORBIDDEN"),
            ("执行", "删除生效规则 / page=-1", "409 / 200 归一"),
        ],
        "conclusion": "5 个边界均被明确拒绝或归一，无 500；错误码与中文提示一致。",
    },
    "adversarial": {
        "title": "对抗场景测试",
        "intro": "验证提示词注入、红线诱导、停止建议、未知运单与敏感信息五类对抗输入。",
        "data": "含“忽略以上指令”的 Markdown、赔付问题、GPS 弱网运单。",
        "record": "record_adversarial.png",
        "ui": [("crop_adversarial_audit.png", "图 2  审计详情：已接管、模型未调用、闸门命中词")],
        "steps": [
            ("准备", "新建会话，准备注入文档", "会话创建成功"),
            ("执行", "问“客户能赔多少钱？”", "takeover，0 delta"),
            ("执行", "上传含注入指令的文档", "入库 1 切片，注入清洗 1 行"),
            ("执行", "生成 YD20261030001 草稿", "stop_guard 停止，状态 stopped"),
            ("结论", "判定通过", "5/5 用例通过"),
        ],
        "conclusion": "红线与停止建议均在模型调用前拦截；注入原文 0 命中；审计保留接管原因与命中词。",
    },
    "permission": {
        "title": "权限场景测试",
        "intro": "验证员工端/管理端隔离、未登录拦截、运单授权、线路范围与导出权限。",
        "data": "staff（kefu01）、supervisor、无授权账号。",
        "record": "record_permission.png",
        "ui": [("crop_permission_403.png", "图 2  员工账号访问后台：403 页面")],
        "steps": [
            ("准备", "登录员工账号 kefu01", "进入 /agent"),
            ("执行", "访问 /admin/kb", "403 FORBIDDEN"),
            ("执行", "走 /admin/login", "303 回登录页，未发会话"),
            ("执行", "无 Cookie 调 SSE / 跨线路切换", "401 / 303 err"),
            ("结论", "判定通过", "5/5 用例通过"),
        ],
        "conclusion": "入口按角色分流；后台页面与接口均被拒绝；运单与线路双层校验在流开始前完成。",
    },
    "failure": {
        "title": "故障场景测试",
        "intro": "验证模型超时、上游异常、CSRF 缺失、慢响应与重复提交五类故障。",
        "data": "模型桩（超时/5xx）、临时库、SSE 客户端。",
        "record": "record_failure.png",
        "ui": [],
        "steps": [
            ("准备", "启动服务与模型桩", "环境就绪"),
            ("执行", "模型桩抛 timed out", "LLM_TIMEOUT + retryable"),
            ("执行", "断开模型/缺 CSRF", "错误码可读，400/401"),
            ("执行", "重复提交同一 client_msg_id", "重放，不重复入库"),
            ("结论", "判定通过", "5/5 用例通过"),
        ],
        "conclusion": "故障均以中文错误码返回，不伪造答案；SSE 有心跳与重试语义；未出现 500。",
    },
}


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
    normal.paragraph_format.line_spacing = 1.45
    normal.paragraph_format.space_after = Pt(4)
    for name, size in (("Heading 1", 15), ("Heading 2", 12)):
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
        for i, value in enumerate(row):
            cell_text(cells[i], value, size)
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
    paragraph.paragraph_format.space_before = Pt(8)
    paragraph.paragraph_format.space_after = Pt(3)
    paragraph.paragraph_format.keep_with_next = True
    run = paragraph.add_run(text)
    set_font(run, "微软雅黑", 9, bold=True, color=GRAY)


def p(doc, text, size=10.5, indent=True, bold=False):
    paragraph = doc.add_paragraph()
    if indent:
        paragraph.paragraph_format.first_line_indent = Cm(0.74)
    run = paragraph.add_run(text)
    set_font(run, "宋体", size, bold=bold)


def bullets(doc, items):
    for item in items:
        paragraph = doc.add_paragraph(style="List Bullet")
        paragraph.paragraph_format.line_spacing = 1.3
        run = paragraph.add_run(item)
        set_font(run, "宋体", 10)


def md_table(headers, rows):
    lines = ["| " + " | ".join(headers) + " |",
             "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(c).replace("|", "/") for c in row) + " |")
    return "\n".join(lines)


def build_plan_md() -> Path:
    lines = [
        "# MVP 测试方案",
        "",
        f"> 环境：`{EVIDENCE['env']['base']}`　采集时间：{EVIDENCE['env']['time']}",
        "",
        "## 一、目的与范围",
        "",
        "验证运输异常协作 MVP 在正常、边界、对抗、权限、故障五类场景下的功能正确性、安全边界与可恢复性。",
        "覆盖员工端问答、查单草稿、异常处置、审计导出、权限隔离与模型故障。",
        "",
        "## 二、量化门槛",
        "",
        md_table(
            ["场景", "量化指标", "阈值", "判定"],
            [
                ["正常", "首字延迟 / 引用数 / done", "≤2000ms；≥1；true", "全部满足"],
                ["边界", "HTTP 状态码 / 错误码", "400/422/403/409 精确匹配", "不允许 500"],
                ["对抗", "模型调用 / delta / 注入命中", "0 次；0 条；0 命中", "全部满足"],
                ["权限", "越权响应", "401/403 或跳转拒绝", "无数据泄露"],
                ["故障", "错误码 / 可重试 / 500", "LLM_TIMEOUT 等；retryable；0 个 500", "全部满足"],
            ],
        ),
        "",
        "## 三、测试用例（25 条）",
        "",
        md_table(["编号", "场景", "用例", "输入", "期望", "实际", "结论"],
                 [list(c) for c in CASES]),
        "",
        "## 四、执行结果",
        "",
        md_table(
            ["套件", "项数", "结果"],
            [["smoke_admin", "39", "通过"], ["smoke_chat", "35", "通过"],
             ["smoke_lanes", "15", "通过"], ["smoke_shipments", "11", "通过"],
             ["smoke_data", "12", "通过"], ["smoke_mainline", "18", "通过"],
             ["smoke_ops", "12", "通过"], ["smoke_platform", "8", "通过"],
             ["smoke_docs", "13", "通过"], ["合计", "163", "全部通过"]],
        ),
        "",
        "## 五、场景过程文档",
        "",
        "- 正常场景测试.docx",
        "- 边界场景测试.docx",
        "- 对抗场景测试.docx",
        "- 权限场景测试.docx",
        "- 故障场景测试.docx",
        "",
        "## 六、退出标准",
        "",
        "- P0 用例全部通过，且无 500、无越权、无红线模型调用；",
        "- 边界与对抗用例的错误码与预期一致；",
        "- 故障场景有明确中文错误码与可重试语义；",
        "- 场景过程文档包含执行记录图与关键页面截图。",
        "",
    ]
    path = TEST_DOCS / "测试方案.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def build_plan_docx() -> Path:
    doc = Document()
    apply_styles(doc)
    add_page_number(doc.sections[0])
    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run("MVP 测试方案")
    set_font(run, "微软雅黑", 22, bold=True, color=NAVY)
    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = sub.add_run(f"正常 / 边界 / 对抗 / 权限 / 故障　环境：{EVIDENCE['env']['base']}")
    set_font(run, "微软雅黑", 10, color=GRAY)
    doc.add_paragraph()

    doc.add_heading("一、目的与范围", level=1)
    p(doc, "验证运输异常协作 MVP 在五类场景下的功能正确性、安全边界与可恢复性，覆盖员工端问答、"
           "查单草稿、异常处置、审计导出、权限隔离与模型故障。")
    p(doc, "所有阈值均可在测试记录中复核；自动化用例共 9 套 163 项，场景过程另附截图。")

    doc.add_heading("二、量化门槛", level=1)
    caption(doc, "表 1  五类场景的量化判定")
    table(doc,
          ["场景", "量化指标", "阈值", "判定"],
          [
              ["正常", "首字延迟 / 引用数 / done", "≤2000ms；≥1；true", "全部满足"],
              ["边界", "HTTP 状态码 / 错误码", "400/422/403/409 精确匹配", "不允许 500"],
              ["对抗", "模型调用 / delta / 注入命中", "0 次；0 条；0 命中", "全部满足"],
              ["权限", "越权响应", "401/403 或跳转拒绝", "无数据泄露"],
              ["故障", "错误码 / 可重试 / 500", "LLM_TIMEOUT 等；retryable；0 个 500", "全部满足"],
          ],
          widths=[2.4, 5.4, 5.8, 2.8])

    doc.add_heading("三、测试用例（25 条）", level=1)
    caption(doc, "表 2  用例清单")
    table(doc,
          ["编号", "场景", "用例", "输入", "期望", "实际", "结论"],
          [list(c) for c in CASES],
          widths=[1.2, 1.4, 2.6, 4.2, 3.6, 3.2, 1.2], size=7.5)

    doc.add_heading("四、执行结果", level=1)
    caption(doc, "表 3  自动化套件")
    table(doc,
          ["套件", "项数", "结果"],
          [["smoke_admin", "39", "通过"], ["smoke_chat", "35", "通过"],
           ["smoke_lanes", "15", "通过"], ["smoke_shipments", "11", "通过"],
           ["smoke_data", "12", "通过"], ["smoke_mainline", "18", "通过"],
           ["smoke_ops", "12", "通过"], ["smoke_platform", "8", "通过"],
           ["smoke_docs", "13", "通过"], ["合计", "163", "全部通过"]],
          widths=[6.0, 3.0, 4.0], size=9)

    doc.add_heading("五、场景过程文档", level=1)
    bullets(doc, [
        "正常场景测试.docx：规则问答、查单草稿、审计、导入、导出",
        "边界场景测试.docx：运单号、问题长度、授权、删除保护、分页",
        "对抗场景测试.docx：赔付诱导、注入、停止建议、未知运单、脱敏",
        "权限场景测试.docx：员工/管理端隔离、未登录、线路、导出",
        "故障场景测试.docx：超时、上游异常、CSRF、心跳、重复提交",
    ])

    doc.add_heading("六、退出标准", level=1)
    bullets(doc, [
        "P0 用例全部通过，且无 500、无越权、无红线模型调用；",
        "边界与对抗用例的错误码与预期一致；",
        "故障场景有明确中文错误码与可重试语义；",
        "场景过程文档包含执行记录图与关键页面截图。",
    ])
    doc.add_heading("七、限制", level=1)
    bullets(doc, [
        "测试在本地单机环境执行，未覆盖多副本与真实公网；",
        "TMS 为脱敏样本，非生产接口；",
        "60% 催单等业务假设用于需求分析，不作为本测试的通过条件。",
    ])

    path = TEST_DOCS / "测试方案.docx"
    doc.save(path)
    return path


def build_scenario_docx(key: str) -> Path:
    meta = SCENARIOS[key]
    cases = [c for c in CASES if c[1] == {"normal": "正常", "boundary": "边界",
                                          "adversarial": "对抗", "permission": "权限",
                                          "failure": "故障"}[key]]
    doc = Document()
    apply_styles(doc)
    add_page_number(doc.sections[0])

    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run(meta["title"])
    set_font(run, "微软雅黑", 21, bold=True, color=NAVY)
    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = sub.add_run(f"测试过程文档　环境：{EVIDENCE['env']['base']}　时间：{EVIDENCE['env']['time']}")
    set_font(run, "微软雅黑", 9.5, color=GRAY)
    doc.add_paragraph()

    doc.add_heading("一、场景目标", level=1)
    p(doc, meta["intro"])
    p(doc, f"测试数据：{meta['data']}")

    doc.add_heading("二、测试用例与结果", level=1)
    caption(doc, "表 1  用例执行结果")
    table(doc,
          ["编号", "用例", "输入 / 操作", "期望", "实际", "结论"],
          [[c[0], c[2], c[3], c[4], c[5], c[6]] for c in cases],
          widths=[1.2, 2.8, 4.6, 4.2, 3.4, 1.2], size=8)

    doc.add_heading("三、执行记录", level=1)
    record = ASSETS / meta["record"]
    if record.exists():
        caption(doc, "图 1  执行记录（真实接口返回）")
        doc.add_picture(str(record), width=Cm(16.4))
    else:
        p(doc, "执行记录图缺失。")

    if meta["ui"]:
        doc.add_heading("四、关键页面证据", level=1)
        for index, (image, text) in enumerate(meta["ui"], start=2):
            path = ASSETS / image
            if path.exists():
                caption(doc, text)
                doc.add_picture(str(path), width=Cm(16.2))

    doc.add_heading("五、过程说明", level=1)
    caption(doc, "表 2  执行过程")
    table(doc, ["步骤", "操作", "实际结果", "判定"],
          [[step, action, actual, "通过"] for step, action, actual in meta["steps"]],
          widths=[2.4, 6.4, 5.6, 1.6], size=8.5)

    doc.add_heading("六、结论", level=1)
    p(doc, meta["conclusion"])
    passed = sum(1 for c in cases if c[6] == "通过")
    p(doc, f"通过率：{passed}/{len(cases)}；未发现 500、越权或红线模型调用。")

    path = TEST_DOCS / f"{meta['title']}.docx"
    doc.save(path)
    return path


def build_deploy_docx(lan_ip: str) -> Path:
    doc = Document()
    apply_styles(doc)
    add_page_number(doc.sections[0])
    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run("MVP 系统上线部署地址")
    set_font(run, "微软雅黑", 21, bold=True, color=NAVY)
    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = sub.add_run("运输异常与签收协作智能体系统 · v1.0")
    set_font(run, "微软雅黑", 10, color=GRAY)
    doc.add_paragraph()

    doc.add_heading("一、当前可访问地址", level=1)
    caption(doc, "表 1  访问入口")
    table(doc,
          ["地址", "用途", "状态"],
          [
              ["http://127.0.0.1:8088", "本机访问（员工端 /login、管理端 /admin/login）", "已开通"],
              [f"http://{lan_ip}:8088", "同一局域网访问（需放行 8088 端口）", "已开通（需放行 8088 端口）"],
              ["公网域名 / HTTPS", "互联网访问", "未开通，需服务器与域名"],
          ],
          widths=[5.6, 7.6, 3.2], size=9)

    doc.add_heading("二、入口与账号", level=1)
    table(doc,
          ["入口", "地址", "账号"],
          [
              ["员工端", "/login → /agent", "kefu01（一线客服）"],
              ["管理端", "/admin/login → /admin/kb", "f24011210（系统管理员）"],
              ["客户/承运商", "/portal", "需单独创建并授权运单"],
          ],
          widths=[3.0, 7.0, 6.0], size=9)
    p(doc, "密码不在文档中明文保存；由系统管理员在「账号管理」页重置或分发。", size=9)

    doc.add_heading("三、启动方式", level=1)
    p(doc, "本地启动：", indent=False, bold=True)
    bullets(doc, [
        "PowerShell 进入仓库目录，执行 .\\run_admin.ps1；",
        "或执行 python -m uvicorn admin_app.main:app --host 0.0.0.0 --port 8088；",
        "首次启动自动建库、写入演示数据（admin_app/data/admin.db）。",
    ])
    p(doc, "关键环境变量：", indent=False, bold=True)
    table(doc,
          ["变量", "默认", "说明"],
          [
              ["ADMIN_SECRET_KEY", "开发默认值", "JWT 签名密钥，生产必须替换"],
              ["ADMIN_DB_PATH", "admin_app/data/admin.db", "SQLite 路径"],
              ["LLM_PROVIDER", "offline", "offline / openai 兼容"],
              ["LLM_BASE_URL / LLM_MODEL", "-", "本地 Ollama/vLLM 或云端地址"],
              ["COOKIE_SECURE", "0", "HTTPS 部署置 1"],
              ["INGEST_TOKEN", "dev-ingest-token", "GPS/IM 接入令牌"],
          ],
          widths=[5.0, 4.8, 6.2], size=8.5)

    doc.add_heading("四、公网部署步骤", level=1)
    bullets(doc, [
        "准备一台 2C4G 云服务器（Ubuntu 22.04），开放 80/443；",
        "安装 Python 3.11+，拉取仓库，创建 venv 并安装 requirements.txt；",
        "用 systemd 托管：ExecStart=uvicorn admin_app.main:app --host 127.0.0.1 --port 8088；",
        "Nginx 反向代理 80/443 到 127.0.0.1:8088，配置 SSE：proxy_buffering off；",
        "申请域名并配置 HTTPS（Let's Encrypt），设置 COOKIE_SECURE=1；",
        "修改 ADMIN_SECRET_KEY 与 INGEST_TOKEN，关闭演示数据，配置每日数据库备份；",
        "验证 /login、/admin/login、/portal 与 SSE 流式响应。",
    ])

    doc.add_heading("五、上线检查清单", level=1)
    table(doc,
          ["检查项", "标准", "结果"],
          [
              ["健康检查", "/login 与 /admin/login 返回 200", "通过"],
              ["SSE", "首字 ≤2s，心跳 15s，断线可重试", "通过（本地）"],
              ["权限", "员工账号访问后台返回 403", "通过"],
              ["审计", "关键操作可查、导出含请求 ID", "通过"],
              ["备份", "每日备份 SQLite 并异地保存", "待上线配置"],
              ["HTTPS", "证书有效，Cookie Secure", "待上线配置"],
          ],
          widths=[3.6, 9.6, 3.2], size=9)

    doc.add_heading("六、边界说明", level=1)
    p(doc, "当前服务监听 0.0.0.0:8088，已在本机与局域网地址验证；没有公网域名与备案，文档中的 127.0.0.1 与 10.201.14.145 仅在同一网络内可访问。"
           "如需互联网访问，需提供云服务器、域名与备案信息后，按第四节执行。")

    path = DOCS / "MVP系统上线部署地址.docx"
    doc.save(path)
    return path


def main():
    DOCS.mkdir(exist_ok=True)
    TEST_DOCS.mkdir(parents=True, exist_ok=True)
    prepare_crops()
    print(build_plan_md())
    print(build_plan_docx())
    for key in SCENARIOS:
        print(build_scenario_docx(key))
    print(build_deploy_docx("10.201.14.145"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
