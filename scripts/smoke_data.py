r"""数据管理冒烟测试：演示数据的逐项删除与按组恢复。

运行：
    $env:PYTHONPATH="D:\Lib\site-packages;D:\wuliu_yunshuyichang"
    python scripts\smoke_data.py
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path

tmp_dir = tempfile.mkdtemp(prefix="data_smoke_")
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


def ask(client: TestClient, session_id: str, question: str) -> list[tuple[str, dict]]:
    with client.stream(
        "POST", "/admin/api/chat/stream",
        data={"question": question, "session_id": session_id, "csrf_token": csrf(client)},
    ) as response:
        if response.status_code != 200:
            return [("http_error", {"status": response.status_code})]
        events: list[tuple[str, dict]] = []
        name = None
        for line in response.iter_lines():
            if line.startswith("event: "):
                name = line[7:].strip()
            elif line.startswith("data: ") and name:
                try:
                    events.append((name, json.loads(line[6:])))
                except ValueError:
                    events.append((name, {}))
                name = None
        return events


def event_names(events: list[tuple[str, dict]]) -> list[str]:
    return [name for name, _ in events]


def cited_titles(events: list[tuple[str, dict]]) -> list[str]:
    for name, data in events:
        if name == "citations":
            return [item.get("doc_title", "") for item in data.get("items", [])]
    return []


def counts() -> dict:
    conn = connect()
    try:
        return {
            "docs": conn.execute("SELECT COUNT(*) FROM kb_documents WHERE is_demo=1").fetchone()[0],
            "sessions": conn.execute("SELECT COUNT(*) FROM sessions WHERE is_demo=1").fetchone()[0],
            "users": conn.execute("SELECT COUNT(*) FROM admin_users WHERE is_demo=1").fetchone()[0],
            "shipments": conn.execute("SELECT COUNT(*) FROM shipments WHERE is_demo=1").fetchone()[0],
            "grants": conn.execute("SELECT COUNT(*) FROM authorization_grants WHERE is_demo=1").fetchone()[0],
        }
    finally:
        conn.close()


def main() -> int:
    db_module.init_db()
    admin = TestClient(app)
    login(admin, "sys_admin")

    # ---- 1. 页面与权限 ----
    page = admin.get("/admin/data")
    if page.status_code != 200:
        fail("数据管理页可访问", str(page.status_code))
    for label in ("演示规则文档", "演示会话", "演示账号", "演示运单", "演示授权"):
        if label not in page.text:
            fail("页面包含分组", label)
    ok("数据管理页可访问，五个分组齐全")

    auditor = TestClient(app)
    login(auditor, "auditor")
    if auditor.get("/admin/data").status_code != 403:
        fail("非管理员访问数据管理页应 403", "auditor 未被拒绝")
    ok("非管理员访问数据管理页 → 403")

    # ---- 2. 默认保留 ----
    before = counts()
    if before != {"docs": 2, "sessions": 3, "users": 5, "shipments": 3, "grants": 5}:
        fail("演示数据默认保留", json.dumps(before))
    ok("演示数据默认保留（文档 1 / 会话 3 / 账号 5 / 运单 3 / 授权 5）")

    # ---- 3. 删会话：连带消息 ----
    delete = admin.post("/admin/data/sessions/delete",
                        data={"csrf_token": csrf(admin), "item_id": "s_002"},
                        follow_redirects=False)
    if delete.status_code != 303:
        fail("删除演示会话", str(delete.status_code))
    conn = connect()
    try:
        left_session = conn.execute("SELECT COUNT(*) FROM sessions WHERE id='s_002'").fetchone()[0]
        left_messages = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id='s_002'"
        ).fetchone()[0]
    finally:
        conn.close()
    if left_session or left_messages:
        fail("会话与其消息一并删除", f"{left_session}/{left_messages}")

    admin.post("/admin/data/sessions/restore", data={"csrf_token": csrf(admin)},
               follow_redirects=False)
    if counts()["sessions"] != 3:
        fail("恢复演示会话", str(counts()))
    ok("删除演示会话连带消息；恢复后回到 3 个")

    # ---- 4. 删文档：该线路检索失效，恢复后恢复 ----
    rule = TestClient(app)
    login(rule, "rule_admin")
    session_id = re.search(r'data-session="([^"]+)"', rule.get("/admin/chat").text).group(1)
    if "delta" not in event_names(ask(rule, session_id, "客户临时改地址，异常应归为哪一类？")):
        fail("删除前可以正常回答", "没有 delta")

    admin.post("/admin/data/docs/delete", data={"csrf_token": csrf(admin), "item_id": "doc_001"},
               follow_redirects=False)
    events = ask(rule, session_id, "客户临时改地址，异常应归为哪一类？")
    if cited_titles(events):
        fail("删除演示文档后该线路无引用", str(cited_titles(events)))
    if not any(name == "guardrail" and data.get("needs_review")
               for name, data in events):
        fail("无引用时应标记需人工复核", str(event_names(events)))
    ok("删除演示文档后该线路无引用，回答标记需人工复核")

    admin.post("/admin/data/docs/restore", data={"csrf_token": csrf(admin)},
               follow_redirects=False)
    if counts()["docs"] != 2 or "delta" not in event_names(
        ask(rule, session_id, "客户临时改地址，异常应归为哪一类？")
    ):
        fail("恢复演示文档后可检索", str(counts()))
    ok("恢复演示文档后检索恢复，对话正常出 delta")

    # ---- 5. 删账号：保护当前登录账号 ----
    self_delete = admin.post("/admin/data/users/delete",
                             data={"csrf_token": csrf(admin), "item_id": "u_sys"},
                             follow_redirects=True)
    if "当前登录" not in self_delete.text:
        fail("不能删除当前登录账号", "未拦截")
    ok("不能删除当前登录的演示账号")

    delete_user = admin.post("/admin/data/users/delete",
                             data={"csrf_token": csrf(admin), "item_id": "u_audit"},
                             follow_redirects=False)
    if delete_user.status_code != 303:
        fail("删除其他演示账号", str(delete_user.status_code))
    conn = connect()
    try:
        gone = conn.execute("SELECT COUNT(*) FROM admin_users WHERE id='u_audit'").fetchone()[0]
        grants_gone = conn.execute(
            "SELECT COUNT(*) FROM authorization_grants WHERE user_id='u_audit'"
        ).fetchone()[0]
    finally:
        conn.close()
    if gone or grants_gone:
        fail("账号与其授权一并删除", f"{gone}/{grants_gone}")
    admin.post("/admin/data/users/restore", data={"csrf_token": csrf(admin)},
               follow_redirects=False)
    if counts()["users"] != 5:
        fail("恢复演示账号", str(counts()))
    ok("删除演示账号连带其授权；恢复后回到 5 个")

    # ---- 6. 删运单与授权 ----
    admin.post("/admin/data/shipments/delete",
               data={"csrf_token": csrf(admin), "item_id": "YD20261030002"},
               follow_redirects=False)
    conn = connect()
    try:
        ship_gone = conn.execute(
            "SELECT COUNT(*) FROM shipments WHERE shipment_no='YD20261030002'"
        ).fetchone()[0]
        grant_gone = conn.execute(
            "SELECT COUNT(*) FROM authorization_grants WHERE shipment_no='YD20261030002'"
        ).fetchone()[0]
    finally:
        conn.close()
    if ship_gone or grant_gone:
        fail("演示运单与其授权一并删除", f"{ship_gone}/{grant_gone}")
    admin.post("/admin/data/shipments/restore", data={"csrf_token": csrf(admin)},
               follow_redirects=False)
    admin.post("/admin/data/grants/restore", data={"csrf_token": csrf(admin)},
               follow_redirects=False)
    after = counts()
    if after["shipments"] != 3 or after["grants"] != 5:
        fail("恢复演示运单与授权", json.dumps(after))
    ok("删除演示运单连带授权；恢复后运单 3 / 授权 5")

    # ---- 7. 提示词模板：默认话术是浅色提示，不是正文 ----
    prompts = rule.get("/admin/prompts")
    match = re.search(
        r'<textarea name="editable_section"[^>]*placeholder="([^"]*)"[^>]*>(.*?)</textarea>',
        prompts.text, re.S,
    )
    if not match:
        fail("提示词 textarea 带 placeholder", "未找到")
    placeholder, body = match.group(1), match.group(2).strip()
    if not placeholder.strip() or body:
        fail("默认话术只作提示、正文为空", f"placeholder={len(placeholder)} body={len(body)}")
    ok("提示词模板：默认话术作为浅色 placeholder，正文为空")

    empty_submit = rule.post(
        "/admin/prompts/pt_001/draft",
        data={"csrf_token": csrf(rule), "editable_section": ""},
        follow_redirects=True,
    )
    if "话术段是空的" not in empty_submit.text:
        fail("空提交被明确拒绝", "未提示")
    ok("提交空话术 → 明确提示（不会把提示文字当成正文保存）")

    # ---- 8. 恢复后仍是「演示」标记 ----
    if counts() != before:
        fail("全部恢复后计数与初始一致", json.dumps(counts()))
    ok("全部恢复后与初始状态一致，演示数据仍在")

    print()
    print(f"全部通过：{len(STEPS)} 项")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
