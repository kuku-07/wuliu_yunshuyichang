"""员工门户（C 端）：独立入口，只保留问答，不出现管理后台导航。

与后台 `/admin/chat` 共用同一套服务、会话与审计；只是外壳不同。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request

from ..deps import get_db, require_page
from ..services import chat_service
from ..web import check_csrf, redirect, render

router = APIRouter(prefix="/agent", tags=["agent"])


@router.get("")
def agent_page(
    request: Request,
    session: str = "",
    user=Depends(require_page("agent:use")),
    db=Depends(get_db),
):
    context = chat_service.page_context(db, user, session)
    return render(
        request, user, "chat.html", layout="base_agent.html", chat_base="/agent",
        **context,
    )


@router.post("/session")
def new_session(
    request: Request,
    csrf_token: str = Form(""),
    user=Depends(require_page("agent:use")),
    db=Depends(get_db),
):
    if not check_csrf(request, csrf_token):
        return redirect("/agent", err="页面已过期，请刷新后重试")
    created = chat_service.create_session(db, user)
    return redirect("/agent", ok=f"已新建会话 · {created['id']}")


@router.post("/lane")
def switch_lane(
    request: Request,
    csrf_token: str = Form(""),
    session_id: str = Form(""),
    lane_scope: str = Form(""),
    user=Depends(require_page("agent:use")),
    db=Depends(get_db),
):
    if not check_csrf(request, csrf_token):
        return redirect("/agent", err="页面已过期，请刷新后重试")
    ok, message = chat_service.set_session_lane(db, user, session_id, lane_scope)
    return redirect(f"/agent?session={session_id}", ok=message if ok else None,
                    err=None if ok else message)


@router.post("/{session_id}/delete")
def delete_session(
    request: Request,
    session_id: str,
    csrf_token: str = Form(""),
    user=Depends(require_page("agent:use")),
    db=Depends(get_db),
):
    if not check_csrf(request, csrf_token):
        return redirect("/agent", err="页面已过期，请刷新后重试")
    ok, message = chat_service.delete_session(db, user, session_id)
    return redirect("/agent", ok=message if ok else None, err=None if ok else message)
