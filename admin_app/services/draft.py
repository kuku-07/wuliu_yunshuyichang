"""查单草稿：证据包 → 闸门 → 模型 → 护栏 → 待审核。

与 `/admin/chat` 的区别：那边回答「规则怎么写」，这里回答「这一票现在什么情况、
下一步怎么处理」。两者共用同一套闸门与护栏，避免两套口径。
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta
from typing import Any

from ..db import now_iso
from . import agent_core, chat_service, circuit
from . import ingest as ingest_service
from . import links as link_service, snapshots
from .audit_log import log as audit

DRAFT_QUESTION = "这票货现在是什么情况？异常应如何处置？"

SCENARIOS = {
    "query": "查单",
    "expedite": "催单",
}

SCENARIO_QUESTIONS = {
    "query": DRAFT_QUESTION,
    "expedite": "这票货是否需要催办？应如何向承运商催办并跟进回执？",
}

SCENARIO_RULES = {
    "query": "说明现状与下一步，不要推断未记录的信息。",
    "expedite": "判断是否需要催办；需要时给出催办对象、话术要点与跟进节点，不要承诺时效。",
}


# ---------------------------------------------------------------------------
# 证据包
# ---------------------------------------------------------------------------


def evidence(conn: sqlite3.Connection, shipment_no: str) -> dict | None:
    shipment = conn.execute(
        "SELECT * FROM shipments WHERE shipment_no=?", (shipment_no,)
    ).fetchone()
    if shipment is None:
        return None

    subs = [
        dict(r) for r in conn.execute(
            "SELECT * FROM sub_shipments WHERE shipment_no=? ORDER BY sub_no",
            (shipment_no,),
        )
    ]
    tracks = [
        dict(r) for r in conn.execute(
            "SELECT * FROM shipment_tracks WHERE shipment_no=? ORDER BY at DESC LIMIT 5",
            (shipment_no,),
        )
    ]
    events = [
        dict(r) for r in conn.execute(
            "SELECT * FROM exception_events WHERE shipment_no=? ORDER BY occurred_at DESC",
            (shipment_no,),
        )
    ]
    data_times = [r["data_time"] for r in tracks if r["data_time"]]
    return {
        "shipment": dict(shipment),
        "sub_shipments": subs,
        "links": link_service.resolve(conn, shipment_no),
        "im_notes": ingest_service.list_im_notes(conn, shipment_no),
        "tracks": tracks,
        "events": events,
        "snapshot": snapshots.latest(conn, shipment_no),
        "data_time": max(data_times + [now_iso()]) if data_times else now_iso(),
    }


def _quote(text: str, limit: int = 120) -> str:
    flat = " ".join(str(text).split())
    return flat[:limit] + ("…" if len(flat) > limit else "")


def evidence_blocks(ev: dict) -> list[dict]:
    """把证据包拆成带来源与时间的数据段，既是提示词素材也是引用来源。"""
    shipment = ev["shipment"]
    blocks: list[dict] = [{
        "title": "TMS 运单",
        "section": "运单主数据",
        "version": "当前",
        "lane_scope": shipment.get("lane_scope") or "",
        "effective_from": "",
        "quote": _quote(
            f"运单 {shipment['shipment_no']}，客户 {shipment.get('customer') or '未登记'}，"
            f"状态 {shipment.get('status')}，计划到达 {shipment.get('plan_eta') or '未登记'}，"
            f"实际到达 {shipment.get('delivered_at') or '未到达'}，"
            f"回执时间 {shipment.get('receipt_at') or '未回传'}"
        ),
        "data_time": ev["data_time"],
    }]

    for sub in ev.get("links") or ev["sub_shipments"]:
        blocks.append({
            "title": "子单映射",
            "section": f"子单 {sub['sub_no']}",
            "version": sub.get("source_version") or "当前",
            "lane_scope": shipment.get("lane_scope") or "",
            "effective_from": "",
            "quote": _quote(
                f"承运商 {sub.get('carrier') or '-'}，状态 {sub.get('status') or '-'}，"
                f"来源 {sub.get('source') or 'TMS'}"
                + (f"（另有 {len(sub.get('candidates') or []) - 1} 个来源）"
                   if len(sub.get("candidates") or []) > 1 else "")
            ),
            "data_time": ev["data_time"],
        })

    for note in ev.get("im_notes") or []:
        blocks.append({
            "title": "IM 留痕",
            "section": note.get("source") or "IM",
            "version": "人工",
            "lane_scope": shipment.get("lane_scope") or "",
            "effective_from": "",
            "quote": _quote(f"{note['occurred_at']} {note.get('operator') or '-'}：{note['content']}"),
            "data_time": note["occurred_at"],
        })

    for track in ev["tracks"]:
        blocks.append({
            "title": "轨迹快照",
            "section": track.get("location") or "轨迹",
            "version": "5min",
            "lane_scope": shipment.get("lane_scope") or "",
            "effective_from": "",
            "quote": _quote(f"{track['at']} {track['status']} {track.get('note') or ''}"),
            "data_time": track.get("data_time") or ev["data_time"],
        })

    for event in ev["events"]:
        blocks.append({
            "title": "异常记录",
            "section": event["event_type"],
            "version": event.get("source_version") or "-",
            "lane_scope": shipment.get("lane_scope") or "",
            "effective_from": "",
            "quote": _quote(
                f"{event['occurred_at']} {event['event_type']}"
                f"（{event.get('reason_code') or '无原因码'}），来源 {event['source']}，"
                f"处理人 {event.get('handler') or '未指定'}，截止 {event.get('due_at') or '未设定'}"
            ),
            "data_time": event.get("data_time") or ev["data_time"],
        })
    return blocks


def render_context(blocks: list[dict]) -> str:
    lines = []
    for index, block in enumerate(blocks, start=1):
        lines.append(
            f"[{index}] {block['title']} · {block['section']} · {block['version']}"
            f"（数据时间 {block['data_time']}）\n{block['quote']}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 生成草稿
# ---------------------------------------------------------------------------


def stop_advice(ev: dict) -> tuple[str, str] | None:
    """按 docs/02 §7 停止自动建议：GPS 弱网、客户改地址、回执延迟。"""
    shipment = ev["shipment"]
    events = ev.get("events") or []

    for event in events:
        text = f"{event['event_type']} {event.get('reason_code') or ''}"
        if any(key in text for key in ("改地址", "改址", "地址变更", "ADDRESS")):
            return "STOP_ADDRESS_CHANGE", "客户改地址"

    delivered = shipment.get("delivered_at")
    if delivered and not shipment.get("receipt_at"):
        try:
            if datetime.now() - datetime.fromisoformat(delivered) > timedelta(hours=24):
                return "STOP_RECEIPT_DELAY", "已签收但回执超过 24 小时未回传"
        except ValueError:
            pass

    tracks = ev.get("tracks") or []
    if not delivered and tracks:
        last = tracks[0]
        raw = last.get("data_time") or last.get("at")
        try:
            if raw and datetime.now() - datetime.fromisoformat(raw) > timedelta(hours=2):
                return "STOP_GPS_WEAK", "轨迹超过 2 小时未刷新（GPS 弱网或停滞后）"
        except ValueError:
            pass
    return None


def generate(
    conn: sqlite3.Connection, user: dict, shipment_no: str, scenario: str = "query",
) -> tuple[bool, str, dict | None]:
    number = (shipment_no or "").strip().upper()
    if scenario not in SCENARIOS:
        return False, "不支持的处理场景", None

    tripped, rate = circuit.status(conn)
    if tripped:
        return False, (
            f"预警误报率 {rate}% 已连续超过 10%，自动建议暂停（熔断），请人工处理"
        ), None

    ev = evidence(conn, number)
    if ev is None:
        return False, f"运单 {number} 不存在，请先在「运单登记」里登记", None

    stop = stop_advice(ev)
    if stop:
        reason, label = stop
        draft_id = f"d_{uuid.uuid4().hex[:12]}"
        conn.execute(
            "INSERT INTO drafts"
            " (id, shipment_no, content, status, scenario, gate_reason, citations_json,"
            "  evidence_json, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (draft_id, number,
             f"已停止自动建议：{label}。请人工接手处置，并记录接手人与确认时间。",
             "stopped", scenario, reason, "[]",
             json.dumps(evidence_blocks(ev), ensure_ascii=False), now_iso()),
        )
        conn.commit()
        audit(conn, user, "draft.stop_advice", "draft", draft_id, f"{number} {reason}")
        conn.commit()
        return True, f"已停止自动建议（{label}），请人工接手", {
            "id": draft_id, "status": "stopped",
        }

    blocks = evidence_blocks(ev)
    context = render_context(blocks)
    gate_question = " ".join(
        [number] + [f"{e['event_type']} {e.get('reason_code') or ''}" for e in ev["events"]]
    )
    gate = agent_core.gate(gate_question)

    system_prompt, prompt_version = chat_service.active_prompt(conn)
    draft_id = f"d_{uuid.uuid4().hex[:12]}"
    now = now_iso()

    if gate:
        conn.execute(
            "INSERT INTO drafts"
            " (id, shipment_no, content, status, scenario, gate_reason, citations_json,"
            "  evidence_json, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (draft_id, number, gate["message"], "taken_over", scenario, gate["reason_code"],
             json.dumps([], ensure_ascii=False), json.dumps(blocks, ensure_ascii=False), now),
        )
        conn.commit()
        audit(conn, user, "draft.takeover", "draft", draft_id,
              f"{number} {gate['reason_code']}")
        conn.commit()
        return True, "命中红线，已转人工接管，未生成草稿", {
            "id": draft_id, "status": "taken_over", "content": gate["message"],
        }

    user_prompt = (
        "【参考片段】\n"
        f"{context}\n\n"
        "【使用者问题】\n"
        f"运单 {number}：{SCENARIO_QUESTIONS[scenario]}\n\n"
        "【要求】\n"
        "只依据上面的记录回答，不要推断未记录的信息；"
        f"{SCENARIO_RULES[scenario]}"
        "涉及赔付、危险品、事故、判责时直接说明需人工接管。"
    )

    try:
        answer = agent_core.build_llm_client().complete(system_prompt, user_prompt)
    except Exception as exc:  # 上游失败不伪造
        return False, f"模型调用失败：{exc}", None

    report = agent_core.check_output(answer)
    citations = [
        {
            "doc_id": "tms",
            "doc_title": block["title"],
            "version": block["version"],
            "effective_from": block["effective_from"],
            "lane_scope": block["lane_scope"],
            "section": block["section"],
            "chunk_id": "",
            "quote": block["quote"],
            "score": None,
            "data_time": block["data_time"],
        }
        for block in blocks
    ]
    status = "pending_review" if report.passed else "needs_recheck"
    conn.execute(
        "INSERT INTO drafts"
        " (id, shipment_no, content, status, scenario, guardrail, citations_json,"
        "  evidence_json, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (draft_id, number, answer, status, scenario,
         "；".join(report.violations) if report.violations else "",
         json.dumps(citations, ensure_ascii=False),
         json.dumps(blocks, ensure_ascii=False), now),
    )
    conn.commit()
    audit(conn, user, "draft.generate", "draft", draft_id,
          f"{number} 引用 {len(citations)} 条，护栏={'通过' if report.passed else '需复核'}"
          f"，提示词={prompt_version}")
    conn.commit()
    return True, "草稿已生成，等待审核", {"id": draft_id, "status": status, "content": answer}


# ---------------------------------------------------------------------------
# 审核
# ---------------------------------------------------------------------------

REVIEW_ACTIONS = {
    "approve": "approved",
    "reject": "rejected",
    "takeover": "taken_over",
}

# 修正原因：可归类才谈得上「人工修正率」（docs/03 §4.2 第 4 条）
REVIEW_REASONS = {
    "EVIDENCE_GAP": "证据不足",
    "WRONG_RULE": "口径/规则错误",
    "CITATION": "引用不符",
    "OVERREACH": "越界表述",
    "OTHER": "其他",
}

SENT_CHANNELS = {"IM": "IM 消息", "PHONE": "电话", "EMAIL": "邮件", "OTHER": "其他"}


def list_drafts(conn: sqlite3.Connection, status: str = "") -> list[dict]:
    sql = "SELECT * FROM drafts"
    params: list = []
    if status:
        sql += " WHERE status=?"
        params.append(status)
    sql += " ORDER BY created_at DESC LIMIT 100"
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def get_draft(conn: sqlite3.Connection, draft_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM drafts WHERE id=?", (draft_id,)).fetchone()
    return dict(row) if row else None


def review(
    conn: sqlite3.Connection, user: dict, draft_id: str, action: str,
    reason: str = "", note: str = "",
) -> tuple[bool, str]:
    status = REVIEW_ACTIONS.get(action)
    if status is None:
        return False, "不支持的审核动作"
    if action == "reject" and reason not in REVIEW_REASONS:
        return False, "退回时必须选择修正原因"
    if reason and reason not in REVIEW_REASONS:
        return False, "修正原因不合法"

    draft = get_draft(conn, draft_id)
    if draft is None:
        return False, "草稿不存在"
    if draft["status"] not in {"pending_review", "needs_recheck"}:
        return False, f"当前状态（{draft['status']}）不能审核"

    conn.execute(
        "UPDATE drafts SET status=?, reviewer_id=?, review_reason=?, review_note=?,"
        " reviewed_at=? WHERE id=?",
        (status, user["id"], reason or "", (note or "").strip()[:200],
         now_iso(), draft_id),
    )
    conn.commit()
    audit(conn, user, f"draft.{action}", "draft", draft_id,
          f"{draft['shipment_no']} → {status}；原因 "
          f"{REVIEW_REASONS.get(reason, '-')}；备注 {note or '-'}")
    conn.commit()
    return True, {
        "approve": "已通过",
        "reject": "已退回",
        "takeover": "已转人工接管",
    }[action]


def mark_sent(
    conn: sqlite3.Connection, user: dict, draft_id: str, channel: str, note: str = "",
) -> tuple[bool, str]:
    """记录「已由人工发出」。系统不发送消息，只登记外发事实。"""
    if channel not in SENT_CHANNELS:
        return False, "请选择外发渠道"
    draft = get_draft(conn, draft_id)
    if draft is None:
        return False, "草稿不存在"
    if draft["status"] != "approved":
        return False, "只有审核通过的草稿才能登记外发"
    if draft["sent_at"]:
        return False, "该草稿已登记过外发"

    conn.execute(
        "UPDATE drafts SET sent_at=?, sent_by=?, sent_channel=? WHERE id=?",
        (now_iso(), user["id"], channel, draft_id),
    )
    conn.commit()
    audit(conn, user, "draft.sent", "draft", draft_id,
          f"{draft['shipment_no']} 人工外发（{SENT_CHANNELS[channel]}）；备注 {note or '-'}")
    conn.commit()
    return True, "已登记外发"
