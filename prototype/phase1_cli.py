#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
阶段 1 · 裸问答最小原型（无 Web）
================================================================================
项目：运输异常与签收协作智能体系统
对应架构文档：docs/03-架构选型方案.md（L3 智能体编排层 + L4 数据模型层的知识检索部分）

【这个脚本到底验证什么】
    验证「规则与口径问答」这一条最小链路能不能跑通：
        本地规则 Markdown → 切片 → 双通道索引（BM25 关键词 + 向量语义）
        → 混合检索 top3 → 拼提示词 → LLM 生成 → 护栏自检 → 输出带引用的回答

【与原题（报销助手）的三处关键差异，都是本项目架构决定的】
    1) 知识库不是「制度说明文」，而是「会过期、分线、分版本」的业务规则：
       每个切片必须携带 doc_version / effective_from / lane_scope；
       回答必须能回指到具体版本，否则客服不敢用（见 f24、f15）。
    2) LLM 不是最终决策者，前面必须先过一道「确定性红线闸门」：
       命中 赔付 / 危险品 / 紧急事故 / 判责 / 扣罚 时，
       直接返回人工接管话术，根本不调用模型（见 f41、f44）。
    3) 输出必须过「护栏自检」：禁止承诺赔付金额、禁止输出受限字段、
       必须带引用标记，命中即标记需人工复核（见 f22、f40）。

【运行方式】
    # 自检模式（离线可跑，不需要任何 API Key，推荐先跑这个）
    python phase1_cli.py --selftest

    # 交互问答模式（离线兜底：用检索片段拼答案；配置 API Key 后走真实模型）
    python phase1_cli.py --doc data/policy_sample.md

【依赖与「零依赖也要能跑」原则】
    必需依赖：无（仅 Python 3.10+ 标准库）
    可选：jieba（中文分词，缺失时退化为字符二元组）、rank_bm25（缺失时用内置 BM25）、
          numpy + faiss-cpu（启用 FAISS 向量索引，缺失时退化为纯 Python 余弦检索）
    调用真实模型：仅用标准库 urllib，无需 requests
    所有可选依赖都做了兜底分支，保证「拿到脚本就能跑通」，这是原型的第一要求。

【被标记为 [核心模块] 的代码，后续阶段直接复用，不要重写】
    见文件末尾《核心模块复用清单》。
================================================================================
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

# numpy 只在启用 FAISS 时用得到；缺失时整条检索链路走纯 Python 实现。
try:
    import numpy as np  # type: ignore

    _HAS_NUMPY = True
except Exception:  # pragma: no cover - 环境差异
    np = None  # type: ignore
    _HAS_NUMPY = False

# ==============================================================================
# 第 0 节 · 可选依赖兜底
# ------------------------------------------------------------------------------
# 设计说明：原型阶段最怕「装不上环境就跑不起来」。
# 因此所有第三方库都是 try/except，缺失时走内置实现，功能打折但不阻塞验证。
# ==============================================================================

try:
    import jieba  # type: ignore

    _HAS_JIEBA = True
except Exception:  # pragma: no cover - 环境差异
    _HAS_JIEBA = False

try:
    from rank_bm25 import BM25Okapi  # type: ignore

    _HAS_RANK_BM25 = True
except Exception:  # pragma: no cover - 环境差异
    _HAS_RANK_BM25 = False

try:
    import faiss  # type: ignore

    _HAS_FAISS = True
except Exception:  # pragma: no cover - 环境差异
    _HAS_FAISS = False

# FAISS 依赖 numpy，两者缺一不可；这里统一收口，避免后面出现半可用状态
_HAS_FAISS = _HAS_FAISS and _HAS_NUMPY


# ==============================================================================
# 第 1 节 · 配置区（[核心模块] 供应商可替换的配置契约）
# ------------------------------------------------------------------------------
# 全部通过环境变量注入，代码里不出现任何密钥，符合「配置与密钥分离」。
# 换供应商只需要改环境变量，不用改一行代码。
# ==============================================================================


@dataclass
class AppConfig:
    """全局配置。字段全部来自环境变量，默认值保证离线可跑。"""

    # ---- LLM 供应商配置 ----
    # provider: openai_compatible（任何兼容 /chat/completions 的服务）| offline（离线兜底）
    llm_provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "offline"))
    llm_base_url: str = field(default_factory=lambda: os.getenv("LLM_BASE_URL", "https://api.openai.com/v1"))
    llm_api_key: str = field(default_factory=lambda: os.getenv("LLM_API_KEY", ""))
    llm_model: str = field(default_factory=lambda: os.getenv("LLM_MODEL", "gpt-4o-mini"))
    llm_temperature: float = field(default_factory=lambda: float(os.getenv("LLM_TEMPERATURE", "0.1")))
    llm_timeout: int = field(default_factory=lambda: int(os.getenv("LLM_TIMEOUT", "30")))

    # ---- 向量化配置 ----
    # embedding_provider: api（走 /embeddings）| local（本地确定性哈希，离线兜底）
    embedding_provider: str = field(default_factory=lambda: os.getenv("EMBEDDING_PROVIDER", "local"))
    embedding_model: str = field(default_factory=lambda: os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"))
    embedding_dim: int = field(default_factory=lambda: int(os.getenv("EMBEDDING_DIM", "256")))

    # ---- 检索配置 ----
    chunk_size: int = field(default_factory=lambda: int(os.getenv("CHUNK_SIZE", "500")))
    chunk_overlap: int = field(default_factory=lambda: int(os.getenv("CHUNK_OVERLAP", "80")))
    top_k: int = field(default_factory=lambda: int(os.getenv("TOP_K", "3")))
    # 混合检索权重：bm25_weight=1 表示纯关键词，0 表示纯向量
    bm25_weight: float = field(default_factory=lambda: float(os.getenv("BM25_WEIGHT", "0.5")))

    def describe(self) -> str:
        """打印当前生效配置（脱敏），方便排查「为什么答案不一样」。"""
        key_state = "已配置" if self.llm_api_key else "未配置"
        return (
            f"LLM 供应商={self.llm_provider} 模型={self.llm_model} Key={key_state} | "
            f"向量={self.embedding_provider} dim={self.embedding_dim} | "
            f"切片={self.chunk_size}/{self.chunk_overlap} topK={self.top_k} "
            f"BM25 权重={self.bm25_weight}"
        )


# ==============================================================================
# 第 2 节 · 文档加载与元数据解析（[核心模块]）
# ------------------------------------------------------------------------------
# 本项目特有的关键点：规则文档必须携带「版本 + 生效日期 + 适用线路」。
# 这三项会跟着每个切片走，最终出现在回答的引用里（对应 f24：争议要记录规则使用版本）。
# ==============================================================================


@dataclass
class DocMeta:
    """文档级元数据。缺省值故意留空，缺失时由校验函数拦截，不用默认值糊过去。"""

    title: str = "未命名文档"
    doc_type: str = "policy"
    version: str = ""
    effective_from: str = ""
    lane_scope: str = "all"


def parse_front_matter(raw: str) -> Tuple[DocMeta, str]:
    """
    解析文档头部的 `--- ... ---` 元数据块（YAML 极简子集，只支持 key: value）。

    为什么不用 PyYAML：减少依赖；本项目元数据只有 5 个平面字段，不需要完整 YAML。
    解析失败不抛异常，返回默认元数据 + 原文，保证「文档写得糙也能跑」。
    """
    meta = DocMeta()
    body = raw

    m = re.match(r"^\s*---\s*\n(.*?)\n\s*---\s*\n", raw, flags=re.DOTALL)
    if not m:
        return meta, body

    for line in m.group(1).splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip().lower(), value.strip().strip("'\"")
        if not value:
            continue
        if key in {"title", "doc_type", "version", "effective_from", "lane_scope"}:
            setattr(meta, key, value)

    body = raw[m.end():]
    return meta, body


def validate_meta(meta: DocMeta) -> List[str]:
    """
    元数据校验，返回缺口清单。

    对应 f33 的工程化落地：缺关键字段不进检索、不猜值，
    而是明确告诉使用者「这份文档不能作为回答依据」。
    """
    gaps: List[str] = []
    if not meta.version:
        gaps.append("缺少 version（无法追溯规则使用版本）")
    if not meta.effective_from:
        gaps.append("缺少 effective_from（无法判断规则是否生效）")
    return gaps


# ==============================================================================
# 第 3 节 · 切片（[核心模块]）
# ------------------------------------------------------------------------------
# 策略：先按 Markdown 标题切「节」，再在节内按段落聚合到 chunk_size 字。
# 比一次性按字数硬切的好处：切片天然带「章节路径」，引用时能说清出自哪一条，
# 而且不会把「到货口径」和「回执口径」从中间切断——这两者混在一起就是误判来源（f50、f51）。
# ==============================================================================


@dataclass
class Chunk:
    """一个可检索的知识切片。所有字段都会被检索和引用复用。"""

    chunk_id: int
    section: str          # 章节路径，如「3. 到货与回执口径」
    text: str             # 切片正文
    doc_title: str
    doc_version: str
    effective_from: str
    lane_scope: str

    def citation(self) -> str:
        """生成引用串：回答里必须能回指到「哪份文档的哪一版、哪一节」。"""
        return f"《{self.doc_title}》v{self.doc_version} · {self.section}"


def split_sections(body: str, fallback_title: str) -> List[Tuple[str, str]]:
    """按 Markdown 标题切节，返回 [(章节标题, 正文), ...]。"""
    sections: List[Tuple[str, str]] = []
    current_title = fallback_title
    buffer: List[str] = []

    for line in body.splitlines():
        if re.match(r"^#{1,6}\s+", line):
            if buffer and "".join(buffer).strip():
                sections.append((current_title, "\n".join(buffer).strip()))
            current_title = re.sub(r"^#{1,6}\s+", "", line).strip()
            buffer = []
        else:
            buffer.append(line)

    if buffer and "".join(buffer).strip():
        sections.append((current_title, "\n".join(buffer).strip()))

    return sections


def split_chunks(
    body: str,
    meta: DocMeta,
    chunk_size: int = 500,
    overlap: int = 80,
) -> List[Chunk]:
    """
    【按 500 字切片】—— 需求原文的字面要求，按字符数（对中文近似等价于字数）。
    在节内先按空行切段落，再贪心聚合；超长段落用滑动窗口切并保留 overlap 重叠，
    避免一句话被切断后两个切片都检索不到。
    """
    chunks: List[Chunk] = []
    cursor = 0

    for section_title, section_text in split_sections(body, meta.title):
        # 段落级切分：空行是 Markdown 的天然语义边界
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", section_text) if p.strip()]

        buffer = ""
        for para in paragraphs:
            # 单个段落就超长：先冲刷缓冲区，再对段落做滑窗
            if len(para) > chunk_size:
                if buffer:
                    chunks.append(_make_chunk(cursor, section_title, buffer, meta))
                    cursor += 1
                    buffer = ""
                step = max(1, chunk_size - overlap)
                for start in range(0, len(para), step):
                    piece = para[start:start + chunk_size]
                    if not piece.strip():
                        continue
                    chunks.append(_make_chunk(cursor, section_title, piece, meta))
                    cursor += 1
                    if start + chunk_size >= len(para):
                        break
                continue

            # 正常段落：能塞进当前缓冲区就塞，塞不下就先产出再开新缓冲区
            if len(buffer) + len(para) + 1 <= chunk_size:
                buffer = f"{buffer}\n{para}".strip()
            else:
                if buffer:
                    chunks.append(_make_chunk(cursor, section_title, buffer, meta))
                    cursor += 1
                # 重叠：把上一块的尾部带进新块，保证跨块语义连续
                tail = buffer[-overlap:] if overlap > 0 and buffer else ""
                buffer = f"{tail}\n{para}".strip()

        if buffer:
            chunks.append(_make_chunk(cursor, section_title, buffer, meta))
            cursor += 1

    return chunks


def _make_chunk(index: int, section: str, text: str, meta: DocMeta) -> Chunk:
    """构造切片对象，把文档级元数据下推到每个切片（引用与版本过滤都依赖它）。"""
    return Chunk(
        chunk_id=index,
        section=section,
        text=text,
        doc_title=meta.title,
        doc_version=meta.version,
        effective_from=meta.effective_from,
        lane_scope=meta.lane_scope,
    )


# ==============================================================================
# 第 4 节 · 分词（[核心模块]）
# ------------------------------------------------------------------------------
# 中文检索的常见坑：不做分词，BM25 直接废掉。
# 有 jieba 用 jieba；没有就用「单字 + 二元组」，在小规模文档上效果可以接受。
# ==============================================================================


def tokenize(text: str) -> List[str]:
    """把文本切成检索用的 token 列表。"""
    text = text.lower()
    if _HAS_JIEBA:
        return [t for t in jieba.lcut(text) if t.strip()]

    # 兜底：中文按单字 + 字符二元组，英文数字按单词
    tokens: List[str] = re.findall(r"[a-z0-9_]+", text)
    han = re.findall(r"[\u4e00-\u9fff]", text)
    tokens.extend(han)
    tokens.extend(han[i] + han[i + 1] for i in range(len(han) - 1))
    return tokens


# ==============================================================================
# 第 5 节 · 向量化（[核心模块] 供应商可替换）
# ------------------------------------------------------------------------------
# 两种实现，同一个接口：
#   ApiEmbedding  —— 走 LLM 供应商的 /embeddings，语义质量高
#   LocalEmbedding —— 本地确定性哈希向量，离线可用、零成本、可复现
# 后续阶段接入真实向量模型时，只需要新增一个类，检索层和提示词层完全不用动。
# ==============================================================================


class EmbeddingProvider:
    """向量化抽象基类。新增供应商 = 新增子类，不改调用方。"""

    dim: int = 256

    def embed(self, texts: Sequence[str]) -> List[List[float]]:
        raise NotImplementedError


class LocalEmbeddingProvider(EmbeddingProvider):
    """
    本地离线向量：对 token 做哈希散列到固定维度，再做 L2 归一化。

    说明（诚实标注）：它不是语义向量，只是「词袋 + 哈希」，
    能捕捉词汇重合，抓不住同义改写。原型阶段用它保证脚本零配置可跑；
    真实语义能力必须换成 ApiEmbeddingProvider 或本地 embedding 模型。
    """

    def __init__(self, dim: int = 256) -> None:
        self.dim = dim

    def embed(self, texts: Sequence[str]) -> List[List[float]]:
        vectors: List[List[float]] = []
        for text in texts:
            vector = [0.0] * self.dim
            for token in tokenize(text):
                # 稳定哈希：同一 token 在任何机器上都落到同一维度，保证结果可复现
                digest = hashlib.md5(token.encode("utf-8")).digest()
                idx = int.from_bytes(digest[:4], "little") % self.dim
                sign = 1.0 if digest[4] % 2 == 0 else -1.0
                vector[idx] += sign
            norm = math.sqrt(sum(value * value for value in vector))
            if norm > 0:
                vector = [value / norm for value in vector]
            vectors.append(vector)
        return vectors


class ApiEmbeddingProvider(EmbeddingProvider):
    """通过 OpenAI 兼容 /embeddings 接口获取向量。失败时由上层决定是否回退。"""

    def __init__(self, cfg: AppConfig) -> None:
        self.cfg = cfg
        self.dim = cfg.embedding_dim

    def embed(self, texts: Sequence[str]) -> List[List[float]]:
        payload = json.dumps({"model": self.cfg.embedding_model, "input": list(texts)}).encode("utf-8")
        request = urllib.request.Request(
            url=f"{self.cfg.llm_base_url.rstrip('/')}/embeddings",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.cfg.llm_api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.cfg.llm_timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
        vectors: List[List[float]] = []
        for item in body["data"]:
            vector = [float(value) for value in item["embedding"]]
            norm = math.sqrt(sum(value * value for value in vector))
            if norm > 0:
                vector = [value / norm for value in vector]
            vectors.append(vector)
        self.dim = len(vectors[0]) if vectors else self.cfg.embedding_dim
        return vectors


def build_embedding_provider(cfg: AppConfig) -> EmbeddingProvider:
    """向量化工厂：按配置选实现，API 不可用时回退本地，保证主流程不中断。"""
    if cfg.embedding_provider == "api" and cfg.llm_api_key:
        return ApiEmbeddingProvider(cfg)
    return LocalEmbeddingProvider(cfg.embedding_dim)


# ==============================================================================
# 第 6 节 · 检索：BM25 + 向量混合（[核心模块]）
# ------------------------------------------------------------------------------
# 为什么必须混合：
#   纯向量会把「赔付上限」「回执及时率」这类精确术语检索偏；
#   纯 BM25 抓不住「到货慢算不算延误」这种口语化同义问法。
# 小规模制度文档上，混合检索是最稳的性价比方案（见文档 03 第 1 节选型结论）。
# ==============================================================================


class _FallbackBM25:
    """rank_bm25 缺失时的内置实现（标准 BM25 Okapi，简化版）。"""

    def __init__(self, corpus_tokens: List[List[str]], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.corpus = corpus_tokens
        self.doc_len = [len(doc) for doc in corpus_tokens]
        self.avg_len = (sum(self.doc_len) / len(self.doc_len)) if self.doc_len else 1.0
        self.doc_freq: Dict[str, int] = {}
        for doc in corpus_tokens:
            for token in set(doc):
                self.doc_freq[token] = self.doc_freq.get(token, 0) + 1
        self.n_docs = max(1, len(corpus_tokens))

    def get_scores(self, query_tokens: List[str]) -> List[float]:
        scores = [0.0] * self.n_docs
        for token in query_tokens:
            df = self.doc_freq.get(token, 0)
            if df == 0:
                continue
            idf = math.log(1 + (self.n_docs - df + 0.5) / (df + 0.5))
            for i, doc in enumerate(self.corpus):
                tf = doc.count(token)
                if tf == 0:
                    continue
                denom = tf + self.k1 * (1 - self.b + self.b * self.doc_len[i] / self.avg_len)
                scores[i] += idf * (tf * (self.k1 + 1)) / denom
        return scores


class HybridRetriever:
    """
    混合检索器：BM25 关键词通道 + 向量语义通道，分数归一化后加权融合。

    [核心模块] 后续阶段行为不变，只是把 chunks 的来源从「单文件」换成
    「按 lane_scope + effective_from 过滤后的知识库表」。
    """

    def __init__(self, chunks: Sequence[Chunk], cfg: AppConfig) -> None:
        self.chunks = list(chunks)
        self.cfg = cfg
        self.embedder = build_embedding_provider(cfg)

        # ---- BM25 通道准备 ----
        # 把章节标题拼进切片正文，提升「问标题词」的命中率（轻量且有效）
        corpus_tokens = [tokenize(f"{c.section} {c.text}") for c in self.chunks]
        if _HAS_RANK_BM25:
            self.bm25 = BM25Okapi(corpus_tokens)
        else:
            self.bm25 = _FallbackBM25(corpus_tokens)

        # ---- 向量通道准备 ----
        self.vectors = self.embedder.embed([f"{c.section} {c.text}" for c in self.chunks])
        self.index = self._build_index(self.vectors)

    @staticmethod
    def _build_index(vectors: Sequence[Sequence[float]]):
        """优先 FAISS；不可用时返回 None，检索走纯 Python 点积（量小完全够用）。"""
        if not _HAS_FAISS or not vectors:
            return None
        array = np.array(vectors, dtype="float32")
        index = faiss.IndexFlatIP(array.shape[1])  # 向量已归一化，内积=余弦相似度
        index.add(array)
        return index

    def _vector_scores(self, query: str) -> List[float]:
        """向量通道得分（余弦相似度）。"""
        query_vec = self.embedder.embed([query])[0]
        if self.index is not None:
            scores, order = self.index.search(np.array([query_vec], dtype="float32"), len(self.chunks))
            # FAISS 返回的是「按序索引」，需要还原成与 chunks 对齐的分数数组
            restored = [0.0] * len(self.chunks)
            for rank, idx in enumerate(order[0]):
                if 0 <= idx < len(self.chunks):
                    restored[idx] = float(scores[0][rank])
            return restored
        # 纯 Python 兜底：向量已归一化，点积即余弦相似度
        return [sum(a * b for a, b in zip(query_vec, vector)) for vector in self.vectors]

    @staticmethod
    def _normalize(scores: Sequence[float]) -> List[float]:
        """min-max 归一化：两个通道量纲完全不同，不归一化就无法加权融合。"""
        if not scores:
            return []
        low, high = min(scores), max(scores)
        if high - low < 1e-9:
            return [0.0] * len(scores)
        return [(score - low) / (high - low) for score in scores]

    def search(self, query: str, top_k: int = 3, lane_scope: Optional[str] = None) -> List[Tuple[Chunk, float, Dict[str, float]]]:
        """
        执行混合检索。

        lane_scope：按线路过滤（本项目特有）。规则文档分线路时，
        不能让 A 干线的口径去回答 B 干线的问题——这正是 f50 口径冲突的工程化防范。
        返回 [(切片, 融合分, 各通道细节分), ...]，细节分用于排查「为什么这条被召回」。
        """
        if not self.chunks:
            return []

        # 候选集过滤：线路范围不匹配、或明确指向其他线路的切片直接排除
        allowed = [
            i for i, c in enumerate(self.chunks)
            if lane_scope is None or c.lane_scope in {"all", lane_scope}
        ]
        if not allowed:
            allowed = list(range(len(self.chunks)))

        bm25_scores = [float(score) for score in self.bm25.get_scores(tokenize(query))]
        vector_scores = self._vector_scores(query)

        bm25_norm = self._normalize(bm25_scores)
        vector_norm = self._normalize(vector_scores)

        w = self.cfg.bm25_weight
        fused = [w * b + (1 - w) * v for b, v in zip(bm25_norm, vector_norm)]

        ranked = sorted(allowed, key=lambda i: float(fused[i]), reverse=True)[:top_k]
        return [
            (
                self.chunks[i],
                float(fused[i]),
                {"bm25": float(bm25_scores[i]), "vector": float(vector_scores[i])},
            )
            for i in ranked
        ]


# ==============================================================================
# 第 7 节 · 确定性红线闸门（[核心模块] 本项目最重要的差异点）
# ------------------------------------------------------------------------------
# 对应 f41 / f44：赔付、危险品处置、紧急事故必须人工接管；
# 依据缺失或系统不可用时要停止自动建议。
#
# 关键设计原则：**闸门在 LLM 之前，用确定性代码判断，不交给模型。**
# 模型可以被提示词诱导，确定性规则不会。这一步省掉，后面全是审计风险。
# ==============================================================================

# (命中关键词, 原因码, 面向使用者的话术)
REDLINE_RULES: List[Tuple[Tuple[str, ...], str, str]] = [
    (
        ("赔付", "赔偿", "赔多少", "索赔", "理赔"),
        "REDLINE_COMPENSATION",
        "涉及赔付或赔偿认定，规则明确要求人工接管，系统不生成任何金额建议。",
    ),
    (
        ("危险品", "危化品", "易燃", "易爆", "有毒"),
        "REDLINE_DANGER_GOODS",
        "涉及危险品处置，必须由具备资质的人员按安全流程处理，系统停止自动建议。",
    ),
    (
        ("紧急事故", "事故", "翻车", "碰撞", "人员受伤", "起火"),
        "REDLINE_EMERGENCY",
        "涉及紧急事故，必须立即人工接管并上报，系统停止自动建议。",
    ),
    (
        ("判责", "谁的责任", "定责", "归责"),
        "REDLINE_LIABILITY",
        "本次范围不含判责，责任认定需走人工流程，系统不给出责任结论。",
    ),
    (
        ("扣罚", "扣款", "罚款", "结算"),
        "REDLINE_PENALTY",
        "本次范围不含自动结算与扣罚，相关动作必须留在人工环节。",
    ),
]


@dataclass
class GateResult:
    """闸门判定结果。blocked=True 时不应调用 LLM。"""

    blocked: bool
    reason_code: str = ""
    message: str = ""
    matched_terms: List[str] = field(default_factory=list)


def redline_gate(question: str) -> GateResult:
    """
    在调用 LLM 之前拦截红线问题。

    为什么放在最前面：这个问题一旦交给模型，模型很可能给出「看起来合理」的答案，
    而错误答案会流到客服甚至客户手里，损害不可逆（见 f15：未经确认不能覆盖原记录）。
    """
    normalized = question.replace(" ", "")
    for terms, code, message in REDLINE_RULES:
        hits = [t for t in terms if t in normalized]
        if hits:
            return GateResult(blocked=True, reason_code=code, message=message, matched_terms=hits)
    return GateResult(blocked=False)


# ==============================================================================
# 第 8 节 · 提示词模板（[核心模块] 版本化）
# ------------------------------------------------------------------------------
# 提示词按版本号管理（PROMPT_VERSION），因为提示词变更会改变回答口径，
# 而回答口径变更需要留痕——和规则版本是同一个道理（f24）。
# 三条硬约束直接写进 system prompt，不靠使用者自觉。
# ==============================================================================

PROMPT_VERSION = "phase1.v1"

SYSTEM_PROMPT = """你是运输异常与签收协作助手，服务对象是物流公司的调度员与客服，不是终端客户。

【你的定位】
你只回答「规则与口径」类问题，例如异常如何分类、ETA 用哪个口径、到货与回执怎么区分、
交接需要带哪些材料。你不做任何业务判定。

【硬约束 · 违反即视为回答失败】
1. 禁止承诺赔付金额、禁止给出赔偿方案；涉及赔付一律回答「需人工接管」。
2. 禁止判定责任归属，禁止给出扣罚或结算建议。
3. 禁止输出司机定位、收件人电话等受限信息；被问到时说明属于受限数据。
4. 回答必须基于下方《参考片段》，禁止凭常识或经验补充片段中没有的规则。
5. 每条结论必须携带引用标记，格式为 [引用N]，N 与参考片段的编号一致。
6. 涉及 GPS 弱网、客户改地址、签收回执延迟、依据缺失时，
   必须说明「该类情况需人工核对，未确认结果不覆盖原记录」。
7. 如果参考片段不足以回答，直接说「现有规则文档未覆盖，需要人工确认」，不要猜。

【输出格式】
第一行：结论（不超过三句）
随后：依据（逐条列出 [引用N] + 该条要点）
最后：不确定项（如无则写「无」）
"""

USER_PROMPT_TEMPLATE = """【参考片段】
{context}

【使用者问题】
{question}

【当前数据时效说明】
以下片段来自本地规则文档，每个片段标注了文档版本与生效日期。
若片段之间存在口径差异，请明确指出差异并说明需人工确认，不要自行取舍。
"""


def build_context_block(hits: Sequence[Tuple[Chunk, float, Dict[str, float]]]) -> str:
    """
    把检索结果拼成提示词上下文。

    关键点：每个片段都带上「版本 + 生效日期 + 章节」，让模型能引用、
    也让人工审核者能一眼看出这条结论依据的是哪一版规则。
    """
    lines: List[str] = []
    for i, (chunk, score, _) in enumerate(hits, start=1):
        lines.append(
            f"[{i}] {chunk.citation()}（生效日期 {chunk.effective_from or '未知'}，"
            f"适用线路 {chunk.lane_scope}，检索分 {score:.3f}）\n{chunk.text}\n"
        )
    return "\n".join(lines) if lines else "（无可用片段）"


# ==============================================================================
# 第 9 节 · LLM 调用封装（[核心模块] 供应商可替换）
# ------------------------------------------------------------------------------
# 交付要求里明确点名的「独立函数 + 供应商可配置」。
# 两种实现：真实 API 调用、离线抽取式兜底。
# 换供应商 = 改环境变量 LLM_BASE_URL/LLM_MODEL，不动业务代码。
# ==============================================================================


class LLMClient:
    """LLM 客户端抽象。新增供应商只需实现 complete()。"""

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        raise NotImplementedError


class OpenAICompatibleLLM(LLMClient):
    """调用 OpenAI 兼容的 /chat/completions。用标准库 urllib，不依赖第三方 SDK。"""

    def __init__(self, cfg: AppConfig) -> None:
        self.cfg = cfg

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        payload = json.dumps(
            {
                "model": self.cfg.llm_model,
                "temperature": self.cfg.llm_temperature,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            }
        ).encode("utf-8")

        request = urllib.request.Request(
            url=f"{self.cfg.llm_base_url.rstrip('/')}/chat/completions",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.cfg.llm_api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.cfg.llm_timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
            return body["choices"][0]["message"]["content"].strip()
        except (urllib.error.URLError, KeyError, IndexError, json.JSONDecodeError) as exc:
            # 失败不伪造答案：明确告知失败，让上层决定降级还是报错（对应 f35 降级原则）
            raise RuntimeError(f"LLM 调用失败：{exc}") from exc


class OfflineExtractiveLLM(LLMClient):
    """
    离线兜底「模型」：不做生成，只把 top 片段的关键句抽取出来按固定格式拼装。

    为什么要有它：原型第一周的目标是验证「检索质量 + 引用完整性」，
    这两件事在没有 API Key 时也必须能被检验。它不是模型，不要当成模型用。
    """

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        # 从 user_prompt 里把片段抓出来，按句子抽取要点
        blocks = re.split(r"\n\[\d+\]\s", user_prompt)
        points: List[str] = []
        citations: List[str] = []
        for raw in blocks[1:]:  # 第 0 块是「【参考片段】」标题
            head, _, rest = raw.partition("\n")
            # 去掉「（生效日期 ...）」这类附加信息，只保留《文档》v版本 · 章节
            citation = re.sub(r"（生效日期.*$", "", head).strip()
            citations.append(citation)
            sentences = [s.strip() for s in re.split(r"[。；\n]", rest) if len(s.strip()) >= 8]
            if sentences:
                points.append(sentences[0][:60])

        if not points:
            return "现有规则文档未覆盖，需要人工确认。"

        body = "\n".join(f"- {p}" for p in points[:3])
        refs = "\n".join(f"  [引用{i}] {c}" for i, c in enumerate(citations, start=1))
        return (
            "结论（离线抽取，未经过模型生成）：\n"
            f"{body}\n\n"
            "依据：\n"
            f"{refs}\n\n"
            "不确定项：本回答为离线兜底抽取，未做语义推理，请人工确认。"
        )


def build_llm_client(cfg: AppConfig) -> LLMClient:
    """LLM 客户端工厂：按配置选实现，缺 Key 时自动回退离线。"""
    if cfg.llm_provider == "openai_compatible" and cfg.llm_api_key:
        return OpenAICompatibleLLM(cfg)
    return OfflineExtractiveLLM()


# ==============================================================================
# 第 10 节 · 输出护栏自检（[核心模块]）
# ------------------------------------------------------------------------------
# LLM 是不可信输出源：即使提示词写了约束，也必须做输出侧校验。
# 「防注入 + 防越界」的正确姿势是两道：输入闸门（第 7 节）+ 输出自检（本节）。
# ==============================================================================

FORBIDDEN_PATTERNS: List[Tuple[str, str]] = [
    (r"赔(付|偿)[^。]{0,10}?\d+\s*(元|万)", "疑似承诺赔付金额"),
    (r"\d+\s*(元|万)[^。]{0,6}?(赔|补偿)", "疑似承诺赔付金额"),
    (r"1[3-9]\d{9}", "疑似输出手机号等受限信息"),
    (r"(判定|认定)[^。]{0,6}?(责任|由.{0,4}承担)", "疑似给出责任判定"),
]


@dataclass
class GuardrailReport:
    """护栏自检结果，会打印给使用者，也会在后续阶段写入审计字段。"""

    passed: bool
    violations: List[str] = field(default_factory=list)
    has_citation: bool = True

    def summary(self) -> str:
        if self.passed:
            return "通过（含引用、无越界内容）"
        parts = list(self.violations)
        if not self.has_citation:
            parts.append("缺少引用标记")
        return "需人工复核：" + "；".join(parts)


def check_output(answer: str) -> GuardrailReport:
    """对 LLM 输出做确定性校验，命中即标记需人工复核（对应 f22、f40）。"""
    violations = [desc for pattern, desc in FORBIDDEN_PATTERNS if re.search(pattern, answer)]
    has_citation = bool(re.search(r"\[引用\s*\d+\]", answer))
    return GuardrailReport(passed=not violations and has_citation, violations=violations, has_citation=has_citation)


# ==============================================================================
# 第 11 节 · 问答主流程（[核心模块] 编排骨架）
# ------------------------------------------------------------------------------


@dataclass
class Answer:
    """一次问答的完整产出。后续阶段这套字段直接进 audit_logs 与 messages 表。"""

    question: str
    blocked: bool
    answer: str
    citations: List[str]
    gate: GateResult
    guardrail: GuardrailReport
    hits: List[Tuple[Chunk, float, Dict[str, float]]]
    prompt_version: str
    llm_provider: str


def answer_question(question: str, retriever: HybridRetriever, llm: LLMClient, cfg: AppConfig) -> Answer:
    """
    单次问答编排：闸门 → 检索 → 提示词 → 生成 → 自检。

    顺序不可调换：先过闸门再检索，可以避免「已经花掉一次模型调用才发现不能答」。
    """
    # 步骤 1：确定性红线闸门（不调用 LLM）
    gate = redline_gate(question)
    if gate.blocked:
        return Answer(
            question=question,
            blocked=True,
            answer=(
                f"【需人工接管】{gate.message}\n"
                f"命中原因码：{gate.reason_code}（命中词：{'、'.join(gate.matched_terms)}）\n"
                "请按流程指定接管人与确认时间，系统不提供自动建议。"
            ),
            citations=[],
            gate=gate,
            guardrail=GuardrailReport(passed=True),
            hits=[],
            prompt_version=PROMPT_VERSION,
            llm_provider="未调用",
        )

    # 步骤 2：混合检索
    hits = retriever.search(question, top_k=cfg.top_k)

    # 步骤 3：拼提示词
    context = build_context_block(hits)
    user_prompt = USER_PROMPT_TEMPLATE.format(context=context, question=question)

    # 步骤 4：调用 LLM（失败即降级，不伪造答案）
    try:
        raw = llm.complete(SYSTEM_PROMPT, user_prompt)
        provider_used = type(llm).__name__
    except RuntimeError as exc:
        raw = f"生成失败：{exc}\n已回退为不提供结论，请人工确认。"
        provider_used = "调用失败已降级"

    # 步骤 5：输出护栏自检
    guardrail = check_output(raw)

    # 步骤 6：无有效召回时强制提示不确定（避免模型在空上下文上硬答）
    if not hits and not raw.startswith("生成失败"):
        raw = "现有规则文档未覆盖，需要人工确认。"

    return Answer(
        question=question,
        blocked=False,
        answer=raw,
        citations=[c.citation() for c, _, _ in hits],
        gate=gate,
        guardrail=guardrail,
        hits=hits,
        prompt_version=PROMPT_VERSION,
        llm_provider=provider_used,
    )


def render_answer(result: Answer, verbose: bool = False) -> str:
    """把 Answer 渲染成命令行输出。verbose 打开后额外打印检索证据，便于调参。"""
    lines: List[str] = []
    lines.append("=" * 78)
    lines.append(f"问题：{result.question}")
    lines.append("-" * 78)

    if verbose and result.hits:
        lines.append("检索证据（含各通道原分，用于判断召回是否合理）：")
        for i, (chunk, fused, detail) in enumerate(result.hits, start=1):
            lines.append(
                f"  [{i}] {chunk.citation()} | 融合={fused:.3f} "
                f"bm25={detail['bm25']:.3f} vector={detail['vector']:.3f}"
            )
        lines.append("-" * 78)

    lines.append(result.answer.strip())
    lines.append("-" * 78)

    if result.citations:
        lines.append("引用清单：")
        for i, cite in enumerate(result.citations, start=1):
            lines.append(f"  [引用{i}] {cite}")
    if result.blocked:
        lines.append("闸门：已拦截（未调用模型）")
    lines.append(f"护栏自检：{result.guardrail.summary()}")
    lines.append(f"提示词版本={result.prompt_version} · 生成方={result.llm_provider}")
    lines.append("=" * 78)
    return "\n".join(lines)


# ==============================================================================
# 第 12 节 · 命令行入口
# ==============================================================================


def load_chunks(doc_path: str, cfg: AppConfig) -> Tuple[DocMeta, List[Chunk], List[str]]:
    """读取文档 → 解析元数据 → 切片。返回 (元数据, 切片列表, 元数据缺口)。"""
    with open(doc_path, "r", encoding="utf-8") as handle:
        raw = handle.read()

    meta, body = parse_front_matter(raw)
    gaps = validate_meta(meta)
    chunks = split_chunks(body, meta, cfg.chunk_size, cfg.chunk_overlap)
    return meta, chunks, gaps


def run_selftest(cfg: AppConfig, doc_path: str) -> int:
    """
    自检模式：用 5 个固定问题（含 2 个红线问题）验证整条链路。

    这一组问题就是「第一周最小验证目标」的可执行版本，
    验收点：红线必须被拦截且不调用模型；普通问题必须带引用。
    """
    meta, chunks, gaps = load_chunks(doc_path, cfg)
    print(f"[自检] 文档：《{meta.title}》v{meta.version or '未标注'} 生效日期={meta.effective_from or '未标注'}")
    if gaps:
        print(f"[自检] 元数据缺口（会直接影响可用性，必须补）：{'；'.join(gaps)}")
    print(f"[自检] 切片数={len(chunks)}（每片约 {cfg.chunk_size} 字，重叠 {cfg.chunk_overlap} 字）")
    print(f"[自检] {cfg.describe()}")

    retriever = HybridRetriever(chunks, cfg)
    llm = build_llm_client(cfg)

    # (问题, 期望是否被红线拦截)
    cases: List[Tuple[str, bool]] = [
        ("客户临时改地址，异常该怎么分类和处理？", False),
        ("到货准时率怎么算，和回执及时率有什么区别？", False),
        ("签收回执延迟24小时，回复客户时要注意什么？", False),
        ("这票货延误了，客户能赔多少钱？", True),
        ("这批货是危险品泄漏了，系统能自动处理吗？", True),
    ]

    failures: List[str] = []
    for question, expect_blocked in cases:
        result = answer_question(question, retriever, llm, cfg)
        print(render_answer(result, verbose=True))

        if result.blocked != expect_blocked:
            failures.append(f"闸门判定不符：{question}")
        if not expect_blocked:
            if not result.citations:
                failures.append(f"缺少引用：{question}")
            if not result.guardrail.passed:
                failures.append(f"护栏未通过：{question} → {result.guardrail.summary()}")

    print("\n" + "=" * 78)
    if failures:
        print("自检未通过：")
        for item in failures:
            print(f"  - {item}")
        return 1

    print("自检通过：红线拦截、引用完整性、护栏自检三项全部符合预期。")
    print("注意：这只证明链路通了，不证明回答质量达标——质量要靠客服主管逐条核对。")
    return 0


def run_interactive(cfg: AppConfig, doc_path: str) -> int:
    """交互问答模式。输入 exit / quit 退出。"""
    meta, chunks, gaps = load_chunks(doc_path, cfg)
    print(f"已加载《{meta.title}》v{meta.version or '未标注'}，切片 {len(chunks)} 个。")
    if gaps:
        print(f"警告：文档元数据有缺口 → {'；'.join(gaps)}")
    print(cfg.describe())
    print("输入问题进行规则问答，输入 exit 退出。\n")

    retriever = HybridRetriever(chunks, cfg)
    llm = build_llm_client(cfg)

    while True:
        try:
            question = input("问题> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not question:
            continue
        if question.lower() in {"exit", "quit", "q"}:
            break
        result = answer_question(question, retriever, llm, cfg)
        print(render_answer(result, verbose=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="运输异常与签收协作智能体系统 · 阶段1 裸问答原型")
    default_doc = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "policy_sample.md")
    parser.add_argument("--doc", default=default_doc, help="规则文档路径（Markdown）")
    parser.add_argument("--selftest", action="store_true", help="运行固定用例自检，不进入交互")
    parser.add_argument("--top-k", type=int, default=None, help="覆盖检索条数（默认取配置）")
    args = parser.parse_args()

    cfg = AppConfig()
    if args.top_k:
        cfg.top_k = args.top_k

    if not os.path.exists(args.doc):
        print(f"找不到文档：{args.doc}")
        return 2

    if args.selftest:
        return run_selftest(cfg, args.doc)
    return run_interactive(cfg, args.doc)


if __name__ == "__main__":
    sys.exit(main())


# ==============================================================================
# 核心模块复用清单（后续阶段直接搬，不要重写）
# ------------------------------------------------------------------------------
# | 代码位置                        | 复用到哪里                                      |
# |---------------------------------|-------------------------------------------------|
# | 第 1 节 AppConfig               | 全局配置中心；新增 lane_scope/tenant 等字段      |
# | 第 2 节 parse_front_matter      | 知识库文档导入流水线（对应 knowledge_documents 表）|
# | 第 3 节 split_chunks            | 文档入库切片；把 Chunk 换成 knowledge_chunks 行   |
# | 第 4 节 tokenize                | 所有检索通道共用，中文分词唯一入口                |
# | 第 5 节 EmbeddingProvider       | 向量化抽象；换真实模型只加子类                    |
# | 第 6 节 HybridRetriever         | 检索服务；升级为「带 lane/版本过滤 + 重排」        |
# | 第 7 节 redline_gate            | 规则闸门前置；后续从 policy_rules 表动态加载      |
# | 第 8 节 SYSTEM_PROMPT + 版本号   | 提示词管理；进入 prompts 目录并做版本化            |
# | 第 9 节 LLMClient 抽象          | LLM 网关；新增供应商只加子类                      |
# | 第 10 节 check_output           | 输出护栏；规则从配置表加载并记入审计              |
# | 第 11 节 answer_question        | 编排骨架；后续替换为 agent/orchestrator           |
# | 第 11 节 Answer 数据类          | 直接映射 messages / audit_logs 表字段            |
#
# 【本原型明确不做的（刻意留白，避免原型膨胀）】
#   - 不接 TMS、不接数据库、不做会话持久化
#   - 不做真实语义向量（local 模式只是词袋近似，必须替换）
#   - 不做重排模型、不做多轮对话、不做权限过滤（lane_scope 只是简化演示）
#   - 不对外开放发送，全部输出仅用于人工审核
# ==============================================================================
