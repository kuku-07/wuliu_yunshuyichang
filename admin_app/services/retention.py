"""90 天留存：按天删掉过期的消息与审计日志。

停止自动建议口径 要求「append-only；留存 90 天」。append-only 指的是不改不删单条，
到期整批清理是合规动作，因此单独成一个受控任务，并记录清理本身。
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

import json
import uuid

from ..db import now_iso
from .audit_log import log as audit

DEFAULT_DAYS = 90
APPROVER_ROLES = {"auditor", "sys_admin"}


def purge(conn: sqlite3.Connection, actor: dict | None, days: int = DEFAULT_DAYS) -> dict:
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")

    message_ids = [
        row[0]
        for row in conn.execute(
            "SELECT id FROM messages WHERE created_at < ?", (cutoff,)
        ).fetchall()
    ]
    citations = flags = 0
    for message_id in message_ids:
        citations += conn.execute(
            "DELETE FROM citations WHERE message_id=?", (message_id,)
        ).rowcount
        flags += conn.execute(
            "DELETE FROM conversation_flags WHERE message_id=?", (message_id,)
        ).rowcount
    messages = conn.execute("DELETE FROM messages WHERE created_at < ?", (cutoff,)).rowcount
    # 只清没有任何消息的过期会话，避免把还有历史的会话删掉
    sessions = conn.execute(
        "DELETE FROM sessions WHERE created_at < ?"
        " AND id NOT IN (SELECT DISTINCT session_id FROM messages)",
        (cutoff,),
    ).rowcount
    logs = conn.execute("DELETE FROM audit_logs WHERE created_at < ?", (cutoff,)).rowcount

    result = {
        "days": days,
        "cutoff": cutoff,
        "messages": messages,
        "citations": citations,
        "flags": flags,
        "sessions": sessions,
        "logs": logs,
        "at": now_iso(),
    }
    if any(result[key] for key in ("messages", "citations", "flags", "sessions", "logs")):
        audit(conn, actor, "retention.purge", "audit", f"{days}d",
              f"消息 {messages} / 引用 {citations} / 标记 {flags} / 会话 {sessions} / 日志 {logs}，"
              f"截止 {cutoff}")
        conn.commit()
    return result


# ---------------------------------------------------------------------------
# 合规确认：申请 → 审批 → 执行
# ---------------------------------------------------------------------------


def request(conn: sqlite3.Connection, actor: dict, days: int = DEFAULT_DAYS,
            note: str = "") -> tuple[bool, str, str]:
    pending = conn.execute(
        "SELECT COUNT(*) FROM retention_requests WHERE status='pending'"
    ).fetchone()[0]
    if pending:
        return False, "已有待审批的清理申请，请先处理", ""

    request_id = f"rr_{uuid.uuid4().hex[:10]}"
    conn.execute(
        "INSERT INTO retention_requests"
        " (id, days, status, requested_by, requested_at, note)"
        " VALUES (?,?, 'pending', ?,?,?)",
        (request_id, days, actor["id"], now_iso(), (note or "").strip()[:200]),
    )
    conn.commit()
    audit(conn, actor, "retention.request", "retention", request_id,
          f"申请清理 {days} 天前数据")
    conn.commit()
    return True, "已提交清理申请，等待合规审批", request_id


def list_requests(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    return [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM retention_requests ORDER BY requested_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    ]


def approve(
    conn: sqlite3.Connection, actor: dict, request_id: str,
) -> tuple[bool, str]:
    row = conn.execute(
        "SELECT * FROM retention_requests WHERE id=? AND status='pending'", (request_id,)
    ).fetchone()
    if row is None:
        return False, "申请不存在或已处理"
    if actor["role"] not in APPROVER_ROLES:
        return False, "只有安全与合规主管可以审批"
    if actor["id"] == row["requested_by"]:
        return False, "申请人不能审批自己的清理申请"

    result = purge(conn, actor, row["days"])
    conn.execute(
        "UPDATE retention_requests SET status='approved', decided_by=?, decided_at=?,"
        " result_json=? WHERE id=?",
        (actor["id"], now_iso(), json.dumps(result, ensure_ascii=False), request_id),
    )
    conn.commit()
    audit(conn, actor, "retention.approve", "retention", request_id,
          f"批准并清理：消息 {result['messages']} / 日志 {result['logs']}")
    conn.commit()
    return True, (
        f"已批准并清理：消息 {result['messages']} 条、日志 {result['logs']} 条"
    )


def reject(
    conn: sqlite3.Connection, actor: dict, request_id: str, note: str = "",
) -> tuple[bool, str]:
    row = conn.execute(
        "SELECT * FROM retention_requests WHERE id=? AND status='pending'", (request_id,)
    ).fetchone()
    if row is None:
        return False, "申请不存在或已处理"
    if actor["role"] not in APPROVER_ROLES:
        return False, "只有安全与合规主管可以审批"
    conn.execute(
        "UPDATE retention_requests SET status='rejected', decided_by=?, decided_at=?,"
        " note=? WHERE id=?",
        (actor["id"], now_iso(), (note or "").strip()[:200], request_id),
    )
    conn.commit()
    audit(conn, actor, "retention.reject", "retention", request_id, note or "驳回")
    conn.commit()
    return True, "已驳回"
