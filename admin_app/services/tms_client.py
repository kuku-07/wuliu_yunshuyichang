"""TMS 只读客户端：样本 / HTTP 两种实现。

默认读 `samples/tms/`（离线可跑）；配置 `TMS_BASE_URL` + `TMS_TOKEN` 后走真实接口：

    GET {base}/queries      → [查单对象...]
    GET {base}/exceptions   → [异常记录...]

只读、带超时与重试；失败不伪造数据，抛 TmsError 让上层提示。
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from .. import config


class TmsError(RuntimeError):
    """TMS 调用失败（网络、超时或返回不合法）。"""


def _get_json(url: str, token: str, timeout: int) -> Any:
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}" if token else "",
            "Accept": "application/json",
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_all(
    base_url: str | None = None, token: str | None = None,
    timeout: int | None = None, retries: int | None = None,
) -> dict[str, Any]:
    """拉取查单与异常记录；失败按 retries 重试，最终仍失败则抛错。"""
    base = (base_url if base_url is not None else config.TMS_BASE_URL).rstrip("/")
    token = token if token is not None else config.TMS_TOKEN
    timeout = timeout or config.TMS_TIMEOUT
    retries = config.TMS_RETRIES if retries is None else retries

    if not base:
        raise TmsError("未配置 TMS_BASE_URL")

    last_error = ""
    for attempt in range(retries + 1):
        try:
            queries = _get_json(f"{base}/queries", token, timeout)
            exceptions = _get_json(f"{base}/exceptions", token, timeout)
            if not isinstance(queries, list) or not isinstance(exceptions, list):
                raise TmsError("TMS 返回格式不合法（应为数组）")
            return {"queries": queries, "exceptions": exceptions, "errors": []}
        except (urllib.error.URLError, TimeoutError, ValueError, TmsError) as exc:
            last_error = str(exc)
            if attempt >= retries:
                break
    raise TmsError(f"TMS 调用失败（已重试 {retries} 次）：{last_error}")
