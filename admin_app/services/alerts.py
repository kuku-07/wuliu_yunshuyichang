"""异常预警：轨迹 + 计划 + 异常记录 的确定性规则。

docs/02 §2 要求「异常预警（关联轨迹 + 计划 + 异常记录）」，§8 还要求误报率 ≤10%。
这里的规则全部是确定性判断，不调模型：

- 预计超时：过了计划到达 + 30 分钟仍未签收
- 轨迹停滞：在途且最近轨迹超过 2 小时没刷新
- 回执超期：已签收但 24 小时内没有回执
- 多异常：同一运单还有 ≥2 条未关闭异常

预警要人工确认或标误报，误报率 = 误报 / (确认 + 误报)。
"""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timedelta

from ..db import now_iso
from . import notify
from .audit_log import log as audit

DELIVERY_GRACE_MINUTES = 30
TRACK_STALE_HOURS = 2
RECEIPT_GRACE_HOURS = 24
MULTI_EXCEPTION_MIN = 2

ALERT_TYPES = {
    "DELIVERY_OVERDUE": "预计超时",
    "TRACK_STALE": "轨迹停滞",
    "RECEIPT_MISSING": "回执超期",
    "MULTI_EXCEPTION": "多异常聚集",
}

SEVERITY = {
    "DELIVERY_OVERDUE": "high",
    "TRACK_STALE": "medium",
    "RECEIPT_MISSING": "medium",
    "MULTI_EXCEPTION": "low",
}


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _raise_alert(
    conn: sqlite3.Connection, shipment_no: str, alert_type: str, reason: str,
) -> bool:
    cursor = conn.execute(
        "INSERT OR IGNORE INTO alerts"
        " (id, shipment_no, alert_type, severity, reason, status, created_at)"
        " VALUES (?,?,?,?,?, 'open', ?)",
        (
            f"al_{uuid.uuid4().hex[:12]}", shipment_no, alert_type,
            SEVERITY.get(alert_type, "medium"), reason, now_iso(),
        ),
    )
    created = cursor.rowcount > 0
    if created:
        notify.push_to_roles(
            conn, ("supervisor", "sys_admin"), "ALERT",
            f"{shipment_no} · {ALERT_TYPES.get(alert_type, alert_type)}",
            reason, "/admin/exceptions",
        )
    return created


def evaluate(conn: sqlite3.Connection, actor: dict | None = None) -> dict:
    """扫描全部运单，生成仍成立的预警（同一运单同一类型只保留一条 open）。"""
    now = datetime.now()
    created = 0
    shipments = [
        dict(r) for r in conn.execute("SELECT * FROM shipments").fetchall()
    ]

    for shipment in shipments:
        number = shipment["shipment_no"]
        delivered = _parse(shipment.get("delivered_at"))
        plan_eta = _parse(shipment.get("plan_eta"))

        if not delivered and plan_eta and now - plan_eta > timedelta(
            minutes=DELIVERY_GRACE_MINUTES
        ):
            if _raise_alert(
                conn, number, "DELIVERY_OVERDUE",
                f"计划到达 {shipment['plan_eta']}，至今未签收",
            ):
                created += 1

        last_track = conn.execute(
            "SELECT at, data_time FROM shipment_tracks WHERE shipment_no=?"
            " ORDER BY at DESC LIMIT 1",
            (number,),
        ).fetchone()
        if not delivered and last_track is not None:
            tracked_at = _parse(last_track["data_time"]) or _parse(last_track["at"])
            if tracked_at and now - tracked_at > timedelta(hours=TRACK_STALE_HOURS):
                if _raise_alert(
                    conn, number, "TRACK_STALE",
                    f"最近轨迹停留在 {last_track['data_time'] or last_track['at']}，超过 "
                    f"{TRACK_STALE_HOURS} 小时未刷新",
                ):
                    created += 1

        if delivered and not shipment.get("receipt_at"):
            if now - delivered > timedelta(hours=RECEIPT_GRACE_HOURS):
                if _raise_alert(
                    conn, number, "RECEIPT_MISSING",
                    f"{shipment['delivered_at']} 已签收，超过 {RECEIPT_GRACE_HOURS} 小时无回执",
                ):
                    created += 1

        open_events = conn.execute(
            "SELECT COUNT(*) FROM exception_events"
            " WHERE shipment_no=? AND closed_at IS NULL",
            (number,),
        ).fetchone()[0]
        if open_events >= MULTI_EXCEPTION_MIN:
            if _raise_alert(
                conn, number, "MULTI_EXCEPTION",
                f"还有 {open_events} 条未关闭异常，需统一处置",
            ):
                created += 1

    conn.commit()
    if created and actor is not None:
        audit(conn, actor, "alert.evaluate", "alert", "batch", f"新增预警 {created} 条")
        conn.commit()
    return {"created": created, "checked": len(shipments)}


def list_alerts(conn: sqlite3.Connection, status: str = "open") -> list[dict]:
    sql = "SELECT * FROM alerts"
    params: list = []
    if status:
        sql += " WHERE status=?"
        params.append(status)
    sql += " ORDER BY CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,"
    sql += " created_at DESC"
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def review(
    conn: sqlite3.Connection, actor: dict, alert_id: str, verdict: str, note: str = "",
) -> tuple[bool, str]:
    status = {"confirm": "confirmed", "false_positive": "false_positive"}.get(verdict)
    if status is None:
        return False, "不支持的处置方式"
    row = conn.execute("SELECT * FROM alerts WHERE id=?", (alert_id,)).fetchone()
    if row is None:
        return False, "预警不存在"
    if row["status"] != "open":
        return False, "该预警已处置"

    conn.execute(
        "UPDATE alerts SET status=?, reviewed_at=?, reviewed_by=?, review_note=? WHERE id=?",
        (status, now_iso(), actor["id"], (note or "").strip()[:200], alert_id),
    )
    conn.commit()
    audit(conn, actor, f"alert.{verdict}", "alert", alert_id,
          f"{row['shipment_no']} {ALERT_TYPES.get(row['alert_type'], row['alert_type'])}")
    conn.commit()
    return True, "已确认" if status == "confirmed" else "已标记误报"


def stats(conn: sqlite3.Connection) -> dict:
    open_count = conn.execute(
        "SELECT COUNT(*) FROM alerts WHERE status='open'"
    ).fetchone()[0]
    confirmed = conn.execute(
        "SELECT COUNT(*) FROM alerts WHERE status='confirmed'"
    ).fetchone()[0]
    false_positive = conn.execute(
        "SELECT COUNT(*) FROM alerts WHERE status='false_positive'"
    ).fetchone()[0]
    reviewed = confirmed + false_positive
    return {
        "open": open_count,
        "confirmed": confirmed,
        "false_positive": false_positive,
        "false_positive_rate": round(false_positive * 100.0 / reviewed, 1) if reviewed else 0.0,
    }
