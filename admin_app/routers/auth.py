"""登录、登出、当前用户。"""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse

from .. import config
from ..db import connect, now_iso
from ..deps import current_user, get_db, require_api, require_page
from ..deps import PERMS
from ..security import create_access_token, verify_password
from ..services.audit_log import log as audit
from ..web import check_csrf, redirect, render

router = APIRouter(prefix="/admin", tags=["auth"])
public_router = APIRouter(tags=["auth"])

ADMIN_PERMS = {
    "kb:read", "kb:edit", "kb:approve", "kb:publish", "kb:offline",
    "prompt:read", "prompt:edit", "prompt:publish",
    "audit:read", "audit:mark", "audit:export", "ops:read", "ops:act",
    "index:rebuild", "users:manage",
}
PORTAL_ROLES = {"customer", "carrier"}


def _login_failure(conn, row, message: str):
    """失败计数 + 5 次锁定 15 分钟。"""
    if row is None:
        return message
    failed = int(row["failed_count"]) + 1
    if failed >= 5:
        locked_until = (datetime.now() + timedelta(minutes=15)).strftime("%Y-%m-%dT%H:%M:%S")
        conn.execute(
            "UPDATE admin_users SET failed_count=?, locked_until=? WHERE id=?",
            (failed, locked_until, row["id"]),
        )
        return "账号已锁定，请 15 分钟后再试"
    conn.execute("UPDATE admin_users SET failed_count=? WHERE id=?", (failed, row["id"]))
    return message


def _verify_login(request: Request, db, employee_no: str, password: str):
    """校验账号密码；返回 (用户行, 错误信息)。失败会累计锁定计数。"""
    row = db.execute(
        "SELECT * FROM admin_users WHERE employee_no=?", (employee_no.strip(),)
    ).fetchone()
    generic = "账号或密码不正确"
    if not row:
        return None, generic

    if row["locked_until"]:
        try:
            if datetime.fromisoformat(row["locked_until"]) > datetime.now():
                return None, "账号已锁定，请 15 分钟后再试"
        except ValueError:
            pass
    if row["status"] != "active":
        return None, "该账号已停用，请联系系统管理员"
    if not verify_password(row["password_hash"], password):
        message = _login_failure(db, row, generic)
        audit(db, None, "login_failed", "admin_user", row["id"],
              f"登录失败：{employee_no}", getattr(request.state, "request_id", ""))
        db.commit()
        return None, message

    db.execute(
        "UPDATE admin_users SET failed_count=0, locked_until=NULL WHERE id=?", (row["id"],)
    )
    audit(db, {"id": row["id"], "name": row["name"]}, "login_success", "admin_user",
          row["id"], "", getattr(request.state, "request_id", ""))
    db.commit()
    return row, ""


def _landing(row, entry: str) -> str:
    """按「账号角色 + 点击的入口」决定落地页；空串表示该入口无权限。"""
    role = row["role"]
    perms = PERMS.get(role, set())
    if role in PORTAL_ROLES:
        return "/portal"
    if entry == "staff" and "agent:use" in perms:
        return "/agent"
    if entry == "admin":
        if perms & ADMIN_PERMS:
            return "/admin/todos" if "kb:read" not in perms else "/admin/kb"
    return ""


def _issue(row, target: str):
    import json

    try:
        lanes = json.loads(row["lane_scopes"] or "[]")
    except Exception:
        lanes = []
    token = create_access_token(
        row["id"], row["role"], lanes, scopes=sorted(PERMS.get(row["role"], set()))
    )
    response = redirect(target, ok="登录成功")
    response.set_cookie(
        config.COOKIE_NAME, token, httponly=True, samesite="strict",
        secure=config.COOKIE_SECURE,
        max_age=config.TOKEN_TTL_MINUTES * 60, path="/",
    )
    return response


@router.get("/login")
def login_page(request: Request, db=Depends(get_db)):
    user = current_user(request, db)
    if user:
        return redirect(_landing(user, "admin") or "/agent")
    return render(request, None, "login.html")


@public_router.get("/login")
def staff_login_page(request: Request, db=Depends(get_db)):
    user = current_user(request, db)
    if user:
        return redirect(_landing(user, "staff") or "/portal")
    return render(request, None, "login_staff.html")


@public_router.post("/login")
def staff_login_submit(
    request: Request,
    employee_no: str = Form(""),
    password: str = Form(""),
    csrf_token: str = Form(""),
    db=Depends(get_db),
):
    if not check_csrf(request, csrf_token):
        return redirect("/login", err="页面已过期，请刷新后重试")
    row, error = _verify_login(request, db, employee_no, password)
    if error:
        return redirect("/login", err=error)
    target = _landing(row, "staff")
    if not target:
        return redirect("/login", err="该账号没有员工端权限，请从管理端登录")
    return _issue(row, target)


@router.post("/login")
def login_submit(
    request: Request,
    employee_no: str = Form(""),
    password: str = Form(""),
    csrf_token: str = Form(""),
    db=Depends(get_db),
):
    if not check_csrf(request, csrf_token):
        return redirect("/admin/login", err="页面已过期，请刷新后重试")

    row, error = _verify_login(request, db, employee_no, password)
    if error:
        return redirect("/admin/login", err=error)

    target = _landing(row, "admin")
    if not target:
        return redirect(
            "/admin/login", err="该账号没有管理后台权限，请从员工端登录"
        )
    return _issue(row, target)


@router.post("/logout")
def logout(
    request: Request,
    csrf_token: str = Form(""),
    user=Depends(require_page()),
    db=Depends(get_db),
):
    if not check_csrf(request, csrf_token):
        return redirect("/admin/kb", err="页面已过期，请刷新后重试")
    audit(db, user, "logout", "admin_user", user["id"], "",
          getattr(request.state, "request_id", ""))
    db.commit()
    perms = PERMS.get(user["role"], set())
    back = "/admin/login" if perms & ADMIN_PERMS else "/login"
    response = redirect(back, ok="已退出登录")
    response.delete_cookie(config.COOKIE_NAME, path="/")
    return response


@router.post("/auth/refresh")
def refresh(
    request: Request,
    csrf_token: str = Form(""),
    user=Depends(require_api()),
    db=Depends(get_db),
):
    """续期：换发新 token（新 jti），旧 token 到期自然失效。"""
    submitted = csrf_token or request.headers.get("X-CSRF-Token", "")
    if not check_csrf(request, submitted):
        raise HTTPException(status_code=403, detail="页面已过期，请刷新后重试")

    token = create_access_token(
        user["id"], user["role"], user.get("lanes") or [],
        scopes=sorted(PERMS.get(user["role"], set())),
    )
    audit(db, user, "auth_refresh", "admin_user", user["id"], "续期会话",
          getattr(request.state, "request_id", ""))
    db.commit()

    response = JSONResponse({
        "code": "OK",
        "message": "",
        "data": {"expires_in": config.TOKEN_TTL_MINUTES * 60, "role": user["role"]},
        "request_id": getattr(request.state, "request_id", ""),
    })
    response.set_cookie(
        config.COOKIE_NAME, token, httponly=True, samesite="strict",
        max_age=config.TOKEN_TTL_MINUTES * 60, path="/",
    )
    return response


@router.get("/api/me")
def me(user=Depends(require_api())):
    return {
        "code": "OK",
        "message": "",
        "data": {
            "id": user["id"],
            "name": user["name"],
            "role": user["role"],
            "role_name": user["role_name"],
            "lanes": user["lanes"],
        },
        "request_id": "",
    }
