r"""账号/线路权限、异常受理与升级、预警 的冒烟测试。"""
from __future__ import annotations

import os
import re
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

tmp_dir = tempfile.mkdtemp(prefix="ops_smoke_")
os.environ["ADMIN_DATA_DIR"] = tmp_dir
os.environ["ADMIN_DB_PATH"] = str(Path(tmp_dir) / "admin.db")
os.environ["ADMIN_SECRET_KEY"] = "smoke-test-secret"
os.environ["ADMIN_SEED_PASSWORD"] = "Admin@123456789"
os.environ.pop("LLM_API_KEY", None)
os.environ["LLM_PROVIDER"] = "offline"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from admin_app import db as db_module  # noqa: E402
from admin_app.db import connect  # noqa: E402
from admin_app.main import app  # noqa: E402
from admin_app.services import ops  # noqa: E402

PASSWORD = "Admin@123456789"
STEPS: list[str] = []


def ok(label: str) -> None:
    STEPS.append(label)
    print(f"[通过] {label}")


def fail(label: str, detail: str = "") -> None:
    print(f"[失败] {label} {detail}")
    raise SystemExit(1)


def csrf(client: TestClient) -> str:
    if "admin_csrf" not in client.cookies:
        client.get("/admin/login", follow_redirects=False)
    return client.cookies.get("admin_csrf")


def login(client: TestClient, employee_no: str, password: str = PASSWORD) -> None:
    token = csrf(client)
    response = client.post(
        "/admin/login",
        data={"employee_no": employee_no, "password": password, "csrf_token": token},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text


def post(client: TestClient, path: str, data: dict):
    payload = dict(data)
    payload["csrf_token"] = csrf(client)
    return client.post(path, data=payload, follow_redirects=True)


def main() -> int:
    db_module.init_db()
    admin = TestClient(app)
    login(admin, "sys_admin")

    # ---- 1. 账号管理 ----
    page = admin.get("/admin/users")
    if page.status_code != 200 or "账号列表" not in page.text:
        fail("账号管理页", str(page.status_code))
    ok("账号管理页可访问")

    created = post(admin, "/admin/users/create", {
        "employee_no": "u_north", "name": "华北客服", "role": "supervisor",
        "password": "NorthPass@123", "lanes": ["试点干线-华北"],
    })
    if "已创建" not in created.text:
        fail("创建账号", "未成功")
    duplicate = post(admin, "/admin/users/create", {
        "employee_no": "u_north", "name": "重复", "role": "supervisor",
        "password": "NorthPass@123", "lanes": [],
    })
    if "已存在" not in duplicate.text:
        fail("重复账号被拒绝", "未拦截")
    short = post(admin, "/admin/users/create", {
        "employee_no": "u_short", "name": "短密码", "role": "auditor",
        "password": "123456", "lanes": [],
    })
    if "至少 12 位" not in short.text:
        fail("短密码被拒绝", "未拦截")
    ok("创建账号成功；重复账号与短密码被拒绝")

    # ---- 2. 线路范围生效 ----
    north = TestClient(app)
    login(north, "u_north", "NorthPass@123")
    chat_page = north.get("/admin/chat")
    options = re.findall(r'<option value="([^"]+)"', chat_page.text)
    if "试点干线-华东" in options or "试点干线-华北" not in options:
        fail("线路范围过滤", str(options))
    ok("新账号只看到自己范围内的干线（华北）")

    session_id = re.search(r'data-session="([^"]+)"', chat_page.text).group(1)
    denied = north.post(
        "/admin/chat/lane",
        data={"csrf_token": csrf(north), "session_id": session_id,
              "lane_scope": "试点干线-华东"},
        follow_redirects=False,
    )
    if "err=" not in denied.headers.get("location", ""):
        fail("范围外线路被拒绝", denied.headers.get("location", ""))
    ok("切到范围外的干线 → 被拒绝")

    # ---- 3. 改密码后能登录 ----
    conn = connect()
    try:
        target = conn.execute(
            "SELECT id FROM admin_users WHERE employee_no='u_north'"
        ).fetchone()
    finally:
        conn.close()
    reset = post(admin, f"/admin/users/{target['id']}/reset", {"password": "NorthPass@456"})
    if "已重置" not in reset.text:
        fail("重置密码", "未成功")
    again = TestClient(app)
    login(again, "u_north", "NorthPass@456")
    ok("重置密码后可用新密码登录")

    # ---- 4. 异常受理与关闭 ----
    post(admin, "/admin/exceptions/import", {})
    conn = connect()
    try:
        event = conn.execute(
            "SELECT id FROM exception_events WHERE accepted_at IS NULL LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    if event is None:
        fail("样本里有待受理事件", "无")
    early_close = post(admin, f"/admin/exceptions/{event['id']}/close", {"note": "x"})
    if "先受理" not in early_close.text:
        fail("未受理不能关闭", "未拦截")
    accepted = post(admin, f"/admin/exceptions/{event['id']}/accept", {})
    if "已受理" not in accepted.text:
        fail("受理事件", "未成功")
    closed = post(admin, f"/admin/exceptions/{event['id']}/close", {"note": "已联系客户"})
    if "已关闭" not in closed.text:
        fail("关闭事件", "未成功")
    ok("异常事件：先受理再关闭，未受理不能关闭")

    # ---- 5. 超时升级 ----
    conn = connect()
    try:
        old = (datetime.now() - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%S")
        conn.execute(
            "INSERT INTO exception_events"
            " (id, shipment_no, event_type, reason_code, occurred_at, source,"
            "  source_version, status, data_time, created_at)"
            " VALUES ('ev_old', 'YD20261030001', '延误', 'OLD', ?, 'TMS', 'v1',"
            "  'normalized', ?, ?)",
            (old, old, old),
        )
        conn.commit()
    finally:
        conn.close()
    admin.get("/admin/exceptions")  # 打开页面即触发扫描
    conn = connect()
    try:
        row = conn.execute(
            "SELECT status, escalation_note FROM exception_events WHERE id='ev_old'"
        ).fetchone()
    finally:
        conn.close()
    if row["status"] != "escalated" or "首次响应超时" not in row["escalation_note"]:
        fail("超时自动升级", dict(row))
    ok("超过 30 分钟未受理 → 自动升级为 escalated 并留原因")

    # ---- 6. 预警与误报 ----
    page = admin.get("/admin/exceptions")
    if "待处置预警" not in page.text:
        fail("预警区展示", "缺失")
    conn = connect()
    try:
        alert = conn.execute("SELECT id FROM alerts WHERE status='open' LIMIT 1").fetchone()
    finally:
        conn.close()
    if alert is None:
        fail("生成了预警", "无")
    reviewed = post(admin, f"/admin/alerts/{alert['id']}/review",
                    {"verdict": "false_positive"})
    if "误报" not in reviewed.text:
        fail("标记误报", "未成功")
    metrics = admin.get("/admin/metrics")
    if "预警误报率" not in metrics.text:
        fail("指标含误报率", "缺失")
    ok("预警可标记误报，指标页展示误报率")

    # ---- 7. 保护性约束 ----
    conn = connect()
    try:
        me = conn.execute(
            "SELECT id FROM admin_users WHERE employee_no='sys_admin'"
        ).fetchone()
    finally:
        conn.close()
    demote = post(admin, f"/admin/users/{me['id']}/update", {
        "name": "陈磊", "role": "auditor", "status": "active", "lanes": [],
    })
    if "不能降级" not in demote.text:
        fail("不能降级当前账号", "未拦截")
    ok("不能降级当前登录账号")

    # ---- 8. 指派通知与我的待办 ----
    conn = connect()
    try:
        event = conn.execute(
            "SELECT id FROM exception_events WHERE closed_at IS NULL LIMIT 1"
        ).fetchone()
        handler = conn.execute(
            "SELECT id FROM admin_users WHERE employee_no='u_north'"
        ).fetchone()
    finally:
        conn.close()
    post(admin, f"/admin/exceptions/{event['id']}/assign", {"handler": handler["id"]})
    conn = connect()
    try:
        notes = conn.execute(
            "SELECT COUNT(*) FROM notifications WHERE user_id=? AND type='ASSIGN'",
            (handler["id"],),
        ).fetchone()[0]
    finally:
        conn.close()
    if not notes:
        fail("指派生成通知", "无通知")
    north_todos = TestClient(app)
    login(north_todos, "u_north", "NorthPass@456")
    page = north_todos.get("/admin/todos")
    if "你有一个新的异常" not in page.text:
        fail("待办页展示指派通知", "缺失")
    post(north_todos, "/admin/notifications/read", {})
    conn = connect()
    try:
        left = conn.execute(
            "SELECT COUNT(*) FROM notifications WHERE user_id=? AND status='unread'",
            (handler["id"],),
        ).fetchone()[0]
    finally:
        conn.close()
    if left:
        fail("标记已读", str(left))
    ok("指派生成站内通知，待办页可见并可标记已读")

    # ---- 9. 巡检：升级并通知主管 ----
    conn = connect()
    try:
        old = (datetime.now() - timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%S")
        conn.execute(
            "INSERT INTO exception_events"
            " (id, shipment_no, event_type, reason_code, occurred_at, source,"
            "  source_version, status, data_time, created_at)"
            " VALUES ('ev_patrol', 'YD20261030001', '延误', 'PATROL', ?, 'TMS', 'v1',"
            "  'normalized', ?, ?)",
            (old, old, old),
        )
        conn.commit()
        before = conn.execute(
            "SELECT COUNT(*) FROM notifications WHERE type='ESCALATION'"
        ).fetchone()[0]
        ops.run_once(conn)
        after = conn.execute(
            "SELECT COUNT(*) FROM notifications WHERE type='ESCALATION'"
        ).fetchone()[0]
    finally:
        conn.close()
    if after <= before:
        fail("巡检生成升级通知", f"{before} → {after}")
    ok("后台巡检：超时事件升级并通知主管")

    # ---- 10. 重试按钮与 15 分钟口径 ----
    chat_page = admin.get("/admin/chat")
    if "重试" not in chat_page.text:
        fail("聊天错误气泡带重试", "缺失")
    metrics = admin.get("/admin/metrics")
    if "≤15min" not in metrics.text:
        fail("指标含 15 分钟占比", "缺失")
    ok("聊天带重试按钮，指标同时给 15 分钟目标占比")

    print()
    print(f"全部通过：{len(STEPS)} 项")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
