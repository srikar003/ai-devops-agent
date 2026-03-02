from __future__ import annotations

import asyncio
import random
import time
from typing import Any, Awaitable, Callable, TypeVar

T = TypeVar("T")


def default_is_transient_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    transient_markers = [
        "timeout",
        "timed out",
        "temporarily unavailable",
        "service unavailable",
        "connection reset",
        "connection aborted",
        "connection refused",
        "connection error",
        "remote protocol error",
        "too many requests",
        "rate exceeded",
        "throttl",
        "429",
        "500",
        "502",
        "503",
        "504",
    ]
    return any(marker in msg for marker in transient_markers)


async def retry_async(
    fn: Callable[[], Awaitable[T]],
    *,
    attempts: int = 3,
    base_delay_seconds: float = 0.5,
    max_delay_seconds: float = 5.0,
    jitter_seconds: float = 0.2,
    should_retry: Callable[[Exception], bool] = default_is_transient_error,
    context: dict[str, Any] | None = None,
) -> T:
    last_exc: Exception | None = None
    started = time.perf_counter()
    for attempt in range(1, max(1, attempts) + 1):
        try:
            value = await fn()
            if context is not None:
                context["attempts"] = attempt
                context["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
            return value
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if context is not None:
                context["attempts"] = attempt
                context["last_error"] = str(exc)
                context["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
            if attempt >= attempts or not should_retry(exc):
                raise
            backoff = min(max_delay_seconds, base_delay_seconds * (2 ** (attempt - 1)))
            await asyncio.sleep(backoff + random.uniform(0, jitter_seconds))
    if last_exc:
        raise last_exc
    raise RuntimeError("retry_async reached unexpected state")


def retry_sync(
    fn: Callable[[], T],
    *,
    attempts: int = 3,
    base_delay_seconds: float = 0.5,
    max_delay_seconds: float = 5.0,
    jitter_seconds: float = 0.2,
    should_retry: Callable[[Exception], bool] = default_is_transient_error,
    context: dict[str, Any] | None = None,
) -> T:
    last_exc: Exception | None = None
    started = time.perf_counter()
    for attempt in range(1, max(1, attempts) + 1):
        try:
            value = fn()
            if context is not None:
                context["attempts"] = attempt
                context["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
            return value
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if context is not None:
                context["attempts"] = attempt
                context["last_error"] = str(exc)
                context["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
            if attempt >= attempts or not should_retry(exc):
                raise
            backoff = min(max_delay_seconds, base_delay_seconds * (2 ** (attempt - 1)))
            time.sleep(backoff + random.uniform(0, jitter_seconds))
    if last_exc:
        raise last_exc
    raise RuntimeError("retry_sync reached unexpected state")
