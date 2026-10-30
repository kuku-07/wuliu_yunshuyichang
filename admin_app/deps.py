"""请求依赖：数据库连接、当前用户、角色权限。"""
from __future__ import annotations

import json
import sqlite3
from typing import Callable

from fastapi import Depends, HTTPException, Request

from . import config
from .db import connect
from .security import decode_access_token


class LoginRequired(Exception):
    """页面未登录：交给全局处理器跳转登录页。"""


class Forbidden(Exception):
    """页面越权：交给全局处理器渲染 403。"""


PERMS: dict[str, set[str]] = {
    "rule_admin": {"kb:read", "kb:edit", "kb:submit", "prompt:read", "prompt:edit", "audit:read"},
    "supervisor": {
        "kb:read", "kb:approve", "kb:publish", "kb:offline",
        "prompt:read", "prompt:edit", "prompt:publish",
        "audit:read", "audit:mark", "audit:export",
    },
    "auditor": {"kb:read", "prompt:read", "audit:read", "audit:mark", "audit:export"},
    "sys_admin": {"kb:read", "prompt:read", "audit:read", "index:rebuild", "users:manage"},
}

ROLE_NAMES = {
    "rule_admin": "规则管理员",
    "supervisor": "客服主管",
    "auditor": "合规审计",
    "sys_admin": "系统管理员",
}


def can(user: dict | None, perm: str) -> bool:
    if not user:
        return False
    return perm in PERMS.get(user.get("role", ""), set())


def get_db():
    """每个请求一个 SQLite 连接，请求结束关闭。"""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


def current_user(request: Request, db: sqlite3.Connection) -> dict | None:
    token = request.cookies.get(config.COOKIE_NAME)
    if not token:
        return None
    payload = decode_access_token(token)
    if not payload:
        return None
    row = db.execute(
        "SELECT * FROM admin_users WHERE id = ? AND status = 'active'", (payload.get("sub"),)
    ).fetchone()
    if not row:
        return None
    user = dict(row)
    try:
        user["lanes"] = json.loads(user.get("lane_scopes") or "[]")
    except json.JSONDecodeError:
        user["lanes"] = []
    user["role_name"] = ROLE_NAMES.get(user["role"], user["role"])
    return user


def require_page(perm: str | None = None) -> Callable:
    """页面依赖：未登录跳转，越权渲染 403。"""

    def dependency(request: Request, db: sqlite3.Connection = Depends(get_db)) -> dict:
        user = current_user(request, db)
        if not user:
            raise LoginRequired()
        if perm and not can(user, perm):
            raise Forbidden()
        return user

    return dependency


def require_api(perm: str | None = None) -> Callable:
    """接口依赖：返回 JSON 错误码，不跳转。"""

    def dependency(request: Request, db: sqlite3.Connection = Depends(get_db)) -> dict:
        user = current_user(request, db)
        if not user:
            raise HTTPException(status_code=401, detail="未登录或登录已过期，请重新登录")
        if perm and not can(user, perm):
            raise HTTPException(status_code=403, detail="当前角色无权执行该操作")
        return user

    return dependency
