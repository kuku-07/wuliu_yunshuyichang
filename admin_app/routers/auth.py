"""登录、登出、当前用户。"""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Form, Request

from .. import config
from ..db import connect, now_iso
from ..deps import current_user, get_db, require_api, require_page
from ..security import create_access_token, verify_password
from ..services.audit_log import log as audit
from ..web import check_csrf, redirect, render

router = APIRouter(prefix="/admin", tags=["auth"])


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


@router.get("/login")
def login_page(request: Request, db=Depends(get_db)):
    if current_user(request, db):
        return redirect("/admin/kb")
    return render(request, None, "login.html")


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

    row = db.execute(
        "SELECT * FROM admin_users WHERE employee_no=?", (employee_no.strip(),)
    ).fetchone()
    generic = "账号或密码不正确"
    if not row:
        return redirect("/admin/login", err=generic)

    if row["locked_until"]:
        try:
            locked = datetime.fromisoformat(row["locked_until"])
            if locked > datetime.now():
                return redirect("/admin/login", err="账号已锁定，请 15 分钟后再试")
        except ValueError:
            pass

    if row["status"] != "active":
        return redirect("/admin/login", err="该账号已停用，请联系系统管理员")

    if not verify_password(row["password_hash"], password):
        message = _login_failure(db, row, generic)
        audit(db, None, "login_failed", "admin_user", row["id"],
              f"登录失败：{employee_no}", getattr(request.state, "request_id", ""))
        db.commit()
        return redirect("/admin/login", err=message)

    db.execute(
        "UPDATE admin_users SET failed_count=0, locked_until=NULL WHERE id=?", (row["id"],)
    )
    audit(db, {"id": row["id"], "name": row["name"]}, "login_success", "admin_user",
          row["id"], "", getattr(request.state, "request_id", ""))
    db.commit()

    lanes = []
    try:
        import json
        lanes = json.loads(row["lane_scopes"] or "[]")
    except Exception:
        lanes = []
    token = create_access_token(row["id"], row["role"], lanes)
    response = redirect("/admin/kb", ok="登录成功")
    response.set_cookie(
        config.COOKIE_NAME, token, httponly=True, samesite="strict",
        max_age=config.TOKEN_TTL_MINUTES * 60, path="/",
    )
    return response


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
    response = redirect("/admin/login", ok="已退出登录")
    response.delete_cookie(config.COOKIE_NAME, path="/")
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
