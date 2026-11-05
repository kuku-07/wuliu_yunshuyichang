"""90 天留存：按天删掉过期的消息与审计日志。

docs/02 §7 要求「append-only；留存 90 天」。append-only 指的是不改不删单条，
到期整批清理是合规动作，因此单独成一个受控任务，并记录清理本身。
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

from ..db import now_iso
from .audit_log import log as audit

DEFAULT_DAYS = 90


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
