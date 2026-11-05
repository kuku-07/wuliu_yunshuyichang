"""主线页面：异常受理、查单工作台、指标。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request

from ..deps import get_db, require_page
from ..services import alerts as alert_service
from ..services import draft as draft_service
from ..services import metrics as metric_service
from ..services import retention
from ..services import tms as tms_service
from ..services.users import list_users
from ..web import check_csrf, redirect, render

router = APIRouter(prefix="/admin", tags=["mainline"])


@router.get("/exceptions")
def exceptions_page(
    request: Request,
    status: str = "",
    user=Depends(require_page("kb:read")),
    db=Depends(get_db),
):
    # 打开页面时顺手扫一次超时与预警，省一个定时任务
    tms_service.escalate_overdue(db)
    alert_service.evaluate(db, user if user["role"] != "auditor" else None)

    return render(
        request, user, "exceptions.html",
        events=tms_service.list_events_with_state(db, status),
        repairs=tms_service.list_repairs(db),
        alerts=alert_service.list_alerts(db),
        handlers=[u for u in list_users(db) if u["status"] == "active"],
        status_filter=status,
    )


@router.post("/exceptions/import")
def import_samples(request: Request, csrf_token: str = Form(""),
                   user=Depends(require_page("users:manage")), db=Depends(get_db)):
    if not check_csrf(request, csrf_token):
        return redirect("/admin/exceptions", err="页面已过期，请刷新后重试")
    stats = tms_service.import_samples(db, user)
    message = (
        f"导入完成：运单 {stats['shipments']}、子单 {stats['sub_shipments']}、"
        f"轨迹 {stats['tracks']}、事件 {stats['events']}、待修复 {stats['queued']}"
    )
    if stats["errors"]:
        message += f"；告警：{'；'.join(stats['errors'][:3])}"
    return redirect("/admin/exceptions", ok=message)


@router.post("/exceptions/repair")
def repair(request: Request, csrf_token: str = Form(""), queue_id: str = Form(""),
           shipment_no: str = Form(""), event_type: str = Form(""),
           occurred_at: str = Form(""), source: str = Form(""),
           user=Depends(require_page("users:manage")), db=Depends(get_db)):
    if not check_csrf(request, csrf_token):
        return redirect("/admin/exceptions", err="页面已过期，请刷新后重试")
    ok, message = tms_service.resolve_repair(db, user, queue_id, {
        "shipment_no": shipment_no,
        "event_type": event_type,
        "occurred_at": occurred_at,
        "source": source,
    })
    return redirect("/admin/exceptions", ok=message if ok else None,
                    err=None if ok else message)


@router.post("/exceptions/{event_id}/accept")
def accept_event(request: Request, event_id: str, csrf_token: str = Form(""),
                 user=Depends(require_page("kb:edit")), db=Depends(get_db)):
    if not check_csrf(request, csrf_token):
        return redirect("/admin/exceptions", err="页面已过期，请刷新后重试")
    ok, message = tms_service.accept_event(db, user, event_id)
    return redirect("/admin/exceptions", ok=message if ok else None,
                    err=None if ok else message)


@router.post("/exceptions/{event_id}/close")
def close_event(request: Request, event_id: str, csrf_token: str = Form(""),
                note: str = Form(""),
                user=Depends(require_page("kb:edit")), db=Depends(get_db)):
    if not check_csrf(request, csrf_token):
        return redirect("/admin/exceptions", err="页面已过期，请刷新后重试")
    ok, message = tms_service.close_event(db, user, event_id, note)
    return redirect("/admin/exceptions", ok=message if ok else None,
                    err=None if ok else message)


@router.post("/exceptions/{event_id}/assign")
def assign_event(request: Request, event_id: str, csrf_token: str = Form(""),
                 handler: str = Form(""),
                 user=Depends(require_page("kb:edit")), db=Depends(get_db)):
    if not check_csrf(request, csrf_token):
        return redirect("/admin/exceptions", err="页面已过期，请刷新后重试")
    ok, message = tms_service.assign_event(db, user, event_id, handler)
    return redirect("/admin/exceptions", ok=message if ok else None,
                    err=None if ok else message)


@router.post("/alerts/{alert_id}/review")
def review_alert(request: Request, alert_id: str, csrf_token: str = Form(""),
                 verdict: str = Form(""), note: str = Form(""),
                 user=Depends(require_page("kb:edit")), db=Depends(get_db)):
    if not check_csrf(request, csrf_token):
        return redirect("/admin/exceptions", err="页面已过期，请刷新后重试")
    ok, message = alert_service.review(db, user, alert_id, verdict, note)
    return redirect("/admin/exceptions", ok=message if ok else None,
                    err=None if ok else message)


@router.get("/workbench")
def workbench_page(request: Request, shipment_no: str = "",
                   user=Depends(require_page("kb:read")), db=Depends(get_db)):
    evidence = draft_service.evidence(db, (shipment_no or "").strip().upper()) if shipment_no else None
    return render(
        request, user, "workbench.html",
        shipment_no=shipment_no,
        evidence=evidence,
        drafts=draft_service.list_drafts(db),
        review_reasons=draft_service.REVIEW_REASONS,
        sent_channels=draft_service.SENT_CHANNELS,
    )


@router.post("/workbench/generate")
def generate_draft(request: Request, csrf_token: str = Form(""),
                   shipment_no: str = Form(""),
                   user=Depends(require_page("kb:edit")), db=Depends(get_db)):
    if not check_csrf(request, csrf_token):
        return redirect("/admin/workbench", err="页面已过期，请刷新后重试")
    ok, message, payload = draft_service.generate(db, user, shipment_no)
    target = f"/admin/workbench?shipment_no={shipment_no.strip().upper()}"
    return redirect(target, ok=message if ok else None, err=None if ok else message)


@router.post("/workbench/{draft_id}/review")
def review_draft(request: Request, draft_id: str, csrf_token: str = Form(""),
                 action: str = Form(""), reason: str = Form(""), note: str = Form(""),
                 user=Depends(require_page("audit:mark")), db=Depends(get_db)):
    if not check_csrf(request, csrf_token):
        return redirect("/admin/workbench", err="页面已过期，请刷新后重试")
    ok, message = draft_service.review(db, user, draft_id, action, reason, note)
    return redirect("/admin/workbench", ok=message if ok else None,
                    err=None if ok else message)


@router.post("/workbench/{draft_id}/sent")
def mark_sent(request: Request, draft_id: str, csrf_token: str = Form(""),
              channel: str = Form(""), note: str = Form(""),
              user=Depends(require_page("kb:edit")), db=Depends(get_db)):
    if not check_csrf(request, csrf_token):
        return redirect("/admin/workbench", err="页面已过期，请刷新后重试")
    ok, message = draft_service.mark_sent(db, user, draft_id, channel, note)
    return redirect("/admin/workbench", ok=message if ok else None,
                    err=None if ok else message)


@router.get("/metrics")
def metrics_page(request: Request, user=Depends(require_page("kb:read")),
                 db=Depends(get_db)):
    return render(request, user, "metrics.html", stats=metric_service.overview(db))


@router.post("/metrics/retention")
def run_retention(request: Request, csrf_token: str = Form(""),
                  user=Depends(require_page("users:manage")), db=Depends(get_db)):
    if not check_csrf(request, csrf_token):
        return redirect("/admin/metrics", err="页面已过期，请刷新后重试")
    result = retention.purge(db, user)
    return redirect(
        "/admin/metrics",
        ok=f"已清理 {result['cutoff']} 之前的数据：消息 {result['messages']} 条、"
           f"日志 {result['logs']} 条",
    )
