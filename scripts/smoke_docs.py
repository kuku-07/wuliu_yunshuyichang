r"""历史需求缺口（快照/路由/交接/停止建议/熔断/角色）的验收测试。"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

tmp_dir = tempfile.mkdtemp(prefix="docs_smoke_")
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
from admin_app.db import connect, now_iso  # noqa: E402
from admin_app.main import app  # noqa: E402
from admin_app.security import decode_access_token  # noqa: E402
from admin_app.services import shipments as shipment_service  # noqa: E402

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
    post(admin, "/admin/exceptions/import", {})

    conn = connect()
    try:
        snaps = conn.execute("SELECT COUNT(*) FROM shipment_snapshots").fetchone()[0]
        assigned = conn.execute(
            "SELECT COUNT(*) FROM exception_events WHERE handler<>''"
        ).fetchone()[0]
        auto = conn.execute(
            "SELECT COUNT(*) FROM exception_events WHERE route_rule<>''"
        ).fetchone()[0]
        events = conn.execute("SELECT COUNT(*) FROM exception_events").fetchone()[0]
    finally:
        conn.close()
    if snaps < 2:
        fail("导入生成快照", str(snaps))
    if assigned < events or not auto:
        fail("自动路由", f"已指派 {assigned}/{events}，自动路由 {auto}")
    ok("导入生成快照版本，异常按类型自动路由到具名处理人")

    # 快照版本递增
    post(admin, "/admin/exceptions/import", {})
    conn = connect()
    try:
        versions = [
            row[0]
            for row in conn.execute(
                "SELECT version FROM shipment_snapshots WHERE shipment_no='YD20261030001'"
                " ORDER BY version"
            ).fetchall()
        ]
    finally:
        conn.close()
    if len(versions) < 2 or versions != list(range(1, len(versions) + 1)):
        fail("快照版本递增", str(versions))
    ok("同一运单再次接入生成 v2 快照，版本连续")

    # 转交
    conn = connect()
    try:
        event = conn.execute(
            "SELECT * FROM exception_events WHERE closed_at IS NULL LIMIT 1"
        ).fetchone()
        sup = conn.execute(
            "SELECT id FROM admin_users WHERE employee_no='supervisor2'"
        ).fetchone()
        actor = dict(conn.execute(
            "SELECT * FROM admin_users WHERE employee_no='sys_admin'"
        ).fetchone())
    finally:
        conn.close()
    post(admin, f"/admin/exceptions/{event['id']}/accept", {})
    post(admin, f"/admin/exceptions/{event['id']}/handover",
         {"handler": sup["id"], "note": "现场处理"})
    conn = connect()
    try:
        handler = conn.execute(
            "SELECT handler FROM exception_events WHERE id=?", (event["id"],)
        ).fetchone()[0]
        handovers = conn.execute(
            "SELECT COUNT(*) FROM event_handovers WHERE event_id=?", (event["id"],)
        ).fetchone()[0]
    finally:
        conn.close()
    if handler != sup["id"] or not handovers:
        fail("转交更新处理人并留痕", f"{handler}/{handovers}")
    ok("转交：处理人变更、交接记录留痕")

    # 退回原因
    post(admin, f"/admin/exceptions/{event['id']}/close",
         {"note": "客户拒收", "return_reason": "包装破损"})
    conn = connect()
    try:
        reason = conn.execute(
            "SELECT return_reason FROM exception_events WHERE id=?", (event["id"],)
        ).fetchone()[0]
    finally:
        conn.close()
    if reason != "包装破损":
        fail("退回原因落库", reason)
    ok("关闭异常时记录退回原因")

    # 催单草稿
    post(admin, "/admin/workbench/generate",
         {"shipment_no": "YD20261030002", "scenario": "expedite"})
    conn = connect()
    try:
        draft = conn.execute(
            "SELECT * FROM drafts WHERE shipment_no='YD20261030002'"
            " ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    if draft is None or draft["scenario"] != "expedite":
        fail("催单草稿场景", dict(draft) if draft else "无")
    ok("查单 / 催单两种场景分别生成草稿")

    # 停止自动建议（GPS 弱网）
    conn = connect()
    try:
        conn.execute(
            "INSERT INTO shipments (shipment_no, lane_scope, customer, status, plan_eta,"
            " is_demo, created_at) VALUES ('YD20261030003','试点干线-华东','测试客户',"
            " 'in_transit','2026-11-10T18:00:00',0,?)",
            (now_iso(),),
        )
        old = (datetime.now() - timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%S")
        conn.execute(
            "INSERT INTO shipment_tracks (id, shipment_no, at, status, location, note, data_time)"
            " VALUES ('t_stale','YD20261030003',?, 'in_transit','杭州','停留',?)",
            (old, old),
        )
        conn.commit()
    finally:
        conn.close()
    post(admin, "/admin/workbench/generate", {"shipment_no": "YD20261030003"})
    conn = connect()
    try:
        stopped = conn.execute(
            "SELECT status, gate_reason FROM drafts WHERE shipment_no='YD20261030003'"
            " ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    if stopped is None or stopped["status"] != "stopped" or "GPS" not in stopped["gate_reason"]:
        fail("GPS 弱网停止自动建议", dict(stopped) if stopped else "无")
    ok("轨迹停滞（GPS 弱网）→ 停止自动建议，转人工")

    # 误报率熔断
    conn = connect()
    try:
        for index in range(5):
            conn.execute(
                "INSERT INTO alerts (id, shipment_no, alert_type, severity, reason, status,"
                " created_at, reviewed_at, reviewed_by)"
                " VALUES (?, ?, 'TRACK_STALE', 'low', '测试', ?, ?, ?, 'u_audit')",
                (
                    f"al_circuit_{index}", f"TEST{index:011d}",
                    "false_positive" if index < 2 else "confirmed",
                    now_iso(), now_iso(),
                ),
            )
        conn.commit()
    finally:
        conn.close()
    tripped = post(admin, "/admin/workbench/generate",
                   {"shipment_no": "YD20261030002"})
    if "熔断" not in tripped.text:
        fail("误报率熔断", tripped.text[:200])
    ok("误报率 40% → 自动建议熔断，拒绝生成草稿")

    # 留存：申请人不能自批
    post(admin, "/admin/metrics/retention/request", {})
    conn = connect()
    try:
        req = conn.execute(
            "SELECT id FROM retention_requests WHERE status='pending'"
            " ORDER BY requested_at DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    self_approve = post(admin, f"/admin/metrics/retention/{req['id']}/approve", {})
    if "申请人不能审批" not in self_approve.text:
        fail("留存申请人不能自批", self_approve.text[:200])
    ok("留存清理：申请人不能审批自己的申请")

    # 客户端门户
    post(admin, "/admin/users/create", {
        "employee_no": "cust_demo", "name": "客户甲", "role": "customer",
        "password": "Customer@1234", "lanes": [],
    })
    conn = connect()
    try:
        customer = conn.execute(
            "SELECT id FROM admin_users WHERE employee_no='cust_demo'"
        ).fetchone()
        conn.execute(
            "INSERT INTO authorization_grants"
            " (id, user_id, shipment_no, lane_scope, status, granted_by, granted_at)"
            " VALUES ('g_cust', ?, 'YD20261030001', '试点干线-华东', 'active', 'u_sys', ?)",
            (customer["id"], now_iso()),
        )
        conn.commit()
    finally:
        conn.close()
    portal_client = TestClient(app)
    login(portal_client, "cust_demo", "Customer@1234")
    portal = portal_client.get("/portal")
    if portal.status_code != 200 or "YD20261030001" not in portal.text:
        fail("客户门户", str(portal.status_code))
    denied = portal_client.get("/admin/kb", follow_redirects=False)
    if denied.status_code != 403:
        fail("客户访问后台应 403", str(denied.status_code))
    ok("客户门户：只读授权运单，后台页面 403")

    # 现场调度
    post(admin, "/admin/users/create", {
        "employee_no": "disp_demo", "name": "调度乙", "role": "dispatcher",
        "password": "Dispatch@1234", "lanes": ["试点干线-华东"],
    })
    dispatch = TestClient(app)
    login(dispatch, "disp_demo", "Dispatch@1234")
    if dispatch.get("/admin/exceptions").status_code != 200:
        fail("调度访问异常页", "403")
    if dispatch.get("/admin/users", follow_redirects=False).status_code != 403:
        fail("调度不能进账号管理", "未拦截")
    ok("现场调度：可看异常与待办，不能进账号/规则管理")

    # 审计前后哈希
    conn = connect()
    try:
        shipment_service.save(conn, actor, "YD20261030003", "试点干线-华东", "改后客户", "delivered")
        row = conn.execute(
            "SELECT before_hash, after_hash FROM audit_logs"
            " WHERE object_type='shipment' ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    if not row["before_hash"] or not row["after_hash"] or row["before_hash"] == row["after_hash"]:
        fail("审计前后哈希", dict(row))
    ok("审计记录带变更前后哈希")

    # JWT scopes + embedding_ref
    token = admin.cookies.get("admin_token")
    payload = decode_access_token(token)
    if "kb:read" not in (payload.get("scopes") or []):
        fail("JWT scopes", str(payload.get("scopes")))
    conn = connect()
    try:
        refs = conn.execute(
            "SELECT COUNT(*) FROM kb_chunks WHERE embedding_ref<>''"
        ).fetchone()[0]
    finally:
        conn.close()
    if not refs:
        fail("embedding_ref 落库", str(refs))
    ok("JWT 含 scopes；切片写入 embedding_ref")

    print()
    print(f"全部通过：{len(STEPS)} 项")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
