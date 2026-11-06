"""故障场景探针：模拟模型超时，采集 SSE 错误事件。"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

tmp = tempfile.mkdtemp(prefix="fail_probe_")
os.environ["ADMIN_DATA_DIR"] = tmp
os.environ["ADMIN_DB_PATH"] = str(Path(tmp) / "admin.db")
os.environ["ADMIN_SECRET_KEY"] = "probe-secret"
os.environ["ADMIN_SEED_PASSWORD"] = "Admin@123456789"
os.environ.pop("LLM_API_KEY", None)
os.environ["LLM_PROVIDER"] = "offline"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from admin_app import db as db_module  # noqa: E402
from admin_app.main import app  # noqa: E402
from admin_app.services import agent_core  # noqa: E402


class TimeoutClient:
    def complete(self, system_prompt, user_prompt):
        raise TimeoutError("timed out")


def main() -> int:
    db_module.init_db()
    client = TestClient(app)
    page = client.get("/admin/login")
    import re

    token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
    client.post("/admin/login", data={"employee_no": "sys_admin",
                                      "password": "Admin@123456789",
                                      "csrf_token": token},
                follow_redirects=False)
    session_id = re.search(r'data-session="([^"]+)"', client.get("/agent").text).group(1)

    original = agent_core.build_llm_client
    agent_core.build_llm_client = lambda: TimeoutClient()
    events = []
    try:
        with client.stream(
            "POST", "/admin/api/chat/stream",
            data={"question": "封路导致延误怎么记录？", "session_id": session_id,
                  "csrf_token": client.cookies.get("admin_csrf", "")},
        ) as response:
            status = response.status_code
            name = None
            for line in response.iter_lines():
                if line.startswith("event: "):
                    name = line[7:].strip()
                elif line.startswith("data: ") and name:
                    events.append({"event": name, "data": json.loads(line[6:])})
                    name = None
    finally:
        agent_core.build_llm_client = original

    print(json.dumps({"status": status, "events": events}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
