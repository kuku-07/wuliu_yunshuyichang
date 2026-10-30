"""模板渲染与页面公共上下文。"""
from __future__ import annotations

from urllib.parse import urlencode

from fastapi import Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from . import config
from .deps import can
from .security import csrf_valid, new_csrf_token

templates = Jinja2Templates(directory=str(config.BASE_DIR / "templates"))

STATUS_TEXT = {
    "draft": "草稿",
    "pending": "待审核",
    "approved": "已批准",
    "active": "已生效",
    "offline": "已下线",
}

FLAG_TYPES = {
    "REDLINE_BYPASS": "红线绕过",
    "UNAUTHORIZED_QUERY": "越权查询",
    "NO_EVIDENCE_SIGN": "未取证签收",
    "UNSIGNED_OUTBOUND": "未签核外发",
    "PII_LEAK": "敏感信息外泄",
}


def status_text(status: str) -> str:
    return STATUS_TEXT.get(status, status)


def flag_text(flag: str) -> str:
    return FLAG_TYPES.get(flag, flag)


def fmt_dt(value: str | None) -> str:
    if not value:
        return "-"
    return value.replace("T", " ")


templates.env.filters["fmt_dt"] = fmt_dt


def render(request: Request, user: dict | None, template_name: str, status_code: int = 200, **ctx):
    """统一注入用户、CSRF、提示消息与权限判断函数。"""
    token = request.cookies.get(config.CSRF_COOKIE) or new_csrf_token()
    context = {
        "request": request,
        "user": user,
        "csrf_token": token,
        "ok": request.query_params.get("ok"),
        "err": request.query_params.get("err"),
        "can": lambda perm: can(user, perm),
        "status_text": status_text,
        "flag_text": flag_text,
        "request_id": getattr(request.state, "request_id", ""),
        **ctx,
    }
    response = templates.TemplateResponse(
        request=request, name=template_name, context=context, status_code=status_code
    )
    if request.cookies.get(config.CSRF_COOKIE) is None:
        response.set_cookie(
            config.CSRF_COOKIE, token, httponly=True, samesite="strict", max_age=8 * 3600, path="/"
        )
    return response


def redirect(url: str, ok: str | None = None, err: str | None = None) -> RedirectResponse:
    """带提示信息的 303 跳转；中文自动 URL 编码。"""
    params = {k: v for k, v in {"ok": ok, "err": err}.items() if v}
    if params:
        url = f"{url}{'&' if '?' in url else '?'}{urlencode(params)}"
    return RedirectResponse(url, status_code=303)


def check_csrf(request: Request, token: str) -> bool:
    return csrf_valid(request.cookies.get(config.CSRF_COOKIE), token)
