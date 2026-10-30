"""FastAPI 应用入口：中间件、异常处理、路由装配。"""
from __future__ import annotations

import logging
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import config, db
from .deps import Forbidden, LoginRequired
from .routers import audit, auth, kb, prompts
from .web import render

logger = logging.getLogger("admin")

CODE_BY_STATUS = {
    400: "INVALID_REQUEST",
    401: "UNAUTHENTICATED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
    413: "UPLOAD_TOO_LARGE",
    415: "UNSUPPORTED_FILE",
    422: "INVALID_REQUEST",
    500: "INTERNAL_ERROR",
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    if config.SECRET_KEY.startswith("dev-only"):
        logger.warning("当前使用默认 SECRET_KEY，仅限本地演示")
    yield


app = FastAPI(title="运输异常与签收协作 · 管理后台", lifespan=lifespan)
app.mount("/admin/static", StaticFiles(directory=str(config.BASE_DIR / "static")), name="admin-static")


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request.state.request_id = f"r_{secrets.token_hex(6)}"
    response = await call_next(request)
    response.headers["X-Request-Id"] = request.state.request_id
    return response


@app.exception_handler(LoginRequired)
async def login_required_handler(request: Request, exc: LoginRequired):
    return RedirectResponse("/admin/login?err=%E8%AF%B7%E5%85%88%E7%99%BB%E5%BD%95", status_code=303)


@app.exception_handler(Forbidden)
async def forbidden_handler(request: Request, exc: Forbidden):
    return render(
        request, None, "error.html", status_code=403,
        code="FORBIDDEN", message="当前角色无权执行该操作",
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    rid = getattr(request.state, "request_id", "")
    code = CODE_BY_STATUS.get(exc.status_code, "INTERNAL_ERROR")
    message = exc.detail if isinstance(exc.detail, str) else "请求处理失败，请稍后重试"
    if request.url.path.startswith("/admin/api"):
        return JSONResponse(
            {"code": code, "message": message, "request_id": rid},
            status_code=exc.status_code,
        )
    return render(
        request, None, "error.html", status_code=exc.status_code,
        code=code, message=message,
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    rid = getattr(request.state, "request_id", "")
    logger.exception("未处理异常 request_id=%s", rid, exc_info=exc)
    if request.url.path.startswith("/admin/api"):
        return JSONResponse(
            {"code": "INTERNAL_ERROR", "message": f"系统内部错误，请联系管理员（编号 {rid}）",
             "request_id": rid},
            status_code=500,
        )
    return render(
        request, None, "error.html", status_code=500,
        code="INTERNAL_ERROR", message=f"系统内部错误，请联系管理员（编号 {rid}）",
    )


@app.get("/")
def root():
    return RedirectResponse("/admin/kb", status_code=307)


app.include_router(auth.router)
app.include_router(kb.router)
app.include_router(prompts.router)
app.include_router(audit.router)
