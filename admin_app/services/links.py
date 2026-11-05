"""运单↔子单映射：多对多 + 来源/版本优先级归并。

同一子单可能被 TMS、承运商回传、人工登记分别报过，字段可能不一致。
这里保留**全部来源**（可追溯），再按「优先级 → 版本 → 更新时间」选出一条
生效口径给上层用。优先级：TMS 100、承运商 80、人工 60。
"""
from __future__ import annotations

import sqlite3


def list_links(conn: sqlite3.Connection, shipment_no: str) -> list[dict]:
    return [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM shipment_links WHERE shipment_no=?"
            " ORDER BY sub_no, priority DESC, source_version DESC",
            (shipment_no,),
        ).fetchall()
    ]


def resolve(conn: sqlite3.Connection, shipment_no: str) -> list[dict]:
    """每个子单选一条生效记录，同时保留候选来源供追溯。"""
    grouped: dict[str, list[dict]] = {}
    for link in list_links(conn, shipment_no):
        if not link.get("is_active"):
            continue
        grouped.setdefault(link["sub_no"], []).append(link)

    resolved = []
    for sub_no, candidates in sorted(grouped.items()):
        winner = sorted(
            candidates,
            key=lambda row: (
                row.get("priority") or 0,
                row.get("source_version") or "",
                row.get("updated_at") or "",
            ),
            reverse=True,
        )[0]
        resolved.append({
            "sub_no": sub_no,
            "shipment_no": winner["shipment_no"],
            "carrier": winner["carrier"],
            "status": winner["status"],
            "source": winner["source"],
            "source_version": winner["source_version"],
            "candidates": [
                {
                    "source": row["source"],
                    "source_version": row["source_version"],
                    "priority": row["priority"],
                    "status": row["status"],
                }
                for row in candidates
            ],
        })
    return resolved


def upsert(
    conn: sqlite3.Connection, shipment_no: str, sub_no: str, carrier: str,
    source: str, source_version: str = "", priority: int = 60, status: str = "",
) -> None:
    from ..db import now_iso

    conn.execute(
        "INSERT INTO shipment_links"
        " (id, shipment_no, sub_no, carrier, source, source_version, priority,"
        "  is_active, status, updated_at)"
        " VALUES (?,?,?,?,?,?,?,1,?,?)"
        " ON CONFLICT(sub_no, source) DO UPDATE SET"
        "   shipment_no=excluded.shipment_no, carrier=excluded.carrier,"
        "   source_version=excluded.source_version, priority=excluded.priority,"
        "   status=excluded.status, updated_at=excluded.updated_at",
        (
            f"lnk_{sub_no}_{source}", shipment_no, sub_no, carrier, source,
            source_version, priority, status, now_iso(),
        ),
    )
