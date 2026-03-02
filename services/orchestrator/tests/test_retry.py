from __future__ import annotations

import unittest

from services.orchestrator.app.utils.retry import retry_async, retry_sync


class RetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_retry_async_succeeds_after_transient_failures(self) -> None:
        attempts = {"count": 0}

        async def flaky_call() -> str:
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise RuntimeError("timeout from upstream")
            return "ok"

        result = await retry_async(
            flaky_call,
            attempts=4,
            base_delay_seconds=0.0,
            max_delay_seconds=0.0,
            jitter_seconds=0.0,
        )
        self.assertEqual("ok", result)
        self.assertEqual(3, attempts["count"])

    async def test_retry_async_does_not_retry_non_transient(self) -> None:
        attempts = {"count": 0}

        async def failing_call() -> str:
            attempts["count"] += 1
            raise RuntimeError("invalid schema")

        with self.assertRaises(RuntimeError):
            await retry_async(
                failing_call,
                attempts=5,
                base_delay_seconds=0.0,
                max_delay_seconds=0.0,
                jitter_seconds=0.0,
            )
        self.assertEqual(1, attempts["count"])


class RetrySyncTests(unittest.TestCase):
    def test_retry_sync_succeeds_after_transient_failures(self) -> None:
        attempts = {"count": 0}

        def flaky_call() -> str:
            attempts["count"] += 1
            if attempts["count"] < 2:
                raise RuntimeError("connection timeout")
            return "done"

        result = retry_sync(
            flaky_call,
            attempts=3,
            base_delay_seconds=0.0,
            max_delay_seconds=0.0,
            jitter_seconds=0.0,
        )
        self.assertEqual("done", result)
        self.assertEqual(2, attempts["count"])
