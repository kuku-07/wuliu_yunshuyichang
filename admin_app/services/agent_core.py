"""阶段 2 适配层：把阶段 1 原型的核心模块接到 SQLite 知识库上。

设计约束（来自 复用阶段 1 模块的约束）：

- 检索（HybridRetriever）、闸门（redline_gate）、提示词拼装（build_context_block）、
  护栏自检（check_output）、LLM 抽象（LLMClient）全部**直接复用**，
  不在这里重写算法；
- 唯一变化是数据源：从「单个 Markdown 文件」换成「kb_chunks 里 is_active=1 的切片」，
  这样后台改了规则、发布了新版本，对话入口立刻用上新规则。

原型脚本没有做成包（没有 __init__.py），这里用 importlib 按路径加载，
避免为了 import 去改原型的目录结构。
"""
from __future__ import annotations

import importlib.util
import sys
import threading
from pathlib import Path
from typing import Any, Optional

from ..security import strip_injection

_PROTOTYPE_PATH = Path(__file__).resolve().parents[2] / "prototype" / "phase1_cli.py"

_core_lock = threading.Lock()
_core_module: Any = None

_retriever_lock = threading.Lock()
_retriever_cache: dict[str, Any] = {"key": None, "retriever": None, "chunks": None}


def core() -> Any:
    """惰性加载原型模块。原型自带降级逻辑，缺第三方库也能跑。"""
    global _core_module
    if _core_module is not None:
        return _core_module
    with _core_lock:
        if _core_module is None:
            if not _PROTOTYPE_PATH.exists():
                raise RuntimeError(f"找不到阶段 1 原型：{_PROTOTYPE_PATH}")
            spec = importlib.util.spec_from_file_location("phase1_cli", _PROTOTYPE_PATH)
            if spec is None or spec.loader is None:
                raise RuntimeError(f"无法加载阶段 1 原型：{_PROTOTYPE_PATH}")
            module = importlib.util.module_from_spec(spec)
            sys.modules.setdefault("phase1_cli", module)
            spec.loader.exec_module(module)
            _core_module = module
    return _core_module


def app_config() -> Any:
    """原型配置对象，字段全部来自环境变量（无 Key 时自动离线兜底）。"""
    return core().AppConfig()


def _index_key(conn) -> tuple:
    """索引版本标识：重建索引或切片数量变化时自动失效缓存。"""
    row = conn.execute(
        "SELECT last_rebuild, active_chunks FROM kb_index_state WHERE id = 1"
    ).fetchone()
    if row is None:
        return ("", 0)
    return (row["last_rebuild"] or "", int(row["active_chunks"] or 0))


def load_chunks(conn) -> list:
    """从知识库读出当前生效切片，转成原型认识的 Chunk 对象。

    只取 is_active=1 且文档状态为 active 的切片——草稿和已下线的规则
    绝不能进入检索，否则会用一份没发布的规则回答一线问题。
    """
    rows = conn.execute(
        "SELECT ch.id, ch.chunk_no, ch.section, ch.text, ch.version,"
        "       d.id AS doc_id, d.title, d.lane_scope, d.effective_from"
        "  FROM kb_chunks ch"
        "  JOIN kb_documents d ON d.id = ch.doc_id"
        " WHERE ch.is_active = 1 AND d.status = 'active'"
        " ORDER BY d.id, ch.chunk_no"
    ).fetchall()

    chunks = []
    for row in rows:
        chunk = core().Chunk(
            chunk_id=int(row["chunk_no"]),
            section=row["section"],
            # 检索端再洗一遍：老数据或直接改库的内容同样进不了提示词
            text=strip_injection(row["text"])[0],
            doc_title=row["title"],
            doc_version=row["version"],
            effective_from=row["effective_from"] or "",
            lane_scope=row["lane_scope"] or "all",
        )
        # 原型只用 chunk_no 做展示编号；引用落库需要真实的文档/切片主键，
        # 这里挂在对象上带走，避免为了拿 ID 再查一次库。
        chunk.db_doc_id = row["doc_id"]
        chunk.db_chunk_id = row["id"]
        chunks.append(chunk)
    return chunks


def get_retriever(conn) -> Optional[Any]:
    """带缓存的检索器。索引键不变就复用，避免每次提问都重建 BM25 + 向量。"""
    key = _index_key(conn)
    with _retriever_lock:
        if _retriever_cache["key"] == key and _retriever_cache["retriever"] is not None:
            return _retriever_cache["retriever"]

        chunks = load_chunks(conn)
        if not chunks:
            _retriever_cache.update({"key": key, "retriever": None, "chunks": []})
            return None

        retriever = core().HybridRetriever(chunks, app_config())
        _retriever_cache.update({"key": key, "retriever": retriever, "chunks": chunks})
        return retriever


def search(conn, question: str, lane_scope: str = "", top_k: int = 0) -> Optional[list]:
    """按线路检索。返回 None 表示知识库不可用，[] 表示本线路没有生效规则。

    注意这里**故意不沿用原型的兜底**：原型在过滤后为空时会退回全量切片，
    那会把别的片区的口径拿来回答（f50 的典型事故）。线路没有规则就返回空，
    让上层老老实实回答「未覆盖」。
    """
    retriever = get_retriever(conn)
    if retriever is None:
        return None

    lane = (lane_scope or "").strip()
    if lane:
        has_lane = any(
            (chunk.lane_scope or "").strip() in {"all", lane} for chunk in retriever.chunks
        )
        if not has_lane:
            return []

    cfg = app_config()
    return retriever.search(
        question, top_k=top_k or cfg.top_k, lane_scope=lane or None
    )


def invalidate_retriever() -> None:
    """后台重建索引后主动清缓存（正常情况下索引键变化也会自动失效）。"""
    with _retriever_lock:
        _retriever_cache.update({"key": None, "retriever": None, "chunks": None})


def gate(question: str) -> dict | None:
    """确定性红线闸门。

    同时取两套规则里命中更早的那个：
    原型那套覆盖赔付/危险品/紧急事故/判责/扣罚，后台试跑那套额外覆盖
    「直接发给客户」这类越界表述。两套并集只会更保守，不会更宽松。
    """
    from . import prompt as prompt_service

    result = core().redline_gate(question)
    if result.blocked:
        return {
            "reason_code": result.reason_code,
            "message": result.message,
            "matched_terms": list(result.matched_terms),
        }
    return prompt_service.redline_gate(question)


def check_output(answer: str) -> Any:
    return core().check_output(answer)


def build_context_block(hits) -> str:
    return core().build_context_block(hits)


def build_llm_client():
    return core().build_llm_client(app_config())


def llm_label() -> tuple[str, str]:
    """返回 (provider, 展示用标签)，用于 done 事件与审计。"""
    cfg = app_config()
    if cfg.llm_provider == "openai_compatible" and cfg.llm_api_key:
        return cfg.llm_provider, cfg.llm_model
    return "offline", "OfflineExtractiveLLM"
