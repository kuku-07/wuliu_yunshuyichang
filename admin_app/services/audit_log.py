"""审计日志写入：只追加，任何业务动作都要留痕。"""
from __future__ import annotations

import sqlite3
import uuid

from ..db import now_iso


def log(
    conn: sqlite3.Connection,
    actor: dict | None,
    action: str,
    object_type: str,
    object_id: str,
    detail: str = "",
    request_id: str = "",
) -> None:
    conn.execute(
        "INSERT INTO audit_logs"
        " (id, actor_id, actor_name, action, object_type, object_id, detail, request_id, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (
            f"a_{uuid.uuid4().hex[:12]}",
            actor.get("id") if actor else None,
            actor.get("name") if actor else None,
            action,
            object_type,
            object_id,
            detail[:500],
            request_id,
            now_iso(),
        ),
    )
