"""管理后台全局配置。

所有可变项都从环境变量读取，避免把密钥与路径写死在代码里。
"""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("ADMIN_DATA_DIR", BASE_DIR / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = Path(os.getenv("ADMIN_DB_PATH", DATA_DIR / "admin.db"))

# 生产必须覆盖；未覆盖时只允许本地演示，启动日志会提示。
SECRET_KEY = os.getenv("ADMIN_SECRET_KEY", "dev-only-change-me-please")
COOKIE_NAME = "admin_token"
CSRF_COOKIE = "admin_csrf"
TOKEN_TTL_MINUTES = int(os.getenv("ADMIN_TOKEN_TTL_MINUTES", "30"))

SEED_PASSWORD = os.getenv("ADMIN_SEED_PASSWORD", "Admin@123456789")
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
ALLOWED_EXTENSIONS = {".md", ".pdf"}
