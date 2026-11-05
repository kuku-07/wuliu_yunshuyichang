"""干线（作业线路）管理。

线路原来只是散落在规则文档、运单、授权里的一串文本，新增只能靠手打，
既容易打错也看不出到底有哪几条。这里把它收成一张表：

- 「干线管理」页负责新建（名称 + 地区）、停用/启用、删除
- 规则上传、运单登记、对话页的线路下拉都从这里取
- 删除前检查是否仍被规则 / 运单 / 授权引用，避免留下悬空引用
"""
from __future__ import annotations

import sqlite3

from ..db import now_iso
from .audit_log import log as audit

NAME_MAX = 40
REGION_MAX = 20
VALID_STATUS = {"active", "disabled"}

# 固定地区选项：干线的所属大区，不允许自由输入，避免出现「华东 / 华东区 / 华 东」这类脏数据
REGIONS = ["华北", "华南", "华中", "华东", "西南", "西北", "东北", "西藏", "新疆", "港澳"]


def list_lanes(conn: sqlite3.Connection, include_disabled: bool = True) -> list[dict]:
    sql = (
        "SELECT l.*,"
        "  (SELECT COUNT(*) FROM kb_documents d WHERE d.lane_scope=l.name) AS doc_count,"
        "  (SELECT COUNT(*) FROM shipments s WHERE s.lane_scope=l.name) AS shipment_count,"
        "  (SELECT COUNT(*) FROM authorization_grants g WHERE g.lane_scope=l.name) AS grant_count"
        " FROM lanes l"
    )
    if not include_disabled:
        sql += " WHERE l.status='active'"
    sql += " ORDER BY l.name"
    return [dict(r) for r in conn.execute(sql).fetchall()]


def active_names(conn: sqlite3.Connection) -> list[str]:
    return [
        row[0]
        for row in conn.execute(
            "SELECT name FROM lanes WHERE status='active' ORDER BY name"
        ).fetchall()
    ]


def options(conn: sqlite3.Connection, extra: tuple[str, ...] | list[str] = ()) -> list[dict]:
    """下拉选项：启用的干线（含地区），再补上用户范围里有、但表里没登记的名字。"""
    rows = list_lanes(conn, include_disabled=False)
    known = {row["name"] for row in rows}
    for name in extra:
        if name and name not in known:
            rows.append({"name": name, "region": "", "status": "active", "note": ""})
            known.add(name)
    return sorted(rows, key=lambda row: ((row.get("region") or "zz"), row["name"]))


def get(conn: sqlite3.Connection, name: str) -> dict | None:
    row = conn.execute("SELECT * FROM lanes WHERE name=?", ((name or "").strip(),)).fetchone()
    return dict(row) if row else None


def name_exists(conn: sqlite3.Connection, name: str, active_only: bool = False) -> bool:
    row = get(conn, name)
    if row is None:
        return False
    return row["status"] == "active" if active_only else True


def create(
    conn: sqlite3.Connection, actor: dict, name: str, region: str, note: str = "",
) -> tuple[bool, str]:
    name = (name or "").strip()
    region = (region or "").strip()
    if not name:
        return False, "干线名称不能为空"
    if len(name) > NAME_MAX:
        return False, f"干线名称过长（上限 {NAME_MAX} 字）"
    if not region:
        return False, "请选择所属地区"
    if region not in REGIONS:
        return False, f"地区「{region}」不在可选范围内"
    if get(conn, name):
        return False, f"干线「{name}」已存在"

    conn.execute(
        "INSERT INTO lanes (name, region, status, note, is_demo, created_at)"
        " VALUES (?,?, 'active', ?, 0, ?)",
        (name, region, note.strip()[:100], now_iso()),
    )
    conn.commit()
    audit(conn, actor, "lane.create", "lane", name, f"地区={region}")
    conn.commit()
    return True, ""


def set_status(
    conn: sqlite3.Connection, actor: dict, name: str, status: str,
) -> tuple[bool, str]:
    if status not in VALID_STATUS:
        return False, "状态不合法"
    row = get(conn, name)
    if row is None:
        return False, "干线不存在"
    if row["status"] == status:
        return True, ""
    conn.execute("UPDATE lanes SET status=? WHERE name=?", (status, name))
    conn.commit()
    audit(conn, actor, "lane.status", "lane", name,
          f"{row['status']} → {status}")
    conn.commit()
    return True, ""


def usage(conn: sqlite3.Connection, name: str) -> dict:
    return {
        "docs": conn.execute(
            "SELECT COUNT(*) FROM kb_documents WHERE lane_scope=?", (name,)
        ).fetchone()[0],
        "shipments": conn.execute(
            "SELECT COUNT(*) FROM shipments WHERE lane_scope=?", (name,)
        ).fetchone()[0],
        "grants": conn.execute(
            "SELECT COUNT(*) FROM authorization_grants WHERE lane_scope=?", (name,)
        ).fetchone()[0],
    }


def delete(conn: sqlite3.Connection, actor: dict, name: str) -> tuple[bool, str]:
    row = get(conn, name)
    if row is None:
        return False, "干线不存在"
    used = usage(conn, name)
    if any(used.values()):
        parts = []
        if used["docs"]:
            parts.append(f"规则 {used['docs']} 份")
        if used["shipments"]:
            parts.append(f"运单 {used['shipments']} 票")
        if used["grants"]:
            parts.append(f"授权 {used['grants']} 条")
        return False, f"该干线仍被引用（{'、'.join(parts)}），请先清理或改为停用"

    conn.execute("DELETE FROM lanes WHERE name=?", (name,))
    conn.commit()
    audit(conn, actor, "lane.delete", "lane", name, f"地区={row['region']}")
    conn.commit()
    return True, ""
