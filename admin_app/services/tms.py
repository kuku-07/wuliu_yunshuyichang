"""TMS 适配器（只读）+ 异常事件归一。

真实系统里这里会调 TMS 的只读接口；当前仓库没有生产接口，所以改成读
`samples/tms/` 下的**脱敏导出样本**，把「查单」和「异常记录」解析进库。
接口形状、校验规则、修复队列逻辑与真实接入一致，换成 HTTP 调用时只改
`load_samples()` 一处。

归一规则（流程口径 / 金路径）：
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
from datetime import datetime, timedelta

from ..db import now_iso
from . import grants as grant_service
from . import lanes as lane_service
from . import notify, routing, snapshots
from .audit_log import log as audit

SAMPLE_DIR = Path(config.BASE_DIR).parent / "samples" / "tms"
REQUIRED_FIELDS = ("shipment_no", "event_type", "occurred_at", "source")


# ---------------------------------------------------------------------------
# 读取样本（真实接入时替换成 TMS 只读 API）
# ---------------------------------------------------------------------------


def load_samples(directory: Path | None = None) -> dict[str, Any]:
    # 配了 TMS_BASE_URL 就走真实只读接口，否则读本地脱敏样本
    if directory is None and config.TMS_BASE_URL:
        from .tms_client import fetch_all

        try:
            payload = fetch_all()
            payload["transport"] = "http"
            return payload
        except Exception as exc:  # 不伪造数据，交给上层提示
            return {"queries": [], "exceptions": [], "errors": [str(exc)],
                    "transport": "http"}

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

    return {"queries": queries, "exceptions": exceptions, "errors": errors,
            "transport": "sample"}


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
        updated = now_iso()
        conn.execute(
            "INSERT INTO sub_shipments (sub_no, shipment_no, carrier, status, updated_at)"
            " VALUES (?,?,?,?,?)"
            " ON CONFLICT(sub_no) DO UPDATE SET"
            "   shipment_no=excluded.shipment_no, carrier=excluded.carrier,"
            "   status=excluded.status, updated_at=excluded.updated_at",
            (sub_no, number, item.get("carrier") or "", item.get("status") or "", updated),
        )
        source = (data.get("source") or "TMS").strip()
        conn.execute(
            "INSERT INTO shipment_links"
            " (id, shipment_no, sub_no, carrier, source, source_version, priority,"
            "  is_active, status, updated_at)"
            " VALUES (?,?,?,?,?,?,?, 1, ?, ?)"
            " ON CONFLICT(sub_no, source) DO UPDATE SET"
            "   shipment_no=excluded.shipment_no, carrier=excluded.carrier,"
            "   source_version=excluded.source_version, priority=excluded.priority,"
            "   status=excluded.status, updated_at=excluded.updated_at",
            (
                f"lnk_{sub_no}_{source}", number, sub_no, item.get("carrier") or "",
                source, (data.get("source_version") or "").strip(),
                100 if source.upper() == "TMS" else 50,
                item.get("status") or "", updated,
            ),
        )
        subs += 1

    tracks = 0
    for item in data.get("tracks") or []:
        if not item.get("at") or not item.get("status"):
            continue
        exists = conn.execute(
            "SELECT 1 FROM shipment_tracks WHERE shipment_no=? AND at=? AND status=?"
            " AND location=? AND note=?",
            (number, item["at"], item["status"],
             item.get("location") or "", item.get("note") or ""),
        ).fetchone()
        if exists:
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
    # 同一运单 + 类型 + 发生时间 + 来源只留一条，重复导入幂等
    exists = conn.execute(
        "SELECT 1 FROM exception_events WHERE shipment_no=? AND event_type=?"
        " AND occurred_at=? AND source=?",
        (event["shipment_no"], event["event_type"], event["occurred_at"], event["source"]),
    ).fetchone()
    if exists:
        return
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
        snapshots.capture(conn, grant_service.normalize(query["shipment_no"]), "TMS")

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
    routed = routing.route_unassigned(conn)
    stats["routed"] = routed["routed"]
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
    routing.route_event(conn, event["id"], actor)
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

# ---------------------------------------------------------------------------
# 受理 / 关闭 / 超时升级
# ---------------------------------------------------------------------------
# 口径来自 流程口径：30 分钟内首次响应，2 小时内给出处置结论，
# 超时未响应自动升级至客服主管。

FIRST_RESPONSE_MINUTES = 30
RESOLUTION_MINUTES = 120


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def event_state(row: dict) -> dict:
    """给列表用的派生状态：是否超时、是否已升级。"""
    state = {
        "label": "待受理" if row.get("status") == "normalized" else
                 ("已关闭" if row.get("status") == "closed" else "处理中"),
        "first_overdue": False,
        "resolve_overdue": False,
    }
    now = datetime.now()
    occurred = _parse(row.get("occurred_at"))
    accepted = _parse(row.get("accepted_at"))
    closed = _parse(row.get("closed_at"))

    if occurred and not accepted:
        state["first_overdue"] = now - occurred > timedelta(minutes=FIRST_RESPONSE_MINUTES)
    if accepted and not closed:
        state["resolve_overdue"] = now - accepted > timedelta(minutes=RESOLUTION_MINUTES)
    if row.get("escalated_at"):
        state["label"] = "已升级"
    return state


def accept_event(conn: sqlite3.Connection, actor: dict, event_id: str) -> tuple[bool, str]:
    row = conn.execute("SELECT * FROM exception_events WHERE id=?", (event_id,)).fetchone()
    if row is None:
        return False, "异常事件不存在"
    if row["closed_at"]:
        return False, "该事件已关闭"
    if row["accepted_at"]:
        return False, "该事件已被受理"

    now = now_iso()
    conn.execute(
        "UPDATE exception_events SET status='accepted', accepted_at=?, accepted_by=?,"
        " handler=CASE WHEN handler='' THEN ? ELSE handler END WHERE id=?",
        (now, actor["id"], actor["id"], event_id),
    )
    conn.commit()
    audit(conn, actor, "event.accept", "exception_event", event_id,
          f"{row['shipment_no']} {row['event_type']}")
    conn.commit()
    return True, "已受理，开始计时"


def close_event(
    conn: sqlite3.Connection, actor: dict, event_id: str, note: str = "",
    return_reason: str = "",
) -> tuple[bool, str]:
    row = conn.execute("SELECT * FROM exception_events WHERE id=?", (event_id,)).fetchone()
    if row is None:
        return False, "异常事件不存在"
    if row["closed_at"]:
        return False, "该事件已关闭"
    if not row["accepted_at"]:
        return False, "请先受理再关闭"

    conn.execute(
        "UPDATE exception_events SET status='closed', closed_at=?, closed_by=?,"
        " escalation_note=?, return_reason=? WHERE id=?",
        (now_iso(), actor["id"], (note or "").strip()[:200],
         (return_reason or "").strip()[:200], event_id),
    )
    conn.commit()
    audit(conn, actor, "event.close", "exception_event", event_id,
          f"{row['shipment_no']} {row['event_type']}；结论 {note or '-'}")
    conn.commit()
    return True, "已关闭"


def assign_event(
    conn: sqlite3.Connection, actor: dict, event_id: str, handler: str,
) -> tuple[bool, str]:
    row = conn.execute("SELECT * FROM exception_events WHERE id=?", (event_id,)).fetchone()
    if row is None:
        return False, "异常事件不存在"
    handler = (handler or "").strip()
    if not handler:
        return False, "请选择处理人"
    conn.execute("UPDATE exception_events SET handler=? WHERE id=?", (handler, event_id))
    conn.commit()
    audit(conn, actor, "event.assign", "exception_event", event_id,
          f"{row['shipment_no']} → {handler}")
    conn.commit()
    notify.push(
        conn, [handler], "ASSIGN",
        f"你有一个新的异常待处理：{row['shipment_no']}",
        f"{row['event_type']}（{row['reason_code'] or '无原因码'}）",
        "/admin/todos",
    )
    return True, f"已指派给 {handler}"


def escalate_overdue(conn: sqlite3.Connection) -> dict:
    """扫描超时：首次响应 >30 分钟、处置 >2 小时，写升级标记（幂等）。"""
    now = datetime.now()
    first, resolve = 0, 0
    rows = [
        dict(r) for r in conn.execute(
            "SELECT * FROM exception_events WHERE closed_at IS NULL AND escalated_at IS NULL"
        )
    ]
    for row in rows:
        occurred = _parse(row["occurred_at"])
        accepted = _parse(row["accepted_at"])
        note = ""
        if not accepted and occurred and now - occurred > timedelta(
            minutes=FIRST_RESPONSE_MINUTES
        ):
            note = f"首次响应超时（> {FIRST_RESPONSE_MINUTES} 分钟）"
            first += 1
        elif accepted and now - accepted > timedelta(minutes=RESOLUTION_MINUTES):
            note = f"处置超时（> {RESOLUTION_MINUTES} 分钟）"
            resolve += 1
        if note:
            conn.execute(
                "UPDATE exception_events SET escalated_at=?, escalation_note=?,"
                " status=CASE WHEN accepted_at IS NULL THEN 'escalated' ELSE status END"
                " WHERE id=?",
                (now_iso(), note, row["id"]),
            )
    if first or resolve:
        conn.commit()
        for row in rows:
            note = conn.execute(
                "SELECT escalation_note FROM exception_events WHERE id=?", (row["id"],)
            ).fetchone()
            if note and note["escalation_note"]:
                notify.push_to_roles(
                    conn, ("supervisor", "sys_admin"), "ESCALATION",
                    f"{row['shipment_no']} · {row['event_type']} 已升级",
                    note["escalation_note"],
                    "/admin/exceptions",
                )
    return {"first_response": first, "resolution": resolve}


def list_events_with_state(conn: sqlite3.Connection, status: str = "") -> list[dict]:
    events = list_events(conn, status)
    for event in events:
        event["state"] = event_state(event)
    return events

def transfer_event(
    conn: sqlite3.Connection, actor: dict, event_id: str, to_user: str, note: str = "",
) -> tuple[bool, str]:
    """显式转交：责任只随受理/转交转移，聊天里发消息不算。"""
    row = conn.execute("SELECT * FROM exception_events WHERE id=?", (event_id,)).fetchone()
    if row is None:
        return False, "异常事件不存在"
    if row["closed_at"]:
        return False, "该事件已关闭"
    if not row["accepted_at"]:
        return False, "请先受理再转交"
    if not to_user:
        return False, "请选择接手人"
    if to_user == row["handler"]:
        return False, "对方已是当前处理人"

    conn.execute(
        "INSERT INTO event_handovers (id, event_id, from_user, to_user, note, created_at)"
        " VALUES (?,?,?,?,?,?)",
        (
            f"ho_{uuid.uuid4().hex[:12]}", event_id, row["handler"] or "",
            to_user, (note or "").strip()[:200], now_iso(),
        ),
    )
    conn.execute("UPDATE exception_events SET handler=? WHERE id=?", (to_user, event_id))
    conn.commit()
    notify.push(
        conn, [to_user], "ASSIGN",
        f"转交给你处理：{row['shipment_no']} · {row['event_type']}",
        (note or "由同事转交")[:200], "/admin/todos",
    )
    audit(conn, actor, "event.handover", "exception_event", event_id,
          f"{row['shipment_no']} {row['handler'] or '-'} → {to_user}；{note or '-'}")
    conn.commit()
    return True, "已转交"


def list_handovers(conn: sqlite3.Connection, event_id: str) -> list[dict]:
    return [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM event_handovers WHERE event_id=? ORDER BY created_at DESC",
            (event_id,),
        ).fetchall()
    ]
