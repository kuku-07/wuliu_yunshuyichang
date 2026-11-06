"""Agent 流水线演示：打印每一步工具、耗时、是否需要人工确认，以及最终结果。

用法：
    python scripts/agent_demo.py YD20261030001
    python scripts/agent_demo.py YD20261030001 expedite
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from admin_app import db as db_module  # noqa: E402
from admin_app.db import connect  # noqa: E402
from admin_app.services import draft  # noqa: E402


def main() -> int:
    shipment_no = sys.argv[1] if len(sys.argv) > 1 else "YD20261030001"
    scenario = sys.argv[2] if len(sys.argv) > 2 else "query"

    db_module.init_db()
    conn = connect()
    try:
        user = conn.execute(
            "SELECT * FROM admin_users WHERE employee_no='sys_admin'"
        ).fetchone()
        if user is None:
            print("缺少 sys_admin 账号")
            return 1
        actor = dict(user)
        result, trace = draft.generate_with_trace(conn, actor, shipment_no, scenario)
    finally:
        conn.close()

    print(f"运单：{shipment_no}　场景：{scenario}")
    print("-" * 72)
    print(f"{'#':<3}{'工具':<14}{'人工确认':<10}{'耗时':>8}  说明")
    for index, step in enumerate(trace, start=1):
        human = "是" if step.get("requires_human") else "-"
        print(
            f"{index:<3}{step['tool']:<14}{human:<10}{step['ms']:>7}ms  "
            f"{step.get('description', '')}"
        )
        if step.get("blocked"):
            print(f"    └─ 在此停止：{step['tool']}")
    print("-" * 72)

    ok, message, payload = result
    print(f"结果：{'成功' if ok else '未生成'}　{message}")
    if payload:
        print(f"草稿：{payload.get('id')}　状态：{payload.get('status')}")
        if payload.get("blocked_reason"):
            print(f"停止原因：{payload['blocked_reason']}")
    human_steps = [s["tool"] for s in trace if s.get("requires_human")]
    print(f"本次涉及人工确认点：{', '.join(human_steps) or '无'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
