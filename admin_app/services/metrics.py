"""指标体系：异常归一、草稿质量、接管与越权、到货/回执。

口径按 docs/02 §8：到货与回执分开算，不用「消息量」代替「完成量」。
"""
from __future__ import annotations

import sqlite3
from datetime import datetime


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

    return {
        "events": events,
        "pending_repairs": pending_repairs,
        "resolved_repairs": resolved_repairs,
        "normalize_rate": _rate(events, events + pending_repairs),
        "drafts": draft_total,
        "draft_by_status": draft_by_status,
        "approve_rate": _rate(approved, reviewed),
        "takeovers": takeovers,
        "forbidden": forbidden,
        "delivered": len(delivered),
        "on_time_rate": _rate(on_time, len(delivered)),
        "receipt_24h_rate": _rate(receipt_in_24h, len(delivered)),
    }
