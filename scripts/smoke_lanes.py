r"""干线管理冒烟测试：新建 / 停用 / 删除，以及与规则、运单、对话的联动。

运行：
    $env:PYTHONPATH="D:\Lib\site-packages;D:\wuliu_yunshuyichang"
    python scripts\smoke_lanes.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import unquote

tmp_dir = tempfile.mkdtemp(prefix="lane_smoke_")
os.environ["ADMIN_DATA_DIR"] = tmp_dir
os.environ["ADMIN_DB_PATH"] = str(Path(tmp_dir) / "admin.db")
os.environ["ADMIN_SECRET_KEY"] = "smoke-test-secret"
os.environ["ADMIN_SEED_PASSWORD"] = "Admin@123456789"
os.environ.pop("LLM_API_KEY", None)
os.environ["LLM_PROVIDER"] = "offline"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from admin_app import db as db_module  # noqa: E402
from admin_app.db import connect  # noqa: E402
from admin_app.main import app  # noqa: E402

PASSWORD = "Admin@123456789"
STEPS: list[str] = []


def ok(label: str) -> None:
    STEPS.append(label)
    print(f"[通过] {label}")


def fail(label: str, detail: str = "") -> None:
    print(f"[失败] {label} {detail}")
    raise SystemExit(1)


def csrf(client: TestClient) -> str:
    if "admin_csrf" not in client.cookies:
        client.get("/admin/login", follow_redirects=False)
    return client.cookies.get("admin_csrf")


def login(client: TestClient, employee_no: str) -> None:
    token = csrf(client)
    response = client.post(
        "/admin/login",
        data={"employee_no": employee_no, "password": PASSWORD, "csrf_token": token},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    assert "admin_token" in client.cookies, f"{employee_no} 登录未下发 token"


def post(client: TestClient, path: str, data: dict, files=None):
    payload = dict(data)
    payload["csrf_token"] = csrf(client)
    return client.post(path, data=payload, files=files, follow_redirects=True)


def main() -> int:
    db_module.init_db()
    admin = TestClient(app)
    login(admin, "sys_admin")

    # ---- 1. 页面与权限 ----
    page = admin.get("/admin/lanes")
    if page.status_code != 200 or "干线列表" not in page.text:
        fail("干线管理页可访问", str(page.status_code))
    for lane in ("试点干线-华东", "试点干线-华北"):
        if lane not in page.text:
            fail("演示干线已登记", lane)
    ok("干线管理页可访问，演示干线含地区")

    auditor = TestClient(app)
    login(auditor, "auditor")
    if auditor.get("/admin/lanes").status_code != 403:
        fail("非管理员访问干线管理应 403", "auditor 未被拒绝")
    ok("非管理员访问干线管理 → 403")

    # ---- 2. 新建与校验 ----
    created = post(admin, "/admin/lanes/create", {
        "name": "试点干线-华南", "region": "华南", "note": "广州、深圳、东莞",
    })
    if "已新建干线" not in created.text:
        fail("新建干线成功", "未提示成功")
    ok("新建干线「试点干线-华南」（名称 + 地区）")

    duplicates = post(admin, "/admin/lanes/create", {
        "name": "试点干线-华南", "region": "华南",
    })
    if "已存在" not in duplicates.text:
        fail("同名干线被拒绝", "未提示已存在")
    ok("同名干线 → 拒绝")

    missing_region = post(admin, "/admin/lanes/create", {
        "name": "试点干线-西北", "region": "",
    })
    if "请选择所属地区" not in missing_region.text:
        fail("地区必选", "未提示")
    ok("地区为空 → 拒绝")

    # 名称不必带地区；地区是固定下拉
    page = admin.get("/admin/lanes")
    for region in ("华北", "华南", "华中", "华东", "西南", "西北", "东北", "西藏", "新疆", "港澳"):
        if region not in page.text:
            fail("地区下拉包含固定选项", region)
    ok("所属地区为固定下拉（10 个地区）")

    short_name = post(admin, "/admin/lanes/create", {"name": "华南快线", "region": "华南"})
    if "已新建干线" not in short_name.text:
        fail("干线名称可以不带地区", "新建失败")
    if "华南快线（华南）" not in admin.get("/admin/chat").text:
        fail("对话下拉显示「名称（地区）」", "未显示")
    ok("名称不带地区也能新建，下拉显示为「名称（地区）」")

    bad_region = post(admin, "/admin/lanes/create", {"name": "测试线", "region": "火星"})
    if "不在可选范围" not in bad_region.text:
        fail("非法地区被拒绝", "未拦截")
    ok("非法地区 → 拒绝")

    # ---- 3. 新干线出现在三个下拉里 ----
    for path, label in (
        ("/admin/kb/upload", "规则上传"),
        ("/admin/shipments", "运单登记"),
        ("/admin/chat", "对话页作业线路"),
    ):
        page = admin.get(path)
        if 'value="试点干线-华南"' not in page.text:
            fail(f"{label}可选新干线", path)
    ok("新干线同步出现在规则上传 / 运单登记 / 对话线路下拉")

    # ---- 4. 用新干线传规则；不存在的干线被拒绝 ----
    body = (
        "# 华南规则\n\n"
        "## 1. 适用范围\n\n本规则适用于华南试点线路的整车与零担运单，覆盖在途、到货与异常升级环节。\n\n"
        "## 2. 异常分类\n\n台风导致的延误归为「天气异常」，需附气象证明与现场照片至少 2 张。\n"
    )
    upload = admin.post(
        "/admin/kb/upload",
        data={"title": "华南试点规则", "lane_scope": "试点干线-华南",
              "effective_from": "2026-11-10", "csrf_token": csrf(admin)},
        files={"file": ("south.md", body.encode("utf-8"), "text/markdown")},
        follow_redirects=True,
    )
    if "已生成草稿" not in upload.text:
        fail("用新干线上传规则", "未生成草稿")
    ok("用新干线上传规则 → 生成草稿")

    bad = admin.post(
        "/admin/kb/upload",
        data={"title": "x", "lane_scope": "不存在的干线", "csrf_token": csrf(admin)},
        files={"file": ("x.md", b"# x\n\n## 1. a\n\ntext\n", "text/markdown")},
        follow_redirects=True,
    )
    if "不存在或已停用" not in bad.text:
        fail("不存在的干线被拒绝", "未拦截")
    ok("上传时选择不存在的干线 → 拒绝")

    # ---- 5. 删除保护 ----
    used = post(admin, "/admin/lanes/delete", {"name": "试点干线-华南"})
    if "仍被引用" not in used.text:
        fail("被规则引用的干线禁止删除", "未拦截")
    ok("被规则引用的干线 → 禁止删除")

    post(admin, "/admin/lanes/create", {"name": "试点干线-西南", "region": "西南"})
    unused = post(admin, "/admin/lanes/delete", {"name": "试点干线-西南"})
    if "已删除" not in unused.text:
        fail("未被引用的干线可删除", "删除失败")
    conn = connect()
    try:
        left = conn.execute("SELECT COUNT(*) FROM lanes WHERE name='试点干线-西南'").fetchone()[0]
    finally:
        conn.close()
    if left:
        fail("删除后库中不再存在", str(left))
    ok("未被引用的干线 → 可删除")

    # ---- 6. 停用后从下拉消失，但记录仍在 ----
    disabled = post(admin, "/admin/lanes/status", {"name": "试点干线-华北", "status": "disabled"})
    if "已停用" not in disabled.text:
        fail("停用干线", "未提示")
    upload_page = admin.get("/admin/kb/upload")
    if 'value="试点干线-华北"' in upload_page.text:
        fail("停用后不再出现在上传下拉", "华北仍在列表里")
    if "试点干线-华北" not in admin.get("/admin/lanes").text:
        fail("停用后管理页仍可见", "记录丢失")
    ok("停用干线：下拉里消失，管理页仍保留记录")

    post(admin, "/admin/lanes/status", {"name": "试点干线-华北", "status": "active"})
    if 'value="试点干线-华北"' not in admin.get("/admin/kb/upload").text:
        fail("重新启用", "下拉里仍没有")
    ok("重新启用后回到下拉")

    print()
    print(f"全部通过：{len(STEPS)} 项")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
