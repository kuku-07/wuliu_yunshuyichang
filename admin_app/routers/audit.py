"""对话审计：筛选、详情、标记、导出、发布记录。"""
from __future__ import annotations

import csv
import io
import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import StreamingResponse

from ..db import now_iso
from ..deps import get_db, require_api, require_page
from ..security import mask_pii
from ..services.audit_log import log as audit
from ..web import check_csrf, redirect, render

router = APIRouter(prefix="/admin", tags=["audit"])

FLAG_TYPES = {
    "REDLINE_BYPASS": "红线绕过",
    "UNAUTHORIZED_QUERY": "越权查询",
    "NO_EVIDENCE_SIGN": "未取证签收",
    "UNSIGNED_OUTBOUND": "未签核外发",
    "PII_LEAK": "敏感信息外泄",
}
PAGE_SIZE = 20


def _filters(employee: str, date_from: str, date_to: str, lane: str,
             flag: str, takeover: str) -> tuple[str, list]:
    clauses, params = [], []
    if employee:
        clauses.append("s.user_id LIKE ?")
        params.append(f"%{employee}%")
    if date_from:
        clauses.append("s.created_at >= ?")
        params.append(f"{date_from}T00:00:00")
    if date_to:
        clauses.append("s.created_at <= ?")
        params.append(f"{date_to}T23:59:59")
    if lane:
        clauses.append("s.lane_scope = ?")
        params.append(lane)
    if takeover == "1":
        clauses.append(
            "EXISTS (SELECT 1 FROM messages m WHERE m.session_id=s.id AND m.status='takeover')"
        )
    if flag:
        clauses.append(
            "EXISTS (SELECT 1 FROM conversation_flags f JOIN messages m ON f.message_id=m.id"
            " WHERE m.session_id=s.id AND f.flag_type=? AND f.revoked_at IS NULL)"
        )
        params.append(flag)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return where, params


@router.get("/audit")
def audit_list(
    request: Request,
    employee: str = "",
    date_from: str = "",
    date_to: str = "",
    lane: str = "",
    flag: str = "",
    takeover: str = "",
    page: int = 1,
    user=Depends(require_page("audit:read")),
    db=Depends(get_db),
):
    where, params = _filters(employee, date_from, date_to, lane, flag, takeover)
    total = db.execute(f"SELECT COUNT(*) FROM sessions s {where}", params).fetchone()[0]
    page = max(1, page)
    sessions = db.execute(
        f"""
        SELECT s.*,
               (SELECT content FROM messages m WHERE m.session_id=s.id AND m.role='user'
                ORDER BY m.created_at LIMIT 1) AS first_question,
               (SELECT COUNT(*) FROM messages m WHERE m.session_id=s.id) AS msg_count,
               (SELECT status FROM messages m WHERE m.session_id=s.id AND m.role='assistant'
                ORDER BY m.created_at DESC LIMIT 1) AS last_status,
               (SELECT COUNT(*) FROM conversation_flags f JOIN messages m ON f.message_id=m.id
                WHERE m.session_id=s.id AND f.revoked_at IS NULL) AS flag_count
        FROM sessions s {where}
        ORDER BY s.last_active_at DESC
        LIMIT ? OFFSET ?
        """,
        params + [PAGE_SIZE, (page - 1) * PAGE_SIZE],
    ).fetchall()
    lanes = [r[0] for r in db.execute("SELECT DISTINCT lane_scope FROM sessions").fetchall()]
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    return render(
        request, user, "audit_list.html",
        sessions=[dict(s) for s in sessions], total=total, page=page, pages=pages,
        lanes=lanes, flag_types=FLAG_TYPES,
        filters={"employee": employee, "date_from": date_from, "date_to": date_to,
                 "lane": lane, "flag": flag, "takeover": takeover},
    )


@router.get("/audit/export")
def export(request: Request, employee: str = "", date_from: str = "", date_to: str = "",
           lane: str = "", flag: str = "", takeover: str = "",
           user=Depends(require_page("audit:export")), db=Depends(get_db)):
    where, params = _filters(employee, date_from, date_to, lane, flag, takeover)
    rows = db.execute(
        f"""
        SELECT s.id AS session_id, s.user_id, s.lane_scope, s.shipment_no, s.created_at,
               m.role, m.status, m.content, m.model, m.prompt_version,
               (SELECT GROUP_CONCAT(f.flag_type) FROM conversation_flags f
                WHERE f.message_id=m.id AND f.revoked_at IS NULL) AS flags
        FROM sessions s JOIN messages m ON m.session_id=s.id
        {where}
        ORDER BY s.created_at DESC, m.created_at
        LIMIT 5000
        """,
        params,
    ).fetchall()
    if len(rows) >= 5000:
        raise HTTPException(status_code=422, detail="导出超过 5000 条，请缩小筛选范围")

    buffer = io.StringIO()
    buffer.write("\ufeff")
    writer = csv.writer(buffer)
    writer.writerow(["会话ID", "员工ID", "线路", "运单号", "会话时间", "角色",
                     "消息状态", "内容", "模型", "提示词版本", "标记类型"])
    for row in rows:
        safe_content, _ = mask_pii(row["content"].replace("\n", " "))
        writer.writerow([row["session_id"], row["user_id"], row["lane_scope"],
                         row["shipment_no"] or "", row["created_at"], row["role"],
                         row["status"], safe_content, row["model"],
                         row["prompt_version"], row["flags"] or ""])
    audit(db, user, "audit_export", "audit", "conversations",
          f"导出 {len(rows)} 行", getattr(request.state, "request_id", ""))
    db.commit()
    filename = f"audit_{now_iso()[:10]}.csv"
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/audit/{session_id}")
def audit_detail(request: Request, session_id: str, user=Depends(require_page("audit:read")),
                 db=Depends(get_db)):
    session = db.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    messages = db.execute(
        "SELECT * FROM messages WHERE session_id=? ORDER BY created_at", (session_id,)
    ).fetchall()
    citations = db.execute(
        "SELECT * FROM citations WHERE message_id IN"
        " (SELECT id FROM messages WHERE session_id=?)", (session_id,)
    ).fetchall()
    citation_map: dict[str, list] = {}
    for c in citations:
        citation_map.setdefault(c["message_id"], []).append(dict(c))
    flags = db.execute(
        "SELECT f.*, u.name AS flagged_name FROM conversation_flags f"
        " LEFT JOIN admin_users u ON u.id=f.flagged_by"
        " WHERE f.message_id IN (SELECT id FROM messages WHERE session_id=?)"
        " ORDER BY f.flagged_at DESC",
        (session_id,),
    ).fetchall()
    flag_map: dict[str, list] = {}
    for f in flags:
        flag_map.setdefault(f["message_id"], []).append(dict(f))
    items = []
    for m in messages:
        safe_content, _ = mask_pii(m["content"])
        items.append({
            "id": m["id"], "role": m["role"], "content": safe_content,
            "status": m["status"], "intent": m["intent"], "model": m["model"],
            "latency_ms": m["latency_ms"], "created_at": m["created_at"],
            "citations": citation_map.get(m["id"], []),
            "flags": flag_map.get(m["id"], []),
        })
    return render(request, user, "audit_detail.html", session=dict(session),
                  items=items, flag_types=FLAG_TYPES)


@router.post("/audit/{session_id}/flags")
def add_flag(request: Request, session_id: str, message_id: str = Form(""),
             flag_type: str = Form(""), reason: str = Form(""),
             csrf_token: str = Form(""), user=Depends(require_page("audit:mark")),
             db=Depends(get_db)):
    if not check_csrf(request, csrf_token):
        return redirect(f"/admin/audit/{session_id}", err="页面已过期，请刷新后重试")
    if flag_type not in FLAG_TYPES:
        return redirect(f"/admin/audit/{session_id}", err="标记类型不合法")
    reason = reason.strip()
    if len(reason) < 5:
        return redirect(f"/admin/audit/{session_id}", err="请填写至少 5 个字的标记原因")
    message = db.execute(
        "SELECT * FROM messages WHERE id=? AND session_id=?", (message_id, session_id)
    ).fetchone()
    if not message:
        return redirect(f"/admin/audit/{session_id}", err="消息不存在或不属于该会话")
    db.execute(
        "INSERT INTO conversation_flags"
        " (id, message_id, flag_type, reason, flagged_by, flagged_at)"
        " VALUES (?,?,?,?,?,?)",
        (f"f_{uuid.uuid4().hex[:10]}", message_id, flag_type, reason, user["id"], now_iso()),
    )
    audit(db, user, "audit_flag", "message", message_id,
          f"{FLAG_TYPES[flag_type]}：{reason[:40]}", getattr(request.state, "request_id", ""))
    db.commit()
    return redirect(f"/admin/audit/{session_id}", ok="标记已记录")


@router.post("/audit/flags/{flag_id}/revoke")
def revoke_flag(request: Request, flag_id: str, session_id: str = Form(""),
                reason: str = Form(""), csrf_token: str = Form(""),
                user=Depends(require_page("audit:mark")), db=Depends(get_db)):
    target = f"/admin/audit/{session_id}" if session_id else "/admin/audit"
    if not check_csrf(request, csrf_token):
        return redirect(target, err="页面已过期，请刷新后重试")
    reason = reason.strip()
    if len(reason) < 5:
        return redirect(target, err="撤销标记需填写至少 5 个字的理由")
    flag = db.execute("SELECT * FROM conversation_flags WHERE id=?", (flag_id,)).fetchone()
    if not flag:
        return redirect(target, err="标记不存在")
    if flag["revoked_at"]:
        return redirect(target, err="该标记已撤销")
    db.execute(
        "UPDATE conversation_flags SET revoked_at=?, revoked_by=?, revoke_reason=? WHERE id=?",
        (now_iso(), user["id"], reason, flag_id),
    )
    audit(db, user, "audit_flag_revoke", "conversation_flag", flag_id, reason,
          getattr(request.state, "request_id", ""))
    db.commit()
    return redirect(target, ok="标记已撤销，原记录保留")


@router.get("/releases")
def releases(request: Request, user=Depends(require_page("audit:read")),
             db=Depends(get_db)):
    actions = ("kb_publish", "kb_offline", "kb_submit", "kb_approve",
               "prompt_publish", "prompt_rollback", "index_rebuild")
    rows = db.execute(
        "SELECT * FROM audit_logs WHERE action IN"
        " ('kb_publish','kb_offline','kb_submit','kb_approve',"
        "  'prompt_publish','prompt_rollback','index_rebuild')"
        " ORDER BY created_at DESC LIMIT 100"
    ).fetchall()
    return render(request, user, "releases.html", rows=[dict(r) for r in rows])


@router.get("/api/audit/admin-actions")
def admin_actions(user=Depends(require_api("audit:read")), db=Depends(get_db)):
    rows = db.execute(
        "SELECT * FROM audit_logs ORDER BY created_at DESC LIMIT 50"
    ).fetchall()
    return {"code": "OK", "message": "", "data": [dict(r) for r in rows]}
