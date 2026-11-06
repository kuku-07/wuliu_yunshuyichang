"""异常自动路由：按类型 + 时限指派到具名处理人（流程口径 第 3 步）。

规则是确定性的：先看类型关键词，再看角色；同角色里选当前未结异常最少的人。
路由后写 due_at（发生时 + 2 小时）并给处理人发通知。
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

from ..db import now_iso
from . import notify
from .audit_log import log as audit

DEFAULT_DUE_HOURS = 2

ROLE_BY_KEYWORD: list[tuple[tuple[str, ...], str, str]] = [
    (("危险品", "事故", "赔付", "货损", "人身"), "sys_admin", "高危异常 → 系统管理员"),
    (("回执", "签收", "单证"), "supervisor", "回执/签收类 → 客服主管"),
    ((), "supervisor", "常规异常 → 客服主管"),
]


def _rule_for(event_type: str) -> tuple[str, str]:
    for keywords, role, label in ROLE_BY_KEYWORD:
        if not keywords:
            return role, label
        if any(keyword in event_type for keyword in keywords):
            return role, label
    return "supervisor", "常规异常 → 客服主管"


def _pick_handler(conn: sqlite3.Connection, role: str) -> str:
    rows = conn.execute(
        "SELECT u.id, COUNT(e.id) AS open_count"
        " FROM admin_users u LEFT JOIN exception_events e"
        "   ON e.handler=u.id AND e.closed_at IS NULL"
        " WHERE u.status='active' AND u.role=?"
        " GROUP BY u.id ORDER BY open_count, u.employee_no LIMIT 1",
        (role,),
    ).fetchone()
    return rows[0] if rows else ""


def route_event(
    conn: sqlite3.Connection, event_id: str, actor: dict | None = None,
) -> tuple[bool, str]:
    row = conn.execute("SELECT * FROM exception_events WHERE id=?", (event_id,)).fetchone()
    if row is None:
        return False, "异常事件不存在"
    if row["handler"]:
        return False, "已有处理人"

    role, label = _rule_for(row["event_type"])
    handler = _pick_handler(conn, role)
    if not handler:
        return False, f"没有可用的{role}账号"

    due_at = row["due_at"]
    if not due_at:
        try:
            occurred = datetime.fromisoformat(row["occurred_at"])
            due_at = (occurred + timedelta(hours=DEFAULT_DUE_HOURS)).strftime(
                "%Y-%m-%dT%H:%M:%S"
            )
        except ValueError:
            due_at = None

    conn.execute(
        "UPDATE exception_events SET handler=?, routed_at=?, route_rule=?, due_at=?"
        " WHERE id=?",
        (handler, now_iso(), label, due_at, event_id),
    )
    conn.commit()
    notify.push(
        conn, [handler], "ASSIGN",
        f"自动路由：{row['shipment_no']} · {row['event_type']}",
        label, "/admin/todos",
    )
    if actor is not None:
        audit(conn, actor, "event.route", "exception_event", event_id,
              f"{row['shipment_no']} → {handler}（{label}）")
        conn.commit()
    return True, label


def route_unassigned(conn: sqlite3.Connection) -> dict:
    rows = conn.execute(
        "SELECT id FROM exception_events WHERE handler='' AND closed_at IS NULL"
    ).fetchall()
    routed = 0
    for row in rows:
        ok, _ = route_event(conn, row[0])
        if ok:
            routed += 1
    return {"routed": routed, "pending": len(rows) - routed}
