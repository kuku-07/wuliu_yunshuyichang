"""阶段 2 对话服务：会话、落库、SSE 编排。

对应文档 docs/04-聊天接口设计.md。这里只做编排，检索/闸门/护栏算法全部
来自阶段 1 原型（见 services/agent_core.py）。

落库顺序严格按文档 3.2 节：
    用户消息 → （闸门命中则直接写 takeover 消息并结束）
              → 助手消息 status=streaming → 结束再更新为 complete 并写 citations
每次状态变更都追加一条 audit_logs，不覆盖历史。
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
import uuid
from typing import Any, Callable, Iterator, Optional

from .. import config
from ..db import now_iso
from ..security import mask_pii
from . import agent_core
from .audit_log import log as audit

QUESTION_MAX = 2000
HISTORY_PAIRS = 6
RATE_LIMIT_PER_MIN = 10

# docs/02 §7：这些场景停止自动建议（只在带运单上下文时生效，纯规则问答不受影响）
STOP_RULES = [
    ("STOP_ADDRESS_CHANGE", ("改地址", "改址", "地址变更"), "客户改地址"),
    ("STOP_GPS_WEAK", ("弱网", "GPS", "定位漂移", "无信号"), "GPS 弱网/定位异常"),
    ("STOP_RECEIPT_DELAY", ("回执延迟", "回执超时", "没回执", "回执未回"), "回执延迟"),
]


def stop_advice(question: str) -> dict | None:
    for code, keywords, label in STOP_RULES:
        hits = [keyword for keyword in keywords if keyword in question]
        if hits:
            return {
                "reason_code": code,
                "message": f"已停止自动建议：{label}。请人工接手处置，并记录接手人与确认时间。",
                "matched_terms": hits,
            }
    return None
_TYPEWRITER_SLICE = 24

# 首页引导问题：都来自演示规则文档里的真实条款，点了就能看到引用
SUGGESTIONS = [
    "客户临时改地址，异常应归为哪一类？",
    "到货准时率和回执及时率有什么区别？",
    "签收单缺少收货人签字怎么办？",
    "卸货排队超过 4 小时算异常吗？",
    "异常处理人需要多久内响应？",
    "代收需要什么授权？",
]

_state_lock = threading.Lock()
_recent_hits: dict[str, list[float]] = {}
_busy_sessions: set[str] = set()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# 会话
# ---------------------------------------------------------------------------


def default_lane(user: dict) -> str:
    lanes = user.get("lanes") or []
    return lanes[0] if lanes else "试点干线-华东"


def page_context(conn: sqlite3.Connection, user: dict, session_id: str = "") -> dict:
    """问答页上下文：两个入口（/agent 与 /admin/chat）共用。"""
    from .lanes import options

    current = None
    if session_id:
        candidate = get_session(conn, session_id)
        if candidate and candidate["user_id"] == user["id"]:
            current = candidate
    if current is None:
        current = get_or_create_session(conn, user)

    lane_options = options(
        conn, user.get("lanes") or [], unrestricted=user.get("role") == "sys_admin"
    )
    if current["lane_scope"] and all(
        option["name"] != current["lane_scope"] for option in lane_options
    ):
        lane_options.append(
            {"name": current["lane_scope"], "region": "", "status": "disabled"}
        )
    return {
        "session": current,
        "sessions": list_sessions(conn, user["id"]),
        "messages": load_messages(conn, current["id"]),
        "lanes": lane_options,
        "suggestions": SUGGESTIONS,
        "question_max": QUESTION_MAX,
    }


def available_lanes(conn: sqlite3.Connection, user: dict) -> list[str]:
    """可选线路名：按账号线路范围过滤（系统管理员不受限）。"""
    from .lanes import options

    names = [
        row["name"]
        for row in options(
            conn, user.get("lanes") or [],
            unrestricted=user.get("role") == "sys_admin",
        )
    ]
    if not names:
        names.append(default_lane(user))
    return sorted(names)


def latest_lane(conn: sqlite3.Connection, user: dict) -> str:
    """新建会话时沿用最近一个会话的线路；没有历史会话就取干线表里第一条启用干线。"""
    row = conn.execute(
        "SELECT lane_scope FROM sessions WHERE user_id=?"
        " ORDER BY last_active_at DESC, rowid DESC LIMIT 1",
        (user["id"],),
    ).fetchone()
    if row and row["lane_scope"]:
        return row["lane_scope"]

    lanes = user.get("lanes") or []
    if lanes:
        return lanes[0]

    from .lanes import active_names

    names = active_names(conn)
    return names[0] if names else default_lane(user)


def set_session_lane(
    conn: sqlite3.Connection, user: dict, session_id: str, lane_scope: str,
) -> tuple[bool, str]:
    """切换会话的作业线路。之后的检索与运单预检都按新线路走。"""
    row = get_session(conn, session_id)
    if row is None:
        return False, "会话不存在"
    if row["user_id"] != user["id"]:
        return False, "无权修改该会话"

    lane = (lane_scope or "").strip()
    if lane not in available_lanes(conn, user):
        return False, "线路不存在或不可用"

    conn.execute("UPDATE sessions SET lane_scope=? WHERE id=?", (lane, session_id))
    conn.commit()
    audit(conn, user, "chat.lane.switch", "session", session_id,
          f"线路 {row['lane_scope']} → {lane}")
    conn.commit()
    return True, ""


def create_session(
    conn: sqlite3.Connection, user: dict, lane_scope: str | None = None,
    shipment_no: str | None = None,
) -> dict:
    sid = _new_id("s")
    now = now_iso()
    lane = lane_scope or latest_lane(conn, user)
    conn.execute(
        "INSERT INTO sessions (id, user_id, lane_scope, shipment_no, status, created_at, last_active_at)"
        " VALUES (?,?,?,?,'active',?,?)",
        (sid, user["id"], lane, shipment_no or None, now, now),
    )
    conn.commit()
    audit(conn, user, "chat.session.create", "session", sid, f"线路={lane}")
    conn.commit()
    return dict(conn.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone())


def get_or_create_session(conn: sqlite3.Connection, user: dict) -> dict:
    row = conn.execute(
        "SELECT * FROM sessions WHERE user_id=? AND status='active'"
        " ORDER BY last_active_at DESC, rowid DESC LIMIT 1",
        (user["id"],),
    ).fetchone()
    if row:
        return dict(row)
    return create_session(conn, user)


def get_session(conn: sqlite3.Connection, session_id: str) -> Optional[dict]:
    row = conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
    return dict(row) if row else None


def list_sessions(conn: sqlite3.Connection, user_id: str, limit: int = 50) -> list[dict]:
    """左侧会话列表：标题取第一句提问，附带消息数与最近活跃时间。"""
    rows = conn.execute(
        "SELECT s.*,"
        "  (SELECT m.content FROM messages m"
        "    WHERE m.session_id=s.id AND m.role='user'"
        "    ORDER BY m.created_at, m.rowid LIMIT 1) AS first_question,"
        "  (SELECT COUNT(*) FROM messages m WHERE m.session_id=s.id) AS msg_count"
        " FROM sessions s WHERE s.user_id=?"
        " ORDER BY s.last_active_at DESC, s.rowid DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    sessions = []
    for row in rows:
        item = dict(row)
        question = (item.pop("first_question", None) or "").strip()
        title = re.sub(r"\s+", " ", question)[:24] or "新会话"
        item["title"] = title
        sessions.append(item)
    return sessions


def delete_session(conn: sqlite3.Connection, user: dict, session_id: str) -> tuple[bool, str]:
    """删除自己的会话，连带消息、引用与标记。"""
    row = conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
    if row is None:
        return False, "会话不存在"
    if row["user_id"] != user["id"]:
        return False, "无权删除该会话"

    message_ids = [
        r["id"] for r in conn.execute(
            "SELECT id FROM messages WHERE session_id=?", (session_id,)
        )
    ]
    for message_id in message_ids:
        conn.execute("DELETE FROM citations WHERE message_id=?", (message_id,))
        conn.execute("DELETE FROM conversation_flags WHERE message_id=?", (message_id,))
    conn.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
    conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
    conn.commit()
    audit(conn, user, "chat.session.delete", "session", session_id,
          f"连带消息 {len(message_ids)} 条")
    conn.commit()
    return True, ""


def load_messages(conn: sqlite3.Connection, session_id: str, limit: int = 60) -> list[dict]:
    """页面回显用：只取已完成/已接管的问答，附带引用。"""
    rows = conn.execute(
        "SELECT * FROM messages WHERE session_id=? AND role IN ('user','assistant')"
        " AND status IN ('complete','takeover')"
        " ORDER BY created_at, rowid LIMIT ?",
        (session_id, limit),
    ).fetchall()
    messages = [dict(row) for row in rows]
    for message in messages:
        if message["role"] != "assistant":
            continue
        cits = conn.execute(
            "SELECT * FROM citations WHERE message_id=? ORDER BY rowid", (message["id"],)
        ).fetchall()
        message["citations"] = [dict(c) for c in cits]
    return messages


def recent_history(conn: sqlite3.Connection, session_id: str, pairs: int = HISTORY_PAIRS) -> list[dict]:
    """最近 N 组问答，用于给模型一点上下文。

    只取「答案 + 是否接管」，不取引用片段：历史里回放完整检索结果会让
    上下文膨胀，也违背「历史只保存脱敏后的内容」这条约束。
    """
    rows = conn.execute(
        "SELECT role, content, status, intent FROM messages"
        " WHERE session_id=? AND status IN ('complete','takeover')"
        " ORDER BY created_at DESC, rowid DESC LIMIT ?",
        (session_id, pairs * 2),
    ).fetchall()
    return [dict(r) for r in reversed(rows)]


def _shipment_payload(info: dict | None) -> dict | None:
    """给前端的运单上下文（已授权才会走到这里）。"""
    if not info:
        return None
    from .shipments import status_text

    return {
        "shipment_no": info.get("shipment_no", ""),
        "lane_scope": info.get("lane_scope", ""),
        "customer": info.get("customer", ""),
        "status": info.get("status", ""),
        "status_text": status_text(info.get("status", "")),
    }


def _shipment_context(info: dict | None) -> str:
    """拼进提示词的运单上下文。

    只放「已登记的客观字段」，并明确禁止由这些字段推断未记录的信息——
    否则模型很容易从「客户是谁」推出一堆规则里没有的结论。
    """
    if not info:
        return ""
    from .shipments import status_text

    return (
        "【运单上下文】\n"
        f"运单号 {info.get('shipment_no', '')}，线路 {info.get('lane_scope', '')}，"
        f"客户 {info.get('customer') or '未登记'}，"
        f"状态 {status_text(info.get('status', ''))}。\n"
        "以上只是系统里已登记的客观字段，不得据此推断订单金额、责任方或任何未记录的信息；"
        "涉及赔付与判责仍按红线接管。"
    )


def _history_block(history: list[dict]) -> str:
    if not history:
        return ""
    lines = ["【最近对话（仅作上下文，不进入引用）】"]
    for item in history:
        tag = "问" if item["role"] == "user" else "答"
        text = re.sub(r"\s+", " ", item["content"]).strip()
        if item["role"] == "assistant" and item["status"] == "takeover":
            text = f"[已转人工接管] {text}"
        lines.append(f"{tag}：{text[:200]}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 幂等：同一 client_msg_id 重复提交时重放已存结果
# ---------------------------------------------------------------------------


def find_reply(
    conn: sqlite3.Connection, session_id: str, client_msg_id: str,
) -> tuple[dict | None, bool]:
    """返回 (可重放的问答, 是否有未完成的流)。

    有未完成的流说明是并发重复提交，调用方应返回 SESSION_BUSY；
    已完成/已接管则直接重放，不重复生成、不重复计数。
    """
    if not client_msg_id:
        return None, False

    user_row = conn.execute(
        "SELECT rowid AS rid, * FROM messages"
        " WHERE session_id=? AND client_msg_id=? AND role='user'"
        " ORDER BY rowid DESC LIMIT 1",
        (session_id, client_msg_id),
    ).fetchone()
    if user_row is None:
        return None, False

    assistant = conn.execute(
        "SELECT * FROM messages WHERE session_id=? AND role='assistant' AND rowid>?"
        " ORDER BY rowid LIMIT 1",
        (session_id, user_row["rid"]),
    ).fetchone()
    if assistant is None:
        return None, False
    if assistant["status"] == "streaming":
        return None, True
    if assistant["status"] not in {"complete", "takeover"}:
        return None, False

    citations = [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM citations WHERE message_id=?", (assistant["id"],)
        )
    ]
    return {
        "user": dict(user_row),
        "assistant": dict(assistant),
        "citations": citations,
    }, False


def replay_events(reply: dict) -> Iterator[tuple[str, dict]]:
    """把已存结果重新按 SSE 事件吐一遍。"""
    user = reply["user"]
    assistant = reply["assistant"]
    takeover = assistant["status"] == "takeover"

    yield ("meta", {
        "request_id": assistant.get("request_id") or "",
        "session_id": assistant["session_id"],
        "user_message_id": user["id"],
        "shipment": None,
        "replayed": True,
    })
    yield ("status", {"stage": "generating", "label": "正在重放已存回答…"})

    if takeover:
        yield ("takeover", {
            "reason_code": assistant["intent"],
            "message": assistant["content"],
            "matched_terms": [],
        })
    else:
        for piece in _slice_text(assistant["content"]):
            yield ("delta", {"text": piece})
        yield ("citations", {
            "items": [
                {
                    "doc_id": c.get("doc_id", ""),
                    "doc_title": c.get("doc_title", ""),
                    "version": c.get("doc_version", ""),
                    "effective_from": c.get("effective_from") or "",
                    "lane_scope": c.get("lane_scope") or "",
                    "section": c.get("section", ""),
                    "chunk_id": c.get("chunk_id", ""),
                    "quote": c.get("quote", ""),
                    "score": c.get("score") or 0,
                }
                for c in reply["citations"]
            ],
        })

    yield ("guardrail", {"passed": True, "needs_review": False, "violations": []})
    yield ("done", {
        "assistant_message_id": assistant["id"],
        "latency_ms": assistant.get("latency_ms") or 0,
        "prompt_version": assistant.get("prompt_version") or "",
        "model": assistant.get("model") or "",
        "data_time": assistant.get("data_time") or "",
        "takeover": takeover,
        "replayed": True,
    })


# ---------------------------------------------------------------------------
# 限流与会话并发
# ---------------------------------------------------------------------------


def rate_limited(user_id: str) -> bool:
    now = time.monotonic()
    with _state_lock:
        hits = [t for t in _recent_hits.get(user_id, []) if now - t < 60]
        if len(hits) >= RATE_LIMIT_PER_MIN:
            _recent_hits[user_id] = hits
            return True
        hits.append(now)
        _recent_hits[user_id] = hits
        return False


def acquire_session(session_id: str) -> bool:
    with _state_lock:
        if session_id in _busy_sessions:
            return False
        _busy_sessions.add(session_id)
        return True


def release_session(session_id: str) -> None:
    with _state_lock:
        _busy_sessions.discard(session_id)


# ---------------------------------------------------------------------------
# 提示词：用后台「已发布」的模板版本，而不是原型里的硬编码常量
# ---------------------------------------------------------------------------


def active_prompt(conn: sqlite3.Connection) -> tuple[str, str]:
    template = conn.execute(
        "SELECT * FROM prompt_templates ORDER BY id LIMIT 1"
    ).fetchone()
    if template is None:
        core = agent_core.core()
        return core.SYSTEM_PROMPT, core.PROMPT_VERSION

    version = conn.execute(
        "SELECT * FROM prompt_template_versions"
        " WHERE template_id=? AND version=? AND status='published'",
        (template["id"], template["active_version"]),
    ).fetchone()
    if version is None:
        core = agent_core.core()
        return core.SYSTEM_PROMPT, core.PROMPT_VERSION

    system_prompt = f"{template['locked_section'].strip()}\n\n{version['editable_section'].strip()}"
    return system_prompt, f"{template['id']}.v{template['active_version']}"


# ---------------------------------------------------------------------------
# 落库辅助
# ---------------------------------------------------------------------------


def _insert_message(
    conn: sqlite3.Connection, session_id: str, role: str, content: str,
    status: str = "complete", intent: str = "", prompt_version: str = "",
    model: str = "", latency_ms: int | None = None, data_time: str | None = None,
    client_msg_id: str | None = None, request_id: str = "",
) -> str:
    mid = _new_id("m")
    conn.execute(
        "INSERT INTO messages"
        " (id, session_id, client_msg_id, role, content, status, intent, prompt_version,"
        "  model, data_time, confidence, latency_ms, created_at, request_id)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (mid, session_id, client_msg_id or None, role, content, status, intent,
         prompt_version, model, data_time, None, latency_ms, now_iso(), request_id or None),
    )
    return mid


def _touch_session(conn: sqlite3.Connection, session_id: str) -> None:
    conn.execute("UPDATE sessions SET last_active_at=? WHERE id=?", (now_iso(), session_id))


def _save_citations(conn: sqlite3.Connection, message_id: str, hits) -> None:
    for chunk, score, _detail in hits:
        conn.execute(
            "INSERT INTO citations"
            " (id, message_id, doc_id, doc_title, doc_version, effective_from,"
            "  lane_scope, section, chunk_id, quote, score)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                _new_id("c"),
                message_id,
                getattr(chunk, "db_doc_id", chunk.doc_title),
                chunk.doc_title,
                chunk.doc_version,
                chunk.effective_from or None,
                chunk.lane_scope,
                chunk.section,
                getattr(chunk, "db_chunk_id", str(chunk.chunk_id)),
                _quote(chunk.text),
                float(score),
            ),
        )


def _quote(text: str, limit: int = 120) -> str:
    flat = re.sub(r"\s+", " ", text).strip()
    return flat[:limit] + ("…" if len(flat) > limit else "")


def citation_payload(hits) -> list[dict]:
    items = []
    for chunk, score, _detail in hits:
        items.append(
            {
                "doc_id": getattr(chunk, "db_doc_id", ""),
                "doc_title": chunk.doc_title,
                "version": chunk.doc_version,
                "effective_from": chunk.effective_from or "",
                "lane_scope": chunk.lane_scope,
                "section": chunk.section,
                "chunk_id": getattr(chunk, "db_chunk_id", str(chunk.chunk_id)),
                "quote": _quote(chunk.text),
                "score": round(float(score), 4),
            }
        )
    return items


def _slice_text(text: str, size: int = _TYPEWRITER_SLICE) -> Iterator[str]:
    for start in range(0, len(text), size):
        yield text[start:start + size]


# ---------------------------------------------------------------------------
# 流式问答
# ---------------------------------------------------------------------------


def stream_turn(
    connect: Callable[[], sqlite3.Connection],
    user: dict,
    session: dict,
    question: str,
    request_id: str,
    shipment_no: str = "",
    shipment_info: dict | None = None,
    client_msg_id: str = "",
) -> Iterator[tuple[str, dict]]:
    """生成 SSE 事件序列。产出 (event, data) 二元组。

    连接在这里自己开、自己关：FastAPI 0.106+ 的 yield 依赖会在响应发出前退出，
    流式接口若复用依赖连接，生成过程中连接已经关了。
    """
    conn = connect()
    started = time.monotonic()
    session_id = session["id"]
    lane_scope = session.get("lane_scope") or default_lane(user)
    assistant_id: str | None = None
    emitted = False

    try:
        history = recent_history(conn, session_id)
        masked_question, pii_hits = mask_pii(question)
        user_msg_id = _insert_message(
            conn, session_id, "user", masked_question, status="complete",
            client_msg_id=client_msg_id, request_id=request_id,
        )
        _touch_session(conn, session_id)
        if shipment_no:
            conn.execute(
                "UPDATE sessions SET shipment_no=? WHERE id=?", (shipment_no, session_id)
            )
        audit(
            conn, user, "chat.question", "message", user_msg_id,
            f"session={session_id} 运单={shipment_no or '-'} 脱敏={pii_hits}"
            f" 长度={len(question)}", request_id,
        )
        conn.commit()

        yield ("meta", {"request_id": request_id, "session_id": session_id,
                        "user_message_id": user_msg_id,
                        "shipment": _shipment_payload(shipment_info)})
        yield ("status", {"stage": "retrieving", "label": "正在检索规则…"})

        # ---- 1. 红线闸门 + 停止自动建议场景：命中就绝不调用模型 ----
        gate = agent_core.gate(question)
        if not gate and shipment_no:
            gate = stop_advice(question)
        system_prompt, prompt_version = active_prompt(conn)

        if gate:
            assistant_id = _insert_message(
                conn, session_id, "assistant", gate["message"], status="takeover",
                intent=gate["reason_code"], prompt_version=prompt_version, model="未调用",
                latency_ms=int((time.monotonic() - started) * 1000), data_time=now_iso(),
                request_id=request_id,
            )
            conn.commit()
            audit(
                conn, user, "chat.takeover", "message", assistant_id,
                f"{gate['reason_code']} 命中词={','.join(gate['matched_terms'])}", request_id,
            )
            conn.commit()
            emitted = True
            yield ("status", {"stage": "gated", "label": "正在判断接管条件…"})
            yield ("takeover", {
                "reason_code": gate["reason_code"],
                "message": gate["message"],
                "matched_terms": gate["matched_terms"],
            })
            yield ("guardrail", {"passed": True, "needs_review": False, "violations": []})
            yield ("done", {
                "assistant_message_id": assistant_id,
                "latency_ms": int((time.monotonic() - started) * 1000),
                "prompt_version": prompt_version,
                "model": "未调用",
                "data_time": now_iso(),
                "takeover": True,
            })
            return

        # ---- 2. 检索 ----
        hits = agent_core.search(conn, question, lane_scope=lane_scope)
        if hits is None:
            yield ("error", {"code": "KNOWLEDGE_UNAVAILABLE",
                             "message": "规则库暂不可用（没有生效的规则切片），请稍后重试",
                             "retryable": True})
            return

        cfg = agent_core.app_config()

        # ---- 3. 生成 ----
        context_block = agent_core.build_context_block(hits)
        core = agent_core.core()
        user_prompt = core.USER_PROMPT_TEMPLATE.format(
            context=context_block or "（本次未检索到规则片段）", question=question
        )
        history_block = _history_block(history)
        if history_block:
            user_prompt = f"{user_prompt}\n\n{history_block}"
        shipment_block = _shipment_context(shipment_info)
        if shipment_block:
            user_prompt = f"{user_prompt}\n\n{shipment_block}"

        assistant_id = _insert_message(
            conn, session_id, "assistant", "", status="streaming",
            prompt_version=prompt_version, model=agent_core.llm_label()[1],
            request_id=request_id,
        )
        conn.commit()
        yield ("status", {"stage": "generating", "label": "正在生成处置草稿…"})

        try:
            answer = agent_core.build_llm_client().complete(system_prompt, user_prompt)
        except Exception as exc:  # 上游失败不伪造答案
            reason = str(exc)
            timed_out = "timed out" in reason.lower() or "timeout" in reason.lower()
            conn.execute(
                "UPDATE messages SET status='error', latency_ms=? WHERE id=?",
                (int((time.monotonic() - started) * 1000), assistant_id),
            )
            conn.commit()
            audit(
                conn, user, "chat.timeout" if timed_out else "chat.error",
                "message", assistant_id, reason[:200], request_id,
            )
            conn.commit()
            yield ("error", {
                "code": "LLM_TIMEOUT" if timed_out else "LLM_UPSTREAM_ERROR",
                "message": "模型响应超时，请稍后重试" if timed_out
                           else f"模型服务异常，本次未生成回答：{reason}",
                "retryable": True,
            })
            return

        emitted = True
        for piece in _slice_text(answer):
            yield ("delta", {"text": piece})

        # ---- 4. 校验 + 落库 ----
        yield ("status", {"stage": "verifying", "label": "正在校验引用…"})
        report = agent_core.check_output(answer)
        citations = citation_payload(hits)
        masked_answer, _ = mask_pii(answer)
        latency_ms = int((time.monotonic() - started) * 1000)

        conn.execute(
            "UPDATE messages SET content=?, status='complete', model=?, data_time=?,"
            " latency_ms=?, intent=? WHERE id=?",
            (masked_answer, agent_core.llm_label()[1], now_iso(), latency_ms,
             "answer" if citations else "no_evidence", assistant_id),
        )
        _save_citations(conn, assistant_id, hits)
        conn.commit()
        audit(
            conn, user, "chat.answer", "message", assistant_id,
            f"引用={len(citations)} 护栏={'通过' if report.passed else '需复核'}"
            f" 版本={prompt_version} 耗时={latency_ms}ms", request_id,
        )
        if not report.passed:
            audit(
                conn, user, "chat.guardrail", "message", assistant_id,
                "；".join(report.violations) or "缺少引用标记", request_id,
            )
        conn.commit()

        yield ("citations", {"items": citations})
        yield ("guardrail", {
            "passed": report.passed,
            "needs_review": not report.passed,
            "violations": list(report.violations) + ([] if report.has_citation else ["缺少引用标记"]),
        })
        yield ("done", {
            "assistant_message_id": assistant_id,
            "latency_ms": latency_ms,
            "prompt_version": prompt_version,
            "model": agent_core.llm_label()[1],
            "data_time": now_iso(),
            "takeover": False,
        })
    except GeneratorExit:
        # 客户端断开：不补全内容，标记 aborted（文档 3.2 第 4 条）
        if assistant_id:
            try:
                conn.execute(
                    "UPDATE messages SET status='aborted' WHERE id=? AND status='streaming'",
                    (assistant_id,),
                )
                conn.commit()
            except sqlite3.Error:
                pass
        raise
    except Exception as exc:  # 兜底：流内异常也走 error 事件，不裸抛
        if not emitted:
            yield ("error", {"code": "INTERNAL_ERROR",
                             "message": f"系统内部错误：{exc}", "retryable": True})
    finally:
        try:
            conn.close()
        except sqlite3.Error:
            pass
