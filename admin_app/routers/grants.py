"""运单级授权的管理入口（仅系统管理员）。

对话入口的预检在 services/grants.py；这里只负责「谁被授权查哪一票」的维护。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request

from ..db import now_iso
from ..deps import get_db, require_page
from ..services import grants as grant_service
from ..web import check_csrf, redirect, render

router = APIRouter(prefix="/admin", tags=["grants"])


@router.get("/grants")
def grants_page(
    request: Request,
    keyword: str = "",
    status: str = "",
    user=Depends(require_page("users:manage")),
    db=Depends(get_db),
):
    rows = grant_service.list_grants(db, keyword.strip(), status)
    return render(
        request, user, "grants.html",
        grants=rows,
        users=grant_service.active_users(db),
        shipments=grant_service.list_shipments(db),
        keyword=keyword,
        status_filter=status,
        now=now_iso(),
    )


@router.post("/grants/create")
def create_grant(
    request: Request,
    csrf_token: str = Form(""),
    user_id: str = Form(""),
    shipment_no: str = Form(""),
    expires_at: str = Form(""),
    reason: str = Form(""),
    user=Depends(require_page("users:manage")),
    db=Depends(get_db),
):
    if not check_csrf(request, csrf_token):
        return redirect("/admin/grants", err="页面已过期，请刷新后重试")
    if not user_id:
        return redirect("/admin/grants", err="请选择被授权人")

    ok, error = grant_service.grant(
        db, user, user_id, shipment_no,
        expires_at=expires_at.strip() or None,
        reason=reason.strip(),
    )
    if not ok:
        return redirect("/admin/grants", err=error)
    return redirect(
        "/admin/grants",
        ok=f"已授权 {grant_service.normalize(shipment_no)}",
    )


@router.post("/grants/{grant_id}/revoke")
def revoke_grant(
    request: Request,
    grant_id: str,
    csrf_token: str = Form(""),
    reason: str = Form(""),
    user=Depends(require_page("users:manage")),
    db=Depends(get_db),
):
    if not check_csrf(request, csrf_token):
        return redirect("/admin/grants", err="页面已过期，请刷新后重试")
    ok, error = grant_service.revoke(db, user, grant_id, reason.strip())
    if not ok:
        return redirect("/admin/grants", err=error)
    return redirect("/admin/grants", ok="授权已撤销")
