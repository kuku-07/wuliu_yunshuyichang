"""生成《运输异常协作智能体系统 · 报价与投入产出测算》docx。"""
from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

OUT = Path(r"D:\wuliu_yunshuyichang\docs\运输异常协作系统-报价与投入产出测算.docx")

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


def build():
    doc = Document()
    apply_styles(doc)
    add_page_number(doc.sections[0])

    # 封面
    doc.add_paragraph().paragraph_format.space_before = Pt(70)
    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run("运输异常与签收协作智能体系统")
    set_font(run, "微软雅黑", 22, bold=True, color=NAVY)
    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = sub.add_run("报价与投入产出测算")
    set_font(run, "微软雅黑", 20, bold=True, color=NAVY)
    sub2 = doc.add_paragraph()
    sub2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = sub2.add_run("低 / 中 / 高三档 · 一次性投入 · 年运行成本 · ROI 与敏感性")
    set_font(run, "微软雅黑", 11, color=GRAY)

    doc.add_paragraph().paragraph_format.space_before = Pt(38)
    meta = [
        ("报价版本", "v1.0（基于阶段 0 设计方案）"),
        ("编制日期", "2026-11-06"),
        ("报价口径", "人民币、含税；人力单价按 4.5 万元/人月估算"),
        ("适用范围", "单干线试点；年运单约 20 万票；10–20 并发"),
        ("说明", "价格为区间报价，最终以需求确认与接口评估为准"),
    ]
    t = doc.add_table(rows=0, cols=2)
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for key, value in meta:
        cells = t.add_row().cells
        cell_text(cells[0], key, 9.5, bold=True, color=NAVY)
        cell_text(cells[1], value, 9.5)
        cells[0].width = Cm(3.2)
        cells[1].width = Cm(12.8)
        shade(cells[0], HEAD_FILL)

    doc.add_page_break()

    # 一、报价说明
    h1(doc, "一、报价说明与测算口径")
    p(doc, "本报价以《运输异常协作系统-项目设计方案（阶段 0）》为范围基线，按“低 / 中 / 高”三档给出一次性投入、"
           "年度运行成本与投入产出测算。三档不是简单的功能加减，而是对应三种落地策略：")
    bullets(doc, [
        "低档（试点验证）：只做规则问答 + 查单草稿 + 基础审计，用最小成本验证“有没有用”。",
        "中档（标准落地）：补齐异常结构化、路由、升级、预警、指标与双入口，是推荐方案。",
        "高档（企业集成）：在中档基础上接真实 TMS/GPS/IM、SSO、多线路/多租户与高可用，适合多干线复制。",
    ])
    p(doc, "测算口径统一为：人力 4.5 万元/人月（含税、管理、基础差旅）；一次性投入含需求、开发、测试、实施与培训；"
           "年度运行成本含维保、模型/云资源；收益只计可量化的工时节省，不计客户留存、投诉下降与赔付减少。")

    # 二、三档总览
    h1(doc, "二、三档方案总览")
    caption(doc, "表 1  三档报价总览（单位：万元）")
    table(doc,
          ["档位", "定位", "人力投入", "一次性报价", "年运行成本", "交付周期", "支持"],
          [
              ["低", "单线试点 / POC", "1.5 人月", "9.8（区间 8–12）", "2.07", "4–6 周", "1 个月 5×8"],
              ["中", "标准落地（推荐）", "5 人月", "28（区间 25–35）", "5.70", "10–12 周", "6 个月 5×8"],
              ["高", "企业集成 / 多干线", "10 人月", "58（区间 50–70）", "13.44", "16–20 周", "12 个月 7×12"],
          ],
          widths=[1.2, 4.0, 2.2, 3.6, 2.4, 2.0, 2.8], size=8.5)

    # 三、范围矩阵
    h1(doc, "三、范围对照矩阵")
    p(doc, "● 完整包含　◐ 简化/部分　○ 不包含")
    caption(doc, "表 2  功能范围对照")
    table(doc,
          ["模块", "低（试点）", "中（标准）", "高（企业）"],
          [
              ["规则知识库与版本审批", "●", "●", "●"],
              ["规则问答与引用", "●", "●", "●"],
              ["查单 / 催单草稿", "◐（仅查单）", "●", "●"],
              ["异常四要素与修复队列", "○", "●", "●"],
              ["自动路由 / 受理 / 转交 / 升级", "○", "●", "●"],
              ["异常预警与误报熔断", "○", "●", "●"],
              ["双入口（员工端 / 管理端）", "◐（仅员工端）", "●", "●"],
              ["账号 / 角色 / 线路权限", "◐（本地账号）", "●", "●"],
              ["审计与导出", "◐（基础）", "●", "●"],
              ["指标看板（首响 / 误报 / 回执）", "○", "●", "●"],
              ["TMS 真实接口联调", "○", "◐（样本/只读）", "●"],
              ["GPS / IM 接入", "○", "◐", "●"],
              ["SSO / 多租户 / 高可用", "○", "○", "●"],
              ["培训与运维 SLA", "1 次 / 1 个月", "2 次 / 6 个月", "4 次 / 12 个月"],
          ],
          widths=[6.4, 3.2, 3.4, 3.0], size=8.5)

    # 四、一次性投入
    h1(doc, "四、一次性投入明细")
    caption(doc, "表 3  一次性投入构成（单位：万元）")
    table(doc,
          ["投入项", "低", "中", "高", "说明"],
          [
              ["需求与方案", "0.9", "1.8", "3.5", "需求确认、流程梳理、接口评估"],
              ["开发（含前端）", "5.4", "18.0", "36.0", "按人月×4.5 万估算"],
              ["测试与文档", "0.8", "1.5", "2.5", "冒烟/回归、部署与运维文档"],
              ["实施与培训", "1.2", "2.5", "3.5", "环境搭建、数据初始化、培训"],
              ["集成联调", "0", "1.2", "5.0", "TMS/GPS/IM、SSO 等"],
              ["项目管理与税费", "1.5", "3.0", "7.5", "管理、差旅、税费"],
              ["合计", "9.8", "28.0", "58.0", "—"],
          ],
          widths=[3.4, 2.0, 2.0, 2.0, 7.0], size=8.5)

    # 五、年运行成本
    h1(doc, "五、年度运行成本")
    caption(doc, "表 4  年度运行成本（单位：万元/年）")
    table(doc,
          ["项目", "低", "中", "高", "口径"],
          [
              ["维保（一次性×比例）", "1.47（15%）", "4.20（15%）", "10.44（18%）", "缺陷修复、版本升级、远程支持"],
              ["模型 / 云资源", "0.60", "1.50", "3.00", "按 20 万票/年估算；本地部署可下降"],
              ["合计", "2.07", "5.70", "13.44", "—"],
          ],
          widths=[4.0, 2.6, 2.6, 2.6, 4.6], size=8.5)

    # 六、收益测算
    h1(doc, "六、投入产出测算")
    h2(doc, "6.1 测算假设（需用真实数据复核）")
    caption(doc, "表 5  业务假设")
    table(doc,
          ["假设项", "取值", "说明"],
          [
              ["年运单量", "20 万票", "单干线试点客户"],
              ["客服人数", "8 人", "含查单与催单"],
              ["调度人数", "6 人", "含异常协调"],
              ["人均综合成本", "12 万元/年", "工资、社保、管理分摊"],
              ["每人每日查单/催单", "40 次", "合计 320 次/天"],
              ["年工作日", "250 天", "查单/催单合计 8 万次/年"],
              ["“到哪里”类占比", "60%", "来自现场访谈 f12，待核实"],
              ["单次节省", "2 分钟", "自助或草稿一次给全"],
              ["二次往返率", "30%", "访谈定性，待统计"],
              ["单次往返节省", "3 分钟", "含翻群记录与再次沟通"],
              ["异常处理效率提升", "10%", "路由、证据包、草稿带来的节省"],
          ],
          widths=[4.2, 3.0, 9.0], size=8.5)

    h2(doc, "6.2 年度收益测算")
    caption(doc, "表 6  可量化年收益（单位：万元/年）")
    income = table(doc,
          ["收益项", "计算过程", "年化收益"],
          [
              ["查单/催单节省", "8 万次×60%×2 分钟 = 1,600 小时；折 0.8 人年×12 万", "9.6"],
              ["二次往返减少", "8 万次×30%×3 分钟 = 1,200 小时；折 0.6 人年×12 万", "7.2"],
              ["异常处理效率", "6 人×10%×12 万", "7.2"],
              ["合计", "—", "24.0"],
          ],
          widths=[3.8, 9.4, 3.0], size=8.5)
    for row in income.rows[:-1]:
        for cell in row.cells:
            for paragraph in cell.paragraphs:
                paragraph.paragraph_format.keep_with_next = True
    p(doc, "未计入：客户投诉下降、赔付/扣罚减少、客户留存与续约、回执及时率提升带来的对账节省。"
           "这些收益真实存在，但缺基线，暂不纳入测算，避免高估。")

    # 七、ROI
    h1(doc, "七、三档 ROI 对比")
    caption(doc, "表 7  投入产出对比（单位：万元）")
    table(doc,
          ["指标", "低", "中", "高"],
          [
              ["一次性投入", "9.8", "28.0", "58.0"],
              ["年运行成本", "2.07", "5.70", "13.44"],
              ["首年总投入", "11.87", "33.70", "71.44"],
              ["年化收益", "24.0", "24.0", "24.0"],
              ["首年净现金流", "+12.13", "−9.70", "−47.44"],
              ["回本周期", "5.4 个月", "18.4 个月", "65.9 个月"],
              ["3 年总成本", "16.01", "45.10", "98.32"],
              ["3 年净收益", "55.99", "26.90", "−26.32"],
              ["3 年 ROI", "350%", "60%", "−27%"],
          ],
          widths=[4.2, 3.8, 3.8, 3.8], size=9)
    p(doc, "结论：在单干线 20 万票的规模下，低档回本最快，中档约 18 个月回本、3 年 ROI 为正；"
           "高档需要多干线或更大票量才能成立，单点试点不建议直接上高档。")

    # 八、敏感性
    h1(doc, "八、敏感性分析")
    p(doc, "收益与票量近似线性。下表给出 0.5 倍、1 倍、3 倍规模下的回本周期与 3 年 ROI。")
    caption(doc, "表 8  规模敏感性")
    table(doc,
          ["档位", "0.5×（10 万票）", "1×（20 万票）", "3×（60 万票）"],
          [
              ["低 · 回本 / 3 年 ROI", "11.8 个月 / 125%", "5.4 个月 / 350%", "1.7 个月 / 1,249%"],
              ["中 · 回本 / 3 年 ROI", "53.3 个月 / −20%", "18.4 个月 / 60%", "5.1 个月 / 379%"],
              ["高 · 回本 / 3 年 ROI", "不可行 / 负", "65.9 个月 / −27%", "11.9 个月 / 120%"],
          ],
          widths=[4.6, 4.2, 4.2, 4.2], size=8.5)
    p(doc, "管理含义：如果只能拿到一条干线的试点预算，选中档要接受“首年不回本”；"
           "如果目标是一年内看到正现金流，低档更稳；高档应按“多干线复制”立项，而不是按单点试点立项。")

    # 九、付款与交付
    h1(doc, "九、付款与交付")
    caption(doc, "表 9  付款节点")
    table(doc,
          ["档位", "合同签订", "上线试运行", "验收", "备注"],
          [
              ["低", "50%", "40%", "10%", "4–6 周交付"],
              ["中", "40%", "40%", "20%", "10–12 周交付"],
              ["高", "30%", "40%", "30%", "16–20 周交付，含集成"],
          ],
          widths=[2.4, 3.2, 3.6, 2.8, 4.6], size=9)
    p(doc, "验收以设计方案中的 W1 验证与功能验收清单为准：规则问答引用、红线 0 次模型调用、"
           "异常归一率、路由覆盖、审计可追溯；业务指标（首响、二次往返）作为试点期观察项，不作为一次性验收门槛。")

    # 十、不包含与前提
    h1(doc, "十、不包含项与前提")
    h2(doc, "10.1 不包含")
    bullets(doc, [
        "服务器、GPU、云资源与对象存储费用；",
        "第三方大模型 token 费用（按实际用量另计）；",
        "TMS/GPS/IM 厂商的接口开发费与授权费；",
        "等保测评、渗透测试与合规认证费用；",
        "超出约定范围的定制开发与数据清洗（按变更单计）；",
        "客户侧项目管理人员与业务专家投入。",
    ])
    h2(doc, "10.2 前提")
    bullets(doc, [
        "客户提供 TMS 只读接口文档、测试环境与脱敏样本；",
        "客户指定业务负责人，确认改地址升级、15 分钟口径等规则；",
        "试点范围为单干线，年运单约 20 万票；",
        "需求变更走变更单，按 4.5 万元/人月计。",
    ])

    # 十一、结论
    h1(doc, "十一、结论与建议")
    bullets(doc, [
        "预算有限、先证明价值：选低档（9.8 万），4–6 周可演示规则问答与查单草稿。",
        "希望形成闭环、可复制：选中档（28 万），18 个月左右回本，3 年 ROI 约 60%，是推荐方案。",
        "多干线、要接生产系统：选高档（58 万），但必须按 3 倍规模立项，否则单点算不过账。",
        "以上收益只算工时节省，未计投诉、赔付与留存；真实测算应先用 2 周基线把 60%、30% 两个假设校准。",
    ])

    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUT)
    return OUT


if __name__ == "__main__":
    print("saved:", build())
