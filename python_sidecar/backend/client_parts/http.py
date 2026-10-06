from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

# URL 查询串中的会话敏感参数：出现在 httpx 异常消息里的完整 URL 必须
# 打码后再进入日志/GUI。
#
# ★ benchmark 最要紧：x25Kn 的 client_parts/live_trace.py 把它作为
#   「benchmark」查询参数下发，而它是服务端给的 **HMAC 签名根密钥**
#   （同响应里的 secret_rule 也是）。拿到它可以离线伪造任意 seq_id 的
#   x25Kn 心跳，即伪造观看时长 —— 这是本项目最核心的业务资产。
#   只匹配 csrf/bili_jct/access_key/token/sessdata 五个 B 站参数是不够的：
#   漏了它，该密钥会经 httpx 异常消息 → 前端 LogHandler →
#   log-entry 事件 → WebView 渲染树 全链路明文可见。
#   （企业微信 corpsecret 不走这里，见 notifier.py —— 那边是自行拼 URL）
_SENSITIVE_PARAM_RE = re.compile(
    r"(?i)([?&])(?:csrf|bili_jct|access_key|token|sessdata|benchmark|s)=([^&\s'\"]+)"
)


def sanitize_url(url: str) -> str:
    """打码 URL 查询串中的敏感参数值，其余部分保持原样。"""
    return _SENSITIVE_PARAM_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}=***", url)


def sanitize_exception_text(exc: BaseException) -> str:
    """供所有 str(exc) 日志点复用的脱敏入口（httpx 异常常携带完整 URL）。"""
    return sanitize_url(str(exc))


def raise_for_status_sanitized(response: httpx.Response, *, method: str) -> None:
    """raise_for_status 的脱敏包装。

    httpx.HTTPStatusError 的消息固定携带完整 request.url（含 query），
    而 csrf/bili_jct 等会话凭据正走在查询串里；捕获后以脱敏消息重抛，
    并用 from None 切断异常链，避免原始消息经 traceback 再次外泄。
    """
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        safe_url = sanitize_url(str(exc.request.url))
        raise httpx.HTTPStatusError(
            f"{method} {safe_url} 返回 HTTP {exc.response.status_code}",
            request=exc.request,
            response=exc.response,
        ) from None


def is_rate_limited_payload(payload: dict[str, Any]) -> bool:
    code = str(payload.get("code") or "")
    message = str(payload.get("message") or "")
    return code in {"-702", "-509"} or "频率" in message or "频繁" in message


def _should_retry_with_fresh_wbi(
    payload: dict[str, Any],
    *,
    retry: int,
    retry_on_wbi_miss: bool,
) -> bool:
    # 限频需要由调用方按退避策略处理，不能在刷新 WBI 时立即重复请求。
    return (
        retry == 0
        and retry_on_wbi_miss
        and not is_rate_limited_payload(payload)
    )


async def request_with_transient_retry(
    request_coro: Callable[[], Awaitable[httpx.Response]],
    *,
    method: str,
    url: str,
    logger: logging.Logger,
) -> httpx.Response:
    # 高并发时，x25Kn/live API 偶发 ConnectTimeout/ReadTimeout。
    # 对这类瞬时网络异常做短退避重试，避免单次抖动就打断会话。
    #
    # 非幂等 POST 的重试口径更紧：ConnectTimeout/ConnectError
    # 意味着连接未建立、请求必然未发出，可安全重试；而 ReadTimeout/
    # RemoteProtocolError 表示请求可能已被服务端受理、仅响应丢失，
    # 盲目重试会导致领奖/上报等重复提交——只记录不重试。
    delays = (0.35, 0.8)
    attempt_total = len(delays) + 1
    if method.upper() == "POST":
        transient_errors: tuple[type[BaseException], ...] = (
            httpx.ConnectTimeout,
            httpx.ConnectError,
        )
    else:
        transient_errors = (
            httpx.ConnectTimeout,
            httpx.ReadTimeout,
            httpx.ConnectError,
            httpx.RemoteProtocolError,
        )
    for attempt in range(1, attempt_total + 1):
        try:
            return await request_coro()
        except transient_errors as exc:
            if attempt >= attempt_total:
                raise
            delay = delays[attempt - 1]
            logger.debug(
                "%s %s 网络瞬时异常(%s/%s)，%s，%.2fs 后重试",
                method,
                url,
                attempt,
                attempt_total,
                type(exc).__name__,
                delay,
            )
            await asyncio.sleep(delay)

    raise RuntimeError("unreachable retry state")


def parse_json_response(
    response: httpx.Response, *, method: str, url: str
) -> dict[str, Any]:
    # HTTP 200 但返回 HTML/空 body 的场景（风控软拦截偶发），
    # 裸 JSONDecodeError 缺少接口上下文，难以定位是哪个请求出错。
    try:
        return response.json()
    except ValueError as exc:
        raise RuntimeError(f"接口 {method} {url} 返回非 JSON 响应") from exc


async def signed_get_json(
    *,
    http: httpx.AsyncClient,
    sign_wbi: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
    clear_wbi_cache: Callable[[], None],
    logger: logging.Logger,
    url: str,
    params: dict[str, Any],
    headers: dict[str, str] | None = None,
    follow_redirects: bool = False,
    retry_on_wbi_miss: bool = True,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    retries = 2 if retry_on_wbi_miss else 1
    for retry in range(retries):
        signed_params = await sign_wbi(params)
        response = await request_with_transient_retry(
            lambda: http.get(
                url,
                params=signed_params,
                headers=headers,
                follow_redirects=follow_redirects,
            ),
            method="GET",
            url=url,
            logger=logger,
        )
        raise_for_status_sanitized(response, method="GET")
        payload = parse_json_response(response, method="GET", url=url)
        if payload.get("code") == 0:
            return payload
        if _should_retry_with_fresh_wbi(
            payload,
            retry=retry,
            retry_on_wbi_miss=retry_on_wbi_miss,
        ):
            clear_wbi_cache()
            continue
        break
    return payload


async def signed_post_json(
    *,
    http: httpx.AsyncClient,
    sign_wbi: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
    clear_wbi_cache: Callable[[], None],
    logger: logging.Logger,
    url: str,
    params: dict[str, Any],
    body: dict[str, Any],
    headers: dict[str, str] | None = None,
    retry_on_wbi_miss: bool = True,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    retries = 2 if retry_on_wbi_miss else 1
    for retry in range(retries):
        signed_params = await sign_wbi(params)
        response = await request_with_transient_retry(
            lambda: http.post(
                url,
                params=signed_params,
                json=body,
                headers=headers,
            ),
            method="POST",
            url=url,
            logger=logger,
        )
        raise_for_status_sanitized(response, method="POST")
        payload = parse_json_response(response, method="POST", url=url)
        if payload.get("code") == 0:
            return payload
        if _should_retry_with_fresh_wbi(
            payload,
            retry=retry,
            retry_on_wbi_miss=retry_on_wbi_miss,
        ):
            clear_wbi_cache()
            continue
        break
    return payload


async def signed_post_query_json(
    *,
    http: httpx.AsyncClient,
    sign_wbi: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
    clear_wbi_cache: Callable[[], None],
    logger: logging.Logger,
    url: str,
    params: dict[str, Any],
    headers: dict[str, str] | None = None,
    follow_redirects: bool = False,
    retry_on_wbi_miss: bool = True,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    retries = 2 if retry_on_wbi_miss else 1
    for retry in range(retries):
        signed_params = await sign_wbi(params)
        response = await request_with_transient_retry(
            lambda: http.post(
                url,
                params=signed_params,
                headers=headers,
                follow_redirects=follow_redirects,
            ),
            method="POST",
            url=url,
            logger=logger,
        )
        raise_for_status_sanitized(response, method="POST")
        payload = parse_json_response(response, method="POST", url=url)
        if payload.get("code") == 0:
            return payload
        if _should_retry_with_fresh_wbi(
            payload,
            retry=retry,
            retry_on_wbi_miss=retry_on_wbi_miss,
        ):
            clear_wbi_cache()
            continue
        break
    return payload


async def signed_post_form_json(
    *,
    http: httpx.AsyncClient,
    sign_wbi: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
    clear_wbi_cache: Callable[[], None],
    logger: logging.Logger,
    url: str,
    params: dict[str, Any],
    body: dict[str, Any],
    headers: dict[str, str] | None = None,
    retry_on_wbi_miss: bool = True,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    retries = 2 if retry_on_wbi_miss else 1
    for retry in range(retries):
        signed_params = await sign_wbi(params)
        response = await request_with_transient_retry(
            lambda: http.post(
                url,
                params=signed_params,
                data=body,
                headers=headers,
            ),
            method="POST",
            url=url,
            logger=logger,
        )
        raise_for_status_sanitized(response, method="POST")
        payload = parse_json_response(response, method="POST", url=url)
        if payload.get("code") == 0:
            return payload
        if _should_retry_with_fresh_wbi(
            payload,
            retry=retry,
            retry_on_wbi_miss=retry_on_wbi_miss,
        ):
            clear_wbi_cache()
            continue
        break
    return payload

