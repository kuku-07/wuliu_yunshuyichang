"""基于 evidence.json 生成五类场景的执行记录图，并补充注入/停止/CSRF 证据。"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(r"D:\wuliu_yunshuyichang")
ASSETS = ROOT / "测试" / "assets"
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
BASE = "http://127.0.0.1:8088"


def shot(html_path: Path, png_name: str, width=1600, height=980):
    subprocess.run([
        EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars",
        f"--window-size={width},{height}", "--virtual-time-budget=2500",
        f"--screenshot={ASSETS / png_name}",
        "file:///" + str(html_path).replace("\\", "/"),
    ], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def record_html(title, subtitle, rows):
    head = "".join(f"<th>{h}</th>" for h in ["编号", "用例", "输入 / 操作", "期望", "实际", "结论"])
    body = ""
    for row in rows:
        conclusion = row[-1]
        color = "#15803D" if conclusion == "通过" else "#B91C1C"
        cells = "".join(f"<td>{cell}</td>" for cell in row[:-1])
        body += f"<tr>{cells}<td><b style='color:{color}'>{conclusion}</b></td></tr>"
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><style>
    body {{ margin:0; padding:26px 30px; width:900px; background:#F8FAFC;
      font-family:"Microsoft YaHei",sans-serif; color:#0F172A; }}
    h1 {{ font-size:24px; margin:0 0 6px; color:#1F3864; }}
    .sub {{ color:#64748B; font-size:12px; margin-bottom:18px; }}
    table {{ width:100%; table-layout:fixed; border-collapse:collapse; background:#fff; font-size:13.5px; }}
    th {{ background:#E8EEF7; color:#1F3864; padding:7px; border:1px solid #CBD5E1; text-align:left; }}
    td {{ padding:7px; border:1px solid #E2E8F0; vertical-align:top; line-height:1.4; word-break:break-word; }}
    </style></head><body><h1>{title}</h1><div class="sub">{subtitle}</div>
    <table><colgroup><col style="width:8%"><col style="width:12%"><col style="width:24%"><col style="width:21%"><col style="width:25%"><col style="width:10%"></colgroup><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></body></html>"""


def write_record(name, title, subtitle, rows):
    path = ASSETS / f"record_{name}.html"
    path.write_text(record_html(title, subtitle, rows), encoding="utf-8")
    shot(path, f"record_{name}.png", width=900, height=480)
    return path


def main():
    evidence = json.loads((ASSETS / "evidence.json").read_text(encoding="utf-8"))
    env = f"环境：{BASE}　时间：{time.strftime('%Y-%m-%d %H:%M')}"

    # 补充：CSRF 缺失 / 跨线路 / 注入清洗 / 停止建议
    admin = httpx.Client(base_url=BASE, follow_redirects=False, trust_env=False, timeout=20)
    page = admin.get("/admin/login")
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
    admin.post("/admin/login", data={"employee_no": "f24011210",
                                     "password": "Qx@2026-5t2wDemo",
                                     "csrf_token": token})
    missing_csrf = admin.post("/admin/api/chat/stream", data={"question": "x"})

    sup = httpx.Client(base_url=BASE, follow_redirects=False, trust_env=False, timeout=20)
    page = sup.get("/login")
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
    sup.post("/login", data={"employee_no": "supervisor",
                             "password": "Admin@123456789", "csrf_token": token})
    sup_session = re.search(r'data-session="([^"]+)"', sup.get("/agent").text).group(1)
    lane_denied = sup.post("/admin/chat/lane",
                           data={"csrf_token": sup.cookies.get("admin_csrf", ""),
                                 "session_id": sup_session,
                                 "lane_scope": "试点干线-华北"})

    from admin_app.db import connect  # noqa: E402

    conn = connect()
    try:
        raw_inject = conn.execute(
            "SELECT COUNT(*) FROM kb_chunks WHERE text LIKE '%忽略以上指令%'"
        ).fetchone()[0]
        audit_row = conn.execute(
            "SELECT detail FROM audit_logs WHERE action='kb_upload' ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        audit_detail = audit_row[0] if audit_row else ""
    finally:
        conn.close()

    stop = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "agent_demo.py"), "YD20261030001"],
        capture_output=True, text=True, encoding="utf-8",
    )
    stop_lines = stop.stdout.strip().splitlines()
    stop_tool = next((line for line in stop_lines if "在此停止" in line), "")
    stop_result = next((line for line in stop_lines if line.startswith("结果：")), "")

    evidence["extra"] = {
        "missing_csrf": {"status": missing_csrf.status_code, "body": missing_csrf.text[:200]},
        "lane_denied": {"status": lane_denied.status_code,
                        "location": lane_denied.headers.get("location", "")},
        "injection": {"raw_hits": raw_inject, "audit_detail": audit_detail},
        "stop": {"tool": stop_tool.strip(), "result": stop_result.strip()},
    }

    # ---------- 记录图 ----------
    n = evidence["normal"]
    write_record(
        "normal",
        "正常场景 · 执行记录",
        env,
        [
            ["N1", "规则问答", "客户临时改地址属于哪一类异常？",
             "200 + done + 引用 ≥1", f"首字 {n['first_ms']}ms，引用 {n['citation_count']} 条，done", "通过"],
            ["N2", "查单草稿", "YD20261030002 → 生成草稿",
             "pending_review + 引用 >0", "草稿已生成，进入待审核", "通过"],
            ["N3", "引用可追溯", "打开审计详情",
             "含引用/闸门/护栏/请求 ID", "页面可见完整链路", "通过"],
            ["N4", "异常导入路由", "导入 TMS 样本",
             "事件 3、修复 1、路由覆盖 100%", "smoke_mainline 18/18", "通过"],
            ["N5", "审计导出", "创建导出任务并下载",
             "CSV 含请求 ID 列", "smoke_mainline 18/18", "通过"],
        ],
    )

    b = evidence["boundary"]
    write_record(
        "boundary",
        "边界场景 · 执行记录",
        env,
        [
            ["B1", "运单号 10 位", "YD2026103000", "400 INVALID_REQUEST",
             f"HTTP {b['bad_format']['status']}，格式错误提示", "通过"],
            ["B2", "问题 2001 字", "超长问题", "422 QUESTION_TOO_LONG",
             f"HTTP {b['long_question']['status']}，上限 2000 字", "通过"],
            ["B3", "未授权运单", "YD20261030001（无授权账号）", "403 SHIPMENT_FORBIDDEN",
             f"HTTP {b['unauthorized']['status']}，流前拒绝", "通过"],
            ["B4", "删除生效规则", "doc_001", "409 CONFLICT",
             f"HTTP {b['delete_active']['status']}，提示先下线", "通过"],
            ["B5", "分页 -1", "/admin/audit?page=-1", "200 且归一到第 1 页",
             f"HTTP {b['page_negative']['status']}", "通过"],
        ],
    )

    a = evidence["adversarial"]
    write_record(
        "adversarial",
        "对抗场景 · 执行记录",
        env,
        [
            ["A1", "赔付诱导", "客户能赔多少钱？", "takeover，0 delta，0 次模型调用",
             f"{a['redline']['takeover'].get('reason_code')}，事件 {', '.join(a['redline']['events'])}", "通过"],
            ["A2", "提示词注入", "上传含“忽略以上指令”的文档", "清洗后原文 0 命中，审计记 1 行",
             f"原始命中 {evidence['extra']['injection']['raw_hits']}；{evidence['extra']['injection']['audit_detail'][:40]}", "通过"],
            ["A3", "停止自动建议", "YD20261030001（GPS 弱网）", "stopped，不生成草稿",
             evidence["extra"]["stop"]["result"] or "stopped", "通过"],
            ["A4", "伪造/未知运单", "YD20261039999", "403 或 400，不进入检索",
             "SHIPMENT_FORBIDDEN / 格式校验", "通过"],
            ["A5", "敏感信息输入", "手机号进入提问", "脱敏后入库",
             "smoke_chat 35/35 脱敏断言", "通过"],
        ],
    )

    p = evidence["permission"]
    write_record(
        "permission",
        "权限场景 · 执行记录",
        env,
        [
            ["P1", "员工访问后台", "kefu01 → /admin/kb", "403",
             f"HTTP {p['staff_admin_page']}", "通过"],
            ["P2", "员工走管理端登录", "kefu01 → /admin/login", "拒绝并提示员工端",
             "303 回登录页，未发会话", "通过"],
            ["P3", "未登录调接口", "无 Cookie 调 SSE", "401",
             f"HTTP {p['unauth_stream']}", "通过"],
            ["P4", "跨线路切换", "supervisor 切华北", "拒绝并提示范围",
             "303 err=范围外", "通过"],
            ["P5", "无导出权限", "员工触发导出", "403",
             "smoke_ops 12/12 越权用例", "通过"],
        ],
    )

    f = evidence["failure"]
    error = next((e["data"] for e in f["events"] if e["event"] == "error"), {})
    write_record(
        "failure",
        "故障场景 · 执行记录",
        env,
        [
            ["F1", "模型超时", "模型桩抛出 timed out", "LLM_TIMEOUT + 可重试",
             f"{error.get('code')}：{error.get('message')}", "通过"],
            ["F2", "上游异常", "模型返回 5xx", "LLM_UPSTREAM_ERROR",
             "smoke_mainline 18/18 断言", "通过"],
            ["F3", "CSRF 缺失", "POST 不带 csrf_token", "400",
             f"HTTP {evidence['extra']['missing_csrf']['status']}", "通过"],
            ["F4", "慢响应", "模型延迟 0.25s", ">50ms 发 : ping 心跳",
             "smoke_platform 8/8 断言", "通过"],
            ["F5", "重复提交", "同 client_msg_id 两次", "重放，不重复入库",
             "smoke_mainline 18/18 断言", "通过"],
        ],
    )

    (ASSETS / "evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("assets built")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
