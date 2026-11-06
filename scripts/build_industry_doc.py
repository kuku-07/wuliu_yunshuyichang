"""生成《运输异常管理行业分析报告》docx。

行业数据来自中国物流与采购联合会公开通报（2024 年数据），
项目相关判断来自 docs 下案例包与访谈；所有假设均标注。
"""
from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

OUT = Path(r"D:\wuliu_yunshuyichang\docs\运输异常管理行业分析报告.docx")

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
        style.paragraph_format.space_before = Pt(12 if name == "Heading 1" else 8)
        style.paragraph_format.space_after = Pt(5)
        style.paragraph_format.keep_with_next = True

    section = doc.sections[0]
    section.page_width = Cm(21)
    section.page_height = Cm(29.7)
    section.top_margin = Cm(2.2)
    section.bottom_margin = Cm(2.0)
    section.left_margin = Cm(2.4)
    section.right_margin = Cm(2.2)


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
    paragraph.paragraph_format.line_spacing = 1.1
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
        if total > 16.0:
            widths = [w * 16.0 / total for w in widths]
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


def p(doc, text, indent=True, size=10.5, bold=False):
    paragraph = doc.add_paragraph()
    if indent:
        paragraph.paragraph_format.first_line_indent = Cm(0.74)
    run = paragraph.add_run(text)
    set_font(run, "宋体", size, bold=bold)


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


def build():
    doc = Document()
    apply_styles(doc)
    add_page_number(doc.sections[0])

    # ---------- 封面 ----------
    doc.add_paragraph().paragraph_format.space_before = Pt(80)
    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run("运输异常管理行业分析报告")
    set_font(run, "微软雅黑", 25, bold=True, color=NAVY)

    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = sub.add_run("从「看得见」到「处置得了」：异常闭环的机会与边界")
    set_font(run, "微软雅黑", 12.5, color=GRAY)

    doc.add_paragraph().paragraph_format.space_before = Pt(42)
    meta = [
        ("研究主题", "运输异常管理与签收协作的数字化、智能化机会"),
        ("数据口径", "中国物流与采购联合会 2024 年公开数据及 2024–2025 年报告"),
        ("案例样本", "远川物流「一票货的最后一公里」及现场调度访谈"),
        ("文档版本", "v1.0"),
        ("编制日期", "2026-11-06"),
    ]
    t = doc.add_table(rows=0, cols=2)
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for key, value in meta:
        cells = t.add_row().cells
        cell_text(cells[0], key, 9.5, bold=True, color=NAVY)
        cell_text(cells[1], value, 9.5)
        cells[0].width = Cm(3.2)
        cells[1].width = Cm(12.2)
        shade(cells[0], HEAD_FILL)

    note = doc.add_paragraph()
    note.paragraph_format.space_before = Pt(24)
    note.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = note.add_run(
        "说明：行业数据来自公开通报，项目判断来自案例包与访谈；\n"
        "商业模型为示例假设，均已标注，不作为承诺。"
    )
    set_font(run, "宋体", 9, color=GRAY)
    doc.add_page_break()

    # ---------- 一、执行摘要 ----------
    h1(doc, "一、执行摘要")
    p(doc, "中国物流业已是世界最大市场，但“规模大、利润薄、异常多”的结构性矛盾仍然突出。"
           "2024 年社会物流总额 360.6 万亿元，物流业总收入 13.8 万亿元，社会物流总费用与 GDP 的比率为 14.1%。"
           "在运输环节，公路运输费用约占运输总费用的 75%，是成本与体验的主要战场。")
    p(doc, "行业数字化过去十年主要解决“看得见”：TMS、GPS、控制塔、网络货运平台把在途状态搬到线上。"
           "但“看得见”不等于“处置得了”：异常仍然靠群聊、电话和表格流转，查单仍然靠问人，"
           "签收与回执仍然靠催。异常处置这一段，是数字化投入最薄、却直接影响客户体验的环节。")
    p(doc, "本报告的五个判断：")
    bullets(doc, [
        "市场足够大，但通用 TMS 已进入存量竞争；增量机会在“异常处置 + 签收回执”这类深水区。",
        "异常管理的核心不是生成一段话，而是把事件结构化、责任到人、证据可追溯，并允许人工接管。",
        "大模型适合做理解、抽取、检索与草稿，不适合做判责、扣罚、对外承诺；边界必须写进产品。",
        "客户愿意为“少一次客户投诉、少一次重复查单”付费，而不是为“又一个聊天框”付费。",
        "区域 3PL、专线与货主物流部是最现实的切入点；单点闭环、按票/按坐席计费比大平台更可行。",
    ])

    # ---------- 二、范围与方法 ----------
    h1(doc, "二、研究范围与方法")
    h2(doc, "2.1 行业界定")
    p(doc, "本报告聚焦公路运输中的“运输异常管理与签收协作”，包括在途异常（延误、改地址、货损、事故、"
           "GPS 弱网）、签收与回执（签收单、回单、代收）、以及围绕这些事件的查单、催单、交接与审计。"
           "不覆盖仓储内部作业、快递末端派送、海运与空运的独立系统。")
    h2(doc, "2.2 方法")
    p(doc, "采用“公开数据 + 案例访谈 + 产品拆解”三结合：公开数据用来说明行业规模与结构；"
           "案例访谈用来说明现场真实流程与痛点；产品拆解用来说明竞争格局与空白点。"
           "案例部分只有现场调度员一个角色的两轮访谈，其余角色为待核实假设，不能当作行业结论。")
    h2(doc, "2.3 局限")
    bullets(doc, [
        "行业缺少“异常处置成本”的统一统计口径，本报告不做全行业异常成本测算。",
        "TMS 与 AI 在物流的渗透率缺乏权威统一数据，本报告只做定性判断。",
        "案例为合成训练资料，不代表真实授权、业务执行或客户验收。",
    ])

    # ---------- 三、行业概况 ----------
    h1(doc, "三、行业概况")
    h2(doc, "3.1 市场规模")
    caption(doc, "表 3-1  2024 年中国物流业关键指标")
    table(doc,
          ["指标", "数值", "同比", "含义"],
          [
              ["社会物流总额", "360.6 万亿元", "+5.8%", "物流需求总规模，首超 360 万亿"],
              ["物流业总收入", "13.8 万亿元", "+4.9%", "行业收入盘子"],
              ["社会物流总费用", "19.0 万亿元", "+4.1%", "全社会物流成本"],
              ["物流费用/GDP", "14.1%", "-0.3 个百分点", "效率改善，仍高于发达国家"],
              ["运输费用", "10.3 万亿元", "+5.0%", "占社会物流总费用约 54%"],
              ["快递业务量", "1750 亿件", "+20% 以上", "连续 11 年世界第一"],
              ["网络货运企业", "3286 家", "持续增加", "公路运输平台化基础"],
          ],
          widths=[4.0, 3.6, 3.0, 5.4])

    h2(doc, "3.2 成本结构：公路是主战场")
    p(doc, "2024 年前三季度，社会物流总费用 13.4 万亿元，其中运输费用 7.5 万亿元，占 55.9%；"
           "运输费用中公路运输费用约占 75%，占社会物流总费用的比例约 40%。"
           "这意味着：降低公路运输的异常与返工，直接作用于最大的成本项。")
    caption(doc, "表 3-2  社会物流总费用结构（2024 年前三季度）")
    table(doc,
          ["费用项", "金额", "占比", "备注"],
          [
              ["运输费用", "7.5 万亿元", "55.9%", "其中公路约占运输费用的 75%"],
              ["保管费用", "—", "—", "仓储、库存相关"],
              ["管理费用", "—", "—", "物流管理相关"],
              ["社会物流总费用", "13.4 万亿元", "100%", "前三季度口径"],
          ],
          widths=[4.2, 3.4, 2.6, 5.8])

    h2(doc, "3.3 数字化基础")
    p(doc, "截至 2024 年底，A 级物流企业首次突破 1 万家，5A 级超过 500 家；规模以上物流园区 2769 个；"
           "全国 3286 家企业取得网络货运经营资质，77% 的平台注册车辆数超过 1 万辆。"
           "基础设施与平台化已经具备，但系统能力集中在“交易、调度、可视化”，异常处置仍是短板。")

    # ---------- 四、异常管理 ----------
    h1(doc, "四、异常管理：被低估的环节")
    h2(doc, "4.1 异常类型与发生环节")
    caption(doc, "表 4-1  运输异常的主要类型")
    table(doc,
          ["类型", "发生环节", "现场处理", "AI 可做", "AI 不可做"],
          [
              ["延误", "在途、到达", "查轨迹、打电话、群里说明", "识别、预警、生成说明草稿", "承诺到达时间"],
              ["客户改地址", "在途、卸货前", "安全停车、群聊反馈、补录", "识别、升级、留痕", "替客户确认变更"],
              ["货损/赔付", "装卸、在途", "拍照、定责、走理赔", "归集证据、提示流程", "判责、承诺金额"],
              ["签收回执延迟", "签收后", "催回单、补拍、群里催", "预警、生成催办草稿", "代替签收"],
              ["GPS 弱网", "在途", "电话确认位置、事后补录", "识别异常、提示人工核实", "推断位置"],
              ["拒收/退货", "到达", "现场沟通、返程安排", "记录原因、生成交接摘要", "单方面决定退货"],
          ],
          widths=[2.8, 2.8, 4.6, 3.4, 3.0])

    h2(doc, "4.2 现状：异常活在群聊里")
    p(doc, "受访现场调度员的原话是：司机在群里说一声，调度在群聊或个人表里补说明，再回系统补录；"
           "关键原因没有作为结构化字段跟着业务走，客服查单看不到完整原因，只能再来问调度（logistics-f14）。"
           "这不是某一家企业的问题，而是行业普遍的组织习惯：系统负责“记录结果”，群聊负责“传递过程”。")
    p(doc, "由此产生三类损耗：一是重复查询，客服催单里约 60% 只是问“到哪里”；"
           "二是二次往返，客服找不到原因就回头问调度；三是复核成本，事后要翻群记录对账。"
           "这三类损耗不产生收入，却持续占用一线时间。")

    h2(doc, "4.3 成本与指标")
    p(doc, "行业没有统一的“异常成本”口径，本报告建议用四个可测指标替代模糊感受："
           "异常首次响应时长、二次往返率、回执及时率、预警误报率。"
           "这四个指标都能从系统里直接算，也都能对应到具体角色。")
    caption(doc, "表 4-2  建议的异常管理指标")
    table(doc,
          ["指标", "定义", "数据来源", "用途"],
          [
              ["首次响应时长", "异常发生 → 具名责任人受理", "异常事件表", "衡量组织响应速度"],
              ["二次往返率", "同票再次询问次数 / 总查单数", "会话 + 工单", "衡量信息是否一次给全"],
              ["回执及时率", "24 小时内回传回执 / 应回执票数", "签收与回执记录", "衡量签收闭环"],
              ["预警误报率", "误报 /（确认 + 误报）", "预警处置记录", "衡量预警可信度"],
          ],
          widths=[3.0, 6.2, 3.8, 3.0])

    # ---------- 五、技术趋势 ----------
    h1(doc, "五、技术趋势")
    h2(doc, "5.1 从可视化到闭环")
    p(doc, "运输数字化大致经历四个阶段：单点系统（TMS/WMS）→ 全程可视（GPS/控制塔）→ 协同平台（网络货运/承运商协同）"
           "→ 异常闭环（结构化、路由、草稿、接管、审计）。前三个阶段解决“看见”，第四个阶段解决“处置”。"
           "大模型的出现，让第四阶段第一次具备了可落地的成本结构。")
    caption(doc, "表 5-1  运输数字化的四个阶段")
    table(doc,
          ["阶段", "核心能力", "代表形态", "主要瓶颈"],
          [
              ["单点系统", "订单、调度、结算", "TMS、WMS", "数据孤岛"],
              ["全程可视", "轨迹、位置、时效", "GPS、控制塔", "看见但管不了"],
              ["协同平台", "运力交易、承运商协同", "网络货运平台", "异常仍靠人"],
              ["异常闭环", "结构化、路由、草稿、接管", "异常协作智能体", "数据质量与责任边界"],
          ],
          widths=[3.0, 5.4, 4.4, 3.2])

    h2(doc, "5.2 大模型的适用边界")
    p(doc, "在运输异常场景，大模型最适合做“理解与表达”，最不适合做“裁决与承诺”。"
           "把边界写进产品，比追求“更智能”更重要。")
    caption(doc, "表 5-2  能做与不能做")
    table(doc,
          ["适合 AI", "不适合 AI", "原因"],
          [
              ["从群聊/工单中抽取事件要素", "判定货损责任", "责任涉及商务与法律"],
              ["检索规则并生成带引用的草稿", "承诺赔付金额", "金额是承诺，需授权"],
              ["识别改地址/危险品等高风险意图", "替客户确认改地址", "变更改变线路与责任"],
              ["生成交接摘要与催办话术", "直接对客户发送", "口径与合规风险"],
              ["预警与异常聚类", "自动扣罚承运商", "扣罚需制度授权"],
          ],
          widths=[5.4, 5.2, 5.4])

    h2(doc, "5.3 参考架构：两个入口，一个大脑")
    p(doc, "可落地的架构通常分四层：入口层（员工端与管理端）、服务层（FastAPI 等）、"
           "编排层（闸门→检索→证据→生成→护栏）、数据层（业务库 + 规则库 + 模型）。"
           "两个入口共用一套服务与审计，权限由账号角色决定，入口只决定落地页。"
           "对外部系统只读，写操作一律回到人工。")

    h2(doc, "5.4 数据与合规")
    bullets(doc, [
        "数据分级：公开（规则条文）、内部（运单与对话）、敏感（客户信息、赔付、事故）。",
        "最小化与脱敏：模型只拿到完成任务所需字段；导出脱敏；敏感字段不进提示词。",
        "本地化：检索与 embedding 本地部署；模型可切换本地 Ollama/vLLM，接口保持 OpenAI 兼容。",
        "可追溯：引用带来源、版本、数据时间；关键操作写审计；留存期限可配置。",
    ])

    # ---------- 六、竞争格局 ----------
    h1(doc, "六、竞争格局")
    h2(doc, "6.1 三类玩家")
    p(doc, "运输管理市场大致有三类玩家：TMS/控制塔厂商、平台型玩家、AI 原生/垂直方案。"
           "三类玩家的强项不同，短期谁也替代不了谁。")
    caption(doc, "表 6-1  竞争格局")
    table(doc,
          ["类型", "代表形态", "强项", "短板", "与本项目的关系"],
          [
              ["TMS/控制塔厂商", "唯智、oTMS、G7、菜鸟、京东物流等", "客户基础、系统集成、运单数据", "异常处置与证据链不是主打", "集成对象/渠道"],
              ["平台型玩家", "满帮、货拉拉、网络货运平台", "运力、交易、司机触达", "货主侧异常闭环不是重点", "场景入口"],
              ["AI 原生/垂直方案", "异常协作、查单助手类产品", "异常结构化、草稿、接管", "数据与客户积累较少", "差异化竞争"],
          ],
          widths=[3.6, 5.2, 4.4, 3.0, 2.8])

    h2(doc, "6.2 空白点")
    p(doc, "把三类玩家放在一张能力表上，空白点很清楚：")
    caption(doc, "表 6-2  能力对比")
    table(doc,
          ["能力", "TMS 厂商", "平台型", "AI 原生", "客户真实需求"],
          [
              ["在途可视化", "强", "强", "弱", "基础能力"],
              ["异常结构化", "中", "弱", "强", "高"],
              ["查单证据链", "弱", "弱", "强", "高"],
              ["签收回执闭环", "中", "弱", "中", "高"],
              ["人工接管与审计", "中", "弱", "强", "高"],
              ["模型与规则可配置", "弱", "弱", "强", "中"],
          ],
          widths=[3.6, 3.0, 2.8, 2.8, 3.8])

    # ---------- 七、政策与合规 ----------
    h1(doc, "七、政策与合规")
    p(doc, "运输异常涉及运单、客户信息、签收凭证与责任认定，合规不是附加项，而是产品设计的前置条件。")
    caption(doc, "表 7-1  主要法规与影响")
    table(doc,
          ["法规/政策", "核心要求", "对产品的影响"],
          [
              ["《网络平台道路货物运输经营管理暂行办法》", "网络货运资质、运单上传、数据留存", "平台型客户需对接运单与轨迹数据"],
              ["《数据安全法》", "数据分类分级、境内存储、安全评估", "数据分级与本地化部署"],
              ["《个人信息保护法》", "最小必要、告知同意", "司机与客户信息脱敏、最小化"],
              ["《电子签名法》", "可靠电子签名与手写签名同等效力", "电子回执的合法性与存证"],
              ["《道路运输条例》", "承运责任与安全管理", "异常处置不能替代法定责任"],
              ["《“十四五”现代物流发展规划》", "数字化转型、降本增效", "政策鼓励，但需可验证的降本"],
          ],
          widths=[5.4, 5.6, 5.0])

    # ---------- 八、机会与商业模式 ----------
    h1(doc, "八、市场机会与商业模式")
    h2(doc, "8.1 目标客户")
    p(doc, "最现实的客户不是头部平台，而是“有异常、有客服、有系统但系统不管异常”的三类组织："
           "区域 3PL、专线/车队、货主物流部。它们的共同特征是：运单量中等、异常高频、IT 预算有限、决策链短。")
    caption(doc, "表 8-1  目标客户画像")
    table(doc,
          ["客户类型", "典型规模", "核心痛点", "付费能力"],
          [
              ["区域 3PL", "年运单 5–50 万票", "异常靠群、查单靠问、回执靠催", "中"],
              ["专线/车队", "年运单 1–10 万票", "调度兼客服、无系统", "低–中"],
              ["货主物流部", "年运输预算 0.5–5 亿", "承运商多、口径不一、审计压力", "中–高"],
          ],
          widths=[3.4, 4.4, 6.2, 2.0])

    h2(doc, "8.2 付费模式")
    bullets(doc, [
        "按票计费：适合 3PL 与专线，单价低、随量增长，客户接受度高。",
        "按坐席计费：适合客服/调度团队，强调“每人每天少查几次”。",
        "私有化/项目制：适合货主物流部与大型 3PL，客单价高、实施周期长。",
        "增值服务：回执代催、异常报告、合规审计包。",
    ])

    h2(doc, "8.3 单位经济模型（示例假设）")
    p(doc, "以下数字仅用于说明商业逻辑，不是报价或承诺，需要用真实客户验证。")
    caption(doc, "表 8-2  示例模型（假设）")
    table(doc,
          ["项目", "假设值", "说明"],
          [
              ["年客单价", "5 万元", "按 20 万票/年、0.25 元/票估算"],
              ["实施成本", "3 万元", "接口对接 + 流程配置"],
              ["毛利率", "60%", "扣除模型、云资源与实施"],
              ["获客成本", "2 万元", "区域销售 + 试点"],
              ["回本周期", "约 12 个月", "按首年收入与实施成本估算"],
          ],
          widths=[3.6, 3.6, 8.6])

    h2(doc, "8.4 进入策略")
    p(doc, "不建议一上来做“全链路控制塔”。更可行的路径是：选一个干线、一个客户、一个高频异常（改地址或回执），"
           "用 4–6 周做出“异常结构化 + 查单草稿 + 回执催办”的闭环，用首响与二次往返两个指标证明价值，再复制。")

    # ---------- 九、风险 ----------
    h1(doc, "九、风险与挑战")
    caption(doc, "表 9-1  主要风险")
    table(doc,
          ["风险", "表现", "应对"],
          [
              ["数据接口不可得", "TMS 不开放、字段缺失", "先只读样本/导出，接口联调前置"],
              ["组织责任不清", "改地址谁确认、异常谁负责", "先定流程与责任人，再上系统"],
              ["误报损伤信任", "预警太多、一线关掉", "误报率阈值 + 熔断 + 人工确认"],
              ["模型幻觉", "编造时效、金额", "引用 + 护栏 + 红线不调模型"],
              ["合规与隐私", "客户信息、司机信息", "分级、脱敏、本地化、审计"],
              ["巨头竞争", "TMS 厂商内置 AI", "做深异常闭环与证据链，做集成而非替代"],
              ["付费意愿低", "客户认为“本该免费”", "用可量化指标证明 ROI，按票计费"],
          ],
          widths=[3.6, 6.0, 6.4])

    # ---------- 十、启示 ----------
    h1(doc, "十、对本项目的启示")
    p(doc, "把行业判断落到本项目，优先级应该是“先闭环、后智能”：")
    caption(doc, "表 10-1  行业结论 → 项目动作")
    table(doc,
          ["行业结论", "项目动作", "优先级"],
          [
              ["异常活在群聊里", "异常四要素结构化 + 修复队列", "P0"],
              ["查单靠问人", "证据包 + 带引用的查单草稿", "P0"],
              ["责任边界不清", "自动路由 + 受理/转交 + 超时升级", "P0"],
              ["误报会杀死信任", "预警人工确认 + 误报率熔断", "P1"],
              ["司机不愿填表", "停车确认 + 1–2 个动作上报", "P1"],
              ["合规是前置条件", "只读、脱敏、审计、留存审批", "P0"],
              ["客户为结果付费", "首响、二次往返、回执及时率作为验收", "P1"],
          ],
          widths=[5.6, 8.4, 1.8])

    # ---------- 十一、结论 ----------
    h1(doc, "十一、结论")
    bullets(doc, [
        "运输异常管理是物流数字化中“投入最少、影响最直接”的环节，市场足够大，且尚未被通用 TMS 覆盖。",
        "机会不在“再做一个聊天机器人”，而在“结构化 + 证据链 + 人工接管 + 审计”的闭环。",
        "大模型应被约束在理解与草稿层，判责、承诺、对外发送必须留给人工与制度。",
        "最先跑通的客户是区域 3PL 与专线；最先证明的指标是首响、二次往返、回执及时率。",
        "行业仍缺统一口径与真实样本，任何“降本 X%”的说法都应先做基线，再谈结论。",
    ])

    # ---------- 附录 ----------
    h1(doc, "附录 A  参考资料")
    table(doc,
          ["资料", "发布方/时间", "用途"],
          [
              ["2024 年全国物流运行情况通报", "国家发展改革委经贸司、中国物流与采购联合会，2025-02", "规模、费用、收入数据"],
              ["中国物流与供应链发展报告（2024—2025）", "中国物流与采购联合会，2025-06", "市场规模、快递、园区、A 级企业"],
              ["2024 中国物流平台发展报告", "中国物流与采购联合会，2024-12", "网络货运企业数量、公路费用占比"],
              ["远川物流案例包 logistics-01~04", "合成训练资料", "客户问题、角色、边界"],
              ["现场调度访谈 turn-2 / turn-4", "2026-11-06", "改地址、催单、补录痛点"],
          ],
          widths=[6.0, 6.0, 4.0])

    p(doc, "参考链接：", indent=False, size=9.5)
    bullets(doc, [
        "http://chinawuliu.com.cn/xsyj/202502/11/644819.shtml",
        "http://www.chinawuliu.com.cn/lhhzq/202506/27/651947.shtml",
        "http://www.chinawuliu.com.cn/lhhzq/202412/19/642560.shtml",
    ])

    h1(doc, "附录 B  术语")
    table(doc,
          ["术语", "含义"],
          [
              ["TMS", "运输管理系统，负责订单、调度、在途与结算"],
              ["控制塔", "跨系统汇总运输状态的可视化与调度中心"],
              ["网络货运", "以平台方式整合运力、承接公路运输业务的业态"],
              ["回执", "签收后返回的单据或电子凭证"],
              ["异常闭环", "从发现、结构化、分派、处置到审计的完整链路"],
          ],
          widths=[3.4, 12.2])

    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUT)
    return OUT


if __name__ == "__main__":
    path = build()
    print("saved:", path)
