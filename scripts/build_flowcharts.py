"""生成改造前 / 改造后两张流程图，并合成对比 docx。"""
from __future__ import annotations

import sys
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

ROOT = Path(r"D:\wuliu_yunshuyichang")
DOCS = ROOT / "docs"
TMP = ROOT / ".flow-tmp"
ASIS_PNG = DOCS / "流程图-改造前.png"
TOBE_PNG = DOCS / "流程图-改造后.png"
OUT_DOCX = DOCS / "运输异常流程对比-改造前后.docx"

NAVY = RGBColor(0x1F, 0x38, 0x64)
GRAY = RGBColor(0x59, 0x59, 0x59)

ROLE_COLORS = {
    "客户": "#0284C7",
    "客服": "#7C3AED",
    "调度": "#EA580C",
    "司机": "#16A34A",
    "系统": "#0F766E",
    "AI": "#1D4ED8",
    "人工": "#B45309",
    "审计": "#475569",
    "复盘": "#BE123C",
    "接入": "#0891B2",
}

AS_IS = {
    "file": "flow_asis.html",
    "badge": "AS-IS · 现状",
    "badge_bg": "#FEE2E2",
    "badge_color": "#B91C1C",
    "title": "改造前：异常与查单流程",
    "subtitle": "信息活在群聊里，系统只记录结果；客服查单靠问，调度被反复打断",
    "accent": "#C2410C",
    "steps": [
        ("客户", "异常发生 / 催问进度", "客户改地址、问“到哪里”、催回执；没有统一入口"),
        ("客服", "在群里问调度", "“这票到哪了？为什么还没到？”——同样的问题每天重复"),
        ("调度", "查 TMS + 翻群消息 + 打电话", "多个渠道来回切换，同一票信息各存一份"),
        ("司机", "群里语音 / 文字说明", "在途需先安全停车，不能边开边处理"),
        ("调度", "群聊 / 个人表补说明", "关键原因停留在非结构化文本，依赖个人习惯"),
        ("调度", "回系统补录", "字段有限，原因缺失或事后补；补录本身也是负担"),
        ("客服", "查单看不到完整原因", "只能再问调度"),
        ("客服", "人工回复客户 / 催回执", "口径靠人记，时效靠催；没有留痕"),
        ("全员", "事后翻群记录核对", "无法统计、无法复盘，下次还会再问一遍"),
    ],
    "loop_after": 7,
    "loop_text": "↺ 二次往返：客服 → 调度 → 客服，同一票反复沟通",
    "panel_title": "关键问题",
    "panel_items": [
        "约 60% 催单只是问“到哪里”，重复查 TMS 与群消息最占时间",
        "关键原因没有结构化字段，客服查单必须回头问调度",
        "改地址与排队、封路不是一套流程，升级责任未定义",
        "改地址需先安全停车，处理时效受安全约束",
        "司机报一次不够，还要靠人补录",
        "次数、耗时没有统计，无法证明改进效果",
    ],
    "panel_note": "证据：logistics-f11 / f12 / f14（现场调度访谈 turn-2、turn-4）",
    "kpis": ["60% 催单问“到哪里”", "二次往返", "原因结构化率≈0", "升级责任未定", "无首响基线"],
}

TO_BE = {
    "file": "flow_tobe.html",
    "badge": "TO-BE · 目标",
    "badge_bg": "#DCFCE7",
    "badge_color": "#15803D",
    "title": "改造后：异常与查单流程",
    "subtitle": "先结构化，再辅助；AI 只做草稿，人工做决定；全链路可追溯",
    "accent": "#1F3864",
    "steps": [
        ("接入", "多源进入", "TMS 只读 / GPS 轨迹 / IM 留痕 / 人工补录，统一入口"),
        ("系统", "四要素归一", "运单号·类型·发生时间·来源；缺字段进修复队列，不猜值"),
        ("系统", "高风险识别 + 红线闸门", "改地址/赔付/危险品/事故：不调模型，转人工接管并留接手人、原因、时间"),
        ("系统", "自动路由 + 通知", "按类型路由到具名处理人，写截止时间；30 分钟未受理自动升级"),
        ("系统", "生成证据包", "运单 / 子单映射 / 轨迹 / 异常 / 数据时间 / 快照版本"),
        ("AI", "查单 / 催单草稿", "规则检索 + 引用（来源/版本/数据时间）；不承诺时效与金额"),
        ("人工", "人工审核", "通过 / 退回（选修正原因）/ 转人工；通过后登记人工外发"),
        ("系统", "异常预警", "预计超时 / 轨迹停滞 / 回执超期 / 多异常；人工确认或标误报"),
        ("审计", "留痕与指标", "审计、首响、≤15 分钟占比、二次往返、回执及时率、误报率"),
        ("复盘", "修正归类 + 熔断", "误报率连续超 10% 暂停自动建议；修正原因可归类"),
    ],
    "loop_after": None,
    "loop_text": "",
    "panel_title": "关键变化",
    "panel_items": [
        "只读接入：不写 TMS，外部写入被禁止并记违规",
        "四要素归一：缺字段进修复队列，不猜值、不糊字段",
        "红线不调模型：赔付、危险品、事故、判责直接转人工",
        "责任到人：路由 + 受理 + 转交 + 超时升级，发消息不算转移",
        "证据化草稿：引用可追溯，人工审核后才可登记外发",
        "可度量：首响、≤15 分钟占比、二次往返、误报率",
        "可熔断：误报率连续超 10% 自动暂停建议",
    ],
    "panel_note": "对应：需求分析方案 FR-01~FR-21；红线 0 次模型调用、引用率 100%",
    "kpis": ["红线 0 次模型调用", "引用率 100%", "路由覆盖 100%", "上报动作 ≤2（目标）", "误报率 ≤10%"],
}


def step_html(index: int, role: str, name: str, desc: str, accent: str) -> str:
    color = ROLE_COLORS.get(role, accent)
    return f"""
    <div class="step" style="--c:{color}">
      <div class="num">{index:02d}</div>
      <div class="content">
        <span class="role">{role}</span>
        <div class="name">{name}</div>
        <div class="desc">{desc}</div>
      </div>
    </div>"""


def render_html(cfg: dict) -> str:
    steps = []
    for i, (role, name, desc) in enumerate(cfg["steps"], start=1):
        if cfg.get("loop_after") and i == cfg["loop_after"] + 1:
            steps.append(f'<div class="loop">{cfg["loop_text"]}</div>')
        steps.append(step_html(i, role, name, desc, cfg["accent"]))
        if i < len(cfg["steps"]):
            steps.append('<div class="arrow"></div>')

    panel_items = "".join(f"<li>{item}</li>" for item in cfg["panel_items"])
    used_roles = []
    for role, _name, _desc in cfg["steps"]:
        if role not in used_roles:
            used_roles.append(role)
    kpis = "".join(f'<span class="kpi">{item}</span>' for item in cfg["kpis"])

    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><style>
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 32px 36px 26px; width: 1000px; background: #F8FAFC;
    font-family: "Microsoft YaHei", "PingFang SC", sans-serif; color: #0F172A;
    -webkit-font-smoothing: antialiased;
  }}
  .head {{ display: flex; justify-content: space-between; align-items: flex-end;
    border-bottom: 3px solid {cfg['accent']}; padding-bottom: 16px; }}
  .title {{ font-size: 30px; font-weight: 800; letter-spacing: .3px; }}
  .sub {{ font-size: 13.5px; color: #64748B; margin-top: 7px; }}
  .badge {{ font-size: 12px; font-weight: 700; padding: 7px 14px; border-radius: 999px;
    background: {cfg['badge_bg']}; color: {cfg['badge_color']}; white-space: nowrap; }}
  .body {{ display: grid; grid-template-columns: 660px 300px; gap: 24px; margin-top: 22px; }}
  .flow {{ display: flex; flex-direction: column; }}
  .step {{ background: #fff; border: 1px solid #E2E8F0; border-left: 7px solid var(--c);
    border-radius: 10px; padding: 12px 14px; display: flex; gap: 10px;
    box-shadow: 0 2px 10px rgba(15,23,42,.05); }}
  .num {{ width: 32px; height: 32px; border-radius: 50%; background: var(--c); color: #fff;
    font-weight: 800; font-size: 14px; display: flex; align-items: center; justify-content: center;
    flex: 0 0 auto; }}
  .role {{ display: inline-block; font-size: 11px; font-weight: 700; color: #fff;
    background: var(--c); border-radius: 6px; padding: 2px 8px; }}
  .name {{ font-size: 19px; font-weight: 800; margin-top: 4px; }}
  .desc {{ font-size: 15px; color: #475569; margin-top: 4px; line-height: 1.55; }}
  .arrow {{ height: 20px; display: flex; flex-direction: column; align-items: center; justify-content: center; }}
  .arrow::before {{ content: ""; width: 2px; height: 13px; background: #CBD5E1; }}
  .arrow::after {{ content: ""; border-left: 5px solid transparent; border-right: 5px solid transparent;
    border-top: 7px solid #CBD5E1; }}
  .loop {{ margin: 8px 0 8px 44px; padding: 8px 12px; border: 2px dashed #EF4444;
    border-radius: 10px; color: #B91C1C; background: #FEF2F2; font-size: 13.5px; font-weight: 700; }}
  aside {{ display: flex; flex-direction: column; gap: 18px; }}
  .panel {{ background: #fff; border: 1px solid #E2E8F0; border-radius: 10px; padding: 14px 16px;
    box-shadow: 0 2px 10px rgba(15,23,42,.04); }}
  .panel h3 {{ margin: 0 0 8px; font-size: 15px; color: {cfg['accent']}; }}
  .panel ul {{ margin: 0; padding-left: 20px; }}
  .panel li {{ font-size: 14px; color: #334155; line-height: 1.55; margin-bottom: 6px; }}
  .panel .note {{ margin-top: 8px; font-size: 12.5px; color: #64748B; border-top: 1px dashed #E2E8F0;
    padding-top: 10px; line-height: 1.5; }}
  .legend {{ display: flex; flex-wrap: wrap; gap: 8px; }}
  .legend span {{ font-size: 11px; color: #fff; border-radius: 6px; padding: 3px 8px; }}
  .kpis {{ display: flex; flex-wrap: wrap; gap: 8px; }}
  .kpi {{ background: #fff; border: 1px dashed #CBD5E1; border-radius: 999px;
    padding: 5px 10px; font-size: 12px; color: #334155; }}
  .foot {{ margin-top: 18px; display: flex; justify-content: space-between;
    font-size: 11.5px; color: #64748B; border-top: 1px solid #E2E8F0; padding-top: 12px; }}
</style></head>
<body>
  <div class="head">
    <div>
      <div class="title">{cfg['title']}</div>
      <div class="sub">{cfg['subtitle']}</div>
    </div>
    <div class="badge">{cfg['badge']}</div>
  </div>

  <div class="body">
    <div class="flow">
      {''.join(steps)}
    </div>

    <aside>
      <div class="panel">
        <h3>{cfg['panel_title']}</h3>
        <ul>{panel_items}</ul>
        <div class="note">{cfg['panel_note']}</div>
      </div>
      <div class="panel">
        <h3>角色图例</h3>
        <div class="legend">
          {''.join(f'<span style="background:{ROLE_COLORS.get(role, cfg["accent"])}">{role}</span>' for role in used_roles)}
        </div>
      </div>
      <div class="panel">
        <h3>关键指标</h3>
        <div class="kpis">{kpis}</div>
      </div>
    </aside>
  </div>

  <div class="foot">
    <span>远川物流 · 一票货的最后一公里 · 运输异常与签收协作</span>
    <span>依据：案例包 logistics-01~04；现场调度访谈 turn-2 / turn-4（f11 / f12 / f14）</span>
  </div>
</body></html>"""


def write_html() -> None:
    TMP.mkdir(parents=True, exist_ok=True)
    for cfg in (AS_IS, TO_BE):
        (TMP / cfg["file"]).write_text(render_html(cfg), encoding="utf-8")
    print("html written:", TMP)


def trim_and_save() -> None:
    from PIL import Image, ImageChops

    for src_name, dst in (("asis.png", ASIS_PNG), ("tobe.png", TOBE_PNG)):
        src = TMP / src_name
        image = Image.open(src).convert("RGB")
        # 容差裁剪：截图里可能有整屏空白，颜色差 1-2 不能被当成内容
        gray = image.convert("L")
        background = Image.new("L", image.size, 248)
        diff = ImageChops.difference(gray, background).point(
            lambda value: 255 if value > 8 else 0
        )
        bbox = diff.getbbox()
        if bbox:
            left, top, right, bottom = bbox
            pad = 24
            image = image.crop((
                max(left - pad, 0), max(top - pad, 0),
                min(right + pad, image.width), min(bottom + pad, image.height),
            ))
        # 控制像素宽度，docx 里按 16cm 排版
        if image.width > 2200:
            ratio = 2200 / image.width
            image = image.resize((2200, int(image.height * ratio)), Image.LANCZOS)
        image.save(dst, "PNG")
        print("saved:", dst, image.size)


def set_font(run, name="宋体", size=None, bold=None, color=None):
    run.font.name = name
    run._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), name)
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.font.bold = bold
    if color is not None:
        run.font.color.rgb = color


def build_docx() -> None:
    doc = Document()
    section = doc.sections[0]
    section.page_width = Cm(21)
    section.page_height = Cm(29.7)
    section.top_margin = Cm(1.8)
    section.bottom_margin = Cm(1.6)
    section.left_margin = Cm(2.0)
    section.right_margin = Cm(2.0)

    normal = doc.styles["Normal"]
    normal.font.name = "宋体"
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    normal.font.size = Pt(10)

    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run("运输异常流程对比：改造前 vs 改造后")
    set_font(run, "微软雅黑", 18, bold=True, color=NAVY)

    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = sub.add_run("远川物流 · 一票货的最后一公里 · 依据现场调度访谈与案例包")
    set_font(run, "微软雅黑", 9.5, color=GRAY)

    for image_path, caption_text in (
        (ASIS_PNG, "图 1  改造前：异常与查单流程（现状）"),
        (TOBE_PNG, "图 2  改造后：异常与查单流程（目标）"),
    ):
        cap = doc.add_paragraph()
        cap.paragraph_format.space_before = Pt(8)
        cap.paragraph_format.space_after = Pt(4)
        run = cap.add_run(caption_text)
        set_font(run, "微软雅黑", 10.5, bold=True, color=NAVY)
        doc.add_picture(str(image_path), width=Cm(17.0))

    doc.add_page_break()
    heading = doc.add_heading("对比与说明", level=1)
    heading.paragraph_format.space_before = Pt(4)

    table = doc.add_table(rows=1, cols=3)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    headers = ["维度", "改造前", "改造后"]
    for i, text in enumerate(headers):
        cell = table.rows[0].cells[i]
        cell.text = ""
        run = cell.paragraphs[0].add_run(text)
        set_font(run, "微软雅黑", 9.5, bold=True, color=NAVY)

    rows = [
        ("信息载体", "群聊、个人表、电话", "结构化字段 + 证据包"),
        ("事件归一", "无，靠人理解", "四要素归一，缺字段进修复队列"),
        ("查单", "问调度，二次往返", "证据包 + 带引用的草稿"),
        ("高风险事件", "靠人判断，责任未定", "闸门拦截、转人工、留接手人"),
        ("责任转移", "群聊里说一声", "受理 / 转交显式留痕"),
        ("时效", "靠催，无计时", "30 分钟升级，≤15 分钟占比可测"),
        ("预警", "无", "四条规则 + 误报确认 + 熔断"),
        ("外发", "凭记忆直接回复", "草稿 + 人工审核 + 外发登记"),
        ("审计", "翻群记录", "append-only + 请求 ID + 指标"),
    ]
    for row in rows:
        cells = table.add_row().cells
        for i, text in enumerate(row):
            cells[i].text = ""
            run = cells[i].paragraphs[0].add_run(text)
            set_font(run, "宋体", 9)

    for row in table.rows:
        row.cells[0].width = Cm(3.4)
        row.cells[1].width = Cm(6.6)
        row.cells[2].width = Cm(6.6)

    doc.add_paragraph()
    note = doc.add_paragraph()
    run = note.add_run("读图说明：")
    set_font(run, "微软雅黑", 10, bold=True, color=NAVY)
    for text in (
        "改造前的问题不是“没有系统”，而是系统只记录结果，过程留在群聊里；",
        "改造后也不是“全自动”，而是把过程变成字段、把决定留给人；",
        "两张图之间不是功能叠加，而是信息载体、责任边界和度量方式的三重变化。",
    ):
        paragraph = doc.add_paragraph(style="List Bullet")
        run = paragraph.add_run(text)
        set_font(run, "宋体", 9.5)

    doc.save(OUT_DOCX)
    print("saved:", OUT_DOCX)


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "html"
    if action == "html":
        write_html()
    elif action == "finish":
        trim_and_save()
        build_docx()
    else:
        raise SystemExit(f"unknown action: {action}")
