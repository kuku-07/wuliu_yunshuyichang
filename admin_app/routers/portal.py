"""客户 / 承运商只读门户。

按 docs/02 §3 的业务角色补入口：客户与承运商不后台，只能看
授权给他们的运单（`authorization_grants`），且字段脱敏。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ..deps import get_db, require_page
from ..security import mask_pii
from ..web import render

router = APIRouter(prefix="/portal", tags=["portal"])


@router.get("")
def portal_page(request: Request, user=Depends(require_page("portal:read")),
                db=Depends(get_db)):
    rows = db.execute(
        "SELECT g.shipment_no, g.lane_scope, s.status, s.customer, s.plan_eta,"
        " s.delivered_at, s.receipt_at"
        " FROM authorization_grants g"
        " LEFT JOIN shipments s ON s.shipment_no=g.shipment_no"
        " WHERE g.user_id=? AND g.status='active'"
        " ORDER BY g.granted_at DESC",
        (user["id"],),
    ).fetchall()

    shipments = []
    for row in rows:
        item = dict(row)
        item["customer_masked"], _ = mask_pii(item.get("customer") or "")
        last_track = db.execute(
            "SELECT at, status, location FROM shipment_tracks WHERE shipment_no=?"
            " ORDER BY at DESC LIMIT 1",
            (row["shipment_no"],),
        ).fetchone()
        item["last_track"] = dict(last_track) if last_track else None
        shipments.append(item)

    return render(request, user, "portal.html", shipments=shipments, portal=True)
