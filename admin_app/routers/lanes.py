"""干线管理：新建（名称 + 地区）、启用/停用、删除。仅系统管理员。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request

from ..deps import get_db, require_page
from ..services import lanes as lane_service
from ..web import check_csrf, redirect, render

router = APIRouter(prefix="/admin", tags=["lanes"])


@router.get("/lanes")
def lanes_page(
    request: Request,
    user=Depends(require_page("users:manage")),
    db=Depends(get_db),
):
    return render(
        request, user, "lanes.html",
        lanes=lane_service.list_lanes(db),
        active_count=len(lane_service.active_names(db)),
    )


@router.post("/lanes/create")
def create_lane(
    request: Request,
    csrf_token: str = Form(""),
    name: str = Form(""),
    region: str = Form(""),
    note: str = Form(""),
    user=Depends(require_page("users:manage")),
    db=Depends(get_db),
):
    if not check_csrf(request, csrf_token):
        return redirect("/admin/lanes", err="页面已过期，请刷新后重试")
    ok, error = lane_service.create(db, user, name, region, note)
    if not ok:
        return redirect("/admin/lanes", err=error)
    return redirect("/admin/lanes", ok=f"已新建干线「{name.strip()}」")


@router.post("/lanes/status")
def toggle_lane(
    request: Request,
    csrf_token: str = Form(""),
    name: str = Form(""),
    status: str = Form(""),
    user=Depends(require_page("users:manage")),
    db=Depends(get_db),
):
    if not check_csrf(request, csrf_token):
        return redirect("/admin/lanes", err="页面已过期，请刷新后重试")
    ok, error = lane_service.set_status(db, user, name, status)
    if not ok:
        return redirect("/admin/lanes", err=error)
    label = "已启用" if status == "active" else "已停用"
    return redirect("/admin/lanes", ok=f"干线「{name}」{label}")


@router.post("/lanes/delete")
def delete_lane(
    request: Request,
    csrf_token: str = Form(""),
    name: str = Form(""),
    user=Depends(require_page("users:manage")),
    db=Depends(get_db),
):
    if not check_csrf(request, csrf_token):
        return redirect("/admin/lanes", err="页面已过期，请刷新后重试")
    ok, error = lane_service.delete(db, user, name)
    if not ok:
        return redirect("/admin/lanes", err=error)
    return redirect("/admin/lanes", ok=f"已删除干线「{name}」")
