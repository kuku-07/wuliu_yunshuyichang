"""运单级授权（ABAC 预检）。

业务约束来自 鉴权与授权约束：
请求带 shipment_no 时，**在流开始之前**校验该用户是否被授权查询这一票；
未授权直接 403 SHIPMENT_FORBIDDEN，不检索、不调用模型、不产生回答。

除「有没有授权」外，还有两道约束：

1. **运单号格式**：默认 `YD + 11 位数字`，可用环境变量 `SHIPMENT_NO_PATTERN` 覆盖；
   格式不合法直接 400，不进入授权查询。
2. **线路一致**：运单的归属线路在 `shipments`（运单主数据）里；
   运单线路必须同时匹配「会话线路」和「授权上的线路」，否则拒绝。
   这条挡的是 f50：A 干线的口径被拿去回答 B 干线的问题。

拒绝原因分开记录，否则出了问题查不出来是「没授权」「被撤销」「过期」还是「跨线路」。
"""
from __future__ import annotations

import re
import sqlite3
import uuid

from .. import config
from ..db import now_iso
from .audit_log import log as audit

# 拒绝原因码（进审计），与用户可见文案分开
REASON_OK = "AUTHORIZED"
REASON_NONE = "NO_GRANT"
REASON_REVOKED = "GRANT_REVOKED"
REASON_EXPIRED = "GRANT_EXPIRED"
REASON_UNKNOWN_SHIPMENT = "SHIPMENT_UNKNOWN"
REASON_LANE_MISMATCH = "LANE_MISMATCH"
REASON_GRANT_LANE_MISMATCH = "GRANT_LANE_MISMATCH"

REASON_TEXT = {
    REASON_NONE: "没有任何授权记录",
    REASON_REVOKED: "授权已被撤销",
    REASON_EXPIRED: "授权已过期",
    REASON_UNKNOWN_SHIPMENT: "运单不在主数据中，无法判定线路",
    REASON_LANE_MISMATCH: "运单线路与会话线路不一致",
    REASON_GRANT_LANE_MISMATCH: "授权线路与运单线路不一致",
}

# 用户可见文案：不暴露「是哪种拒绝」，避免被用来试探运单是否存在
FORBIDDEN_MESSAGE = "你无权查询该运单，请联系管理员授权"

_PATTERN = re.compile(config.SHIPMENT_NO_PATTERN)


def normalize(shipment_no: str | None) -> str:
    return (shipment_no or "").strip().upper()


def validate_format(shipment_no: str | None) -> tuple[str, str]:
    """返回 (规范化后的运单号, 错误文案)。错误文案为空表示通过。"""
    shipment = normalize(shipment_no)
    if not shipment:
        return "", "运单号不能为空"
    if len(shipment) > 40:
        return shipment, "运单号过长（上限 40 字符）"
    if not _PATTERN.match(shipment):
        return shipment, f"运单号格式不正确（示例 {config.SHIPMENT_NO_EXAMPLE}）"
    return shipment, ""


def get_shipment(conn: sqlite3.Connection, shipment_no: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM shipments WHERE shipment_no=?", (normalize(shipment_no),)
    ).fetchone()
    return dict(row) if row else None


def check(
    conn: sqlite3.Connection, user_id: str, shipment_no: str, session_lane: str = "",
) -> tuple[bool, str]:
    """返回 (是否放行, 原因码)。只读，不写任何东西。"""
    shipment = normalize(shipment_no)
    if not shipment:
        return True, REASON_OK

    # 1) 运单必须存在于主数据：不存在就无从判定线路，不能放行
    ship = get_shipment(conn, shipment)
    if ship is None:
        return False, REASON_UNKNOWN_SHIPMENT

    # 2) 运单线路 vs 会话线路
    ship_lane = (ship.get("lane_scope") or "").strip()
    lane = (session_lane or "").strip()
    if ship_lane and lane and ship_lane != lane:
        return False, REASON_LANE_MISMATCH

    # 3) 授权记录本身的三种状态
    row = conn.execute(
        "SELECT status, expires_at, lane_scope FROM authorization_grants"
        " WHERE user_id=? AND shipment_no=?",
        (user_id, shipment),
    ).fetchone()
    if row is None:
        return False, REASON_NONE
    if row["status"] != "active":
        return False, REASON_REVOKED
    expires_at = row["expires_at"]
    if expires_at and expires_at < now_iso():
        return False, REASON_EXPIRED

    # 4) 授权线路 vs 运单线路
    grant_lane = (row["lane_scope"] or "").strip()
    if grant_lane and ship_lane and grant_lane != ship_lane:
        return False, REASON_GRANT_LANE_MISMATCH

    return True, REASON_OK


def record_check(
    conn: sqlite3.Connection, actor: dict, shipment_no: str, allowed: bool, reason: str,
    request_id: str = "",
) -> None:
    """把预检结果写进审计：放行和拒绝都要留痕。"""
    action = "chat.shipment_allowed" if allowed else "chat.shipment_forbidden"
    detail = f"运单={normalize(shipment_no)} 结果={reason}"
    if not allowed:
        detail += f"（{REASON_TEXT.get(reason, reason)}）"
    audit(conn, actor, action, "shipment", normalize(shipment_no), detail, request_id)
    conn.commit()


# ---------------------------------------------------------------------------
# 管理入口用
# ---------------------------------------------------------------------------


def list_grants(conn: sqlite3.Connection, keyword: str = "", status: str = "") -> list[dict]:
    sql = (
        "SELECT g.*, u.name AS user_name, u.employee_no AS employee_no,"
        "       u.role AS user_role, gb.name AS granted_by_name,"
        "       s.lane_scope AS shipment_lane,"
        "       CASE WHEN g.status='active' AND g.expires_at IS NOT NULL"
        "                 AND g.expires_at < ? THEN 'expired'"
        "            ELSE g.status END AS state"
        "  FROM authorization_grants g"
        "  LEFT JOIN admin_users u ON u.id = g.user_id"
        "  LEFT JOIN admin_users gb ON gb.id = g.granted_by"
        "  LEFT JOIN shipments s ON s.shipment_no = g.shipment_no"
        " WHERE 1=1"
    )
    params: list = [now_iso()]
    if keyword:
        sql += " AND (g.shipment_no LIKE ? OR u.name LIKE ? OR u.employee_no LIKE ?)"
        like = f"%{keyword}%"
        params += [like, like, like]
    sql += " ORDER BY g.granted_at DESC"
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    if status:
        rows = [r for r in rows if r["state"] == status]
    return rows


def list_shipments(conn: sqlite3.Connection) -> list[dict]:
    return [
        dict(r)
        for r in conn.execute(
            "SELECT shipment_no, lane_scope, customer, status FROM shipments"
            " ORDER BY shipment_no"
        ).fetchall()
    ]


def active_users(conn: sqlite3.Connection) -> list[dict]:
    return [
        dict(r)
        for r in conn.execute(
            "SELECT id, employee_no, name, role FROM admin_users"
            " WHERE status='active' ORDER BY employee_no"
        ).fetchall()
    ]


def grant(
    conn: sqlite3.Connection, actor: dict, user_id: str, shipment_no: str,
    expires_at: str | None = None, reason: str = "",
) -> tuple[bool, str]:
    """新增或重新启用一条授权。

    线路不让人填：一律取运单主数据里的归属线路，避免人工填错导致越权。
    """
    shipment, error = validate_format(shipment_no)
    if error:
        return False, error

    ship = get_shipment(conn, shipment)
    if ship is None:
        return False, f"运单 {shipment} 不在运单主数据中，无法判定线路，不能授权"
    lane = ship.get("lane_scope") or ""

    row = conn.execute(
        "SELECT id FROM authorization_grants WHERE user_id=? AND shipment_no=?",
        (user_id, shipment),
    ).fetchone()
    now = now_iso()
    if row:
        conn.execute(
            "UPDATE authorization_grants"
            "   SET status='active', granted_by=?, granted_at=?, expires_at=?,"
            "       revoked_at=NULL, revoked_by=NULL, lane_scope=?, reason=?"
            " WHERE id=?",
            (actor["id"], now, expires_at or None, lane, reason[:200], row["id"]),
        )
        action = "grant.reactivate"
    else:
        conn.execute(
            "INSERT INTO authorization_grants"
            " (id, user_id, shipment_no, lane_scope, status, granted_by, granted_at,"
            "  expires_at, reason)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (f"g_{uuid.uuid4().hex[:10]}", user_id, shipment, lane, "active",
             actor["id"], now, expires_at or None, reason[:200]),
        )
        action = "grant.create"
    conn.commit()
    audit(conn, actor, action, "shipment", shipment,
          f"user={user_id} 线路={lane} 到期={expires_at or '长期'}")
    conn.commit()
    return True, ""


def revoke(
    conn: sqlite3.Connection, actor: dict, grant_id: str, reason: str = "",
) -> tuple[bool, str]:
    row = conn.execute(
        "SELECT * FROM authorization_grants WHERE id=?", (grant_id,)
    ).fetchone()
    if row is None:
        return False, "授权记录不存在"
    if row["status"] != "active":
        return False, "该授权当前不是生效状态"
    conn.execute(
        "UPDATE authorization_grants SET status='revoked', revoked_at=?, revoked_by=?,"
        " reason=? WHERE id=?",
        (now_iso(), actor["id"], reason[:200] or row["reason"], grant_id),
    )
    conn.commit()
    audit(conn, actor, "grant.revoke", "shipment", row["shipment_no"],
          f"grant={grant_id} user={row['user_id']} 原因={reason or '-'}")
    conn.commit()
    return True, ""
