"""生成《运输异常典型事件资料》docx。

数据来源仅限两份访谈记录（turn-2 / turn-4），未核实项显式标注，不补造数字。
"""
from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

OUT = Path(r"D:\wuliu-many\运输异常典型事件资料.docx")

NAVY = RGBColor(0x1F, 0x38, 0x64)
GRAY = RGBColor(0x59, 0x59, 0x59)
HEAD_FILL = "E8EEF7"


def set_run_font(run, name: str = "宋体", size: float | None = None,
                 bold: bool | None = None, color: RGBColor | None = None):
    run.font.name = name
    run._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), name)
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.font.bold = bold
    if color is not None:
        run.font.color.rgb = color


def style_document(doc: Document) -> None:
    normal = doc.styles["Normal"]
    normal.font.name = "宋体"
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    normal.font.size = Pt(10.5)
    normal.paragraph_format.line_spacing = 1.5
    normal.paragraph_format.space_after = Pt(4)

    for name, size in (("Heading 1", 16), ("Heading 2", 13), ("Heading 3", 11.5)):
        style = doc.styles[name]
        style.font.name = "微软雅黑"
        style._element.rPr.rFonts.set(qn("w:eastAsia"), "微软雅黑")
        style.font.size = Pt(size)
        style.font.bold = True
        style.font.color.rgb = NAVY
        style.paragraph_format.space_before = Pt(14 if name == "Heading 1" else 10)
        style.paragraph_format.space_after = Pt(6)
        style.paragraph_format.keep_with_next = True

    section = doc.sections[0]
    section.page_width = Cm(21)
    section.page_height = Cm(29.7)
    section.top_margin = Cm(2.4)
    section.bottom_margin = Cm(2.2)
    section.left_margin = Cm(2.6)
    section.right_margin = Cm(2.4)


def add_page_number(section) -> None:
    footer = section.footer
    paragraph = footer.paragraphs[0]
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = paragraph.add_run()
    set_run_font(run, "微软雅黑", 9, color=GRAY)
    fld_begin = OxmlElement("w:fldChar")
    fld_begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = " PAGE "
    fld_end = OxmlElement("w:fldChar")
    fld_end.set(qn("w:fldCharType"), "end")
    run._r.append(fld_begin)
    run._r.append(instr)
    run._r.append(fld_end)


def shade_cell(cell, hex_color: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_color)
    tc_pr.append(shd)


def set_cell_text(cell, text: str, size: float = 9, bold: bool = False,
                  align=WD_ALIGN_PARAGRAPH.LEFT, color: RGBColor | None = None):
    cell.text = ""
    paragraph = cell.paragraphs[0]
    paragraph.alignment = align
    paragraph.paragraph_format.line_spacing = 1.15
    paragraph.paragraph_format.space_after = Pt(1)
    run = paragraph.add_run(str(text))
    set_run_font(run, "宋体", size, bold=bold, color=color)


def add_table(doc: Document, headers: list[str], rows: list[list[str]],
              widths: list[float] | None = None, size: float = 9,
              header_size: float = 9):
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False

    tbl_pr = table._tbl.tblPr
    layout = OxmlElement("w:tblLayout")
    layout.set(qn("w:type"), "fixed")
    tbl_pr.append(layout)

    header_row = table.rows[0]
    # 表头跨页重复
    tr_pr = header_row._tr.get_or_add_trPr()
    tbl_header = OxmlElement("w:tblHeader")
    tbl_header.set(qn("w:val"), "true")
    tr_pr.append(tbl_header)

    for index, text in enumerate(headers):
        cell = header_row.cells[index]
        set_cell_text(cell, text, header_size, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER,
                      color=NAVY)
        shade_cell(cell, HEAD_FILL)

    for row in rows:
        cells = table.add_row().cells
        for index, text in enumerate(row):
            set_cell_text(cells[index], text, size)

    if widths:
        for index, width in enumerate(widths):
            table.columns[index].width = Cm(width)
        for row in table.rows:
            for index, width in enumerate(widths):
                row.cells[index].width = Cm(width)
    return table


def add_caption(doc: Document, text: str) -> None:
    paragraph = doc.add_paragraph()
    paragraph.paragraph_format.space_before = Pt(8)
    paragraph.paragraph_format.space_after = Pt(3)
    paragraph.paragraph_format.keep_with_next = True
    run = paragraph.add_run(text)
    set_run_font(run, "微软雅黑", 9.5, bold=True, color=GRAY)


def add_paragraph(doc: Document, text: str, size: float = 10.5, indent: bool = True,
                  bold: bool = False):
    paragraph = doc.add_paragraph()
    if indent:
        paragraph.paragraph_format.first_line_indent = Cm(0.74)
    run = paragraph.add_run(text)
    set_run_font(run, "宋体", size, bold=bold)
    return paragraph


def add_bullets(doc: Document, items: list[str]) -> None:
    for item in items:
        paragraph = doc.add_paragraph(style="List Bullet")
        paragraph.paragraph_format.line_spacing = 1.4
        run = paragraph.add_run(item)
        set_run_font(run, "宋体", 10.5)


def build() -> Path:
    doc = Document()
    style_document(doc)
    add_page_number(doc.sections[0])

    # ---------------- 封面 ----------------
    spacer = doc.add_paragraph()
    spacer.paragraph_format.space_before = Pt(80)

    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run("运输异常典型事件资料")
    set_run_font(run, "微软雅黑", 26, bold=True, color=NAVY)

    subtitle = doc.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = subtitle.add_run("基于现场调度员访谈的案例、问题与量化指标")
    set_run_font(run, "微软雅黑", 13, color=GRAY)

    spacer = doc.add_paragraph()
    spacer.paragraph_format.space_before = Pt(36)

    meta = [
        ("资料来源", "访谈记录 turn-2、turn-4（2026-11-06）"),
        ("受访对象", "林亦舟 · 现场调度员"),
        ("引用事实", "logistics-f11、logistics-f12、logistics-f14"),
        ("编制日期", "2026-11-06"),
        ("用途", "需求验证、试点准备、结课答辩材料"),
    ]
    table = doc.add_table(rows=0, cols=2)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    for key, value in meta:
        cells = table.add_row().cells
        set_cell_text(cells[0], key, 10, bold=True, color=NAVY)
        set_cell_text(cells[1], value, 10)
        cells[0].width = Cm(3.2)
        cells[1].width = Cm(11.5)
        shade_cell(cells[0], HEAD_FILL)

    note = doc.add_paragraph()
    note.paragraph_format.space_before = Pt(28)
    note.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = note.add_run(
        "说明：本文只使用访谈中明确出现的信息与数字；受访人未核实的次数、耗时，\n"
        "一律标注“未统计/待验证”，不做推测性补数。"
    )
    set_run_font(run, "宋体", 9.5, color=GRAY)

    doc.add_page_break()

    # ---------------- 一、访谈概况 ----------------
    doc.add_heading("一、访谈概况", level=1)
    add_paragraph(
        doc,
        "本次访谈对象为现场调度员林亦舟，共两轮，聚焦“最近一次具体异常”和“最耗时耗力的环节”。"
        "访谈方式为开放式追问，要求尽量给出量化信息；受访人明确表示手上没有准确的次数与耗时统计，"
        "只能提供现场感受和已知比例，因此本文对相关数字做了来源与可信度标注。",
    )

    add_caption(doc, "表 1  访谈基本信息")
    add_table(
        doc,
        ["项目", "内容"],
        [
            ["受访角色", "现场调度员（负责在途异常协调、司机沟通、系统补录）"],
            ["访谈轮次", "2 轮：典型事件复盘（turn-2）；耗时耗力环节（turn-4）"],
            ["访谈时间", "2026-11-06 00:49、00:54（UTC）"],
            ["提问方式", "请讲述一次具体异常，能量化就量化；还有哪些耗时耗力、不方便的地方"],
            ["回答特点", "细节充分，但次数/耗时未统计；主动拒绝编造数字"],
            ["引用事实", "logistics-f11、logistics-f12、logistics-f14"],
        ],
        widths=[3.2, 12.0],
    )

    add_caption(doc, "表 2  访谈结论摘要")
    add_table(
        doc,
        ["序号", "结论", "证据"],
        [
            ["1", "客户临时改地址是高干扰、低结构化的典型异常，处理方式与卸货排队、封路完全不同", "f11"],
            ["2", "现场靠“司机群聊说一声 → 调度在群聊/个人表补说明 → 回系统补录”兜底", "f14"],
            ["3", "关键原因没有作为结构化字段随业务流转，客服查单看不到完整原因，只能再问调度", "f14"],
            ["4", "客服催单中约 60% 只是问“到哪里”，重复查 TMS 与群消息最占时间", "f12"],
            ["5", "司机上报应做到安全停车后 1–2 个动作完成，原因要能直接带进查单回复", "f11、f14"],
        ],
        widths=[1.6, 10.4, 3.2],
    )

    # ---------------- 二、典型事件一 ----------------
    doc.add_heading("二、典型事件一：客户临时改地址", level=1)
    add_paragraph(
        doc,
        "这是受访人主动选择的“比较典型”的一次异常：司机在途、原目的地已经排好卸货，客户突然要求更换收货点。"
        "该事件集中暴露了安全约束、处理方式差异、原因非结构化、查单信息缺失和升级责任不清五个问题。",
    )

    add_caption(doc, "表 3  事件基本信息")
    add_table(
        doc,
        ["字段", "内容"],
        [
            ["事件类型", "客户临时改地址（收货点变更）"],
            ["发生环节", "在途运输、原目的地已排卸货"],
            ["触发方", "客户"],
            ["涉及角色", "客户、司机、现场调度、客服"],
            ["现场处理方式", "司机群聊反馈 → 调度在群聊/个人表补说明 → 回系统补录"],
            ["系统记录情况", "关键原因未作为结构化字段留存，查单时不可见"],
            ["安全前置条件", "必须让司机先安全停车后再反馈，不能边开边处理"],
            ["证据", "logistics-f11、logistics-f14"],
        ],
        widths=[3.4, 11.8],
    )

    add_caption(doc, "表 4  事件经过（按访谈还原）")
    add_table(
        doc,
        ["时点", "发生了什么", "现场动作", "暴露的问题"],
        [
            ["T0", "客户提出更换收货点", "客户联系客服/调度", "变更请求没有标准入口"],
            ["T1", "司机在途，原目的地已排卸货", "调度先确认车辆位置与安全状态", "边开边处理存在安全风险"],
            ["T2", "要求司机安全停车", "电话/语音通知司机", "停车后才能反馈，时效被拉长"],
            ["T3", "司机在群聊说明情况", "群消息，无固定字段", "原因停留在非结构化文本"],
            ["T4", "调度在群聊或个人表补说明", "人工补录", "信息分散，依赖个人习惯"],
            ["T5", "回系统补录", "事后补录，字段有限", "关键原因未随业务流转"],
            ["T6", "客服查单", "看不到完整原因", "只能再问调度"],
            ["T7", "二次往返", "调度翻群记录核对", "重复沟通、耗时增加"],
        ],
        widths=[1.2, 5.2, 4.4, 4.4],
    )

    add_caption(doc, "表 5  具体问题清单")
    add_table(
        doc,
        ["编号", "问题", "具体表现", "影响", "证据"],
        [
            ["P1", "安全约束强", "司机在途，必须先安全停车才能处理，不能边开边处理", "处理时效受安全要求约束，不能一味求快", "f11"],
            ["P2", "处理方式不可复用", "改地址与卸货排队、封路不是一套处理方式", "通用异常流程无法直接套用", "f11"],
            ["P3", "原因未结构化", "司机群聊说、调度在群聊/个人表补，再回系统补录", "关键原因不随业务走，无法统计与检索", "f14"],
            ["P4", "查单信息缺失", "客服查单看不到完整原因，只能再来问调度", "二次往返，客服与调度都耗时", "f14"],
            ["P5", "升级责任未定义", "改地址是否触发升级路由、由谁确认尚未明确", "现场只能继续靠群聊兜底", "f11"],
            ["P6", "补录负担重", "司机报一次不够，还要靠人补", "与“低负担采集”目标冲突", "f14"],
        ],
        widths=[1.2, 3.0, 5.7, 4.0, 1.4],
    )

    add_caption(doc, "表 6  本事件的量化信息")
    add_table(
        doc,
        ["指标", "已知信息", "口径/说明", "来源", "可信度"],
        [
            ["改地址事件频次", "未统计", "受访人明确没有准确次数", "f11", "缺失"],
            ["单次处理时长", "未统计", "需小范围计时记录", "f11", "缺失"],
            ["司机上报动作数", "目标 1–2 个动作", "安全停车后完成，属诉求而非现状", "f11、f14", "诉求"],
            ["原因结构化率", "现状为 0（群聊/个人表）", "关键原因未进入系统字段", "f14", "定性"],
            ["二次往返", "存在，未统计比例", "客服看不到原因 → 再问调度", "f14", "定性"],
        ],
        widths=[3.4, 4.2, 5.0, 1.6, 1.8],
    )

    add_paragraph(
        doc,
        "受访人对该事件的期望很明确：司机安全停车后一两个动作就能报完；改地址这类异常要明确是否触发升级、"
        "由谁确认；原因要能直接带进查单回复，而不是留在群聊里。",
    )

    # ---------------- 三、典型事件二 ----------------
    doc.add_heading("三、典型事件二：催单只问“到哪里”", level=1)
    add_paragraph(
        doc,
        "第二类高频消耗不是单次大异常，而是客服催单中的重复查询。受访人给出的唯一明确比例是："
        "催单里约 60% 只是问“到哪里”；重复查 TMS 和群消息最占时间。",
    )

    add_caption(doc, "表 7  事件与问题")
    add_table(
        doc,
        ["项目", "内容"],
        [
            ["场景", "客服催单，询问货物当前位置/进度"],
            ["现状做法", "调度分别查 TMS 与群消息，再人工回复客服"],
            ["量化信息", "60% 的催单只是问“到哪里”（受访人现场估计）"],
            ["主要问题", "同一信息重复查询；群消息与 TMS 割裂；无自助状态视图"],
            ["二次影响", "调度一边被催、一边翻群记录核对，挤占异常处理时间"],
            ["证据", "logistics-f12、logistics-f14"],
        ],
        widths=[3.0, 12.2],
    )

    add_caption(doc, "表 8  该场景的量化信息")
    add_table(
        doc,
        ["指标", "已知信息", "口径/说明", "来源", "可信度"],
        [
            ["“到哪里”类催单占比", "约 60%", "受访人现场估计；统计周期、样本量未提供", "f12", "待核实"],
            ["单次催单处理时长", "未统计", "需计时记录", "f12", "缺失"],
            ["重复查询次数", "未统计", "同一票多次查询的次数", "f12", "缺失"],
            ["查单一次解决率", "未统计", "一次回复即解决的比例", "f12", "缺失"],
        ],
        widths=[4.0, 3.4, 5.6, 1.6, 1.8],
    )

    # ---------------- 四、同类事件群 ----------------
    doc.add_heading("四、同类事件群：GPS 弱网与回执延迟", level=1)
    add_paragraph(
        doc,
        "受访人把 GPS 弱网、客户改地址、签收回执延迟归为同一类问题：同事先在群聊或个人表补说明，"
        "再回系统补录，关键原因没有结构化地跟着业务走。三者可共用一套“补录 + 查单”的改法。",
    )

    add_caption(doc, "表 9  同类事件对照")
    add_table(
        doc,
        ["事件", "现场处理", "共同问题", "证据"],
        [
            ["GPS 弱网", "群聊说明定位异常，事后补录", "原因非结构化、查单不可见", "f14"],
            ["客户改地址", "安全停车后群聊反馈，调度补表", "同上，且升级责任未定", "f11、f14"],
            ["签收回执延迟", "群聊/个人表补说明，回系统补录", "同上，回执状态与原因脱节", "f14"],
        ],
        widths=[3.6, 6.4, 5.2, 1.8],
    )

    # ---------------- 五、量化指标汇总 ----------------
    doc.add_heading("五、量化指标汇总", level=1)
    add_paragraph(
        doc,
        "下表把访谈中出现的数字、定性判断和缺失项分开列示。带“待核实”的指标需要在试点前做一次小范围"
        "计时记录；带“项目目标”的数值来自需求文档，不是本次访谈结论，不能混用。",
    )

    add_caption(doc, "表 10  访谈中出现的量化信息")
    add_table(
        doc,
        ["指标", "数值", "性质", "来源"],
        [
            ["“到哪里”类催单占比", "约 60%", "受访人现场估计，待核实", "f12"],
            ["司机单次上报动作数", "目标 1–2 个", "诉求/设计目标", "f11、f14"],
            ["改地址安全前置", "必须停车后处理", "硬性要求", "f11"],
            ["改地址频次、耗时", "未统计", "数据缺口", "f11"],
            ["催单耗时、二次往返率", "未统计", "数据缺口", "f12、f14"],
        ],
        widths=[4.4, 3.6, 6.0, 2.0],
    )

    add_caption(doc, "表 11  待验证指标与采集方法（建议）")
    add_table(
        doc,
        ["指标", "定义", "采集方法", "建议样本/周期", "责任人"],
        [
            ["改地址频次", "每周客户改地址事件数", "群记录/工单打标", "2 周", "现场调度"],
            ["改地址端到端时长", "客户提出 → 司机确认 → 系统更新", "逐单计时", "20 起", "调度 + 客服"],
            ["催单平均处理时长", "客服发起 → 回复完成", "工单时间戳", "50 起", "客服主管"],
            ["二次往返率", "同票再次询问次数 / 总查单数", "会话与工单关联", "2 周", "客服主管"],
            ["原因结构化率", "有结构化原因的异常 / 总异常", "系统字段统计", "持续", "产品/研发"],
            ["司机上报动作数", "停车后到提交完成的操作步数", "现场观察", "10 名司机", "现场调度"],
        ],
        widths=[3.6, 4.6, 4.0, 2.4, 2.2],
    )

    add_caption(doc, "表 12  与项目目标的对应（来源：需求文档，非访谈数据）")
    add_table(
        doc,
        ["项目目标", "目标值", "说明"],
        [
            ["异常首次响应", "90 分钟 → 15 分钟", "业务目标；15 分钟指被具名责任人受理"],
            ["首次响应硬性时限", "30 分钟", "超时自动升级，与 15 分钟目标分层"],
            ["处置结论", "2 小时内", "受理后计时"],
            ["预警误报率", "≤ 10%", "误报 /（确认 + 误报）"],
            ["回放验收样本", "20 票、近两周", "试点前历史回放"],
        ],
        widths=[4.0, 4.4, 7.0],
    )

    # ---------------- 六、根因分析 ----------------
    doc.add_heading("六、根因分析", level=1)
    add_paragraph(
        doc,
        "把两个事件放在一起看，问题不在“客服不努力”或“调度不配合”，而在信息在流转过程中不断落到"
        "非结构化的群聊和个人表里。",
    )

    add_caption(doc, "表 13  根因分解")
    add_table(
        doc,
        ["层面", "根因", "访谈证据", "造成的后果"],
        [
            ["流程", "异常处理没有标准入口，靠群聊兜底", "f14", "处理过程不可追踪"],
            ["数据", "关键原因没有结构化字段", "f14", "无法统计、无法检索、无法复用"],
            ["系统", "TMS、群消息、个人表相互割裂", "f12、f14", "客服查单要多次切换"],
            ["组织", "改地址是否升级、由谁确认未定义", "f11", "只能继续问人"],
            ["工具", "司机上报动作多、需二次补录", "f14", "违背低负担采集"],
        ],
        widths=[1.8, 6.2, 3.6, 5.2],
    )

    # ---------------- 七、改进建议 ----------------
    doc.add_heading("七、改进建议与系统映射", level=1)
    add_paragraph(
        doc,
        "改进思路不是“再做一个群”，而是把群聊里的关键信息变成结构化字段，让它在查单、统计和升级时"
        "可以直接使用；同时把司机上报压缩到停车后 1–2 个动作。",
    )

    add_caption(doc, "表 14  问题—措施—系统功能—验收指标")
    add_table(
        doc,
        ["问题", "改进措施", "对应系统功能", "验收指标"],
        [
            ["P1 安全约束", "上报入口前置“已安全停车”确认", "司机端极简上报", "违规边开边报 = 0"],
            ["P3 原因非结构化", "改地址原因做成枚举字段，随单流转", "异常事件结构化（四要素 + 原因码）", "原因结构化率"],
            ["P4 查单缺原因", "查单页直接展示异常原因与时间线", "查单证据包 / 草稿引用", "二次往返率下降"],
            ["P5 升级责任", "定义改地址升级规则与确认人", "自动路由 + 通知 + 交接留痕", "升级响应时长"],
            ["P6 补录负担", "司机 1–2 动作完成，调度只补例外", "低负担采集 + 修复队列", "上报动作数 ≤ 2"],
            ["催单重复查询", "提供状态自助与证据化查单草稿", "状态查询 + 查单草稿", "“到哪里”类催单占比下降"],
        ],
        widths=[2.8, 5.6, 5.2, 3.2],
    )

    # ---------------- 八、度量与验证 ----------------
    doc.add_heading("八、度量与验证方案", level=1)
    add_paragraph(
        doc,
        "访谈中的数字只能作为假设。建议在试点前做一次小范围计时记录，把“感受”变成“可复核的数”。",
    )
    add_bullets(doc, [
        "假设 1：改地址类事件单次端到端处理超过 2 小时；验证方式：20 起逐单计时。",
        "假设 2：客服查单存在二次往返，且比例不低于 30%；验证方式：2 周会话与工单关联统计。",
        "假设 3：司机上报步骤可从“群聊 + 补录”压缩到 2 步以内；验证方式：10 名司机现场观察。",
    ])

    add_caption(doc, "表 15  验证记录字段（建议）")
    add_table(
        doc,
        ["字段", "说明"],
        [
            ["事件编号", "与运单号关联"],
            ["发生时间 / 受理时间", "用于计算首响"],
            ["处理人", "具名责任人"],
            ["原因码", "枚举，不允许只写自由文本"],
            ["是否二次往返", "客服是否再次询问"],
            ["是否触发升级", "改地址等高风险事件"],
        ],
        widths=[4.2, 10.8],
    )

    # ---------------- 九、待确认 ----------------
    doc.add_heading("九、待确认事项", level=1)
    confirm_table = add_table(
        doc,
        ["编号", "待确认问题", "需谁确认", "影响"],
        [
            ["Q1", "改地址是否触发升级路由，由谁最终确认", "顾明岚、唐映秋", "决定异常路由与责任边界"],
            ["Q2", "“60% 催单问到哪里”的统计周期与样本", "客服主管", "决定指标可信度"],
            ["Q3", "是否允许做小范围计时记录及隐私边界", "业务负责人", "决定能否验证耗时"],
            ["Q4", "15 分钟首响的分母、周期、排除规则", "运输负责人", "决定验收口径"],
        ],
        widths=[1.2, 7.0, 4.0, 4.6],
    )
    # 小表不分页：除最后一行外都与下一行同页
    for row in confirm_table.rows[:-1]:
        for cell in row.cells:
            for paragraph in cell.paragraphs:
                paragraph.paragraph_format.keep_with_next = True

    # ---------------- 附录 ----------------
    doc.add_heading("附录 A  访谈原文摘录", level=1)
    add_paragraph(doc, "以下为受访人原话节选，保留口语表达，未做改写。", indent=False)
    quotes = [
        "“我讲一个比较典型的：客户临时改地址。司机在途，原目的地已经排好卸货，客户突然要求换收货点……”",
        "“得先让司机安全停车后再反馈，不能边开边处理。”",
        "“司机在群里说一声，我在群聊或个人表里补说明，再回系统补录，关键原因没有作为结构化字段跟着业务走。”",
        "“客服查单时看不到完整原因，只能再来问我；我这边又得翻群记录核对。”",
        "“客服催单里，60% 只是问‘到哪里’，重复查 TMS 和群消息最占时间。”",
        "“司机能不能安全停车后一两个动作就报完，而不是多填表。”",
        "“具体次数、耗时我手上没有准确统计，尚未核实，不能给你编数字。”",
    ]
    for text in quotes:
        paragraph = doc.add_paragraph()
        paragraph.paragraph_format.left_indent = Cm(0.6)
        paragraph.paragraph_format.line_spacing = 1.4
        run = paragraph.add_run(text)
        set_run_font(run, "楷体", 10.5)

    doc.add_heading("附录 B  引用事实对照", level=1)
    add_table(
        doc,
        ["编号", "事实内容", "出处"],
        [
            ["logistics-f11", "客户临时改地址；须安全停车后反馈；与排队/封路处理方式不同；升级路由未定", "turn-2"],
            ["logistics-f12", "催单中 60% 只是问“到哪里”；重复查 TMS 与群消息最耗时", "turn-4"],
            ["logistics-f14", "群聊/个人表补说明再回系统补录；原因未结构化；客服二次往返；GPS 弱网/回执延迟同类", "turn-2、turn-4"],
        ],
        widths=[3.2, 10.6, 2.6],
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUT)
    return OUT


if __name__ == "__main__":
    path = build()
    print(f"saved: {path}")
