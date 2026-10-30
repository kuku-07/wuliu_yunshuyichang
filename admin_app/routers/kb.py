"""规则知识库：上传、审核、发布、下线、版本对比、索引切换。"""
from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from .. import config
from ..db import now_iso
from ..deps import get_db, require_api, require_page
from ..security import mask_pii, sha256_text
from ..services import kb as kb_service
from ..services.audit_log import log as audit
from ..web import check_csrf, redirect, render

router = APIRouter(prefix="/admin", tags=["kb"])

ALLOWED_MIME = {
    "text/markdown", "text/plain", "application/pdf", "application/octet-stream",
    "text/x-markdown",
}


def _doc_or_404(db, doc_id: str) -> dict:
    row = db.execute("SELECT * FROM kb_documents WHERE id=?", (doc_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="规则文档不存在或已删除")
    return dict(row)


@router.get("/kb")
def kb_list(
    request: Request,
    status: str = "",
    lane: str = "",
    keyword: str = "",
    user=Depends(require_page("kb:read")),
    db=Depends(get_db),
):
    clauses, params = [], []
    if status:
        clauses.append("d.status = ?")
        params.append(status)
    if lane:
        clauses.append("d.lane_scope = ?")
        params.append(lane)
    if keyword:
        clauses.append("(d.title LIKE ? OR d.id LIKE ?)")
        params.extend([f"%{keyword}%", f"%{keyword}%"])
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    docs = db.execute(
        f"""
        SELECT d.*,
               (SELECT COUNT(*) FROM kb_chunks c WHERE c.doc_id=d.id AND c.version=d.current_version) AS chunk_count,
               (SELECT COUNT(*) FROM kb_chunks c WHERE c.doc_id=d.id AND c.is_active=1) AS active_count
        FROM kb_documents d {where}
        ORDER BY d.updated_at DESC
        """,
        params,
    ).fetchall()
    lanes = [r[0] for r in db.execute("SELECT DISTINCT lane_scope FROM kb_documents").fetchall()]
    return render(
        request, user, "kb_list.html",
        docs=[dict(r) for r in docs], lanes=lanes,
        filter_status=status, filter_lane=lane, keyword=keyword,
    )


@router.get("/kb/upload")
def upload_page(request: Request, user=Depends(require_page("kb:edit"))):
    return render(request, user, "kb_upload.html", today=datetime.now().strftime("%Y-%m-%d"))


@router.post("/kb/upload")
async def upload_submit(
    request: Request,
    title: str = Form(""),
    lane_scope: str = Form(""),
    effective_from: str = Form(""),
    csrf_token: str = Form(""),
    file: UploadFile = File(...),
    user=Depends(require_page("kb:edit")),
    db=Depends(get_db),
):
    if not check_csrf(request, csrf_token):
        return redirect("/admin/kb/upload", err="页面已过期，请刷新后重试")

    title = title.strip()
    lane_scope = lane_scope.strip()
    if not title or not lane_scope:
        return redirect("/admin/kb/upload", err="标题与适用线路不能为空")
    if effective_from:
        try:
            datetime.strptime(effective_from, "%Y-%m-%d")
        except ValueError:
            return redirect("/admin/kb/upload", err="生效日期格式应为 YYYY-MM-DD")

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in config.ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=415, detail="仅支持 .md 和 .pdf 文件")
    if (file.content_type or "") not in ALLOWED_MIME:
        raise HTTPException(status_code=415, detail="文件类型校验未通过，仅支持 .md 和 .pdf")

    data = await file.read()
    if len(data) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="文件超过 20MB，请拆分后上传")
    if not data:
        return redirect("/admin/kb/upload", err="文件为空，请重新选择")

    try:
        text = kb_service.parse_document(file.filename or "", data)
    except kb_service.PdfWithoutText as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        return redirect("/admin/kb/upload", err=str(exc))

    chunks = kb_service.chunk_text(text)
    if not chunks:
        return redirect("/admin/kb/upload", err="未解析出有效切片，请检查文档内容")
    chunks, pii_hits = kb_service.mask_all(chunks)

    existing = db.execute(
        "SELECT * FROM kb_documents WHERE title=? AND lane_scope=? ORDER BY updated_at DESC LIMIT 1",
        (title, lane_scope),
    ).fetchone()
    if existing and existing["status"] in ("pending", "approved"):
        return redirect(f"/admin/kb/{existing['id']}", err="该规则已有待审或已批准版本，请先处理")
    if existing and existing["status"] == "draft":
        return redirect(f"/admin/kb/{existing['id']}", err="该规则已有草稿，请编辑或删除后再上传")

    now = now_iso()
    if existing:
        doc_id = existing["id"]
        version = kb_service.next_version(existing["current_version"])
        db.execute(
            "UPDATE kb_documents SET status='draft', current_version=?, submitted_by=NULL,"
            " approved_by=NULL, pii_masked=?, effective_from=?, updated_at=? WHERE id=?",
            (version, pii_hits, effective_from or existing["effective_from"], now, doc_id),
        )
        change_note = "新上传版本"
    else:
        doc_id = f"doc_{uuid.uuid4().hex[:10]}"
        version = "0.1"
        db.execute(
            "INSERT INTO kb_documents"
            " (id, title, lane_scope, status, current_version, active_version, effective_from,"
            "  submitted_by, approved_by, pii_masked, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (doc_id, title, lane_scope, "draft", version, None, effective_from or None,
             None, None, pii_hits, now, now),
        )
        change_note = "首版草稿"

    content_hash = sha256_text("\n".join(f"{c['section']}|{c['text']}" for c in chunks))
    db.execute(
        "INSERT INTO kb_document_versions"
        " (id, doc_id, version, content_hash, change_note, created_at)"
        " VALUES (?,?,?,?,?,?)",
        (f"kbv_{uuid.uuid4().hex[:10]}", doc_id, version, content_hash, change_note, now),
    )
    for idx, chunk in enumerate(chunks, start=1):
        db.execute(
            "INSERT INTO kb_chunks"
            " (id, doc_id, version, chunk_no, section, text, token_count, is_active, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (f"chk_{uuid.uuid4().hex[:10]}", doc_id, version, idx,
             chunk["section"], chunk["text"], len(chunk["text"]), 0, now),
        )

    stored = f"{uuid.uuid4().hex}{suffix}"
    (config.UPLOAD_DIR / stored).write_bytes(data)
    audit(db, user, "kb_upload", "kb_document", doc_id,
          f"{title} v{version}，切片 {len(chunks)}，脱敏 {pii_hits} 处",
          getattr(request.state, "request_id", ""))
    db.commit()
    return redirect(f"/admin/kb/{doc_id}", ok=f"已生成草稿 v{version}，请检查切片后提交审核")


@router.get("/kb/{doc_id}")
def kb_detail(request: Request, doc_id: str, user=Depends(require_page("kb:read")),
              db=Depends(get_db)):
    doc = _doc_or_404(db, doc_id)
    chunks = db.execute(
        "SELECT * FROM kb_chunks WHERE doc_id=? AND version=? ORDER BY chunk_no",
        (doc_id, doc["current_version"]),
    ).fetchall()
    versions = db.execute(
        "SELECT * FROM kb_document_versions WHERE doc_id=? ORDER BY created_at DESC", (doc_id,)
    ).fetchall()
    conflicts = kb_service.find_conflicts(db, doc_id, doc["current_version"]) if doc["active_version"] else []
    submitter = db.execute("SELECT name FROM admin_users WHERE id=?", (doc["submitted_by"],)).fetchone()
    approver = db.execute("SELECT name FROM admin_users WHERE id=?", (doc["approved_by"],)).fetchone()
    return render(
        request, user, "kb_detail.html",
        doc=doc, chunks=[dict(c) for c in chunks], versions=[dict(v) for v in versions],
        conflicts=conflicts,
        submitter_name=submitter[0] if submitter else "-",
        approver_name=approver[0] if approver else "-",
        active_chunks=db.execute(
            "SELECT COUNT(*) FROM kb_chunks WHERE doc_id=? AND is_active=1", (doc_id,)
        ).fetchone()[0],
    )


@router.post("/kb/{doc_id}/submit-review")
def submit_review(request: Request, doc_id: str, csrf_token: str = Form(""),
                  user=Depends(require_page("kb:submit")), db=Depends(get_db)):
    if not check_csrf(request, csrf_token):
        return redirect(f"/admin/kb/{doc_id}", err="页面已过期，请刷新后重试")
    doc = _doc_or_404(db, doc_id)
    if doc["status"] != "draft":
        return redirect(f"/admin/kb/{doc_id}", err="只有草稿可以提交审核")
    count = db.execute(
        "SELECT COUNT(*) FROM kb_chunks WHERE doc_id=? AND version=?",
        (doc_id, doc["current_version"]),
    ).fetchone()[0]
    if count == 0:
        return redirect(f"/admin/kb/{doc_id}", err="当前版本没有切片，无法提交")
    db.execute(
        "UPDATE kb_documents SET status='pending', submitted_by=?, updated_at=? WHERE id=?",
        (user["id"], now_iso(), doc_id),
    )
    audit(db, user, "kb_submit", "kb_document", doc_id, f"v{doc['current_version']} 提交审核",
          getattr(request.state, "request_id", ""))
    db.commit()
    return redirect(f"/admin/kb/{doc_id}", ok="已提交审核，草稿已锁定")


@router.post("/kb/{doc_id}/approve")
def approve(request: Request, doc_id: str, csrf_token: str = Form(""),
            user=Depends(require_page("kb:approve")), db=Depends(get_db)):
    if not check_csrf(request, csrf_token):
        return redirect(f"/admin/kb/{doc_id}", err="页面已过期，请刷新后重试")
    doc = _doc_or_404(db, doc_id)
    if doc["status"] != "pending":
        return redirect(f"/admin/kb/{doc_id}", err="只有待审版本可以批准")
    if doc["submitted_by"] == user["id"]:
        return redirect(f"/admin/kb/{doc_id}", err="提交人与批准人不能为同一人")
    db.execute(
        "UPDATE kb_documents SET status='approved', approved_by=?, updated_at=? WHERE id=?",
        (user["id"], now_iso(), doc_id),
    )
    audit(db, user, "kb_approve", "kb_document", doc_id, f"v{doc['current_version']} 批准",
          getattr(request.state, "request_id", ""))
    db.commit()
    return redirect(f"/admin/kb/{doc_id}", ok="已批准，等待另一位主管发布")


@router.post("/kb/{doc_id}/publish")
def publish(request: Request, doc_id: str, csrf_token: str = Form(""),
            user=Depends(require_page("kb:publish")), db=Depends(get_db)):
    if not check_csrf(request, csrf_token):
        return redirect(f"/admin/kb/{doc_id}", err="页面已过期，请刷新后重试")
    doc = _doc_or_404(db, doc_id)
    if doc["status"] != "approved":
        return redirect(f"/admin/kb/{doc_id}", err="只有已批准版本可以发布")
    if not doc["approved_by"]:
        return redirect(f"/admin/kb/{doc_id}", err="缺少批准人，不能发布")
    if doc["approved_by"] == user["id"]:
        return redirect(f"/admin/kb/{doc_id}", err="发布人与批准人不能为同一人")
    count = db.execute(
        "SELECT COUNT(*) FROM kb_chunks WHERE doc_id=? AND version=?",
        (doc_id, doc["current_version"]),
    ).fetchone()[0]
    if count == 0:
        return redirect(f"/admin/kb/{doc_id}", err="当前版本没有切片，无法发布")

    now = now_iso()
    db.execute("UPDATE kb_chunks SET is_active=0 WHERE doc_id=?", (doc_id,))
    db.execute(
        "UPDATE kb_chunks SET is_active=1 WHERE doc_id=? AND version=?",
        (doc_id, doc["current_version"]),
    )
    effective = doc["effective_from"] or now[:10]
    db.execute(
        "UPDATE kb_documents SET status='active', active_version=?, effective_from=?, updated_at=?"
        " WHERE id=?",
        (doc["current_version"], effective, now, doc_id),
    )
    db.execute(
        "UPDATE kb_document_versions SET published_at=?, published_by=? WHERE doc_id=? AND version=?",
        (now, user["id"], doc_id, doc["current_version"]),
    )
    _refresh_index_state(db)
    audit(db, user, "kb_publish", "kb_document", doc_id,
          f"发布 v{doc['current_version']}，生效 {effective}",
          getattr(request.state, "request_id", ""))
    db.commit()
    return redirect(f"/admin/kb/{doc_id}", ok=f"已发布 v{doc['current_version']}，检索已切换")


@router.post("/kb/{doc_id}/offline")
def offline(request: Request, doc_id: str, csrf_token: str = Form(""),
            user=Depends(require_page("kb:offline")), db=Depends(get_db)):
    if not check_csrf(request, csrf_token):
        return redirect(f"/admin/kb/{doc_id}", err="页面已过期，请刷新后重试")
    doc = _doc_or_404(db, doc_id)
    if doc["status"] != "active":
        return redirect(f"/admin/kb/{doc_id}", err="只有已生效规则可以下线")
    db.execute("UPDATE kb_chunks SET is_active=0 WHERE doc_id=?", (doc_id,))
    db.execute("UPDATE kb_documents SET status='offline', updated_at=? WHERE id=?",
               (now_iso(), doc_id))
    _refresh_index_state(db)
    audit(db, user, "kb_offline", "kb_document", doc_id,
          f"下线 v{doc['active_version']}", getattr(request.state, "request_id", ""))
    db.commit()
    return redirect(f"/admin/kb/{doc_id}", ok="已下线，历史版本仍保留可查")


@router.post("/kb/{doc_id}/delete")
def delete_draft(request: Request, doc_id: str, csrf_token: str = Form(""),
                 user=Depends(require_page("kb:edit")), db=Depends(get_db)):
    if not check_csrf(request, csrf_token):
        return redirect(f"/admin/kb/{doc_id}", err="页面已过期，请刷新后重试")
    doc = _doc_or_404(db, doc_id)
    if doc["status"] != "draft" or doc["active_version"]:
        return redirect(f"/admin/kb/{doc_id}", err="已生效规则不可删除，请使用下线")
    db.execute("DELETE FROM kb_chunks WHERE doc_id=?", (doc_id,))
    db.execute("DELETE FROM kb_document_versions WHERE doc_id=?", (doc_id,))
    db.execute("DELETE FROM kb_documents WHERE id=?", (doc_id,))
    audit(db, user, "kb_delete_draft", "kb_document", doc_id,
          f"删除草稿 v{doc['current_version']}", getattr(request.state, "request_id", ""))
    db.commit()
    return redirect("/admin/kb", ok="草稿已删除")


@router.post("/kb/{doc_id}/chunks/{chunk_id}")
def edit_chunk(request: Request, doc_id: str, chunk_id: str, text: str = Form(""),
               csrf_token: str = Form(""), user=Depends(require_page("kb:edit")),
               db=Depends(get_db)):
    if not check_csrf(request, csrf_token):
        return redirect(f"/admin/kb/{doc_id}", err="页面已过期，请刷新后重试")
    doc = _doc_or_404(db, doc_id)
    if doc["status"] != "draft":
        return redirect(f"/admin/kb/{doc_id}", err="只有草稿可以编辑切片")
    text = text.strip()
    if len(text) < 20:
        return redirect(f"/admin/kb/{doc_id}", err="切片内容少于 20 字")
    masked, hits = mask_pii(text)
    db.execute(
        "UPDATE kb_chunks SET text=?, token_count=?, is_active=0 WHERE id=? AND doc_id=?",
        (masked, len(masked), chunk_id, doc_id),
    )
    if hits:
        db.execute("UPDATE kb_documents SET pii_masked=pii_masked+? WHERE id=?", (hits, doc_id))
    audit(db, user, "kb_edit_chunk", "kb_chunk", chunk_id,
          f"编辑切片，脱敏 {hits} 处", getattr(request.state, "request_id", ""))
    db.commit()
    return redirect(f"/admin/kb/{doc_id}", ok="切片已更新")


@router.get("/kb/{doc_id}/diff")
def diff(request: Request, doc_id: str, from_v: str = "", to_v: str = "",
         user=Depends(require_page("kb:read")), db=Depends(get_db)):
    doc = _doc_or_404(db, doc_id)
    versions = [r[0] for r in db.execute(
        "SELECT DISTINCT version FROM kb_chunks WHERE doc_id=? ORDER BY version", (doc_id,)
    ).fetchall()]
    if not versions:
        return redirect(f"/admin/kb/{doc_id}", err="该文档没有可对比的版本")
    old_v = from_v or (doc["active_version"] or versions[0])
    new_v = to_v or doc["current_version"]
    if old_v not in versions or new_v not in versions:
        return redirect(f"/admin/kb/{doc_id}", err="所选版本不存在")

    def grouped(version: str) -> dict[str, str]:
        rows = db.execute(
            "SELECT section, text FROM kb_chunks WHERE doc_id=? AND version=? ORDER BY chunk_no",
            (doc_id, version),
        ).fetchall()
        result: dict[str, list[str]] = {}
        for row in rows:
            result.setdefault(row["section"], []).append(row["text"])
        return {k: "\n".join(v) for k, v in result.items()}

    old, new = grouped(old_v), grouped(new_v)
    rows = []
    for section in sorted(set(old) | set(new)):
        old_text, new_text = old.get(section, ""), new.get(section, "")
        if not old_text:
            state = "新增"
        elif not new_text:
            state = "移除"
        elif old_text != new_text:
            state = "修改"
        else:
            state = "未变"
        rows.append({"section": section, "old": old_text, "new": new_text, "state": state})
    return render(request, user, "kb_diff.html", doc=doc, versions=versions,
                  old_v=old_v, new_v=new_v, rows=rows)


# ---------- 索引 ----------
def _refresh_index_state(db) -> None:
    db.execute(
        """
        UPDATE kb_chunks SET is_active = CASE WHEN EXISTS (
            SELECT 1 FROM kb_documents d
            WHERE d.id = kb_chunks.doc_id AND d.status='active' AND d.active_version = kb_chunks.version
        ) THEN 1 ELSE 0 END
        """
    )
    count = db.execute("SELECT COUNT(*) FROM kb_chunks WHERE is_active=1").fetchone()[0]
    db.execute("UPDATE kb_index_state SET last_rebuild=?, active_chunks=?, note=? WHERE id=1",
               (now_iso(), count, "按生效版本重算"))


@router.get("/api/kb/index/status")
def index_status(user=Depends(require_api("kb:read")), db=Depends(get_db)):
    state = db.execute("SELECT * FROM kb_index_state WHERE id=1").fetchone()
    return {
        "code": "OK", "message": "",
        "data": {
            "active_chunks": state["active_chunks"],
            "last_rebuild": state["last_rebuild"],
            "docs": db.execute("SELECT COUNT(*) FROM kb_documents").fetchone()[0],
            "active_docs": db.execute(
                "SELECT COUNT(*) FROM kb_documents WHERE status='active'"
            ).fetchone()[0],
        },
    }


@router.post("/api/kb/index/rebuild")
def index_rebuild(request: Request, user=Depends(require_api("index:rebuild")),
                  db=Depends(get_db)):
    _refresh_index_state(db)
    count = db.execute("SELECT COUNT(*) FROM kb_chunks WHERE is_active=1").fetchone()[0]
    audit(db, user, "index_rebuild", "kb_index", "1", f"重建索引，生效切片 {count}",
          getattr(request.state, "request_id", ""))
    db.commit()
    return {"code": "OK", "message": "索引已重建", "data": {"active_chunks": count}}
