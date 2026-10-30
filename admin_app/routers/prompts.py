"""提示词模板：锁定段只读，草稿 → 试跑 → 发布 → 回滚。"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Form, HTTPException, Request

from ..db import now_iso
from ..deps import get_db, require_page
from ..security import locked_hash
from ..services import prompt as prompt_service
from ..services.audit_log import log as audit
from ..web import check_csrf, redirect, render

router = APIRouter(prefix="/admin", tags=["prompts"])


def _template_or_404(db, template_id: str) -> dict:
    row = db.execute("SELECT * FROM prompt_templates WHERE id=?", (template_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="提示词模板不存在")
    return dict(row)


def _latest_draft(db, template_id: str):
    return db.execute(
        "SELECT * FROM prompt_template_versions"
        " WHERE template_id=? AND status='draft' ORDER BY version DESC LIMIT 1",
        (template_id,),
    ).fetchone()


@router.get("/prompts")
def prompts_page(request: Request, user=Depends(require_page("prompt:read")),
                 db=Depends(get_db)):
    template = _template_or_404(db, "pt_001")
    versions = db.execute(
        "SELECT * FROM prompt_template_versions WHERE template_id=? ORDER BY version DESC",
        ("pt_001",),
    ).fetchall()
    draft = _latest_draft(db, "pt_001")
    result = None
    if draft and draft["dry_run_result"]:
        try:
            result = json.loads(draft["dry_run_result"])
        except json.JSONDecodeError:
            result = None
    active = db.execute(
        "SELECT * FROM prompt_template_versions WHERE template_id=? AND version=?",
        ("pt_001", template["active_version"]),
    ).fetchone()
    return render(
        request, user, "prompts.html",
        template=template,
        versions=[dict(v) for v in versions],
        draft=dict(draft) if draft else None,
        active=dict(active) if active else None,
        result=result,
        locked_hash_now=locked_hash(template["locked_section"]),
    )


@router.post("/prompts/{template_id}/draft")
def save_draft(request: Request, template_id: str, editable_section: str = Form(""),
               csrf_token: str = Form(""), user=Depends(require_page("prompt:edit")),
               db=Depends(get_db)):
    if not check_csrf(request, csrf_token):
        return redirect("/admin/prompts", err="页面已过期，请刷新后重试")
    template = _template_or_404(db, template_id)
    editable = editable_section.strip()
    if not editable:
        return redirect("/admin/prompts", err="可编辑段不能为空")

    errors = prompt_service.validate_editable(editable, template["locked_section"])
    if errors:
        return redirect("/admin/prompts", err="；".join(errors))

    draft = _latest_draft(db, template_id)
    now = now_iso()
    if draft:
        db.execute(
            "UPDATE prompt_template_versions SET editable_section=?, dry_run_result=NULL,"
            " dry_run_at=NULL WHERE id=?",
            (editable, draft["id"]),
        )
        version = draft["version"]
    else:
        version = db.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 FROM prompt_template_versions WHERE template_id=?",
            (template_id,),
        ).fetchone()[0]
        db.execute(
            "INSERT INTO prompt_template_versions"
            " (id, template_id, version, locked_hash, editable_section, status, created_by, created_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (f"ptv_{version:03d}_{now[-6:]}", template_id, version,
             locked_hash(template["locked_section"]), editable, "draft", user["id"], now),
        )
    audit(db, user, "prompt_draft", "prompt_template", template_id,
          f"保存草稿 v{version}", getattr(request.state, "request_id", ""))
    db.commit()
    return redirect("/admin/prompts", ok=f"草稿 v{version} 已保存，请试跑")


@router.post("/prompts/{template_id}/validate")
def validate(request: Request, template_id: str, csrf_token: str = Form(""),
             user=Depends(require_page("prompt:edit")), db=Depends(get_db)):
    if not check_csrf(request, csrf_token):
        return redirect("/admin/prompts", err="页面已过期，请刷新后重试")
    template = _template_or_404(db, template_id)
    draft = _latest_draft(db, template_id)
    if not draft:
        return redirect("/admin/prompts", err="没有草稿，请先保存")
    if draft["locked_hash"] != locked_hash(template["locked_section"]):
        return redirect("/admin/prompts", err="锁定段哈希不一致，草稿已失效，请重新保存")
    errors = prompt_service.validate_editable(draft["editable_section"], template["locked_section"])
    if errors:
        return redirect("/admin/prompts", err="；".join(errors))
    return redirect("/admin/prompts", ok="结构校验通过")


@router.post("/prompts/{template_id}/dry-run")
def dry_run(request: Request, template_id: str, csrf_token: str = Form(""),
            user=Depends(require_page("prompt:edit")), db=Depends(get_db)):
    if not check_csrf(request, csrf_token):
        return redirect("/admin/prompts", err="页面已过期，请刷新后重试")
    template = _template_or_404(db, template_id)
    draft = _latest_draft(db, template_id)
    if not draft:
        return redirect("/admin/prompts", err="没有草稿，请先保存")
    if draft["locked_hash"] != locked_hash(template["locked_section"]):
        return redirect("/admin/prompts", err="锁定段哈希不一致，请重新保存草稿")

    result = prompt_service.dry_run(db, draft["editable_section"], template["locked_section"])
    db.execute(
        "UPDATE prompt_template_versions SET dry_run_result=?, dry_run_at=? WHERE id=?",
        (json.dumps(result, ensure_ascii=False), result["at"], draft["id"]),
    )
    audit(db, user, "prompt_dry_run", "prompt_template", template_id,
          f"试跑 v{draft['version']}：{result['passed']}/{result['total']}",
          getattr(request.state, "request_id", ""))
    db.commit()
    ok, reason = prompt_service.publish_ready(result)
    if ok:
        return redirect("/admin/prompts", ok=f"试跑通过 {result['passed']}/{result['total']}")
    return redirect("/admin/prompts", err=reason)


@router.post("/prompts/{template_id}/publish")
def publish(request: Request, template_id: str, csrf_token: str = Form(""),
            user=Depends(require_page("prompt:publish")), db=Depends(get_db)):
    if not check_csrf(request, csrf_token):
        return redirect("/admin/prompts", err="页面已过期，请刷新后重试")
    template = _template_or_404(db, template_id)
    draft = _latest_draft(db, template_id)
    if not draft:
        return redirect("/admin/prompts", err="没有待发布草稿")
    if draft["locked_hash"] != locked_hash(template["locked_section"]):
        return redirect("/admin/prompts", err="锁定段哈希不一致，禁止发布")
    result = json.loads(draft["dry_run_result"]) if draft["dry_run_result"] else None
    ok, reason = prompt_service.publish_ready(result)
    if not ok:
        return redirect("/admin/prompts", err=reason)
    if draft["dry_run_at"]:
        try:
            elapsed = datetime.now() - datetime.fromisoformat(draft["dry_run_at"])
            if elapsed > timedelta(hours=24):
                return redirect("/admin/prompts", err="试跑已超过 24 小时，请重新试跑")
        except ValueError:
            return redirect("/admin/prompts", err="试跑时间无效，请重新试跑")
    else:
        return redirect("/admin/prompts", err="缺少试跑记录，请先试跑")
    if draft["created_by"] == user["id"]:
        return redirect("/admin/prompts", err="草稿创建人与发布人不能为同一人")

    now = now_iso()
    db.execute(
        "UPDATE prompt_templates SET editable_section=?, active_version=?, updated_at=? WHERE id=?",
        (draft["editable_section"], draft["version"], now, template_id),
    )
    db.execute(
        "UPDATE prompt_template_versions SET status='published', published_by=?,"
        " published_at=? WHERE id=?",
        (user["id"], now, draft["id"]),
    )
    audit(db, user, "prompt_publish", "prompt_template", template_id,
          f"发布 v{draft['version']}", getattr(request.state, "request_id", ""))
    db.commit()
    return redirect("/admin/prompts", ok=f"已发布 v{draft['version']}，问答立即生效")


@router.post("/prompts/{template_id}/rollback")
def rollback(request: Request, template_id: str, version: int = Form(...),
             csrf_token: str = Form(""), user=Depends(require_page("prompt:publish")),
             db=Depends(get_db)):
    if not check_csrf(request, csrf_token):
        return redirect("/admin/prompts", err="页面已过期，请刷新后重试")
    target = db.execute(
        "SELECT * FROM prompt_template_versions WHERE template_id=? AND version=?",
        (template_id, version),
    ).fetchone()
    if not target:
        return redirect("/admin/prompts", err="目标版本不存在")
    db.execute(
        "UPDATE prompt_templates SET editable_section=?, active_version=?, updated_at=? WHERE id=?",
        (target["editable_section"], version, now_iso(), template_id),
    )
    audit(db, user, "prompt_rollback", "prompt_template", template_id,
          f"回滚到 v{version}", getattr(request.state, "request_id", ""))
    db.commit()
    return redirect("/admin/prompts", ok=f"已回滚到 v{version}")
