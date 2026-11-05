"""演示数据管理：逐项删除 + 按组恢复。

设计前提：**演示数据默认保留**。这里只提供「删减」和「恢复」，
不提供「一键清空」——清空不是这个页面的语义。

所有删除都只针对 is_demo=1 的行；恢复用 INSERT OR IGNORE，
只补缺失的行，不覆盖已经改过的自建数据。
"""
from __future__ import annotations

import sqlite3

from ..db import (
    _seed_audit_sessions,
    _seed_grants,
    _seed_rule_doc,
    _seed_shipments,
    _seed_users,
    now_iso,
)
from .audit_log import log as audit
from .shipments import status_text as shipment_status_text

CATEGORIES = {
    "docs": "演示规则文档",
    "sessions": "演示会话",
    "users": "演示账号",
    "shipments": "演示运单",
    "grants": "演示授权",
}


# ---------------------------------------------------------------------------
# 列表
# ---------------------------------------------------------------------------


def overview(conn: sqlite3.Connection) -> dict:
    rows = {
        "docs": conn.execute(
            "SELECT COUNT(*) FROM kb_documents WHERE is_demo=1"
        ).fetchone()[0],
        "sessions": conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE is_demo=1"
        ).fetchone()[0],
        "users": conn.execute(
            "SELECT COUNT(*) FROM admin_users WHERE is_demo=1"
        ).fetchone()[0],
        "shipments": conn.execute(
            "SELECT COUNT(*) FROM shipments WHERE is_demo=1"
        ).fetchone()[0],
        "grants": conn.execute(
            "SELECT COUNT(*) FROM authorization_grants WHERE is_demo=1"
        ).fetchone()[0],
    }
    return rows


def list_docs(conn: sqlite3.Connection) -> list[dict]:
    return [
        dict(r)
        for r in conn.execute(
            "SELECT d.*, (SELECT COUNT(*) FROM kb_chunks c WHERE c.doc_id=d.id) AS chunk_count"
            "  FROM kb_documents d WHERE d.is_demo=1 ORDER BY d.id"
        ).fetchall()
    ]


def list_sessions(conn: sqlite3.Connection) -> list[dict]:
    return [
        dict(r)
        for r in conn.execute(
            "SELECT s.*, (SELECT COUNT(*) FROM messages m WHERE m.session_id=s.id) AS msg_count"
            "  FROM sessions s WHERE s.is_demo=1 ORDER BY s.id"
        ).fetchall()
    ]


def list_users(conn: sqlite3.Connection) -> list[dict]:
    return [
        dict(r)
        for r in conn.execute(
            "SELECT id, employee_no, name, role, status FROM admin_users"
            " WHERE is_demo=1 ORDER BY id"
        ).fetchall()
    ]


def list_shipments(conn: sqlite3.Connection) -> list[dict]:
    rows = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM shipments WHERE is_demo=1 ORDER BY shipment_no"
        ).fetchall()
    ]
    for row in rows:
        row["status_text"] = shipment_status_text(row.get("status", ""))
    return rows


def list_grants(conn: sqlite3.Connection) -> list[dict]:
    return [
        dict(r)
        for r in conn.execute(
            "SELECT g.*, u.name AS user_name FROM authorization_grants g"
            "  LEFT JOIN admin_users u ON u.id=g.user_id"
            " WHERE g.is_demo=1 ORDER BY g.shipment_no, g.id"
        ).fetchall()
    ]


# ---------------------------------------------------------------------------
# 删除（逐项）
# ---------------------------------------------------------------------------


def delete_doc(conn: sqlite3.Connection, actor: dict, doc_id: str) -> tuple[bool, str]:
    row = conn.execute(
        "SELECT * FROM kb_documents WHERE id=? AND is_demo=1", (doc_id,)
    ).fetchone()
    if row is None:
        return False, "演示规则文档不存在"

    conn.execute("DELETE FROM kb_chunks WHERE doc_id=?", (doc_id,))
    conn.execute("DELETE FROM kb_document_versions WHERE doc_id=?", (doc_id,))
    conn.execute("DELETE FROM kb_documents WHERE id=?", (doc_id,))
    # 检索索引数量按实际生效切片重算，对话缓存会因 last_rebuild 变化而失效
    active = conn.execute("SELECT COUNT(*) FROM kb_chunks WHERE is_active=1").fetchone()[0]
    conn.execute(
        "UPDATE kb_index_state SET active_chunks=?, last_rebuild=?, note=? WHERE id=1",
        (active, now_iso(), f"删除演示文档 {doc_id}"),
    )
    conn.commit()
    audit(conn, actor, "demo.delete_doc", "kb_document", doc_id, row["title"])
    conn.commit()
    return True, ""


def delete_session(conn: sqlite3.Connection, actor: dict, session_id: str) -> tuple[bool, str]:
    row = conn.execute(
        "SELECT * FROM sessions WHERE id=? AND is_demo=1", (session_id,)
    ).fetchone()
    if row is None:
        return False, "演示会话不存在"

    message_ids = [
        r["id"] for r in conn.execute(
            "SELECT id FROM messages WHERE session_id=?", (session_id,)
        )
    ]
    for mid in message_ids:
        conn.execute("DELETE FROM citations WHERE message_id=?", (mid,))
        conn.execute("DELETE FROM conversation_flags WHERE message_id=?", (mid,))
    conn.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
    conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
    conn.commit()
    audit(conn, actor, "demo.delete_session", "session", session_id,
          f"连带消息 {len(message_ids)} 条")
    conn.commit()
    return True, ""


def delete_user(conn: sqlite3.Connection, actor: dict, user_id: str) -> tuple[bool, str]:
    row = conn.execute(
        "SELECT * FROM admin_users WHERE id=? AND is_demo=1", (user_id,)
    ).fetchone()
    if row is None:
        return False, "演示账号不存在"
    if user_id == actor.get("id"):
        return False, "不能删除当前登录的账号"
    if row["role"] == "sys_admin":
        remaining = conn.execute(
            "SELECT COUNT(*) FROM admin_users"
            " WHERE role='sys_admin' AND status='active' AND id<>?",
            (user_id,),
        ).fetchone()[0]
        if remaining == 0:
            return False, "这是最后一个系统管理员，删掉就没人能管理了"

    sessions = [
        r["id"] for r in conn.execute("SELECT id FROM sessions WHERE user_id=?", (user_id,))
    ]
    for sid in sessions:
        message_ids = [
            r["id"] for r in conn.execute("SELECT id FROM messages WHERE session_id=?", (sid,))
        ]
        for mid in message_ids:
            conn.execute("DELETE FROM citations WHERE message_id=?", (mid,))
            conn.execute("DELETE FROM conversation_flags WHERE message_id=?", (mid,))
        conn.execute("DELETE FROM messages WHERE session_id=?", (sid,))
        conn.execute("DELETE FROM sessions WHERE id=?", (sid,))
    conn.execute("DELETE FROM authorization_grants WHERE user_id=?", (user_id,))
    conn.execute("DELETE FROM admin_users WHERE id=?", (user_id,))
    conn.commit()
    audit(conn, actor, "demo.delete_user", "admin_user", user_id,
          f"{row['employee_no']} / {row['name']}，连带会话 {len(sessions)} 个")
    conn.commit()
    return True, ""


def delete_shipment(conn: sqlite3.Connection, actor: dict, shipment_no: str) -> tuple[bool, str]:
    row = conn.execute(
        "SELECT * FROM shipments WHERE shipment_no=? AND is_demo=1", (shipment_no,)
    ).fetchone()
    if row is None:
        return False, "演示运单不存在"
    conn.execute("DELETE FROM authorization_grants WHERE shipment_no=?", (shipment_no,))
    conn.execute("DELETE FROM shipments WHERE shipment_no=?", (shipment_no,))
    conn.commit()
    audit(conn, actor, "demo.delete_shipment", "shipment", shipment_no,
          f"线路={row['lane_scope']}（连带授权）")
    conn.commit()
    return True, ""


def delete_grant(conn: sqlite3.Connection, actor: dict, grant_id: str) -> tuple[bool, str]:
    row = conn.execute(
        "SELECT * FROM authorization_grants WHERE id=? AND is_demo=1", (grant_id,)
    ).fetchone()
    if row is None:
        return False, "演示授权不存在"
    conn.execute("DELETE FROM authorization_grants WHERE id=?", (grant_id,))
    conn.commit()
    audit(conn, actor, "demo.delete_grant", "shipment", row["shipment_no"],
          f"grant={grant_id} user={row['user_id']}")
    conn.commit()
    return True, ""


DELETE_HANDLERS = {
    "docs": delete_doc,
    "sessions": delete_session,
    "users": delete_user,
    "shipments": delete_shipment,
    "grants": delete_grant,
}


def delete(conn: sqlite3.Connection, actor: dict, category: str, item_id: str) -> tuple[bool, str]:
    handler = DELETE_HANDLERS.get(category)
    if handler is None:
        return False, "不支持的数据类型"
    return handler(conn, actor, item_id)


# ---------------------------------------------------------------------------
# 恢复（按组）
# ---------------------------------------------------------------------------


def restore(conn: sqlite3.Connection, actor: dict, category: str) -> tuple[bool, int]:
    created = now_iso()
    if category == "docs":
        _seed_rule_doc(conn, created)
    elif category == "sessions":
        _seed_audit_sessions(conn, created)
    elif category == "users":
        _seed_users(conn, created)
    elif category == "shipments":
        _seed_shipments(conn, created)
    elif category == "grants":
        # 授权依赖运单，先把运单补齐，否则会造出指向不存在运单的授权
        _seed_shipments(conn, created)
        _seed_grants(conn, created)
    else:
        return False, 0

    conn.commit()
    count = overview(conn).get(category, 0)
    audit(conn, actor, "demo.restore", "demo", category, f"当前 {count} 条")
    conn.commit()
    return True, count
