"""账号与角色管理。

补上 `users:manage` 的界面：新建账号、改角色与线路范围、重置密码、解锁。
线路范围（lane_scopes）从此不再只是默认值——对话页的线路下拉会按它过滤。
"""
from __future__ import annotations

import json
import sqlite3

from ..db import now_iso
from ..security import hash_password, object_hash
from . import lanes as lane_service
from .audit_log import log as audit

ROLES = {
    "rule_admin": "规则管理员",
    "supervisor": "客服主管",
    "auditor": "合规审计",
    "sys_admin": "系统管理员",
    "dispatcher": "现场调度",
    "carrier": "承运商经理",
    "customer": "客户",
}
MIN_PASSWORD = 12


def list_users(conn: sqlite3.Connection) -> list[dict]:
    rows = []
    for row in conn.execute(
        "SELECT id, employee_no, name, role, lane_scopes, status, failed_count,"
        " locked_until, created_at FROM admin_users ORDER BY role, employee_no"
    ).fetchall():
        item = dict(row)
        try:
            item["lanes"] = json.loads(item["lane_scopes"] or "[]")
        except ValueError:
            item["lanes"] = []
        rows.append(item)
    return rows


def _validate_lanes(conn: sqlite3.Connection, lanes: list[str]) -> tuple[bool, str]:
    valid = {row["name"] for row in lane_service.list_lanes(conn)}
    unknown = [lane for lane in lanes if lane not in valid]
    if unknown:
        return False, f"线路不存在：{', '.join(unknown)}"
    return True, ""


def _active_admins(conn: sqlite3.Connection, exclude: str = "") -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM admin_users WHERE role='sys_admin' AND status='active' AND id<>?",
        (exclude,),
    ).fetchone()[0]


def create(
    conn: sqlite3.Connection, actor: dict, employee_no: str, name: str, role: str,
    lanes: list[str], password: str,
) -> tuple[bool, str]:
    employee_no = (employee_no or "").strip()
    name = (name or "").strip()
    if not employee_no:
        return False, "账号不能为空"
    if len(employee_no) > 32:
        return False, "账号过长（上限 32 字符）"
    if not name:
        return False, "姓名不能为空"
    if role not in ROLES:
        return False, "角色不合法"
    if len(password or "") < MIN_PASSWORD:
        return False, f"密码至少 {MIN_PASSWORD} 位"
    if conn.execute(
        "SELECT COUNT(*) FROM admin_users WHERE employee_no=?", (employee_no,)
    ).fetchone()[0]:
        return False, f"账号「{employee_no}」已存在"
    ok, error = _validate_lanes(conn, lanes)
    if not ok:
        return False, error

    conn.execute(
        "INSERT INTO admin_users"
        " (id, employee_no, name, role, lane_scopes, password_hash, status, created_at)"
        " VALUES (?,?,?,?,?,?, 'active', ?)",
        (
            f"u_{employee_no}", employee_no, name, role,
            json.dumps(lanes, ensure_ascii=False), hash_password(password), now_iso(),
        ),
    )
    conn.commit()
    audit(conn, actor, "user.create", "admin_user", f"u_{employee_no}",
          f"{employee_no} / {name} / {role} / {','.join(lanes) or '-'}")
    conn.commit()
    return True, ""


def update(
    conn: sqlite3.Connection, actor: dict, user_id: str, name: str, role: str,
    lanes: list[str], status: str,
) -> tuple[bool, str]:
    row = conn.execute("SELECT * FROM admin_users WHERE id=?", (user_id,)).fetchone()
    if row is None:
        return False, "账号不存在"
    if role not in ROLES:
        return False, "角色不合法"
    if status not in {"active", "disabled"}:
        return False, "状态不合法"
    ok, error = _validate_lanes(conn, lanes)
    if not ok:
        return False, error

    if user_id == actor["id"] and (role != "sys_admin" or status != "active"):
        return False, "不能降级或停用当前登录账号"
    if row["role"] == "sys_admin" and _active_admins(conn, exclude=user_id) == 0:
        if role != "sys_admin" or status != "active":
            return False, "这是最后一个系统管理员，不能降级或停用"

    before_hash = object_hash(
        {"name": row["name"], "role": row["role"], "status": row["status"],
         "lanes": row["lane_scopes"]}
    )
    after_lanes = json.dumps(lanes, ensure_ascii=False)
    conn.execute(
        "UPDATE admin_users SET name=?, role=?, lane_scopes=?, status=? WHERE id=?",
        (name.strip(), role, after_lanes, status, user_id),
    )
    conn.commit()
    audit(conn, actor, "user.update", "admin_user", user_id,
          f"{row['employee_no']} → {role} / {status} / {','.join(lanes) or '-'}",
          before_hash=before_hash,
          after_hash=object_hash({"name": name.strip(), "role": role,
                                  "status": status, "lanes": after_lanes}))
    conn.commit()
    return True, ""


def reset_password(
    conn: sqlite3.Connection, actor: dict, user_id: str, password: str,
) -> tuple[bool, str]:
    if len(password or "") < MIN_PASSWORD:
        return False, f"密码至少 {MIN_PASSWORD} 位"
    row = conn.execute("SELECT * FROM admin_users WHERE id=?", (user_id,)).fetchone()
    if row is None:
        return False, "账号不存在"
    conn.execute(
        "UPDATE admin_users SET password_hash=?, failed_count=0, locked_until=NULL"
        " WHERE id=?",
        (hash_password(password), user_id),
    )
    conn.commit()
    audit(conn, actor, "user.reset_password", "admin_user", user_id, row["employee_no"])
    conn.commit()
    return True, "密码已重置"


def unlock(conn: sqlite3.Connection, actor: dict, user_id: str) -> tuple[bool, str]:
    row = conn.execute("SELECT * FROM admin_users WHERE id=?", (user_id,)).fetchone()
    if row is None:
        return False, "账号不存在"
    conn.execute(
        "UPDATE admin_users SET failed_count=0, locked_until=NULL WHERE id=?", (user_id,)
    )
    conn.commit()
    audit(conn, actor, "user.unlock", "admin_user", user_id, row["employee_no"])
    conn.commit()
    return True, "已解锁"
