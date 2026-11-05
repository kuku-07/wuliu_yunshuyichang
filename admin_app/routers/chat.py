"""阶段 2 一线问答入口：页面 + SSE 流式接口。

与 docs/04 的差异（有意为之，写在 README 里）：
- 文档设计的是 /api/v1/* + Bearer Token，本后台已有 Cookie/JWT 会话体系，
  为了不出现两套鉴权，接口挂在 /admin 下并复用现有登录态与 CSRF。
- 事件协议、错误码、落库顺序与文档一致。
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse, StreamingResponse

from ..db import connect
from ..deps import get_db, require_api, require_page
from ..services import chat_service
from ..services import grants as grant_service
from ..web import check_csrf, redirect, render

router = APIRouter(prefix="/admin", tags=["chat"])

SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _error(code: str, message: str, status_code: int, request_id: str) -> JSONResponse:
    return JSONResponse(
        {"code": code, "message": message, "data": {}, "request_id": request_id},
        status_code=status_code,
    )


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.get("/chat")
def chat_page(
    request: Request,
    user=Depends(require_page()),
    db=Depends(get_db),
):
    session = chat_service.get_or_create_session(db, user)
    messages = chat_service.load_messages(db, session["id"])
    return render(
        request, user, "chat.html",
        session=session,
        messages=messages,
        lanes=[session["lane_scope"]],
        question_max=chat_service.QUESTION_MAX,
    )


@router.post("/chat/session")
def new_session(
    request: Request,
    csrf_token: str = Form(""),
    user=Depends(require_page()),
    db=Depends(get_db),
):
    if not check_csrf(request, csrf_token):
        return redirect("/admin/chat", err="页面已过期，请刷新后重试")
    db.execute(
        "UPDATE sessions SET status='closed' WHERE user_id=? AND status='active'",
        (user["id"],),
    )
    db.commit()
    session = chat_service.create_session(db, user)
    return redirect("/admin/chat", ok=f"已新建会话 · {session['id']}")


@router.post("/api/chat/stream")
def chat_stream(
    request: Request,
    question: str = Form(""),
    session_id: str = Form(""),
    shipment_no: str = Form(""),
    csrf_token: str = Form(""),
    user=Depends(require_api()),
):
    request_id = getattr(request.state, "request_id", "")

    if not check_csrf(request, csrf_token):
        return _error("INVALID_REQUEST", "页面已过期，请刷新后重试", 400, request_id)

    text = question.strip()
    if not text or not session_id:
        return _error("INVALID_REQUEST", "请求参数不合法：问题或会话不能为空", 400, request_id)
    if len(text) > chat_service.QUESTION_MAX:
        return _error(
            "QUESTION_TOO_LONG",
            f"问题超过 {chat_service.QUESTION_MAX} 字，请精简后重试", 422, request_id,
        )

    conn = connect()
    try:
        session = chat_service.get_session(conn, session_id)
    finally:
        conn.close()

    if session is None:
        return _error("SESSION_NOT_FOUND", "会话不存在或已关闭", 404, request_id)
    if session["user_id"] != user["id"]:
        return _error("SESSION_FORBIDDEN", "无权访问该会话", 403, request_id)

    # ---- 运单级授权预检：必须在流开始前，未授权不检索、不调模型 ----
    shipment = ""
    shipment_info = None
    if (shipment_no or "").strip():
        shipment, format_error = grant_service.validate_format(shipment_no)
        if format_error:
            return _error(
                "INVALID_REQUEST", f"请求参数不合法：{format_error}", 400, request_id
            )
        conn = connect()
        try:
            allowed, reason = grant_service.check(
                conn, user["id"], shipment,
                session_lane=session.get("lane_scope") or "",
            )
            grant_service.record_check(conn, user, shipment, allowed, reason, request_id)
            if allowed:
                shipment_info = grant_service.get_shipment(conn, shipment)
        finally:
            conn.close()
        if not allowed:
            return _error(
                "SHIPMENT_FORBIDDEN", grant_service.FORBIDDEN_MESSAGE, 403, request_id
            )

    if chat_service.rate_limited(user["id"]):
        return _error("RATE_LIMITED", "提问过于频繁，请稍后再试", 429, request_id)
    if not chat_service.acquire_session(session_id):
        return _error("SESSION_BUSY", "当前会话正在回答，请等待完成", 409, request_id)

    def event_stream():
        try:
            for event, data in chat_service.stream_turn(
                connect, user, session, text, request_id, shipment_no=shipment,
                shipment_info=shipment_info,
            ):
                yield _sse(event, data)
        finally:
            chat_service.release_session(session_id)

    return StreamingResponse(
        event_stream(), media_type="text/event-stream; charset=utf-8", headers=SSE_HEADERS
    )
