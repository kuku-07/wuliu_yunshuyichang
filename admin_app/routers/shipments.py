"""运单主数据登记页（仅系统管理员）。

对话入口的授权预检依赖这里的「运单 → 线路」映射；同一页也负责演示数据的
清理与恢复，方便把演示环境切成干净环境。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request

from ..deps import get_db, require_page
from ..services import lanes as lane_service
from ..services import shipments as shipment_service
from ..web import check_csrf, redirect, render

router = APIRouter(prefix="/admin", tags=["shipments"])


@router.get("/shipments")
def shipments_page(
    request: Request,
    keyword: str = "",
    status: str = "",
    edit: str = "",
    user=Depends(require_page("users:manage")),
    db=Depends(get_db),
):
    rows = shipment_service.list_shipments(db, keyword.strip(), status)
    editing = shipment_service.get(db, edit) if edit else None
    return render(
        request, user, "shipments.html",
        shipments=rows,
        editing=editing,
        lanes=lane_service.list_lanes(db, include_disabled=False),
        status_options=shipment_service.status_options(),
        keyword=keyword,
        status_filter=status,
    )


@router.post("/shipments/save")
def save_shipment(
    request: Request,
    csrf_token: str = Form(""),
    shipment_no: str = Form(""),
    original_no: str = Form(""),
    lane_scope: str = Form(""),
    customer: str = Form(""),
    status: str = Form("in_transit"),
    user=Depends(require_page("users:manage")),
    db=Depends(get_db),
):
    if not check_csrf(request, csrf_token):
        return redirect("/admin/shipments", err="页面已过期，请刷新后重试")

    # 改号等于新建一条 + 删旧的一条，这里直接禁止，避免把历史授权搞成孤儿
    if original_no and shipment_service.normalize(original_no) != shipment_service.normalize(shipment_no):
        return redirect("/admin/shipments", err="运单号不可修改，如需换号请删除后重新登记")

    ok, error = shipment_service.save(
        db, user, shipment_no, lane_scope, customer, status
    )
    if not ok:
        return redirect(
            f"/admin/shipments?edit={original_no}" if original_no else "/admin/shipments",
            err=error,
        )
    return redirect(
        "/admin/shipments",
        ok=f"已保存 {shipment_service.normalize(shipment_no)}",
    )


@router.post("/shipments/{shipment_no}/delete")
def delete_shipment(
    request: Request,
    shipment_no: str,
    csrf_token: str = Form(""),
    user=Depends(require_page("users:manage")),
    db=Depends(get_db),
):
    if not check_csrf(request, csrf_token):
        return redirect("/admin/shipments", err="页面已过期，请刷新后重试")
    ok, error = shipment_service.delete(db, user, shipment_no)
    if not ok:
        return redirect("/admin/shipments", err=error)
    return redirect("/admin/shipments", ok=f"已删除 {shipment_service.normalize(shipment_no)}")
