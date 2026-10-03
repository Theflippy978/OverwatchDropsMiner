from __future__ import annotations

import asyncio
import threading

from python_sidecar.backend.async_backend import ensure_anyio_asyncio_backend_ready
from python_sidecar.backend.client import BilibiliClient


def test_anyio_asyncio_backend_warmup_is_idempotent() -> None:
    ensure_anyio_asyncio_backend_ready()
    ensure_anyio_asyncio_backend_ready()


def test_bilibili_client_concurrent_startup_warms_anyio_once() -> None:
    errors: list[BaseException] = []
    errors_lock = threading.Lock()
    start_gate = threading.Barrier(8)

    async def close_client(client: BilibiliClient) -> None:
        await client.close()

    def create_client() -> None:
        try:
            start_gate.wait(timeout=5)
            client = BilibiliClient("")
            asyncio.run(close_client(client))
        except BaseException as exc:
            with errors_lock:
                errors.append(exc)

    threads = [threading.Thread(target=create_client) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert not errors
    assert not any(thread.is_alive() for thread in threads)
