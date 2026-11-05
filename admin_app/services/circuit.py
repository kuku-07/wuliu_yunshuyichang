"""预警误报率熔断。

docs/02 §10：误报率连续两周超过 10% 时，暂停自动建议，回退到纯人工。
实现取「最近 14 天已处置预警」的误报率，样本少于 5 条不触发（避免误杀）。
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

WINDOW_DAYS = 14
THRESHOLD = 10.0
MIN_REVIEWED = 5


def status(conn: sqlite3.Connection) -> tuple[bool, float]:
    cutoff = (datetime.now() - timedelta(days=WINDOW_DAYS)).strftime("%Y-%m-%dT%H:%M:%S")
    rows = conn.execute(
        "SELECT status FROM alerts WHERE status IN ('confirmed','false_positive')"
        " AND COALESCE(reviewed_at, created_at) >= ?",
        (cutoff,),
    ).fetchall()
    reviewed = len(rows)
    if reviewed < MIN_REVIEWED:
        return False, 0.0
    false_positive = sum(1 for row in rows if row[0] == "false_positive")
    rate = round(false_positive * 100.0 / reviewed, 1)
    return rate > THRESHOLD, rate
