"""规则文档解析、切片与冲突检测。"""
from __future__ import annotations

import io
import re
import sqlite3
from difflib import SequenceMatcher

from ..security import mask_pii

HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.*\S)\s*$")


class PdfWithoutText(Exception):
    """PDF 能打开但没有文字层（扫描件）。"""


def parse_document(filename: str, data: bytes) -> str:
    """把 .md 或 .pdf 解析成纯文本；失败抛中文异常。"""
    lower = filename.lower()
    if lower.endswith(".md"):
        text = data.decode("utf-8", errors="replace")
        return _strip_front_matter(text)
    if lower.endswith(".pdf"):
        try:
            from pypdf import PdfReader
        except ImportError as exc:  # pragma: no cover
            raise ValueError("服务器缺少 PDF 解析组件，请上传 Markdown") from exc
        try:
            reader = PdfReader(io.BytesIO(data))
            pages = [(page.extract_text() or "") for page in reader.pages]
        except Exception as exc:
            raise ValueError("PDF 解析失败，请确认文件未加密且可正常打开") from exc
        text = "\n".join(pages).strip()
        if len(re.sub(r"\s", "", text)) < 50:
            raise PdfWithoutText("该 PDF 无文字层，请先 OCR 后再上传")
        return text
    raise ValueError("仅支持 .md 和 .pdf 文件")


def _strip_front_matter(text: str) -> str:
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            return parts[2].lstrip("\n")
    return text


def extract_sections(text: str) -> list[tuple[str, str]]:
    """按 Markdown 标题分组；PDF 无标题时整体归入「正文」。"""
    sections: list[tuple[str, list[str]]] = []
    current_title = "正文"
    buffer: list[str] = []

    def flush() -> None:
        body = "\n".join(buffer).strip()
        if body:
            sections.append((current_title, body.splitlines()))

    for line in text.splitlines():
        match = HEADING_RE.match(line)
        if match:
            flush()
            current_title = match.group(2).strip()
            buffer = []
            continue
        buffer.append(line)
    flush()
    if not sections:
        sections = [("正文", text.splitlines())]
    return [(title, "\n".join(lines).strip()) for title, lines in sections if "\n".join(lines).strip()]


def chunk_text(text: str, size: int = 500, overlap: int = 80) -> list[dict]:
    """500 字切片、80 字重叠；每片带所在章节。"""
    result: list[dict] = []
    for section, body in extract_sections(text):
        start = 0
        while start < len(body):
            piece = body[start:start + size].strip()
            if len(piece) >= 20:
                result.append({"section": section, "text": piece})
            if start + size >= len(body):
                break
            start += size - overlap
    return result


def mask_all(chunks: list[dict]) -> tuple[list[dict], int]:
    """切片入库前统一脱敏，返回脱敏后的切片与命中总数。"""
    total = 0
    cleaned = []
    for chunk in chunks:
        masked, hits = mask_pii(chunk["text"])
        total += hits
        cleaned.append({"section": chunk["section"], "text": masked})
    return cleaned, total


def find_conflicts(conn: sqlite3.Connection, doc_id: str, version: str) -> list[dict]:
    """与当前生效版本对比：同章节但文本相似度处于「可能冲突」区间的，提示人工复核。"""
    draft = conn.execute(
        "SELECT section, text FROM kb_chunks WHERE doc_id=? AND version=? ORDER BY chunk_no",
        (doc_id, version),
    ).fetchall()
    active = conn.execute(
        "SELECT section, text FROM kb_chunks WHERE doc_id=? AND is_active=1 ORDER BY chunk_no",
        (doc_id,),
    ).fetchall()
    conflicts = []
    for new in draft:
        for old in active:
            if new["section"] != old["section"]:
                continue
            ratio = SequenceMatcher(None, old["text"], new["text"]).ratio()
            if 0.30 <= ratio < 0.85:
                conflicts.append(
                    {
                        "section": new["section"],
                        "old": old["text"][:120],
                        "new": new["text"][:120],
                        "ratio": round(ratio, 2),
                    }
                )
    return conflicts[:5]


def next_version(current: str) -> str:
    try:
        value = float(current)
    except (TypeError, ValueError):
        return "0.1"
    return f"{value + 0.1:.1f}"
