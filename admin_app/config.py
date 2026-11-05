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

# 运单号格式：默认 YD + 11 位数字（演示数据 YD20261030001 = 2026-10-30 的第 001 单）。
# 真实规则不同就改环境变量 SHIPMENT_NO_PATTERN，不用动代码。
SHIPMENT_NO_PATTERN = os.getenv("SHIPMENT_NO_PATTERN", r"^YD\d{11}$")
SHIPMENT_NO_EXAMPLE = "YD20261030001"
