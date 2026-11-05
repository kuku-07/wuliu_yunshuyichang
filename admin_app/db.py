"""SQLite 连接、建表与演示数据。

设计要点：
- 规则版本、提示词版本、审计日志都只追加，不覆盖；
- 会话与消息表沿用 docs/04 的字段，便于阶段 2 的 /chat 直接复用；
- 所有时间使用本地 ISO 字符串，避免跨平台时区解析差异。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from . import config
from .security import hash_password, locked_hash

SCHEMA = """
CREATE TABLE IF NOT EXISTS admin_users (
    id            TEXT PRIMARY KEY,
    employee_no   TEXT NOT NULL UNIQUE,
    name          TEXT NOT NULL,
    role          TEXT NOT NULL,
    lane_scopes   TEXT NOT NULL DEFAULT '[]',
    password_hash TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'active',
    failed_count  INTEGER NOT NULL DEFAULT 0,
    locked_until  TEXT,
    is_demo       INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id          TEXT PRIMARY KEY,
    actor_id    TEXT,
    actor_name  TEXT,
    action      TEXT NOT NULL,
    object_type TEXT NOT NULL,
    object_id   TEXT NOT NULL,
    detail      TEXT NOT NULL DEFAULT '',
    request_id  TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS kb_documents (
    id             TEXT PRIMARY KEY,
    title          TEXT NOT NULL,
    lane_scope     TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'draft',
    current_version TEXT NOT NULL,
    active_version TEXT,
    effective_from TEXT,
    submitted_by   TEXT,
    approved_by    TEXT,
    pii_masked     INTEGER NOT NULL DEFAULT 0,
    is_demo        INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS kb_document_versions (
    id           TEXT PRIMARY KEY,
    doc_id       TEXT NOT NULL,
    version      TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    change_note  TEXT NOT NULL DEFAULT '',
    published_at TEXT,
    published_by TEXT,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS kb_chunks (
    id          TEXT PRIMARY KEY,
    doc_id      TEXT NOT NULL,
    version     TEXT NOT NULL,
    chunk_no    INTEGER NOT NULL,
    section     TEXT NOT NULL,
    text        TEXT NOT NULL,
    token_count INTEGER NOT NULL,
    is_active   INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS kb_index_state (
    id            INTEGER PRIMARY KEY CHECK (id = 1),
    last_rebuild  TEXT,
    active_chunks INTEGER NOT NULL DEFAULT 0,
    note          TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS prompt_templates (
    id               TEXT PRIMARY KEY,
    name             TEXT NOT NULL,
    locked_section   TEXT NOT NULL,
    editable_section TEXT NOT NULL,
    active_version   INTEGER NOT NULL DEFAULT 1,
    updated_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS prompt_template_versions (
    id               TEXT PRIMARY KEY,
    template_id      TEXT NOT NULL,
    version          INTEGER NOT NULL,
    locked_hash      TEXT NOT NULL,
    editable_section TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'draft',
    dry_run_result   TEXT,
    dry_run_at       TEXT,
    created_by       TEXT,
    published_by     TEXT,
    published_at     TEXT,
    created_at       TEXT NOT NULL,
    UNIQUE(template_id, version)
);

CREATE TABLE IF NOT EXISTS sessions (
    id             TEXT PRIMARY KEY,
    user_id        TEXT NOT NULL,
    lane_scope     TEXT NOT NULL,
    shipment_no    TEXT,
    status         TEXT NOT NULL DEFAULT 'active',
    is_demo        INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL,
    last_active_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id             TEXT PRIMARY KEY,
    session_id     TEXT NOT NULL,
    client_msg_id  TEXT,
    role           TEXT NOT NULL,
    content        TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'complete',
    intent         TEXT NOT NULL DEFAULT '',
    prompt_version TEXT NOT NULL DEFAULT '',
    model          TEXT NOT NULL DEFAULT '',
    data_time      TEXT,
    confidence     REAL,
    latency_ms     INTEGER,
    created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS citations (
    id           TEXT PRIMARY KEY,
    message_id   TEXT NOT NULL,
    doc_id       TEXT NOT NULL,
    doc_title    TEXT NOT NULL,
    doc_version  TEXT NOT NULL,
    effective_from TEXT,
    lane_scope   TEXT,
    section      TEXT NOT NULL,
    chunk_id     TEXT NOT NULL,
    quote        TEXT NOT NULL,
    score        REAL
);

CREATE TABLE IF NOT EXISTS conversation_flags (
    id           TEXT PRIMARY KEY,
    message_id   TEXT NOT NULL,
    flag_type    TEXT NOT NULL,
    reason       TEXT NOT NULL,
    flagged_by   TEXT NOT NULL,
    flagged_at   TEXT NOT NULL,
    revoked_at   TEXT,
    revoked_by   TEXT,
    revoke_reason TEXT
);

CREATE TABLE IF NOT EXISTS shipments (
    shipment_no  TEXT PRIMARY KEY,
    lane_scope   TEXT NOT NULL,
    customer     TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'in_transit',
    is_demo      INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS app_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS authorization_grants (
    id           TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL,
    shipment_no  TEXT NOT NULL,
    lane_scope   TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'active',
    granted_by   TEXT,
    granted_at   TEXT NOT NULL,
    expires_at   TEXT,
    revoked_at   TEXT,
    revoked_by   TEXT,
    reason       TEXT NOT NULL DEFAULT '',
    is_demo      INTEGER NOT NULL DEFAULT 0,
    UNIQUE(user_id, shipment_no)
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_citations_message ON citations(message_id);
CREATE INDEX IF NOT EXISTS idx_grants_lookup ON authorization_grants(user_id, shipment_no, status);
CREATE INDEX IF NOT EXISTS idx_docs_status ON kb_documents(status, lane_scope);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON kb_chunks(doc_id, version, is_active);
CREATE INDEX IF NOT EXISTS idx_flags_message ON conversation_flags(message_id);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_logs(action, created_at);
"""

DEFAULT_LOCKED_SECTION = """【安全约束 · 不可编辑】
1. 只依据检索到的规则条文回答，不得推断规则外内容。
2. 未检索到规则时，必须回答「规则中未找到，请转人工确认」。
3. 禁止输出赔付金额、责任认定、扣罚结论、绕行建议。
4. 不得生成对外发送的最终文本，只生成内部处置草稿。
5. 回答末尾必须附引用（文档名 + 版本 + 章节）。
6. 不得输出客户电话、地址、车牌等受限字段。"""

DEFAULT_EDITABLE_SECTION = """你是运输异常与签收协作助手，服务对象是一线客服与调度。
语气：简洁、直接，先给结论再给依据。
称呼：使用「你」，不使用「您」。
不确定时：说明缺少哪条规则或哪项数据，并建议转人工确认。
输出结构：1) 结论 2) 处置步骤 3) 引用来源。"""


def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def connect() -> sqlite3.Connection:
    """每次请求一个连接；WAL 提升并发读性能。"""
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, timeout=15, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        _migrate(conn)
        conn.execute(
            "INSERT OR IGNORE INTO kb_index_state (id, active_chunks) VALUES (1, 0)"
        )
        if conn.execute("SELECT COUNT(*) FROM admin_users").fetchone()[0] == 0:
            _seed(conn)
            set_meta(conn, DEMO_SEED_KEY, "seeded")
        else:
            _backfill_demo_data(conn)
        conn.commit()
    finally:
        conn.close()


DEMO_SEED_KEY = "demo_seed_state"


def get_meta(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM app_meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO app_meta (key, value) VALUES (?, ?)"
        " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def _migrate(conn: sqlite3.Connection) -> None:
    """老库补列，并给「本来就存在的」演示行补上 is_demo 标记。

    标记用的是已知编号，而不是 `LIKE 'g_00%'` 这种前缀猜测——
    自建授权的 id 是 `g_` + 随机 hex，理论上可能撞上前缀，不能误标。
    """
    for table, column, ddl in (
        ("shipments", "is_demo",
         "ALTER TABLE shipments ADD COLUMN is_demo INTEGER NOT NULL DEFAULT 0"),
        ("authorization_grants", "is_demo",
         "ALTER TABLE authorization_grants ADD COLUMN is_demo INTEGER NOT NULL DEFAULT 0"),
        ("admin_users", "is_demo",
         "ALTER TABLE admin_users ADD COLUMN is_demo INTEGER NOT NULL DEFAULT 0"),
        ("kb_documents", "is_demo",
         "ALTER TABLE kb_documents ADD COLUMN is_demo INTEGER NOT NULL DEFAULT 0"),
        ("sessions", "is_demo",
         "ALTER TABLE sessions ADD COLUMN is_demo INTEGER NOT NULL DEFAULT 0"),
    ):
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            conn.execute(ddl)

    if DEMO_SHIPMENTS:
        marks = ",".join("?" * len(DEMO_SHIPMENTS))
        conn.execute(
            f"UPDATE shipments SET is_demo=1 WHERE shipment_no IN ({marks})",
            tuple(item[0] for item in DEMO_SHIPMENTS),
        )
    if DEMO_GRANTS:
        marks = ",".join("?" * len(DEMO_GRANTS))
        conn.execute(
            f"UPDATE authorization_grants SET is_demo=1 WHERE id IN ({marks})",
            tuple(item[0] for item in DEMO_GRANTS),
        )
    if DEMO_USERS:
        marks = ",".join("?" * len(DEMO_USERS))
        conn.execute(
            f"UPDATE admin_users SET is_demo=1 WHERE id IN ({marks})",
            tuple(item[0] for item in DEMO_USERS),
        )
    if DEMO_SESSIONS:
        marks = ",".join("?" * len(DEMO_SESSIONS))
        conn.execute(
            f"UPDATE sessions SET is_demo=1 WHERE id IN ({marks})",
            tuple(item[0] for item in DEMO_SESSIONS),
        )
    conn.execute("UPDATE kb_documents SET is_demo=1 WHERE id=?", (DEMO_DOC[0],))


# ---------------------------------------------------------------------------
# 演示数据（全部虚构）
# ---------------------------------------------------------------------------
# 演示数据默认保留；「数据管理」页可以逐项删除，也可以按组恢复。
# 所有行都带 is_demo=1，删除时按 id 精确匹配，不会误伤自建数据。

DEMO_USERS = [
    ("u_rule", "rule_admin", "张敏", "rule_admin", ["试点干线-华东"]),
    ("u_sup1", "supervisor", "李强", "supervisor", ["试点干线-华东"]),
    ("u_sup2", "supervisor2", "赵敏", "supervisor", ["试点干线-华东"]),
    ("u_audit", "auditor", "王芳", "auditor", ["试点干线-华东"]),
    ("u_sys", "sys_admin", "陈磊", "sys_admin", ["试点干线-华东"]),
]

DEMO_DOC = ("doc_001", "运输异常处置与签收协作规则（试点版）", "试点干线-华东", "0.1", "2026-11-01")

DEMO_CHUNKS = [
    ("1. 适用范围", "本规则适用于试点干线-华东的整车与零担运单，覆盖在途、到货、回执与异常升级环节。未纳入试点的线路仍按原流程执行。"),
    ("2. 异常分类", "异常分为固定核心类型：延误、货损、货差、拒收、地址变更、单证缺失。核心类型不可自定义；细分原因以原因码记录，原因码可由规则管理员新增，但不得改变核心类型。"),
    ("2. 异常分类", "客户临时改地址属于「地址变更」，不是「延误」；卸货排队超过 4 小时属于「延误」并需记录排队起止时间；封路导致无法通行属于「延误」，需附路段与封路证明。"),
    ("3. 到货与回执口径", "到货准时率按运单承诺到达时间计算，分母为应到运单数；回执及时率按签收后回传时间计算，分母为已签收运单数。两者不可互相替代，也不得用回执时间反推到货时间。"),
    ("4. 签收与证据要求", "签收必须有收货人签字或电子签收记录，并附货物外观照片至少 2 张；代收需提供代收授权。缺少签字、照片或授权的签收，一律标记为「未取证签收」，不得直接关闭异常。"),
    ("5. 交接与升级", "异常处理人需在 30 分钟内首次响应，2 小时内给出处置结论。超时未响应自动升级至客服主管。涉及赔付、危险品、人员受伤、对外承诺的，不得由智能体处理，必须转人工接管。"),
]

DEMO_SESSIONS = [
    ("s_001", "u_1001", "试点干线-华东", "YD20261030001", "active",
     "2026-10-29T09:12:00", "2026-10-29T09:15:00"),
    ("s_002", "u_1002", "试点干线-华东", "YD20261030002", "active",
     "2026-10-29T10:20:00", "2026-10-29T10:22:00"),
    ("s_003", "u_1003", "试点干线-华东", "YD20261030009", "active",
     "2026-10-29T14:05:00", "2026-10-29T14:06:00"),
]

DEMO_MESSAGES = [
    ("m_101", "s_001", "user", "客户临时改地址，异常该怎么分类？", "complete", "规则问答", "", "", None, None, 0, "2026-10-29T09:12:00"),
    ("m_102", "s_001", "assistant",
     "结论：归为「地址变更」，不要归入「延误」。\n处置：1) 核对新地址是否在原线路范围内；2) 记录变更时间与新地址；3) 通知调度改单。\n依据见引用。",
     "complete", "规则问答", "phase2.v1", "gpt-4o-mini", "2026-10-29T09:12:00", 0.86, 4200,
     "2026-10-29T09:12:05"),
    ("m_201", "s_002", "user", "客户说货损了，能赔多少钱？", "complete", "红线问题", "", "", None, None, 0, "2026-10-29T10:20:00"),
    ("m_202", "s_002", "assistant",
     "【需人工接管】涉及赔付或赔偿认定，规则要求人工接管，系统不生成任何金额建议。\n命中原因码：REDLINE_COMPENSATION",
     "takeover", "红线问题", "phase2.v1", "未调用", "2026-10-29T10:20:00", None, 120,
     "2026-10-29T10:20:00"),
    ("m_301", "s_003", "user", "帮我查一下 YD20261030009 现在到哪了？", "complete", "运单查询", "", "", None, None, 0, "2026-10-29T14:05:00"),
    ("m_302", "s_003", "assistant",
     "结论：该运单已到达杭州转运中心，预计 18:00 前送达。\n（演示数据：未做运单级授权校验）",
     "complete", "运单查询", "phase2.v1", "gpt-4o-mini", "2026-10-29T14:05:00", 0.72, 3800,
     "2026-10-29T14:05:04"),
]

DEMO_CITATION = (
    "c_101", "m_102", "doc_001", "运输异常处置与签收协作规则（试点版）", "0.1",
    "2026-11-01", "试点干线-华东", "2. 异常分类", "chk_002",
    "客户临时改地址属于「地址变更」，不是「延误」；卸货排队超过 4 小时属于「延误」……", 0.91,
)

DEMO_FLAG = (
    "f_001", "m_301", "UNAUTHORIZED_QUERY", "演示标记：运单查询未做授权校验，疑似越权。",
    "u_audit", "2026-10-29T15:00:00",
)


def _seed_users(conn: sqlite3.Connection, created: str) -> None:
    for uid, no, name, role, lanes in DEMO_USERS:
        conn.execute(
            "INSERT OR IGNORE INTO admin_users"
            " (id, employee_no, name, role, lane_scopes, password_hash, is_demo, created_at)"
            " VALUES (?,?,?,?,?,?,1,?)",
            (uid, no, name, role, json.dumps(lanes, ensure_ascii=False),
             hash_password(config.SEED_PASSWORD), created),
        )


def _seed_rule_doc(conn: sqlite3.Connection, created: str) -> None:
    doc_id, title, lane, version, effective_from = DEMO_DOC
    conn.execute(
        "INSERT OR IGNORE INTO kb_documents"
        " (id, title, lane_scope, status, current_version, active_version, effective_from,"
        "  is_demo, created_at, updated_at)"
        " VALUES (?,?,?,?,?,?,?,1,?,?)",
        (doc_id, title, lane, "active", version, version, effective_from, created, created),
    )
    conn.execute(
        "INSERT OR IGNORE INTO kb_document_versions"
        " (id, doc_id, version, content_hash, change_note, published_at, published_by, created_at)"
        " VALUES (?,?,?,?,?,?,?,?)",
        ("kbv_001", doc_id, version, "seed-v01", "试点首版", created, "u_sup2", created),
    )
    for idx, (section, text) in enumerate(DEMO_CHUNKS, start=1):
        conn.execute(
            "INSERT OR IGNORE INTO kb_chunks"
            " (id, doc_id, version, chunk_no, section, text, token_count, is_active, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (f"chk_{idx:03d}", doc_id, version, idx, section, text, len(text), 1, created),
        )
    # 按实际生效切片重算，删除/恢复演示文档后检索缓存会自动失效
    active = conn.execute("SELECT COUNT(*) FROM kb_chunks WHERE is_active=1").fetchone()[0]
    conn.execute(
        "UPDATE kb_index_state SET active_chunks=?, last_rebuild=?, note=? WHERE id=1",
        (active, created, "演示规则"),
    )


def _seed_audit_sessions(conn: sqlite3.Connection, created: str) -> None:
    for sid, uid, lane, shipment, status, started, active_at in DEMO_SESSIONS:
        conn.execute(
            "INSERT OR IGNORE INTO sessions"
            " (id, user_id, lane_scope, shipment_no, status, is_demo, created_at, last_active_at)"
            " VALUES (?,?,?,?,?,1,?,?)",
            (sid, uid, lane, shipment, status, started, active_at),
        )
    for row in DEMO_MESSAGES:
        conn.execute(
            "INSERT OR IGNORE INTO messages"
            " (id, session_id, role, content, status, intent, prompt_version, model,"
            "  data_time, confidence, latency_ms, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            row,
        )
    conn.execute(
        "INSERT OR IGNORE INTO citations"
        " (id, message_id, doc_id, doc_title, doc_version, effective_from, lane_scope,"
        "  section, chunk_id, quote, score)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        DEMO_CITATION,
    )
    conn.execute(
        "INSERT OR IGNORE INTO conversation_flags"
        " (id, message_id, flag_type, reason, flagged_by, flagged_at)"
        " VALUES (?,?,?,?,?,?)",
        DEMO_FLAG,
    )


def _seed(conn: sqlite3.Connection) -> None:
    """写入演示账号、规则、提示词与会话；所有内容均为虚构。"""
    created = now_iso()
    _seed_users(conn, created)

    # ---- 默认提示词 ----
    conn.execute(
        "INSERT INTO prompt_templates (id, name, locked_section, editable_section, active_version, updated_at)"
        " VALUES (?,?,?,?,?,?)",
        ("pt_001", "运输异常问答提示词", DEFAULT_LOCKED_SECTION, DEFAULT_EDITABLE_SECTION, 1, created),
    )
    conn.execute(
        "INSERT INTO prompt_template_versions"
        " (id, template_id, version, locked_hash, editable_section, status, created_by, created_at)"
        " VALUES (?,?,?,?,?,?,?,?)",
        ("ptv_001", "pt_001", 1, locked_hash(DEFAULT_LOCKED_SECTION),
         DEFAULT_EDITABLE_SECTION, "published", "u_sys", created),
    )

    # ---- 已生效规则 v0.1 ----
    _seed_rule_doc(conn, created)

    # ---- 演示会话（审计页示例）----
    _seed_audit_sessions(conn, created)

    # ---- 运单主数据 + 运单级授权（ABAC 预检用）----
    _seed_shipments(conn, created)
    _seed_grants(conn, created)


def _backfill_demo_data(conn: sqlite3.Connection) -> None:
    """老库升级：只在「从未标记过演示数据」时补一次。

    管理员手动清掉演示数据后 `demo_seed_state='purged'`，重启不会再塞回来，
    否则「删除」就形同虚设。
    """
    if get_meta(conn, DEMO_SEED_KEY):
        return
    created = now_iso()
    if conn.execute("SELECT COUNT(*) FROM shipments").fetchone()[0] == 0:
        _seed_shipments(conn, created)
    if conn.execute("SELECT COUNT(*) FROM authorization_grants").fetchone()[0] == 0:
        _seed_grants(conn, created)
    set_meta(conn, DEMO_SEED_KEY, "seeded")


# ---------------------------------------------------------------------------
# 运单主数据演示数据
# ---------------------------------------------------------------------------
# 用于判定「运单属于哪条线路」，从而挡住跨线路提问（f50：口径混用）。
# YD20261030009 故意放在华北，用来演示「授权有效但线路不符」被拒。
DEMO_SHIPMENTS = [
    ("YD20261030001", "试点干线-华东", "杭州 · 某家电客户", "in_transit"),
    ("YD20261030002", "试点干线-华东", "宁波 · 某建材客户", "delivered"),
    ("YD20261030009", "试点干线-华北", "北京 · 某商超客户", "in_transit"),
]


def _seed_shipments(conn: sqlite3.Connection, created: str) -> None:
    for shipment, lane, customer, status in DEMO_SHIPMENTS:
        conn.execute(
            "INSERT OR IGNORE INTO shipments"
            " (shipment_no, lane_scope, customer, status, is_demo, created_at)"
            " VALUES (?,?,?,?,1,?)",
            (shipment, lane, customer, status, created),
        )


# ---------------------------------------------------------------------------
# 运单级授权演示数据
# ---------------------------------------------------------------------------
# 故意留出五种情况，方便演示：
#   u_rule  YD20261030001 生效
#   u_rule  YD20261030009 生效，但运单在华北、会话在华东 → 线路不符被拒
#   u_sup1  YD20261030002 生效
#   u_sup2  YD20261030001 已撤销
#   u_audit YD20261030001 已过期（2026-10-01 到期）
DEMO_GRANTS = [
    ("g_001", "u_rule", "YD20261030001", "active", "u_sys", None, None,
     "规则管理员查试点首单"),
    ("g_002", "u_rule", "YD20261030009", "active", "u_sys", None, None,
     "跨线路：授权有效但不满足线路约束"),
    ("g_003", "u_sup1", "YD20261030002", "active", "u_sys", None, None,
     "客服主管跟进异常"),
    ("g_004", "u_sup2", "YD20261030001", "revoked", "u_sys", None, "2026-10-29T16:00:00",
     "已撤销：移交他人跟进"),
    ("g_005", "u_audit", "YD20261030001", "active", "u_sys", "2026-10-01T00:00:00", None,
     "临时授权已过期"),
]


def _seed_grants(conn: sqlite3.Connection, created: str) -> None:
    lane_by_shipment = {shipment: lane for shipment, lane, _, _ in DEMO_SHIPMENTS}
    for gid, uid, shipment, status, granted_by, expires_at, revoked_at, reason in DEMO_GRANTS:
        conn.execute(
            "INSERT OR IGNORE INTO authorization_grants"
            " (id, user_id, shipment_no, lane_scope, status, granted_by, granted_at,"
            "  expires_at, revoked_at, reason, is_demo)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,1)",
            (gid, uid, shipment, lane_by_shipment.get(shipment, ""), status, granted_by,
             created, expires_at, revoked_at, reason),
        )
