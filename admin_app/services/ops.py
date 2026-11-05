"""运维巡检：超时升级 + 预警评估。

同一个入口给两个地方用：后台定时线程（每分钟）和异常页打开时。
两者都跑也没关系——升级有幂等标记，预警有唯一约束。
"""
from __future__ import annotations

import sqlite3

from . import alerts, tms


def run_once(conn: sqlite3.Connection, actor: dict | None = None) -> dict:
    escalated = tms.escalate_overdue(conn)
    generated = alerts.evaluate(conn, actor)
    return {"escalated": escalated, "alerts": generated}
