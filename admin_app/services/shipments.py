"""运单主数据维护。

运单线路是授权预检的判定依据（见 services/grants.py），所以这张表要能维护：
登记、改客户/状态、删除。删除前先看有没有生效中的授权，避免
「删了运单、授权还在」这种自相矛盾的状态。

线路本身由 services/lanes.py 管理；这里只做校验（必须存在且启用）。
"""
from __future__ import annotations

import sqlite3

from ..db import now_iso
from . import grants as grant_service
from ..security import object_hash
from .audit_log import log as audit

# 状态码 → 展示文案。中文直接给到界面和提示词，避免模型自己翻译。
STATUS_TEXT = {
    "in_transit": "在途",
    "delivered": "已签收",
    "exception": "异常",
    "cancelled": "已取消",
}
STATUS_CHOICES = tuple(STATUS_TEXT.keys())


def status_text(status: str) -> str:
    return STATUS_TEXT.get(status, status)


def normalize(shipment_no: str | None) -> str:
    return grant_service.normalize(shipment_no)


def status_options() -> list[tuple[str, str]]:
    return [(code, text) for code, text in STATUS_TEXT.items()]


# ---------------------------------------------------------------------------
# 查询
# ---------------------------------------------------------------------------


def list_shipments(conn: sqlite3.Connection, keyword: str = "", status: str = "") -> list[dict]:
    sql = (
        "SELECT s.*,"
        "       (SELECT COUNT(*) FROM authorization_grants g"
        "         WHERE g.shipment_no=s.shipment_no AND g.status='active'"
        "           AND (g.expires_at IS NULL OR g.expires_at >= ?)) AS active_grants"
        "  FROM shipments s WHERE 1=1"
    )
    params: list = [now_iso()]
    if keyword:
        sql += " AND (s.shipment_no LIKE ? OR s.customer LIKE ? OR s.lane_scope LIKE ?)"
        like = f"%{keyword}%"
        params += [like, like, like]
    if status:
        sql += " AND s.status=?"
        params.append(status)
    sql += " ORDER BY s.shipment_no"
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def get(conn: sqlite3.Connection, shipment_no: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM shipments WHERE shipment_no=?", (grant_service.normalize(shipment_no),)
    ).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# 写操作
# ---------------------------------------------------------------------------


def save(
    conn: sqlite3.Connection, actor: dict, shipment_no: str, lane_scope: str,
    customer: str = "", status: str = "in_transit",
) -> tuple[bool, str]:
    number, error = grant_service.validate_format(shipment_no)
    if error:
        return False, error
    lane = (lane_scope or "").strip()
    if not lane:
        return False, "线路不能为空：授权预检要靠它判断是否跨线"
    from .lanes import name_exists

    if not name_exists(conn, lane, active_only=True):
        return False, f"线路「{lane}」不存在或已停用，请先在「干线管理」里新建"
    if status not in STATUS_TEXT:
        return False, f"运单状态不合法：{status}"

    existing = get(conn, number)
    before_hash = object_hash(
        {key: existing[key] for key in ("lane_scope", "customer", "status")}
        if existing else None
    )
    after_hash = object_hash(
        {"lane_scope": lane, "customer": customer or "", "status": status}
    )
    now = now_iso()
    if existing:
        conn.execute(
            "UPDATE shipments SET lane_scope=?, customer=?, status=? WHERE shipment_no=?",
            (lane, customer.strip()[:100], status, number),
        )
        # 线路改了，历史授权的线路要跟着改，否则会与新主数据冲突
        if existing["lane_scope"] != lane:
            conn.execute(
                "UPDATE authorization_grants SET lane_scope=? WHERE shipment_no=?",
                (lane, number),
            )
        action = "shipment.update"
    else:
        conn.execute(
            "INSERT INTO shipments (shipment_no, lane_scope, customer, status, is_demo, created_at)"
            " VALUES (?,?,?,?,0,?)",
            (number, lane, customer.strip()[:100], status, now),
        )
        action = "shipment.create"
    conn.commit()
    audit(conn, actor, action, "shipment", number,
          f"线路={lane} 客户={customer or '-'} 状态={status}",
          before_hash=before_hash, after_hash=after_hash)
    conn.commit()
    return True, ""


def delete(conn: sqlite3.Connection, actor: dict, shipment_no: str) -> tuple[bool, str]:
    number = grant_service.normalize(shipment_no)
    row = get(conn, number)
    if row is None:
        return False, "运单不存在"

    active = conn.execute(
        "SELECT COUNT(*) FROM authorization_grants"
        " WHERE shipment_no=? AND status='active'"
        "   AND (expires_at IS NULL OR expires_at >= ?)",
        (number, now_iso()),
    ).fetchone()[0]
    if active:
        return False, f"该运单还有 {active} 条生效中的授权，请先在「运单授权」页撤销"

    conn.execute("DELETE FROM authorization_grants WHERE shipment_no=?", (number,))
    conn.execute("DELETE FROM shipments WHERE shipment_no=?", (number,))
    conn.commit()
    audit(conn, actor, "shipment.delete", "shipment", number,
          f"同时清理撤销状态授权 演示={row['is_demo']}")
    conn.commit()
    return True, ""
