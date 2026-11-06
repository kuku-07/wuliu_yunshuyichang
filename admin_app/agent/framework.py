"""轻量 Agent 编排框架：工具注册 + 流水线 + 上下文 / 轨迹。

设计目标不是“让模型自由调工具”，而是把业务步骤显式化：
每一步是一个可测试的 Tool，按固定顺序执行，失败或需要人工确认时立即停止，
并把每一步的耗时与结果记进 trace，供审计和演示使用。

生产路径里的“查单草稿生成”已经接在这套框架上（见 services/draft.py）。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class AgentContext:
    """一次 Agent 运行的上下文。"""

    conn: Any
    user: dict
    payload: dict
    state: dict = field(default_factory=dict)
    trace: list[dict] = field(default_factory=list)
    blocked: bool = False
    result: Any = None

    def block(self, reason: str, result: Any = None) -> None:
        """停止流水线，并记录原因。"""
        self.blocked = True
        self.state["block_reason"] = reason
        self.result = result


@dataclass
class Tool:
    """一个可执行步骤。requires_human=True 表示该步骤会产出人工确认点。"""

    name: str
    handler: Callable[[AgentContext], None]
    description: str = ""
    requires_human: bool = False


class ToolRegistry:
    """工具注册表：按名字取工具，便于编排、替换和测试。"""

    def __init__(self, tools: list[Tool] | None = None):
        self._tools: dict[str, Tool] = {}
        for tool in tools or []:
            self.register(tool)

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"工具已存在：{tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise KeyError(f"未注册的工具：{name}")
        return self._tools[name]

    def names(self) -> list[str]:
        return list(self._tools)

    def describe(self) -> list[dict]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "requires_human": tool.requires_human,
            }
            for tool in self._tools.values()
        ]


class AgentPipeline:
    """按固定顺序执行工具；遇到 block 立即停止。"""

    def __init__(self, registry: ToolRegistry, steps: list[str], name: str = "pipeline"):
        self.registry = registry
        self.steps = steps
        self.name = name

    def run(self, ctx: AgentContext) -> AgentContext:
        for step in self.steps:
            tool = self.registry.get(step)
            started = time.monotonic()
            ok = True
            error = ""
            try:
                tool.handler(ctx)
            except Exception as exc:  # 记录后继续抛，避免静默失败
                ok = False
                error = f"{type(exc).__name__}: {exc}"
                raise
            finally:
                ctx.trace.append({
                    "pipeline": self.name,
                    "tool": tool.name,
                    "description": tool.description,
                    "requires_human": tool.requires_human,
                    "ok": ok,
                    "error": error,
                    "ms": round((time.monotonic() - started) * 1000, 1),
                    "blocked": ctx.blocked,
                })
            if ctx.blocked:
                break
        return ctx

    def describe(self) -> list[dict]:
        return [
            {
                "step": index + 1,
                "tool": name,
                "description": self.registry.get(name).description,
                "requires_human": self.registry.get(name).requires_human,
            }
            for index, name in enumerate(self.steps)
        ]
