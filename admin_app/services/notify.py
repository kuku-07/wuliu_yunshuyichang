"""站内通知：升级、预警、指派。

没有短信/邮件通道，先在系统内做到「有事必有人被通知」：
通知落库，未读数进入「待办」页，点开即标记已读。
"""
from __future__ import annotations

import sqlite3
import uuid

from ..db import now_iso

TYPES = {
    "ESCALATION": "超时升级",
    "ALERT": "异常预警",
    "ASSIGN": "任务指派",
    "REVIEW": "待审核",
}


def recipients_by_role(conn: sqlite3.Connection, roles: tuple[str, ...]) -> list[str]:
    marks = ",".join("?" * len(roles))
    return [
        row[0]
        for row in conn.execute(
            f"SELECT id FROM admin_users WHERE status='active' AND role IN ({marks})",
            roles,
        ).fetchall()
    ]


def push(
    conn: sqlite3.Connection, user_ids: list[str], type_name: str,
    title: str, body: str = "", link: str = "",
) -> int:
    """给一组用户各写一条通知；空用户集合直接跳过。"""
    created = 0
    for user_id in dict.fromkeys(user_ids):
        if not user_id:
            continue
        conn.execute(
            "INSERT INTO notifications"
            " (id, user_id, type, title, body, link, status, created_at)"
            " VALUES (?,?,?,?,?,?, 'unread', ?)",
            (
                f"nt_{uuid.uuid4().hex[:12]}", user_id, type_name,
                title[:120], (body or "")[:300], link or "", now_iso(),
            ),
        )
        created += 1
    if created:
        conn.commit()
    return created


def push_to_roles(
    conn: sqlite3.Connection, roles: tuple[str, ...], type_name: str,
    title: str, body: str = "", link: str = "",
) -> int:
    return push(conn, recipients_by_role(conn, roles), type_name, title, body, link)


def list_for(
    conn: sqlite3.Connection, user_id: str, unread_only: bool = False, limit: int = 50,
) -> list[dict]:
    sql = "SELECT * FROM notifications WHERE user_id=?"
    params: list = [user_id]
    if unread_only:
        sql += " AND status='unread'"
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def unread_count(conn: sqlite3.Connection, user_id: str) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM notifications WHERE user_id=? AND status='unread'",
        (user_id,),
    ).fetchone()[0]


def mark_read(conn: sqlite3.Connection, user_id: str, notification_id: str = "") -> int:
    if notification_id:
        cursor = conn.execute(
            "UPDATE notifications SET status='read' WHERE id=? AND user_id=?",
            (notification_id, user_id),
        )
    else:
        cursor = conn.execute(
            "UPDATE notifications SET status='read' WHERE user_id=? AND status='unread'",
            (user_id,),
        )
    conn.commit()
    return cursor.rowcount
