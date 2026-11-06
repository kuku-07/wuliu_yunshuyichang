"""生成《项目上线交付运行手册》docx。"""
from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

OUT = Path(r"D:\wuliu_yunshuyichang\docs\项目上线交付运行手册.docx")

NAVY = RGBColor(0x1F, 0x38, 0x64)
GRAY = RGBColor(0x59, 0x59, 0x59)
HEAD_FILL = "E8EEF7"
CODE_FILL = "F1F5F9"


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
    normal.font.size = Pt(10)
    normal.paragraph_format.line_spacing = 1.4
    normal.paragraph_format.space_after = Pt(3)
    for name, size in (("Heading 1", 14.5), ("Heading 2", 11.5), ("Heading 3", 10.5)):
        style = doc.styles[name]
        style.font.name = "微软雅黑"
        style._element.rPr.rFonts.set(qn("w:eastAsia"), "微软雅黑")
        style.font.size = Pt(size)
        style.font.bold = True
        style.font.color.rgb = NAVY
        style.paragraph_format.space_before = Pt(11 if name == "Heading 1" else 8)
        style.paragraph_format.space_after = Pt(4)
        style.paragraph_format.keep_with_next = True
    section = doc.sections[0]
    section.page_width = Cm(21)
    section.page_height = Cm(29.7)
    section.top_margin = Cm(1.9)
    section.bottom_margin = Cm(1.7)
    section.left_margin = Cm(2.1)
    section.right_margin = Cm(1.9)


def add_page_number(section):
    paragraph = section.footer.paragraphs[0]
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = paragraph.add_run()
    set_font(run, "微软雅黑", 8.5, color=GRAY)
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


def cell_text(cell, text, size=8.5, bold=False, align=WD_ALIGN_PARAGRAPH.LEFT,
              color=None, mono=False):
    cell.text = ""
    paragraph = cell.paragraphs[0]
    paragraph.alignment = align
    paragraph.paragraph_format.line_spacing = 1.05
    paragraph.paragraph_format.space_after = Pt(1)
    run = paragraph.add_run(str(text))
    set_font(run, "等线" if mono else "宋体", size, bold=bold, color=color)


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
        if total > 16.8:
            widths = [w * 16.8 / total for w in widths]
        for i, width in enumerate(widths):
            t.columns[i].width = Cm(width)
        for row in t.rows:
            for i, width in enumerate(widths):
                row.cells[i].width = Cm(width)
    return t


def caption(doc, text):
    paragraph = doc.add_paragraph()
    paragraph.paragraph_format.space_before = Pt(7)
    paragraph.paragraph_format.space_after = Pt(2)
    paragraph.paragraph_format.keep_with_next = True
    run = paragraph.add_run(text)
    set_font(run, "微软雅黑", 8.8, bold=True, color=GRAY)


def p(doc, text, size=10, indent=True, bold=False):
    paragraph = doc.add_paragraph()
    if indent:
        paragraph.paragraph_format.first_line_indent = Cm(0.7)
    run = paragraph.add_run(text)
    set_font(run, "宋体", size, bold=bold)


def bullets(doc, items):
    for item in items:
        paragraph = doc.add_paragraph(style="List Bullet")
        paragraph.paragraph_format.line_spacing = 1.25
        run = paragraph.add_run(item)
        set_font(run, "宋体", 9.5)


def code_block(doc, text):
    t = doc.add_table(rows=1, cols=1)
    t.style = "Table Grid"
    cell = t.rows[0].cells[0]
    shade(cell, CODE_FILL)
    cell.text = ""
    lines = text.strip("\n").splitlines()
    for index, line in enumerate(lines):
        paragraph = cell.paragraphs[0] if index == 0 else cell.add_paragraph()
        paragraph.paragraph_format.line_spacing = 1.05
        paragraph.paragraph_format.space_after = Pt(0)
        run = paragraph.add_run(line)
        set_font(run, "等线", 8.2)


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
    set_font(run, "微软雅黑", 20, bold=True, color=NAVY)
    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = sub.add_run("项目上线交付运行手册")
    set_font(run, "微软雅黑", 24, bold=True, color=NAVY)
    sub2 = doc.add_paragraph()
    sub2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = sub2.add_run("部署 · 启停 · 备份 · 监控 · 故障处置 · 升级回滚")
    set_font(run, "微软雅黑", 10, color=GRAY)

    doc.add_paragraph().paragraph_format.space_before = Pt(34)
    meta = [
        ("文档版本", "v1.0（上线交付版）"),
        ("编制日期", "2026-11-06"),
        ("适用系统", "运输异常与签收协作智能体系统（MVP）"),
        ("适用环境", "单机 Linux / Windows，SQLite，FastAPI + Uvicorn"),
        ("读者", "运维、实施、客服主管、系统管理员"),
        ("密级", "内部"),
    ]
    t = doc.add_table(rows=0, cols=2)
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for key, value in meta:
        cells = t.add_row().cells
        cell_text(cells[0], key, 9, bold=True, color=NAVY)
        cell_text(cells[1], value, 9)
        cells[0].width = Cm(3.0)
        cells[1].width = Cm(13.6)
        shade(cells[0], HEAD_FILL)

    note = doc.add_paragraph()
    note.paragraph_format.space_before = Pt(20)
    note.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = note.add_run(
        "说明：本手册中的命令以 Linux 生产环境为主，Windows 本地环境在括号内标注；\n"
        "所有示例密钥、令牌、密码均须在上线前替换。"
    )
    set_font(run, "宋体", 8.8, color=GRAY)
    doc.add_page_break()

    # 目录
    h1(doc, "目录")
    for line in [
        "1  系统概述与交付物",
        "2  部署架构与环境要求",
        "3  首次部署与初始化",
        "4  日常启停与健康检查",
        "5  账号、角色与权限运行",
        "6  知识库与提示词运维",
        "7  数据备份、恢复与留存",
        "8  监控、日志与审计",
        "9  故障处理 Runbook",
        "10 安全与合规",
        "11 版本升级与回滚",
        "12 应急响应与联系人",
        "13 交付验收清单",
        "附录 A 命令速查　B 错误码　C 目录结构",
    ]:
        p(doc, line, indent=False, size=9.5)
    doc.add_page_break()

    # 1
    h1(doc, "1  系统概述与交付物")
    p(doc, "本系统面向运输异常与签收协作场景，提供规则问答、查单/催单草稿、异常受理与升级、"
           "预警、审计与指标。系统为单机部署的 MVP，数据落在 SQLite，外部系统只读接入。")
    h2(doc, "1.1 入口")
    caption(doc, "表 1-1  访问入口")
    table(doc,
          ["入口", "地址", "说明"],
          [
              ["员工端", "/login → /agent", "一线客服/调度问答与查单"],
              ["管理端", "/admin/login → /admin/kb", "规则、异常、审计、账号、指标"],
              ["客户/承运商门户", "/portal", "只读授权运单"],
              ["机器接入", "/admin/api/ingest/tracks、/im", "GPS 轨迹、IM 留痕，X-Ingest-Token"],
          ],
          widths=[3.4, 7.0, 6.2], size=8.5)

    h2(doc, "1.2 交付物")
    caption(doc, "表 1-2  交付清单")
    table(doc,
          ["交付物", "位置", "说明"],
          [
              ["应用代码", "admin_app/", "FastAPI 服务、Agent 框架、模板与静态资源"],
              ["归档问答助手", "archive/qa_assistant/", "阶段 1 CLI，冻结保留"],
              ["数据库", "admin_app/data/admin.db", "首次启动自动创建并写入演示数据"],
              ["上传文件", "admin_app/data/uploads/", "规则文档原文件"],
              ["导出文件", "admin_app/data/exports/", "审计导出 CSV（首次导出时创建）"],
              ["启动脚本", "run_admin.ps1", "Windows 本地启动"],
              ["测试与示例", "scripts/、samples/", "冒烟测试、TMS 脱敏样本"],
              ["文档", "docs/", "需求、设计、测试、部署、运行手册"],
          ],
          widths=[3.4, 6.4, 6.8], size=8.5)

    # 2
    h1(doc, "2  部署架构与环境要求")
    h2(doc, "2.1 部署拓扑")
    p(doc, "单机部署：浏览器 → Nginx（HTTPS，可选）→ Uvicorn（127.0.0.1:8088）→ SQLite 与本地文件目录。"
           "后台线程每 60 秒执行一次异常升级与预警扫描；无独立消息队列与缓存。")
    h2(doc, "2.2 软硬件要求")
    caption(doc, "表 2-1  环境要求")
    table(doc,
          ["项目", "最低", "建议"],
          [
              ["CPU / 内存", "2 核 / 2 GB", "2 核 / 4 GB"],
              ["磁盘", "10 GB", "50 GB（含备份与导出）"],
              ["操作系统", "Windows 10 / Ubuntu 20.04", "Ubuntu 22.04 LTS"],
              ["Python", "3.11", "3.11 / 3.12"],
              ["数据库", "SQLite（WAL）", "PostgreSQL（多副本时）"],
              ["浏览器", "Chrome/Edge 最近两个大版本", "同上"],
          ],
          widths=[3.6, 6.0, 7.0], size=8.5)

    h2(doc, "2.3 目录与端口")
    caption(doc, "表 2-2  关键路径与端口")
    table(doc,
          ["项", "值", "说明"],
          [
              ["服务端口", "8088", "Uvicorn 监听；公网只暴露 80/443"],
              ["数据目录", "admin_app/data/", "可用 ADMIN_DATA_DIR 覆盖"],
              ["数据库", "admin_app/data/admin.db", "可用 ADMIN_DB_PATH 覆盖"],
              ["上传目录", "admin_app/data/uploads/", "单文件 ≤20 MB，仅 .md/.pdf"],
              ["导出目录", "admin_app/data/exports/", "首次导出时创建"],
              ["日志", "stdout / journalctl", "建议由 systemd 收集"],
          ],
          widths=[3.2, 7.2, 6.2], size=8.5)

    h2(doc, "2.4 环境变量")
    caption(doc, "表 2-3  环境变量清单")
    table(doc,
          ["变量", "默认", "生产要求"],
          [
              ["ADMIN_SECRET_KEY", "dev-only-change-me-please", "必须替换为 32 位以上随机值"],
              ["ADMIN_DATA_DIR", "admin_app/data", "按磁盘规划调整"],
              ["ADMIN_DB_PATH", "<data>/admin.db", "备份对象"],
              ["ADMIN_SEED_PASSWORD", "Admin@123456789", "首次登录后立即修改"],
              ["ADMIN_TOKEN_TTL_MINUTES", "30", "按安全要求调整"],
              ["COOKIE_SECURE", "0", "HTTPS 部署置 1"],
              ["LLM_PROVIDER", "offline", "openai 兼容时配置下列三项"],
              ["LLM_BASE_URL / LLM_MODEL / LLM_API_KEY", "-", "本地 Ollama/vLLM 或云端"],
              ["TMS_BASE_URL / TMS_TOKEN", "空 / 空", "只读 TMS 接口；不配则用样本"],
              ["INGEST_TOKEN", "dev-ingest-token", "必须替换，机器接入用"],
              ["SSE_HEARTBEAT_SECONDS", "15", "SSE 心跳间隔"],
              ["OPS_TICK_SECONDS", "60", "后台巡检间隔"],
          ],
          widths=[5.6, 4.4, 6.6], size=8)

    # 3
    h1(doc, "3  首次部署与初始化")
    h2(doc, "3.1 本地 / 内网启动")
    p(doc, "Windows 本地可直接运行启动脚本；内网访问需将监听地址改为 0.0.0.0，并在防火墙放行 8088。")
    code_block(doc, """
# Windows（本地）
.\\run_admin.ps1

# 通用（内网）
python -m uvicorn admin_app.main:app --host 0.0.0.0 --port 8088
""")
    h2(doc, "3.2 Linux 生产部署")
    p(doc, "建议使用 venv + systemd 托管，Nginx 反向代理并开启 HTTPS。")
    code_block(doc, """
# 1) 代码与依赖
cd /opt && git clone <repo> wuliu && cd wuliu
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt

# 2) 环境变量（写入 /etc/wuliu/env，权限 600）
ADMIN_SECRET_KEY=<32位随机值>
ADMIN_DATA_DIR=/var/lib/wuliu
ADMIN_SEED_PASSWORD=<首次登录密码>
INGEST_TOKEN=<32位随机值>
COOKIE_SECURE=1
LLM_PROVIDER=openai
LLM_BASE_URL=http://127.0.0.1:11434/v1
LLM_MODEL=qwen2.5:7b

# 3) systemd
[Unit] Description=Wuliu Agent
After=network.target
[Service]
WorkingDirectory=/opt/wuliu
EnvironmentFile=/etc/wuliu/env
ExecStart=/opt/wuliu/.venv/bin/uvicorn admin_app.main:app --host 127.0.0.1 --port 8088
Restart=always
User=www-data
[Install] WantedBy=multi-user.target
""")
    h2(doc, "3.3 Nginx 与 HTTPS")
    code_block(doc, """
server {
  listen 443 ssl;
  server_name agent.example.com;
  ssl_certificate     /etc/letsencrypt/live/agent.example.com/fullchain.pem;
  ssl_certificate_key /etc/letsencrypt/live/agent.example.com/privkey.pem;
  location / {
    proxy_pass http://127.0.0.1:8088;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_buffering off;          # SSE 必须关闭缓冲
    proxy_read_timeout 300s;
  }
}
""")
    h2(doc, "3.4 初始化与账号")
    p(doc, "首次启动自动建库、建表并写入演示数据；用 ADMIN_SEED_PASSWORD 登录管理端后，"
           "立即在「账号管理」修改系统管理员密码，并按需创建一线客服账号。")
    bullets(doc, [
        "系统管理员：维护账号、线路、运单授权、规则与数据；",
        "客服主管：审核草稿、处理升级；",
        "合规审计：只读审计与留存审批；",
        "一线客服：仅员工端问答；客户/承运商：仅 /portal。",
    ])

    h2(doc, "3.5 部署后验证清单")
    caption(doc, "表 3-1  上线验证")
    table(doc,
          ["检查项", "方法", "通过标准"],
          [
              ["服务存活", "curl -I http://127.0.0.1:8088/login", "HTTP 200"],
              ["数据库", "python -c \"from admin_app.db import connect; print(connect().execute('select 1').fetchone())\"", "输出 (1,)"],
              ["管理端登录", "浏览器 /admin/login", "进入规则库"],
              ["员工端问答", "/login 后提问", "返回引用，done"],
              ["SSE", "浏览器开发者工具看流", "15s 心跳，无缓冲"],
              ["权限", "员工账号访问 /admin/kb", "403"],
              ["备份", "执行一次数据库备份", "文件可恢复"],
          ],
          widths=[3.4, 7.6, 5.8], size=8)

    # 4
    h1(doc, "4  日常启停与健康检查")
    h2(doc, "4.1 启停命令")
    code_block(doc, """
sudo systemctl start   wuliu-agent
sudo systemctl stop    wuliu-agent
sudo systemctl restart wuliu-agent
sudo systemctl status  wuliu-agent
journalctl -u wuliu-agent -f
""")
    p(doc, "Windows 本地：在仓库目录执行 .\\run_admin.ps1；停止用 Ctrl+C。")
    h2(doc, "4.2 健康检查")
    table(doc,
          ["层级", "检查", "频率"],
          [
              ["进程", "systemctl is-active wuliu-agent", "每分钟"],
              ["HTTP", "GET /login 返回 200", "每分钟"],
              ["数据库", "SELECT 1 与最近审计写入", "每 5 分钟"],
              ["业务", "员工端提问返回 done；指标页可打开", "每日"],
          ],
          widths=[3.0, 9.4, 4.0], size=8.5)
    h2(doc, "4.3 后台任务")
    bullets(doc, [
        "巡检线程：每 OPS_TICK_SECONDS（默认 60s）扫描超时升级与预警；",
        "留存清理：不再启动即删，需在「指标」页发起申请，由合规审计审批后执行；",
        "导出：异步任务，文件落在 data/exports/，需定期清理。",
    ])

    # 5
    h1(doc, "5  账号、角色与权限运行")
    p(doc, "权限分三层：登录态 → 角色权限 → 线路/运单授权。入口按角色分流，员工端不能进入管理端。")
    caption(doc, "表 5-1  角色与职责")
    table(doc,
          ["角色", "入口", "关键权限"],
          [
              ["系统管理员", "管理端", "账号、线路、运单、规则、审计、数据"],
              ["客服主管", "管理端", "草稿审核、异常处置、指标"],
              ["合规审计", "管理端", "审计只读、留存审批"],
              ["一线客服", "员工端", "问答、查单（本人线路）"],
              ["客户/承运商", "/portal", "只读授权运单"],
          ],
          widths=[3.4, 4.0, 9.0], size=8.5)
    h2(doc, "5.1 账号操作")
    bullets(doc, [
        "新建：账号管理 → 填工号、姓名、角色、线路范围、初始密码（≥12 位）；",
        "停用：状态改为 disabled，会话到期后失效；",
        "重置密码：账号管理 → 重置密码；同时清零失败次数与锁定；",
        "锁定：连续 5 次失败锁 15 分钟，可在账号管理解锁。",
    ])
    h2(doc, "5.2 线路与运单授权")
    bullets(doc, [
        "线路范围决定员工端可见干线；系统管理员不受限；",
        "运单授权决定能否查询某票运单，未授权返回 403 SHIPMENT_FORBIDDEN；",
        "授权可设有效期，到期自动失效；离职/换岗时同步回收。",
    ])

    # 6
    h1(doc, "6  知识库与提示词运维")
    h2(doc, "6.1 规则更新流程")
    code_block(doc, """
上传（自动脱敏 + 注入清洗）
  → 生成草稿版本
  → 提交审核
  → 批准（主管/系统管理员）
  → 发布（active，旧版本下线）
""")
    p(doc, "发布后 5 分钟内新会话引用新版本；已发出的历史引用保留原版本快照，可追溯。")
    h2(doc, "6.2 下线与回滚")
    bullets(doc, [
        "下线：规则详情 → 下线；已生效规则不能直接删除，删除返回 409；",
        "回滚：重新发布上一版本，或上传历史文件并走审批；",
        "提示词：草稿 → 发布；锁定安全段不可修改，篡改返回 409 PROMPT_LOCKED_SECTION。",
    ])
    h2(doc, "6.3 索引与切片")
    bullets(doc, [
        "上传后自动切片；切片可人工编辑，编辑后需重新提交审核；",
        "索引重建：POST /admin/api/kb/index/rebuild（需 index:rebuild 权限）；",
        "无可用切片时，问答应提示知识库为空，不得编造。",
    ])

    # 7
    h1(doc, "7  数据备份、恢复与留存")
    h2(doc, "7.1 备份对象与策略")
    caption(doc, "表 7-1  备份策略")
    table(doc,
          ["对象", "频率", "保留", "方式"],
          [
              ["admin.db", "每日 + 变更前", "30 天", "SQLite backup / 停机复制"],
              ["uploads/", "每周", "4 周", "文件同步"],
              ["exports/", "按需", "7 天", "清理过期文件"],
              ["systemd/env/nginx 配置", "变更时", "永久", "配置仓库"],
          ],
          widths=[4.2, 4.0, 3.0, 5.4], size=8.5)
    h2(doc, "7.2 备份与恢复命令")
    code_block(doc, """
# 在线备份（SQLite 官方 backup，避免复制到一半）
sqlite3 /var/lib/wuliu/admin.db ".backup '/backup/admin-$(date +%F).db'"

# 停机复制（Windows）
Copy-Item admin_app\\data\\admin.db backups\\admin-$(Get-Date -Format yyyyMMdd-HHmm).db

# 恢复
sudo systemctl stop wuliu-agent
cp /backup/admin-2026-11-06.db /var/lib/wuliu/admin.db
chown www-data:www-data /var/lib/wuliu/admin.db
sudo systemctl start wuliu-agent
""")
    p(doc, "恢复后必须验证：登录、规则列表、最近会话、审计记录、指标页。建议每季度做一次恢复演练。")
    h2(doc, "7.3 90 天留存")
    p(doc, "消息与审计默认保留 90 天；到期由系统管理员在「指标」页发起清理申请，合规审计审批后执行，"
           "申请人不能审批自己的申请。清理动作本身会写入审计。")

    # 8
    h1(doc, "8  监控、日志与审计")
    h2(doc, "8.1 关键指标")
    table(doc,
          ["指标", "来源", "告警建议"],
          [
              ["服务存活", "systemd / HTTP", "连续 2 次失败告警"],
              ["5xx 比例", "Uvicorn 日志", ">1% 持续 5 分钟"],
              ["首字延迟", "浏览器/日志", "P95 >2s 告警"],
              ["模型超时", "错误码 LLM_TIMEOUT", ">5 次/小时"],
              ["预警误报率", "指标页", ">10% 触发熔断并通知"],
              ["磁盘使用", "系统监控", ">80% 告警"],
          ],
          widths=[3.4, 5.6, 7.8], size=8.5)
    h2(doc, "8.2 日志")
    p(doc, "应用日志输出到 stdout，由 systemd/journald 收集；关键业务动作写 audit_logs 表，"
           "包含 request_id，可用于串联一次请求。")
    h2(doc, "8.3 审计")
    bullets(doc, [
        "管理端 → 对话审计：按员工、日期、线路、标记筛选；",
        "详情页展示引用、闸门、护栏、请求 ID；",
        "导出为异步任务，CSV 含请求 ID，单次最多 5000 条；",
        "标记与撤销均留痕，导出动作本身也写审计。",
    ])

    # 9
    h1(doc, "9  故障处理 Runbook")
    caption(doc, "表 9-1  常见故障与处置")
    table(doc,
          ["现象", "可能原因", "排查", "处置"],
          [
              ["服务起不来", "端口占用 / 依赖缺失 / 环境变量错误", "systemctl status；journalctl -n 100；ss -lntp | grep 8088", "释放端口；补依赖；修正 env 后重启"],
              ["502 / 无法访问", "Uvicorn 未启动 / Nginx 配置", "curl 127.0.0.1:8088/login；nginx -t", "重启服务；修正 proxy_pass 与缓冲"],
              ["登录失败", "密码错 / 账号停用 / 锁定", "账号管理查看状态与失败次数", "重置密码或解锁；确认角色"],
              ["模型超时", "上游慢 / 网络 / Key 失效", "日志 LLM_TIMEOUT；curl 模型地址", "切换本地模型或降级；检查配额"],
              ["知识库无结果", "未发布 / 线路不匹配 / 切片为空", "规则库状态；线路范围", "发布规则；核对线路；重建索引"],
              ["SSE 中断", "Nginx 缓冲 / 超时 / 客户端断网", "查看心跳；proxy_buffering", "关闭缓冲；调整 read_timeout"],
              ["数据库锁", "长事务 / 备份复制", "查看 sqlite 日志；进程", "停写后备份；必要时重启"],
              ["磁盘满", "导出/日志/备份堆积", "df -h；du -sh data/*", "清理 exports 与旧备份"],
              ["403 越权", "角色/线路/运单未授权", "审计日志记录原因", "补授权或调整角色"],
              ["导出失败", "任务异常 / 文件被清理", "导出记录页状态与错误", "重新创建任务；检查磁盘"],
              ["预警不触发", "巡检线程异常", "journalctl 查后台巡检日志", "重启服务；检查 OPS_TICK_SECONDS"],
          ],
          widths=[3.0, 4.4, 5.2, 4.2], size=7.8)

    h2(doc, "9.1 处置原则")
    bullets(doc, [
        "先止血：保证登录与问答可用，再定位根因；",
        "不改数据：未经备份不要手工改库；",
        "留证据：保留 request_id、日志时间、错误码；",
        "升级：影响面超过单用户或涉及数据安全，立即升级到系统管理员/负责人。",
    ])

    # 10
    h1(doc, "10  安全与合规")
    h2(doc, "10.1 基础安全")
    bullets(doc, [
        "生产必须 HTTPS，COOKIE_SECURE=1；",
        "ADMIN_SECRET_KEY、INGEST_TOKEN 使用 32 位以上随机值，定期轮换；",
        "数据库与备份文件权限 600，仅服务账号可读；",
        "公网只暴露 80/443，8088 仅本机监听；",
        "关闭演示数据或上线前清理演示账号。",
    ])
    h2(doc, "10.2 数据与合规")
    bullets(doc, [
        "数据分级：公开（已发布规则）、内部（运单/对话/审计）、敏感（客户信息/赔付/事故）；",
        "输入输出脱敏，导出脱敏；敏感字段不进提示词；",
        "审计 append-only，关键写操作记录前后哈希；",
        "留存 90 天，清理需合规审批；",
        "TMS 只读，禁止写入外部系统。",
    ])
    h2(doc, "10.3 上线安全检查")
    table(doc,
          ["检查项", "标准"],
          [
              ["密钥", "默认密钥/令牌已替换"],
              ["HTTPS", "证书有效，HTTP 跳转 HTTPS"],
              ["账号", "演示账号已停用，管理员密码已改"],
              ["权限", "员工账号访问后台 403"],
              ["备份", "每日备份任务已生效并验证恢复"],
              ["日志", "journald 保留 ≥30 天"],
              ["数据", "演示数据已清理或标注"],
          ],
          widths=[4.4, 12.0], size=8.5)

    # 11
    h1(doc, "11  版本升级与回滚")
    h2(doc, "11.1 升级步骤")
    code_block(doc, """
1) 备份数据库与上传目录
2) git fetch && git checkout <tag>
3) pip install -r requirements.txt
4) 重启服务（自动执行数据库迁移）
5) 验证：登录、规则、问答、审计、指标
""")
    h2(doc, "11.2 回滚")
    bullets(doc, [
        "代码回滚：git checkout 上一版本并重启；",
        "数据回滚：停服 → 恢复备份 DB → 启动；",
        "数据库结构变更不可逆时，优先用备份恢复，不在生产手工改表。",
    ])
    h2(doc, "11.3 变更窗口")
    p(doc, "建议在业务低峰（20:00 后）执行，单次窗口 30 分钟；升级前通知一线，准备回滚包与备份。")

    # 12
    h1(doc, "12  应急响应与联系人")
    caption(doc, "表 12-1  事件分级")
    table(doc,
          ["级别", "定义", "响应"],
          [
              ["P1", "全站不可用 / 数据泄露 / 红线失效", "15 分钟内响应，立即升级"],
              ["P2", "单干线不可用 / 大量模型超时", "30 分钟内响应"],
              ["P3", "单用户问题 / 单条规则错误", "当日处理"],
          ],
          widths=[2.0, 9.0, 5.4], size=8.5)
    caption(doc, "表 12-2  联系人（上线前填写）")
    table(doc,
          ["角色", "姓名", "电话", "职责"],
          [
              ["业务负责人", "", "", "验收与口径决策"],
              ["系统管理员", "", "", "部署、账号、数据"],
              ["运维值班", "", "", "监控、重启、备份"],
              ["合规审计", "", "", "留存与审计审批"],
              ["模型/接口支持", "", "", "LLM 与 TMS 接口"],
          ],
          widths=[3.4, 3.2, 3.6, 6.2], size=8.5)

    # 13
    h1(doc, "13  交付验收清单")
    table(doc,
          ["编号", "验收项", "标准", "结果"],
          [
              ["D1", "部署", "服务可启动，/login 200", "□"],
              ["D2", "账号", "管理员可登录，员工端可登录", "□"],
              ["D3", "知识库", "规则可上传/发布/生效", "□"],
              ["D4", "问答", "引用可追溯，红线转人工", "□"],
              ["D5", "异常", "导入、路由、受理、升级可用", "□"],
              ["D6", "草稿", "生成、审核、外发登记可用", "□"],
              ["D7", "审计", "详情与导出可用，含请求 ID", "□"],
              ["D8", "备份", "完成一次备份并验证恢复", "□"],
              ["D9", "安全", "HTTPS、密钥替换、演示账号处理", "□"],
              ["D10", "监控", "日志与告警接入", "□"],
          ],
          widths=[1.4, 3.2, 9.6, 2.2], size=8.5)

    # 附录
    h1(doc, "附录 A  命令速查")
    code_block(doc, """
# 状态
systemctl status wuliu-agent
curl -I http://127.0.0.1:8088/login

# 日志
journalctl -u wuliu-agent -f
journalctl -u wuliu-agent --since "1 hour ago"

# 数据库
sqlite3 /var/lib/wuliu/admin.db ".tables"
sqlite3 /var/lib/wuliu/admin.db "select count(*) from messages;"

# 备份
sqlite3 /var/lib/wuliu/admin.db ".backup '/backup/admin.db'"
""")

    h1(doc, "附录 B  错误码")
    table(doc,
          ["错误码", "HTTP", "含义", "处置"],
          [
              ["UNAUTHENTICATED", "401", "未登录/会话过期", "重新登录"],
              ["FORBIDDEN", "403", "角色无权", "调整角色"],
              ["SHIPMENT_FORBIDDEN", "403", "运单未授权/跨线", "补授权"],
              ["INVALID_REQUEST", "400", "参数错误", "核对输入"],
              ["QUESTION_TOO_LONG", "422", "问题超过 2000 字", "精简"],
              ["SESSION_BUSY", "409", "会话正在生成", "稍后重试"],
              ["LLM_TIMEOUT", "504", "模型超时", "重试/降级"],
              ["LLM_UPSTREAM_ERROR", "502", "模型上游异常", "检查服务"],
              ["KB_EMPTY", "503", "本线路无规则", "发布规则"],
              ["PROMPT_LOCKED_SECTION", "409", "提示词锁定段被改", "还原"],
              ["CONFLICT", "409", "删除生效规则", "先下线"],
          ],
          widths=[4.4, 1.6, 6.0, 4.4], size=8)

    h1(doc, "附录 C  目录结构")
    code_block(doc, """
admin_app/
  main.py          服务入口
  agent/           Agent 框架
  routers/         接口层
  services/        领域服务
  templates/       页面
  static/          CSS/JS
  data/            admin.db、uploads、exports
archive/           归档问答助手
samples/           TMS 脱敏样本
scripts/           测试与工具
docs/              交付文档
""")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUT)
    return OUT


if __name__ == "__main__":
    print("saved:", build())
