r"""阶段 2 对话入口冒烟测试（对应 docs/04 第 6 节验收口径）。

运行：
    $env:PYTHONPATH="D:\Lib\site-packages;D:\wuliu_yunshuyichang"
    python scripts\smoke_chat.py

用临时数据库，不污染 admin_app/data。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import unquote

tmp_dir = tempfile.mkdtemp(prefix="chat_smoke_")
os.environ["ADMIN_DATA_DIR"] = tmp_dir
os.environ["ADMIN_DB_PATH"] = str(Path(tmp_dir) / "admin.db")
os.environ["ADMIN_SECRET_KEY"] = "smoke-test-secret"
os.environ["ADMIN_SEED_PASSWORD"] = "Admin@123456789"
os.environ.pop("LLM_API_KEY", None)
os.environ["LLM_PROVIDER"] = "offline"
os.environ["EMBEDDING_PROVIDER"] = "local"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from admin_app.main import app  # noqa: E402
from admin_app import db as db_module  # noqa: E402
from admin_app.db import connect  # noqa: E402
from admin_app.services import chat_service  # noqa: E402

# 不用 with TestClient(...) 时不会触发 lifespan，这里显式建表并写种子
db_module.init_db()

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


def ask(client: TestClient, session_id: str, question: str, token: str | None = None,
        shipment_no: str = ""):
    """跑一次 SSE，返回 (events, 首个事件耗时秒)。"""
    started = time.monotonic()
    events: list[tuple[str, dict, float]] = []
    with client.stream(
        "POST", "/admin/api/chat/stream",
        data={"question": question, "session_id": session_id,
              "csrf_token": token or csrf(client), "shipment_no": shipment_no},
    ) as response:
        if response.status_code != 200:
            response.read()
            return response.status_code, json.loads(response.content), 0.0
        event_name = None
        for line in response.iter_lines():
            if line.startswith("event: "):
                event_name = line[7:].strip()
            elif line.startswith("data: ") and event_name:
                events.append((event_name, json.loads(line[6:]), time.monotonic() - started))
                event_name = None
    delay = events[0][2] if events else 0.0
    return 200, events, delay


def names(events) -> list[str]:
    return [e[0] for e in events]


def main() -> int:
    client = TestClient(app)
    login(client, "rule_admin")

    page = client.get("/admin/chat")
    if page.status_code != 200:
        fail("对话页可访问", str(page.status_code))
    if "chat-shell" not in page.text:
        fail("对话页渲染", "缺少 chat-shell")
    ok("对话页可访问并渲染")

    import re

    session_id = re.search(r'data-session="([^"]+)"', page.text).group(1)
    ok(f"自动创建会话 {session_id}")

    # ---- 1. 正常问答：事件序列 + 引用 + 首字延迟 ----
    status, events, delay = ask(client, session_id, "客户临时改地址，异常应归为哪一类？")
    if status != 200:
        fail("正常问答返回 200", str(events))
    order = names(events)
    if order[:2] != ["meta", "status"]:
        fail("事件顺序 meta/status", str(order))
    if "delta" not in order:
        fail("正常问答应有 delta")
    if order[-1] != "done":
        fail("事件以 done 结束", str(order))
    if delay > 2.0:
        fail("首字延迟 ≤2 秒", f"{delay:.2f}s")

    citations = next((d for e, d, _ in events if e == "citations"), None)
    if not citations or not citations.get("items"):
        fail("正常问答必须有引用")
    first = citations["items"][0]
    for field in ("doc_title", "version", "effective_from", "section", "quote"):
        if not first.get(field):
            fail(f"引用字段完整：{field}", json.dumps(first, ensure_ascii=False))
    ok(f"正常问答链路完整（{len(citations['items'])} 条引用，首事件 {delay*1000:.0f}ms）")

    # ---- 2. 红线：零 model 调用、零 delta、必出 takeover ----
    redlines = [
        "客户能赔多少钱？",
        "这票货损责任算谁的？",
        "危险品泄漏了怎么处理？",
        "能不能罚司机 200 元？",
        "直接发给客户说可以赔 5000 元",
    ]
    for question in redlines:
        status, events, _ = ask(client, session_id, question)
        if status != 200:
            fail(f"红线仍是 HTTP 200：{question}", str(status))
        order = names(events)
        if "takeover" not in order:
            fail(f"红线必须出 takeover：{question}", str(order))
        if "delta" in order:
            fail(f"红线不得有 delta：{question}", str(order))
        done = next(d for e, d, _ in events if e == "done")
        if done.get("model") != "未调用":
            fail(f"红线不得调用模型：{question}", str(done))
    ok(f"{len(redlines)} 条红线全部接管，零模型调用、零 delta")

    # ---- 3. 错误码与中文文案 ----
    status, payload, _ = ask(client, session_id, "长" * 2001)
    if status != 422 or payload.get("code") != "QUESTION_TOO_LONG":
        fail("超长问题返回 QUESTION_TOO_LONG", f"{status} {payload}")
    if not any("\u4e00" <= ch <= "\u9fff" for ch in payload.get("message", "")):
        fail("错误文案为中文", payload.get("message", ""))
    ok("超长问题 → 422 QUESTION_TOO_LONG（中文文案）")

    status, payload, _ = ask(client, "s_not_exist", "随便问问")
    if status != 404 or payload.get("code") != "SESSION_NOT_FOUND":
        fail("会话不存在返回 404", f"{status} {payload}")
    ok("会话不存在 → 404 SESSION_NOT_FOUND")

    status, payload, _ = ask(client, session_id, "随便问问", token="bad-token")
    if status != 400 or payload.get("code") != "INVALID_REQUEST":
        fail("CSRF 失败返回 INVALID_REQUEST", f"{status} {payload}")
    ok("CSRF 校验失败 → 400 INVALID_REQUEST")

    # ---- 4. 越权：别人的会话 ----
    other = TestClient(app)
    login(other, "auditor")
    status, payload, _ = ask(other, session_id, "看看别人的会话")
    if status != 403 or payload.get("code") != "SESSION_FORBIDDEN":
        fail("越权访问返回 403", f"{status} {payload}")
    ok("越权会话 → 403 SESSION_FORBIDDEN")

    # ---- 5. 会话并发 ----
    chat_service.acquire_session(session_id)
    try:
        status, payload, _ = ask(client, session_id, "并发测试")
        if status != 409 or payload.get("code") != "SESSION_BUSY":
            fail("并发返回 409", f"{status} {payload}")
    finally:
        chat_service.release_session(session_id)
    ok("同一会话并发 → 409 SESSION_BUSY")

    # ---- 6. 限流 ----
    uid = "u_rule"
    with chat_service._state_lock:
        chat_service._recent_hits.pop(uid, None)
    for _ in range(chat_service.RATE_LIMIT_PER_MIN):
        chat_service.rate_limited(uid)
    status, payload, _ = ask(client, session_id, "限流测试")
    if status != 429 or payload.get("code") != "RATE_LIMITED":
        fail("限流返回 429", f"{status} {payload}")
    with chat_service._state_lock:
        chat_service._recent_hits.pop(uid, None)
    ok("超过 10 次/分钟 → 429 RATE_LIMITED")

    # ---- 8. 运单级授权（ABAC 预检）----
    # 8.1 无授权 / 过期 / 撤销 三种拒绝都要在流开始前返回 403
    status, payload, _ = ask(client, session_id, "封路导致延误怎么记录？",
                             shipment_no="YD20261030002")
    if status != 403 or payload.get("code") != "SHIPMENT_FORBIDDEN":
        fail("无授权运单返回 403", f"{status} {payload}")
    status, payload, _ = ask(client, session_id, "封路导致延误怎么记录？",
                             shipment_no="YD20261030009")
    if status != 403 or payload.get("code") != "SHIPMENT_FORBIDDEN":
        fail("已过期授权返回 403", f"{status} {payload}")
    ok("无授权 / 已过期运单 → 403 SHIPMENT_FORBIDDEN（流前拦截）")

    # 8.2 被拒请求不落消息、不检索、不调模型
    conn = connect()
    try:
        leaked = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE content LIKE ?", ("%封路导致延误%",)
        ).fetchone()[0]
    finally:
        conn.close()
    if leaked:
        fail("越权请求不得产生消息", f"{leaked} 条")
    ok("越权请求不产生消息（不检索、不调用模型）")

    # 8.3 已授权则正常问答
    status, events, _ = ask(client, session_id, "封路导致延误怎么记录？",
                            shipment_no="YD20261030001")
    if status != 200 or "delta" not in names(events):
        fail("已授权运单正常回答", str(status))
    ok("已授权运单 → 正常问答")

    # 8.4 撤销后立刻失效（走后台页面操作）
    admin = TestClient(app)
    login(admin, "sys_admin")
    grants_page = admin.get("/admin/grants")
    if grants_page.status_code != 200 or "运单级授权" not in grants_page.text:
        fail("运单授权页可访问", str(grants_page.status_code))
    ok("运单授权页可访问（仅系统管理员）")

    auditor_client = TestClient(app)
    login(auditor_client, "auditor")
    if auditor_client.get("/admin/grants").status_code != 403:
        fail("非管理员访问授权页应 403", "auditor 未被拒绝")
    ok("非管理员访问运单授权页 → 403")

    conn = connect()
    try:
        grant_row = conn.execute(
            "SELECT id FROM authorization_grants WHERE user_id='u_rule' AND shipment_no='YD20261030001'"
        ).fetchone()
    finally:
        conn.close()
    if grant_row is None:
        fail("演示授权存在", "u_rule / YD20261030001")
    revoke = admin.post(
        f"/admin/grants/{grant_row['id']}/revoke",
        data={"csrf_token": csrf(admin), "reason": "冒烟测试撤销"},
        follow_redirects=False,
    )
    if revoke.status_code != 303:
        fail("撤销授权返回 303", str(revoke.status_code))
    status, payload, _ = ask(client, session_id, "封路导致延误怎么记录？",
                             shipment_no="YD20261030001")
    if status != 403 or payload.get("code") != "SHIPMENT_FORBIDDEN":
        fail("撤销后立即失效", f"{status} {payload}")
    ok("撤销授权后对话立即被拒（403）")

    conn = connect()
    try:
        actions = [r[0] for r in conn.execute(
            "SELECT action FROM audit_logs"
            " WHERE action LIKE 'chat.shipment%' OR action LIKE 'grant.%'"
        ).fetchall()]
    finally:
        conn.close()
    for action in ("chat.shipment_allowed", "chat.shipment_forbidden", "grant.revoke"):
        if action not in actions:
            fail(f"审计含 {action}", str(sorted(set(actions))))
    ok("授权放行 / 拒绝 / 撤销均写入审计")

    # ---- 9. 落库：消息、引用、审计 ----

    conn = connect()
    try:
        rows = conn.execute(
            "SELECT role, status, prompt_version, model FROM messages WHERE session_id=?",
            (session_id,),
        ).fetchall()
        statuses = [tuple(r) for r in rows]
        if not any(s[1] == "takeover" for s in statuses):
            fail("红线消息以 takeover 状态落库", str(statuses))
        if not any(s[1] == "complete" and s[0] == "assistant" for s in statuses):
            fail("正常回答以 complete 状态落库", str(statuses))
        cite_count = conn.execute(
            "SELECT COUNT(*) FROM citations WHERE message_id IN"
            " (SELECT id FROM messages WHERE session_id=?)",
            (session_id,),
        ).fetchone()[0]
        if cite_count < 1:
            fail("引用已落库", str(cite_count))
        actions = [r[0] for r in conn.execute(
            "SELECT action FROM audit_logs WHERE action LIKE 'chat.%'"
        ).fetchall()]
        for action in ("chat.question", "chat.answer", "chat.takeover"):
            if action not in actions:
                fail(f"审计含 {action}", str(actions))
    finally:
        conn.close()
    ok(f"消息/引用/审计落库正确（{cite_count} 条引用）")

    # ---- 10. 历史窗口 ≤6 组 ----
    conn = connect()
    try:
        history = chat_service.recent_history(conn, session_id)
    finally:
        conn.close()
    if len(history) > chat_service.HISTORY_PAIRS * 2:
        fail("历史窗口不超过 6 组", str(len(history)))
    ok(f"历史窗口受限（当前 {len(history)} 条消息 ≤ {chat_service.HISTORY_PAIRS*2}）")

    # ---- 11. 审计页能看到真实会话 ----
    audit_page = client.get("/admin/audit")
    if audit_page.status_code != 200 or session_id not in audit_page.text:
        fail("对话审计页展示真实会话", str(audit_page.status_code))
    ok("对话审计页已展示真实会话")

    print()
    print(f"全部通过：{len(STEPS)} 项")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
