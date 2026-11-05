"""运单快照：每次接入后存一份带版本的全量数据。

文档要求「快照版本」，因为运单、子单、轨迹都会被后续数据覆盖；
只存当前值会导致争议时无法还原「当时看到的是什么」。
"""
from __future__ import annotations

import json
import sqlite3
import uuid

from ..db import now_iso


def _collect(conn: sqlite3.Connection, shipment_no: str) -> dict:
    shipment = conn.execute(
        "SELECT * FROM shipments WHERE shipment_no=?", (shipment_no,)
    ).fetchone()
    if shipment is None:
        return {}
    subs = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM sub_shipments WHERE shipment_no=? ORDER BY sub_no",
            (shipment_no,),
        ).fetchall()
    ]
    tracks = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM shipment_tracks WHERE shipment_no=? ORDER BY at DESC LIMIT 20",
            (shipment_no,),
        ).fetchall()
    ]
    return {"shipment": dict(shipment), "sub_shipments": subs, "tracks": tracks}


def capture(
    conn: sqlite3.Connection, shipment_no: str, source: str = "TMS",
) -> dict | None:
    """写入新版本快照；运单不存在返回 None。"""
    data = _collect(conn, shipment_no)
    if not data:
        return None

    version = conn.execute(
        "SELECT COALESCE(MAX(version), 0) + 1 FROM shipment_snapshots WHERE shipment_no=?",
        (shipment_no,),
    ).fetchone()[0]
    data_time = max(
        [track["data_time"] for track in data["tracks"] if track.get("data_time")]
        + [now_iso()]
    )
    snapshot_id = f"snap_{uuid.uuid4().hex[:12]}"
    conn.execute(
        "INSERT INTO shipment_snapshots"
        " (id, shipment_no, version, data_json, data_time, source, created_at)"
        " VALUES (?,?,?,?,?,?,?)",
        (
            snapshot_id, shipment_no, version,
            json.dumps(data, ensure_ascii=False), data_time, source, now_iso(),
        ),
    )
    conn.commit()
    return {
        "id": snapshot_id, "version": version, "data_time": data_time, "source": source,
    }


def latest(conn: sqlite3.Connection, shipment_no: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM shipment_snapshots WHERE shipment_no=?"
        " ORDER BY version DESC LIMIT 1",
        (shipment_no,),
    ).fetchone()
    if row is None:
        return None
    item = dict(row)
    try:
        item["data"] = json.loads(item["data_json"])
    except ValueError:
        item["data"] = {}
    return item


def list_for(conn: sqlite3.Connection, shipment_no: str, limit: int = 10) -> list[dict]:
    return [
        dict(r)
        for r in conn.execute(
            "SELECT id, version, data_time, source, created_at FROM shipment_snapshots"
            " WHERE shipment_no=? ORDER BY version DESC LIMIT ?",
            (shipment_no, limit),
        ).fetchall()
    ]
