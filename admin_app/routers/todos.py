"""我的待办与站内通知。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request

from ..deps import get_db, require_page
from ..services import draft as draft_service
from ..services import notify as notify_service
from ..web import check_csrf, redirect, render

router = APIRouter(prefix="/admin", tags=["todos"])


@router.get("/todos")
def todos_page(request: Request, user=Depends(require_page()), db=Depends(get_db)):
    events = [
        dict(r)
        for r in db.execute(
            "SELECT * FROM exception_events WHERE handler=? AND closed_at IS NULL"
            " ORDER BY COALESCE(due_at, occurred_at)",
            (user["id"],),
        ).fetchall()
    ]
    drafts = (
        draft_service.list_drafts(db, "pending_review")
        if user["role"] in {"supervisor", "sys_admin", "auditor"}
        else []
    )
    return render(
        request, user, "todos.html",
        events=events,
        drafts=drafts,
        notifications=notify_service.list_for(db, user["id"]),
        unread=notify_service.unread_count(db, user["id"]),
    )


@router.post("/notifications/read")
def mark_read(
    request: Request,
    csrf_token: str = Form(""),
    notification_id: str = Form(""),
    user=Depends(require_page()),
    db=Depends(get_db),
):
    if not check_csrf(request, csrf_token):
        return redirect("/admin/todos", err="页面已过期，请刷新后重试")
    notify_service.mark_read(db, user["id"], notification_id)
    return redirect("/admin/todos", ok="已标记为已读")
