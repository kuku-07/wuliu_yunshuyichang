"""数据管理：演示数据的逐项删除与按组恢复（仅系统管理员）。

页面语义是「保留 + 可删减」：演示数据默认都在，需要时一条条删；
不做一键清空。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request

from ..deps import get_db, require_page
from ..services import data_admin as data_service
from ..web import check_csrf, redirect, render

router = APIRouter(prefix="/admin", tags=["data"])


@router.get("/data")
def data_page(
    request: Request,
    user=Depends(require_page("users:manage")),
    db=Depends(get_db),
):
    return render(
        request, user, "data.html",
        overview=data_service.overview(db),
        docs=data_service.list_docs(db),
        sessions=data_service.list_sessions(db),
        users=data_service.list_users(db),
        shipments=data_service.list_shipments(db),
        grants=data_service.list_grants(db),
        categories=data_service.CATEGORIES,
    )


@router.post("/data/{category}/delete")
def delete_item(
    request: Request,
    category: str,
    csrf_token: str = Form(""),
    item_id: str = Form(""),
    user=Depends(require_page("users:manage")),
    db=Depends(get_db),
):
    if not check_csrf(request, csrf_token):
        return redirect("/admin/data", err="页面已过期，请刷新后重试")
    ok, error = data_service.delete(db, user, category, item_id)
    if not ok:
        return redirect("/admin/data", err=error)
    label = data_service.CATEGORIES.get(category, category)
    return redirect("/admin/data", ok=f"已删除{label} · {item_id}")


@router.post("/data/{category}/restore")
def restore_group(
    request: Request,
    category: str,
    csrf_token: str = Form(""),
    user=Depends(require_page("users:manage")),
    db=Depends(get_db),
):
    if not check_csrf(request, csrf_token):
        return redirect("/admin/data", err="页面已过期，请刷新后重试")
    ok, count = data_service.restore(db, user, category)
    if not ok:
        return redirect("/admin/data", err="不支持的数据类型")
    label = data_service.CATEGORIES.get(category, category)
    return redirect("/admin/data", ok=f"已恢复{label} · 当前 {count} 条")
