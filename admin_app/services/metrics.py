"""指标体系：异常归一、草稿质量、接管与越权、到货/回执。

口径按 指标口径：到货与回执分开算，不用「消息量」代替「完成量」。
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

from . import alerts as alert_service
from .tms import FIRST_RESPONSE_MINUTES, RESOLUTION_MINUTES, _parse


def _rate(numerator: int, denominator: int) -> float:
    if not denominator:
        return 0.0
    return round(numerator * 100.0 / denominator, 1)


def overview(conn: sqlite3.Connection) -> dict:
    events = conn.execute("SELECT COUNT(*) FROM exception_events").fetchone()[0]
    pending_repairs = conn.execute(
        "SELECT COUNT(*) FROM repair_queue WHERE status='pending'"
    ).fetchone()[0]
    resolved_repairs = conn.execute(
        "SELECT COUNT(*) FROM repair_queue WHERE status='resolved'"
    ).fetchone()[0]
    draft_total = conn.execute("SELECT COUNT(*) FROM drafts").fetchone()[0]
    draft_by_status = {
        row[0]: row[1]
        for row in conn.execute(
            "SELECT status, COUNT(*) FROM drafts GROUP BY status"
        ).fetchall()
    }
    approved = draft_by_status.get("approved", 0)
    reviewed = approved + draft_by_status.get("rejected", 0)
    rejected = draft_by_status.get("rejected", 0)
    sent = conn.execute(
        "SELECT COUNT(*) FROM drafts WHERE sent_at IS NOT NULL"
    ).fetchone()[0]

    forbidden = conn.execute(
        "SELECT COUNT(*) FROM audit_logs WHERE action='chat.shipment_forbidden'"
    ).fetchone()[0]
    takeovers = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE status='takeover'"
    ).fetchone()[0]

    delivered = [
        dict(row)
        for row in conn.execute(
            "SELECT delivered_at, receipt_at, plan_eta FROM shipments"
            " WHERE delivered_at IS NOT NULL AND delivered_at <> ''"
        ).fetchall()
    ]
    on_time = 0
    receipt_in_24h = 0
    for row in delivered:
        if row["plan_eta"] and row["delivered_at"] <= row["plan_eta"]:
            on_time += 1
        if row["receipt_at"]:
            try:
                delivered_at = datetime.fromisoformat(row["delivered_at"])
                receipt_at = datetime.fromisoformat(row["receipt_at"])
                if (receipt_at - delivered_at).total_seconds() <= 24 * 3600:
                    receipt_in_24h += 1
            except ValueError:
                continue

    # ---- 异常时效（首响 / 处置 / 超时升级）----
    rows = [
        dict(r) for r in conn.execute("SELECT * FROM exception_events").fetchall()
    ]
    accepted = [r for r in rows if r.get("accepted_at")]
    first_ok = 0
    first_15 = 0
    response_minutes = []
    for row in accepted:
        occurred = _parse(row.get("occurred_at"))
        accepted_at = _parse(row.get("accepted_at"))
        if not occurred or not accepted_at:
            continue
        minutes = (accepted_at - occurred).total_seconds() / 60
        response_minutes.append(minutes)
        if minutes <= FIRST_RESPONSE_MINUTES:
            first_ok += 1
        if minutes <= 15:
            first_15 += 1

    closed = [r for r in rows if r.get("closed_at") and r.get("accepted_at")]
    resolve_ok = 0
    for row in closed:
        accepted_at = _parse(row.get("accepted_at"))
        closed_at = _parse(row.get("closed_at"))
        if accepted_at and closed_at and (
            closed_at - accepted_at
        ).total_seconds() / 60 <= RESOLUTION_MINUTES:
            resolve_ok += 1

    now = datetime.now()
    overdue = 0
    for row in rows:
        if row.get("closed_at"):
            continue
        occurred = _parse(row.get("occurred_at"))
        accepted_at = _parse(row.get("accepted_at"))
        if not accepted_at and occurred and now - occurred > timedelta(
            minutes=FIRST_RESPONSE_MINUTES
        ):
            overdue += 1
        elif accepted_at and now - accepted_at > timedelta(minutes=RESOLUTION_MINUTES):
            overdue += 1

    response_minutes.sort()
    median = (
        round(response_minutes[len(response_minutes) // 2], 1)
        if response_minutes else 0.0
    )

    return {

        "events": events,
        "pending_repairs": pending_repairs,
        "resolved_repairs": resolved_repairs,
        "normalize_rate": _rate(events, events + pending_repairs),
        "drafts": draft_total,
        "draft_by_status": draft_by_status,
        "approve_rate": _rate(approved, reviewed),
        "correction_rate": _rate(rejected, reviewed),
        "sent": sent,
        "sent_rate": _rate(sent, approved),
        "takeovers": takeovers,
        "forbidden": forbidden,
        "delivered": len(delivered),
        "on_time_rate": _rate(on_time, len(delivered)),
        "receipt_24h_rate": _rate(receipt_in_24h, len(delivered)),
        "accepted": len(accepted),
        "first_response_rate": _rate(first_ok, len(accepted)),
        "first_response_15_rate": _rate(first_15, len(accepted)),
        "median_first_response": median,
        "closed": len(closed),
        "resolution_rate": _rate(resolve_ok, len(closed)),
        "overdue": overdue,
        "escalated": sum(1 for r in rows if r.get("escalated_at")),
        **{f"alert_{key}": value for key, value in alert_service.stats(conn).items()},
    }
