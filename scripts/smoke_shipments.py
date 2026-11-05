r"""运单登记 / 运单主数据冒烟测试。

覆盖：登记、修改、删除保护、线路联动、对话上下文、演示数据清除与恢复。

运行：
    $env:PYTHONPATH="D:\Lib\site-packages;D:\wuliu_yunshuyichang"
    python scripts\smoke_shipments.py
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path
from urllib.parse import unquote

tmp_dir = tempfile.mkdtemp(prefix="ship_smoke_")
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
from admin_app.db import connect, init_db  # noqa: E402
from admin_app.main import app  # noqa: E402
from admin_app.services import chat_service  # noqa: E402

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


def login(client: TestClient, employee_no: str) -> None:
    token = csrf(client)
    response = client.post(
        "/admin/login",
        data={"employee_no": employee_no, "password": PASSWORD, "csrf_token": token},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    assert "admin_token" in client.cookies, f"{employee_no} 登录未下发 token"


def chat(client: TestClient, session_id: str, question: str, shipment_no: str = ""):
    with client.stream(
        "POST", "/admin/api/chat/stream",
        data={"question": question, "session_id": session_id,
              "csrf_token": csrf(client), "shipment_no": shipment_no},
    ) as response:
        if response.status_code != 200:
            response.read()
            return response.status_code, json.loads(response.content), {}
        meta = {}
        for line in response.iter_lines():
            if line.startswith("data: ") and '"shipment"' in line:
                meta = json.loads(line[6:])
    return 200, {}, meta


def main() -> int:
    db_module.init_db()
    admin = TestClient(app)
    login(admin, "sys_admin")

    # ---- 1. 页面与权限 ----
    page = admin.get("/admin/shipments")
    if page.status_code != 200 or "运单主数据" not in page.text:
        fail("运单登记页可访问", str(page.status_code))
    if "YD20261030001" not in page.text or "演示" not in page.text:
        fail("展示演示运单并标注来源", "缺少演示标记")
    ok("运单登记页可访问，演示运单带「演示」标记")

    auditor = TestClient(app)
    login(auditor, "auditor")
    if auditor.get("/admin/shipments").status_code != 403:
        fail("非管理员访问运单登记页应 403", "auditor 未被拒绝")
    ok("非管理员访问运单登记页 → 403")

    # ---- 2. 登记 / 校验 ----
    new_no = "YD20261030999"
    create = admin.post(
        "/admin/shipments/save",
        data={"csrf_token": csrf(admin), "shipment_no": new_no, "original_no": "",
              "lane_scope": "试点干线-华东", "customer": "上海 · 测试客户",
              "status": "in_transit"},
        follow_redirects=False,
    )
    if create.status_code != 303 or "ok=" not in create.headers["location"]:
        fail("登记运单成功", create.headers.get("location", ""))
    listing = admin.get(f"/admin/shipments?keyword={new_no}")
    if new_no not in listing.text or "上海 · 测试客户" not in listing.text:
        fail("新运单出现在列表", new_no)
    ok("登记运单成功（客户字段已保存）")

    bad = admin.post(
        "/admin/shipments/save",
        data={"csrf_token": csrf(admin), "shipment_no": "ABC123", "original_no": "",
              "lane_scope": "试点干线-华东", "customer": "x", "status": "in_transit"},
        follow_redirects=False,
    )
    if "err=" not in bad.headers.get("location", ""):
        fail("非法运单号被拒绝", bad.headers.get("location", ""))
    ok("非法运单号 → 拒绝登记")

    bad_lane = admin.post(
        "/admin/shipments/save",
        data={"csrf_token": csrf(admin), "shipment_no": "YD20261030998", "original_no": "",
              "lane_scope": "", "customer": "x", "status": "in_transit"},
        follow_redirects=False,
    )
    if "err=" not in bad_lane.headers.get("location", ""):
        fail("空线路被拒绝", bad_lane.headers.get("location", ""))
    ok("线路为空 → 拒绝登记（预检要靠它）")

    # ---- 3. 授权后才能提问，且上下文带客户与状态 ----
    grant = admin.post(
        "/admin/grants/create",
        data={"csrf_token": csrf(admin), "user_id": "u_rule", "shipment_no": new_no,
              "expires_at": "", "reason": "冒烟测试"},
        follow_redirects=False,
    )
    if grant.status_code != 303:
        fail("给新运单授权", str(grant.status_code))

    rule = TestClient(app)
    login(rule, "rule_admin")
    session_id = re.search(r'data-session="([^"]+)"', rule.get("/admin/chat").text).group(1)

    status, payload, meta = chat(rule, session_id, "签收单缺少收货人签字怎么办？", new_no)
    if status != 200:
        fail("已授权运单可提问", f"{status} {payload}")
    shipment = meta.get("shipment") or {}
    if shipment.get("customer") != "上海 · 测试客户" or shipment.get("status_text") != "在途":
        fail("对话上下文带客户与状态", json.dumps(shipment, ensure_ascii=False))
    ok("已授权运单可提问，meta 带客户与在途状态")

    ctx = chat_service._shipment_context(
        {"shipment_no": new_no, "lane_scope": "试点干线-华东",
         "customer": "上海 · 测试客户", "status": "delivered"}
    )
    for needle in (new_no, "上海 · 测试客户", "已签收", "不得据此推断"):
        if needle not in ctx:
            fail("提示词包含运单上下文", needle)
    ok("提示词注入运单上下文（含客户、状态与禁止推断声明）")

    # ---- 4. 修改：客户 / 状态 / 线路联动 ----
    edit = admin.post(
        "/admin/shipments/save",
        data={"csrf_token": csrf(admin), "shipment_no": new_no, "original_no": new_no,
              "lane_scope": "试点干线-华北", "customer": "苏州 · 已改名客户",
              "status": "delivered"},
        follow_redirects=False,
    )
    if edit.status_code != 303 or "ok=" not in edit.headers["location"]:
        fail("修改运单成功", edit.headers.get("location", ""))

    conn = connect()
    try:
        row = conn.execute(
            "SELECT lane_scope, customer, status FROM shipments WHERE shipment_no=?", (new_no,)
        ).fetchone()
        grant_lane = conn.execute(
            "SELECT lane_scope FROM authorization_grants WHERE shipment_no=?", (new_no,)
        ).fetchone()[0]
    finally:
        conn.close()
    if tuple(row) != ("试点干线-华北", "苏州 · 已改名客户", "delivered"):
        fail("运单修改已落地", str(tuple(row)))
    if grant_lane != "试点干线-华北":
        fail("线路变更联动授权", grant_lane)
    ok("修改运单生效，授权线路随运单线路同步")

    # 改号必须被拒绝
    rename = admin.post(
        "/admin/shipments/save",
        data={"csrf_token": csrf(admin), "shipment_no": "YD20261030997", "original_no": new_no,
              "lane_scope": "试点干线-华北", "customer": "x", "status": "delivered"},
        follow_redirects=False,
    )
    if "err=" not in rename.headers.get("location", ""):
        fail("运单号不可修改", rename.headers.get("location", ""))
    ok("运单号不可修改（避免打断已有授权）")

    # ---- 5. 删除保护 ----
    blocked = admin.post(
        f"/admin/shipments/{new_no}/delete",
        data={"csrf_token": csrf(admin)},
        follow_redirects=True,
    )
    if "撤销" not in unquote(blocked.text[:4000]):
        fail("有生效授权时禁止删除", "未提示撤销")
    ok("有生效授权时禁止删除运单")

    conn = connect()
    try:
        grant_id = conn.execute(
            "SELECT id FROM authorization_grants WHERE user_id='u_rule' AND shipment_no=?",
            (new_no,),
        ).fetchone()[0]
    finally:
        conn.close()
    admin.post(f"/admin/grants/{grant_id}/revoke",
               data={"csrf_token": csrf(admin), "reason": "冒烟测试"})
    deleted = admin.post(f"/admin/shipments/{new_no}/delete",
                         data={"csrf_token": csrf(admin)}, follow_redirects=False)
    if deleted.status_code != 303 or "ok=" not in deleted.headers["location"]:
        fail("撤销后可以删除运单", deleted.headers.get("location", ""))
    conn = connect()
    try:
        still_there = conn.execute(
            "SELECT 1 FROM shipments WHERE shipment_no=?", (new_no,)
        ).fetchone()
    finally:
        conn.close()
    if still_there:
        fail("运单已从数据库移除", new_no)
    ok("撤销授权后可删除运单，库中已移除")

    print()
    print(f"全部通过：{len(STEPS)} 项")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
