"""TMS 适配器（只读）+ 异常事件归一。

真实系统里这里会调 TMS 的只读接口；当前仓库没有生产接口，所以改成读
`samples/tms/` 下的**脱敏导出样本**，把「查单」和「异常记录」解析进库。
接口形状、校验规则、修复队列逻辑与真实接入一致，换成 HTTP 调用时只改
`load_samples()` 一处。

归一规则（docs/02 §4.2 / docs/03 §4.1）：
- 四要素：运单号、事件类型、发生时间、来源；缺任意一项 → 修复队列，不猜值。
- 运单必须在运单主数据里；不在就进修复队列。
- 事件本身带红线类型（赔付/危险品/事故）时不丢弃，交给后续闸门判定。
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from .. import config
from ..db import now_iso
from . import grants as grant_service
from . import lanes as lane_service
from .audit_log import log as audit

SAMPLE_DIR = Path(config.BASE_DIR).parent / "samples" / "tms"
REQUIRED_FIELDS = ("shipment_no", "event_type", "occurred_at", "source")


# ---------------------------------------------------------------------------
# 读取样本（真实接入时替换成 TMS 只读 API）
# ---------------------------------------------------------------------------


def load_samples(directory: Path | None = None) -> dict[str, Any]:
    base = directory or SAMPLE_DIR
    queries, exceptions, errors = [], [], []

    for path in sorted(base.glob("query_*.json")):
        try:
            queries.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            errors.append(f"{path.name}: {exc}")

    exc_path = base / "exceptions.json"
    if exc_path.exists():
        try:
            payload = json.loads(exc_path.read_text(encoding="utf-8"))
            if isinstance(payload, list):
                exceptions.extend(payload)
            else:
                errors.append("exceptions.json 应为数组")
        except (OSError, ValueError) as exc:
            errors.append(f"exceptions.json: {exc}")

    return {"queries": queries, "exceptions": exceptions, "errors": errors}


# ---------------------------------------------------------------------------
# 查单入库
# ---------------------------------------------------------------------------


def _upsert_shipment(conn: sqlite3.Connection, data: dict) -> tuple[bool, str]:
    number, error = grant_service.validate_format(data.get("shipment_no"))
    if error:
        return False, error
    lane = (data.get("lane_scope") or "").strip()
    if not lane or not lane_service.name_exists(conn, lane, active_only=True):
        return False, f"线路「{lane}」不存在或已停用"

    conn.execute(
        "INSERT INTO shipments"
        " (shipment_no, lane_scope, customer, status, plan_eta, delivered_at, receipt_at,"
        "  is_demo, created_at)"
        " VALUES (?,?,?,?,?,?,?,0,?)"
        " ON CONFLICT(shipment_no) DO UPDATE SET"
        "   lane_scope=excluded.lane_scope, customer=excluded.customer,"
        "   status=excluded.status, plan_eta=excluded.plan_eta,"
        "   delivered_at=excluded.delivered_at, receipt_at=excluded.receipt_at",
        (
            number, lane, data.get("customer") or "", data.get("status") or "in_transit",
            data.get("plan_eta"), data.get("delivered_at"), data.get("receipt_at"),
            now_iso(),
        ),
    )
    return True, ""


def _upsert_children(conn: sqlite3.Connection, number: str, data: dict) -> tuple[int, int]:
    subs = 0
    for item in data.get("sub_shipments") or []:
        sub_no = (item.get("sub_no") or "").strip()
        if not sub_no:
            continue
        conn.execute(
            "INSERT INTO sub_shipments (sub_no, shipment_no, carrier, status, updated_at)"
            " VALUES (?,?,?,?,?)"
            " ON CONFLICT(sub_no) DO UPDATE SET"
            "   shipment_no=excluded.shipment_no, carrier=excluded.carrier,"
            "   status=excluded.status, updated_at=excluded.updated_at",
            (sub_no, number, item.get("carrier") or "", item.get("status") or "", now_iso()),
        )
        subs += 1

    tracks = 0
    for item in data.get("tracks") or []:
        if not item.get("at") or not item.get("status"):
            continue
        conn.execute(
            "INSERT OR IGNORE INTO shipment_tracks"
            " (id, shipment_no, at, status, location, note, data_time)"
            " VALUES (?,?,?,?,?,?,?)",
            (
                f"t_{uuid.uuid4().hex[:12]}", number, item["at"], item["status"],
                item.get("location") or "", item.get("note") or "",
                data.get("data_time") or now_iso(),
            ),
        )
        tracks += 1
    return subs, tracks


# ---------------------------------------------------------------------------
# 异常归一
# ---------------------------------------------------------------------------


def normalize(raw: dict) -> tuple[dict | None, list[str]]:
    """返回 (可入库的事件, 缺失字段)。缺字段一律进修复队列，不用默认值糊。"""
    missing = [field for field in REQUIRED_FIELDS if not str(raw.get(field) or "").strip()]
    number, format_error = grant_service.validate_format(raw.get("shipment_no"))
    if format_error:
        missing.append("shipment_no_format")
    if missing:
        return None, missing

    event = {
        "id": f"ev_{uuid.uuid4().hex[:12]}",
        "shipment_no": number,
        "sub_no": (raw.get("sub_no") or "").strip() or None,
        "event_type": str(raw["event_type"]).strip(),
        "reason_code": (raw.get("reason_code") or "").strip(),
        "occurred_at": str(raw["occurred_at"]).strip(),
        "source": str(raw["source"]).strip(),
        "source_version": (raw.get("source_version") or "").strip(),
        "handler": (raw.get("handler") or "").strip(),
        "due_at": (raw.get("due_at") or "").strip() or None,
        "status": "normalized",
        "raw_ref": (raw.get("raw_ref") or "").strip(),
        "data_time": (raw.get("data_time") or raw["occurred_at"]).strip(),
        "created_at": now_iso(),
    }
    return event, []


def _enqueue(conn: sqlite3.Connection, raw: dict, missing: list[str]) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO repair_queue (id, raw_ref, raw_json, missing, status, created_at)"
        " VALUES (?,?,?,?, 'pending', ?)",
        (
            f"rq_{uuid.uuid4().hex[:12]}",
            str(raw.get("raw_ref") or ""),
            json.dumps(raw, ensure_ascii=False),
            ",".join(missing),
            now_iso(),
        ),
    )


def _insert_event(conn: sqlite3.Connection, event: dict) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO exception_events"
        " (id, shipment_no, sub_no, event_type, reason_code, occurred_at, source,"
        "  source_version, handler, due_at, status, raw_ref, data_time, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            event["id"], event["shipment_no"], event["sub_no"], event["event_type"],
            event["reason_code"], event["occurred_at"], event["source"],
            event["source_version"], event["handler"], event["due_at"], event["status"],
            event["raw_ref"], event["data_time"], event["created_at"],
        ),
    )


def import_samples(conn: sqlite3.Connection, actor: dict, directory: Path | None = None) -> dict:
    """把样本导进库；返回统计与告警，供页面展示。"""
    payload = load_samples(directory)
    stats = {
        "shipments": 0, "sub_shipments": 0, "tracks": 0,
        "events": 0, "queued": 0, "errors": list(payload["errors"]),
    }

    for query in payload["queries"]:
        ok, error = _upsert_shipment(conn, query)
        if not ok:
            stats["errors"].append(f"{query.get('shipment_no') or '?'}: {error}")
            continue
        stats["shipments"] += 1
        subs, tracks = _upsert_children(conn, grant_service.normalize(query["shipment_no"]), query)
        stats["sub_shipments"] += subs
        stats["tracks"] += tracks

    known_shipments = {
        row[0] for row in conn.execute("SELECT shipment_no FROM shipments").fetchall()
    }
    for raw in payload["exceptions"]:
        event, missing = normalize(raw)
        if event is not None and event["shipment_no"] not in known_shipments:
            missing = ["shipment_master"]
        if missing:
            _enqueue(conn, raw, missing)
            stats["queued"] += 1
            continue
        _insert_event(conn, event)
        stats["events"] += 1

    conn.commit()
    audit(
        conn, actor, "tms.import", "tms", "samples",
        f"运单 {stats['shipments']} / 事件 {stats['events']} / 待修复 {stats['queued']}",
    )
    conn.commit()
    return stats


# ---------------------------------------------------------------------------
# 修复队列
# ---------------------------------------------------------------------------


def list_repairs(conn: sqlite3.Connection, status: str = "pending") -> list[dict]:
    sql = "SELECT * FROM repair_queue"
    params: list = []
    if status:
        sql += " WHERE status=?"
        params.append(status)
    sql += " ORDER BY created_at DESC"
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def resolve_repair(
    conn: sqlite3.Connection, actor: dict, queue_id: str, patch: dict,
) -> tuple[bool, str]:
    row = conn.execute(
        "SELECT * FROM repair_queue WHERE id=? AND status='pending'", (queue_id,)
    ).fetchone()
    if row is None:
        return False, "修复项不存在或已处理"

    try:
        raw = json.loads(row["raw_json"])
    except ValueError:
        return False, "原始记录损坏，无法修复"

    raw.update({key: value for key, value in patch.items() if str(value or "").strip()})
    event, missing = normalize(raw)
    if event is None:
        conn.execute(
            "UPDATE repair_queue SET raw_json=?, missing=? WHERE id=?",
            (json.dumps(raw, ensure_ascii=False), ",".join(missing), queue_id),
        )
        conn.commit()
        return False, f"仍缺少字段：{', '.join(missing)}"

    if conn.execute(
        "SELECT COUNT(*) FROM shipments WHERE shipment_no=?", (event["shipment_no"],)
    ).fetchone()[0] == 0:
        conn.execute(
            "UPDATE repair_queue SET raw_json=?, missing='shipment_master' WHERE id=?",
            (json.dumps(raw, ensure_ascii=False), queue_id),
        )
        conn.commit()
        return False, f"运单 {event['shipment_no']} 不在主数据中，请先登记运单"

    _insert_event(conn, event)
    conn.execute(
        "UPDATE repair_queue SET status='resolved', resolved_at=? WHERE id=?",
        (now_iso(), queue_id),
    )
    conn.commit()
    audit(conn, actor, "tms.repair", "exception_event", event["id"],
          f"{row['raw_ref']} 补齐后归一")
    conn.commit()
    return True, ""


# ---------------------------------------------------------------------------
# 查询
# ---------------------------------------------------------------------------


def list_events(conn: sqlite3.Connection, status: str = "") -> list[dict]:
    sql = "SELECT * FROM exception_events"
    params: list = []
    if status:
        sql += " WHERE status=?"
        params.append(status)
    sql += " ORDER BY occurred_at DESC"
    return [dict(r) for r in conn.execute(sql, params).fetchall()]
