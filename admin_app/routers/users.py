"""账号与角色管理（仅系统管理员）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request

from ..deps import get_db, require_page
from ..services import lanes as lane_service
from ..services import users as user_service
from ..web import check_csrf, redirect, render

router = APIRouter(prefix="/admin", tags=["users"])


@router.get("/users")
def users_page(request: Request, user=Depends(require_page("users:manage")),
               db=Depends(get_db)):
    return render(
        request, user, "users.html",
        users=user_service.list_users(db),
        roles=user_service.ROLES,
        lanes=lane_service.list_lanes(db),
        min_password=user_service.MIN_PASSWORD,
    )


@router.post("/users/create")
async def create_user(
    request: Request,
    csrf_token: str = Form(""),
    employee_no: str = Form(""),
    name: str = Form(""),
    role: str = Form(""),
    password: str = Form(""),
    user=Depends(require_page("users:manage")),
    db=Depends(get_db),
):
    if not check_csrf(request, csrf_token):
        return redirect("/admin/users", err="页面已过期，请刷新后重试")
    form = await request.form()
    ok, error = user_service.create(
        db, user, employee_no, name, role,
        [value for value in form.getlist("lanes") if value], password,
    )
    if not ok:
        return redirect("/admin/users", err=error)
    return redirect("/admin/users", ok=f"已创建账号 {employee_no}")


@router.post("/users/{user_id}/update")
async def update_user(
    request: Request,
    user_id: str,
    csrf_token: str = Form(""),
    name: str = Form(""),
    role: str = Form(""),
    status: str = Form("active"),
    user=Depends(require_page("users:manage")),
    db=Depends(get_db),
):
    if not check_csrf(request, csrf_token):
        return redirect("/admin/users", err="页面已过期，请刷新后重试")
    form = await request.form()
    ok, error = user_service.update(
        db, user, user_id, name, role,
        [value for value in form.getlist("lanes") if value], status,
    )
    if not ok:
        return redirect("/admin/users", err=error)
    return redirect("/admin/users", ok="账号已更新")


@router.post("/users/{user_id}/reset")
def reset_password(
    request: Request,
    user_id: str,
    csrf_token: str = Form(""),
    password: str = Form(""),
    user=Depends(require_page("users:manage")),
    db=Depends(get_db),
):
    if not check_csrf(request, csrf_token):
        return redirect("/admin/users", err="页面已过期，请刷新后重试")
    ok, message = user_service.reset_password(db, user, user_id, password)
    return redirect("/admin/users", ok=message if ok else None,
                    err=None if ok else message)


@router.post("/users/{user_id}/unlock")
def unlock_user(
    request: Request,
    user_id: str,
    csrf_token: str = Form(""),
    user=Depends(require_page("users:manage")),
    db=Depends(get_db),
):
    if not check_csrf(request, csrf_token):
        return redirect("/admin/users", err="页面已过期，请刷新后重试")
    ok, message = user_service.unlock(db, user, user_id)
    return redirect("/admin/users", ok=message if ok else None,
                    err=None if ok else message)
