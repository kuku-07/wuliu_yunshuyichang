"""外部数据接入：GPS 轨迹与 IM 留痕。

这两类数据不进后台登录体系，用 `INGEST_TOKEN` 做机器鉴权：
    POST /admin/api/ingest/tracks
    POST /admin/api/ingest/im
"""
from __future__ import annotations

import sqlite3
import uuid

from ..db import now_iso
from . import links as link_service, snapshots


def add_tracks(conn: sqlite3.Connection, records: list[dict]) -> tuple[int, list[str]]:
    """写入轨迹快照；运单必须已登记，缺字段的记录直接拒绝并说明。"""
    accepted, errors = 0, []
    known = {
        row[0] for row in conn.execute("SELECT shipment_no FROM shipments").fetchall()
    }
    for index, record in enumerate(records):
        number = (record.get("shipment_no") or "").strip().upper()
        at = (record.get("at") or "").strip()
        status = (record.get("status") or "").strip()
        if number not in known:
            errors.append(f"第 {index + 1} 条：运单 {number or '-'} 未登记")
            continue
        if not at or not status:
            errors.append(f"第 {index + 1} 条：缺少 at 或 status")
            continue
        conn.execute(
            "INSERT INTO shipment_tracks"
            " (id, shipment_no, at, status, location, note, data_time)"
            " VALUES (?,?,?,?,?,?,?)",
            (
                f"t_{uuid.uuid4().hex[:12]}", number, at, status,
                record.get("location") or "", record.get("note") or "",
                record.get("data_time") or now_iso(),
            ),
        )
        accepted += 1
    if accepted:
        conn.commit()
        for number in {str(record.get("shipment_no") or "").strip().upper() for record in records}:
            if number:
                snapshots.capture(conn, number, "GPS")
    return accepted, errors


def add_im_notes(conn: sqlite3.Connection, records: list[dict]) -> tuple[int, list[str]]:
    accepted, errors = 0, []
    known = {
        row[0] for row in conn.execute("SELECT shipment_no FROM shipments").fetchall()
    }
    for index, record in enumerate(records):
        number = (record.get("shipment_no") or "").strip().upper()
        content = (record.get("content") or "").strip()
        if number not in known:
            errors.append(f"第 {index + 1} 条：运单 {number or '-'} 未登记")
            continue
        if not content:
            errors.append(f"第 {index + 1} 条：content 不能为空")
            continue
        conn.execute(
            "INSERT INTO im_notes"
            " (id, shipment_no, operator, content, occurred_at, source, created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (
                f"im_{uuid.uuid4().hex[:12]}", number,
                record.get("operator") or "", content[:1000],
                record.get("occurred_at") or now_iso(),
                record.get("source") or "IM", now_iso(),
            ),
        )
        accepted += 1
    if accepted:
        conn.commit()
    return accepted, errors


def list_im_notes(conn: sqlite3.Connection, shipment_no: str) -> list[dict]:
    return [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM im_notes WHERE shipment_no=? ORDER BY occurred_at DESC",
            (shipment_no,),
        ).fetchall()
    ]


def upsert_carrier_link(
    conn: sqlite3.Connection, shipment_no: str, sub_no: str, carrier: str,
    status: str,
) -> None:
    """承运商回传的子单映射（优先级 80，低于 TMS）。"""
    link_service.upsert(
        conn, shipment_no, sub_no, carrier, "CARRIER", "", 80, status
    )
    conn.commit()
