r"""接入层、映射归并、修正原因、外发留痕、心跳 的冒烟测试。"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

tmp_dir = tempfile.mkdtemp(prefix="platform_smoke_")
os.environ["ADMIN_DATA_DIR"] = tmp_dir
os.environ["ADMIN_DB_PATH"] = str(Path(tmp_dir) / "admin.db")
os.environ["ADMIN_SECRET_KEY"] = "smoke-test-secret"
os.environ["ADMIN_SEED_PASSWORD"] = "Admin@123456789"
os.environ["INGEST_TOKEN"] = "test-ingest-token"
os.environ.pop("LLM_API_KEY", None)
os.environ["LLM_PROVIDER"] = "offline"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from admin_app import db as db_module  # noqa: E402
from admin_app.db import connect  # noqa: E402
from admin_app.main import app  # noqa: E402
from admin_app.routers import chat as chat_router  # noqa: E402
from admin_app.services import agent_core, links as link_service, tms_client  # noqa: E402

PASSWORD = "Admin@123456789"
TOKEN = "test-ingest-token"
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


def login(client: TestClient, employee_no: str) -> None:
    token = csrf(client)
    client.post(
        "/admin/login",
        data={"employee_no": employee_no, "password": PASSWORD, "csrf_token": token},
        follow_redirects=False,
    )


def post(client: TestClient, path: str, data: dict):
    payload = dict(data)
    payload["csrf_token"] = csrf(client)
    return client.post(path, data=payload, follow_redirects=True)


def main() -> int:
    db_module.init_db()
    admin = TestClient(app)
    login(admin, "sys_admin")
    post(admin, "/admin/exceptions/import", {})

    # ---- 1. 轨迹接入 ----
    tracks = {"records": [
        {"shipment_no": "YD20261030001", "at": "2026-11-05T10:00:00",
         "status": "in_transit", "location": "杭州北", "data_time": "2026-11-05T10:01:00"},
        {"shipment_no": "YD20269999999", "at": "2026-11-05T10:00:00", "status": "in_transit"},
    ]}
    bad = admin.post("/admin/api/ingest/tracks", json=tracks,
                     headers={"X-Ingest-Token": "wrong"})
    if bad.status_code != 401:
        fail("接入令牌校验", str(bad.status_code))
    good = admin.post("/admin/api/ingest/tracks", json=tracks,
                      headers={"X-Ingest-Token": TOKEN})
    body = good.json()
    if body["data"]["accepted"] != 1 or body["data"]["rejected"] != 1:
        fail("轨迹接入统计", json.dumps(body, ensure_ascii=False))
    ok("GPS 轨迹接入：令牌校验、未登记运单被拒、有效记录入库")

    # ---- 2. IM 留痕 ----
    im = {"records": [{
        "shipment_no": "YD20261030001", "operator": "张敏",
        "content": "客户来电确认改地址，已记录新地址", "occurred_at": "2026-11-05T10:05:00",
    }]}
    res = admin.post("/admin/api/ingest/im", json=im, headers={"X-Ingest-Token": TOKEN})
    if res.json()["data"]["accepted"] != 1:
        fail("IM 留痕接入", res.text[:200])
    page = admin.get("/admin/workbench?shipment_no=YD20261030001")
    if "客户来电确认改地址" not in page.text:
        fail("IM 留痕在查单页展示", "未显示")
    ok("IM 留痕接入并在查单页展示")

    # ---- 3. 子单映射归并 ----
    conn = connect()
    try:
        link_service.upsert(conn, "YD20261030001", "YD20261030001-01", "顺丰",
                            "CARRIER", "v2", priority=80, status="delivered")
        conn.commit()
        resolved = link_service.resolve(conn, "YD20261030001")
    finally:
        conn.close()
    winner = next(r for r in resolved if r["sub_no"] == "YD20261030001-01")
    if winner["source"] != "TMS" or len(winner["candidates"]) < 2:
        fail("来源优先级归并", json.dumps(winner, ensure_ascii=False))
    ok("子单映射多来源：TMS（优先级 100）压过承运商（80），候选来源保留")

    # ---- 4. 修正原因 ----
    post(admin, "/admin/workbench/generate", {"shipment_no": "YD20261030002"})
    conn = connect()
    try:
        draft = conn.execute(
            "SELECT * FROM drafts WHERE status='pending_review'"
            " ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    no_reason = post(admin, f"/admin/workbench/{draft['id']}/review",
                     {"action": "reject", "note": "口径不对"})
    if "修正原因" not in no_reason.text:
        fail("退回必须选原因", "未拦截")
    rejected = post(admin, f"/admin/workbench/{draft['id']}/review",
                    {"action": "reject", "reason": "WRONG_RULE", "note": "口径不对"})
    if "已退回" not in rejected.text:
        fail("退回成功", rejected.text[:200])
    conn = connect()
    try:
        row = conn.execute("SELECT review_reason FROM drafts WHERE id=?", (draft["id"],)).fetchone()
    finally:
        conn.close()
    if row["review_reason"] != "WRONG_RULE":
        fail("修正原因落库", str(row["review_reason"]))
    ok("退回必须选择修正原因，原因落库（WRONG_RULE）")

    # ---- 5. 外发留痕 ----
    post(admin, "/admin/workbench/generate", {"shipment_no": "YD20261030002"})
    conn = connect()
    try:
        draft2 = conn.execute(
            "SELECT * FROM drafts WHERE status='pending_review'"
            " ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    early_send = post(admin, f"/admin/workbench/{draft2['id']}/sent", {"channel": "IM"})
    if "审核通过" not in early_send.text:
        fail("未通过不能登记外发", "未拦截")
    post(admin, f"/admin/workbench/{draft2['id']}/review", {"action": "approve"})
    sent = post(admin, f"/admin/workbench/{draft2['id']}/sent",
                {"channel": "IM", "note": "已由客服发出"})
    if "已登记外发" not in sent.text:
        fail("登记外发", sent.text[:200])
    again = post(admin, f"/admin/workbench/{draft2['id']}/sent", {"channel": "IM"})
    if "已登记过" not in again.text:
        fail("重复外发被拒绝", "未拦截")
    ok("审核通过后才能登记外发，且只能登记一次")

    # ---- 6. 指标包含修正率与外发 ----
    metrics = admin.get("/admin/metrics")
    for key in ("修正率", "外发"):
        if key not in metrics.text:
            fail("指标页包含新指标", key)
    ok("指标页展示人工修正率与外发数")

    # ---- 7. 心跳 ----
    class SlowClient:
        def complete(self, system_prompt, user_prompt):
            time.sleep(0.25)
            return "结论：离线自检\n依据：无\n不确定项：无"

    original_client = agent_core.build_llm_client
    original_beat = chat_router.HEARTBEAT_SECONDS
    agent_core.build_llm_client = lambda: SlowClient()
    chat_router.HEARTBEAT_SECONDS = 0.05
    try:
        session_id = re.search(
            r'data-session="([^"]+)"', admin.get("/admin/chat").text
        ).group(1)
        with admin.stream(
            "POST", "/admin/api/chat/stream",
            data={"question": "封路导致延误怎么记录？", "session_id": session_id,
                  "csrf_token": csrf(admin)},
        ) as response:
            raw = "".join(response.iter_text())
    finally:
        agent_core.build_llm_client = original_client
        chat_router.HEARTBEAT_SECONDS = original_beat
    if ": ping" not in raw:
        fail("SSE 心跳", "未出现 : ping")
    ok("SSE 心跳：慢响应期间发送 : ping 注释行")

    # ---- 8. TMS HTTP 客户端 ----
    payload = {
        "/queries": [{"shipment_no": "YD20261030001", "lane_scope": "试点干线-华东"}],
        "/exceptions": [],
    }

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            body = json.dumps(payload.get(self.path, [])).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        fetched = tms_client.fetch_all(
            f"http://127.0.0.1:{server.server_port}", "token", timeout=3, retries=0
        )
    finally:
        server.shutdown()
    if not fetched["queries"] or fetched["exceptions"]:
        fail("TMS HTTP 客户端", json.dumps(fetched, ensure_ascii=False))
    ok("TMS HTTP 客户端可拉取 /queries 与 /exceptions")

    print()
    print(f"全部通过：{len(STEPS)} 项")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
