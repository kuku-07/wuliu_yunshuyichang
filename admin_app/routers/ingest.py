"""机器接入端点：GPS 轨迹与 IM 留痕（X-Ingest-Token 鉴权）。"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Header, HTTPException

from .. import config
from ..deps import get_db
from ..services import ingest as ingest_service

router = APIRouter(prefix="/admin/api/ingest", tags=["ingest"])


def _check_token(token: str) -> None:
    if not config.INGEST_TOKEN or token != config.INGEST_TOKEN:
        raise HTTPException(status_code=401, detail="接入令牌不正确")


@router.post("/tracks")
def ingest_tracks(
    payload: dict = Body(...),
    x_ingest_token: str = Header("", alias="X-Ingest-Token"),
    db=Depends(get_db),
):
    _check_token(x_ingest_token)
    records = payload.get("records") or []
    if not isinstance(records, list):
        raise HTTPException(status_code=400, detail="records 应为数组")
    accepted, errors = ingest_service.add_tracks(db, records)
    return {
        "code": "OK" if not errors else "PARTIAL",
        "message": "" if not errors else "；".join(errors[:3]),
        "data": {"accepted": accepted, "rejected": len(errors)},
    }


@router.post("/im")
def ingest_im(
    payload: dict = Body(...),
    x_ingest_token: str = Header("", alias="X-Ingest-Token"),
    db=Depends(get_db),
):
    _check_token(x_ingest_token)
    records = payload.get("records") or []
    if not isinstance(records, list):
        raise HTTPException(status_code=400, detail="records 应为数组")
    accepted, errors = ingest_service.add_im_notes(db, records)
    return {
        "code": "OK" if not errors else "PARTIAL",
        "message": "" if not errors else "；".join(errors[:3]),
        "data": {"accepted": accepted, "rejected": len(errors)},
    }
