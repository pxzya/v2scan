"""
tester.py
Latency-tests extracted configs via a raw TCP connect to each server's
host:port. This proves the server is online and listening -- it's not a
full VLESS/VMess/Trojan protocol handshake (that would require bundling an
actual proxy engine), but it's exactly what filters out the great majority
of dead/expired nodes people post.
"""
from __future__ import annotations

import asyncio
import socket
import time
from dataclasses import dataclass
from typing import Callable, Optional

from parser import VpnConfig

DEFAULT_CONCURRENCY = 60
DEFAULT_TIMEOUT = 3.0


@dataclass
class TestResult:
    config: VpnConfig
    alive: bool
    ping_ms: Optional[int]
    error: str = ""


async def _tcp_ping(host: str, port: int, override_ip: Optional[str], timeout: float) -> tuple[bool, Optional[int], str]:
    start = time.perf_counter()
    try:
        loop = asyncio.get_running_loop()
        if override_ip:
            addr = override_ip
        else:
            infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
            addr = infos[0][4][0]

        conn = asyncio.open_connection(addr, port)
        reader, writer = await asyncio.wait_for(conn, timeout=timeout)
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return True, elapsed_ms, ""
    except asyncio.TimeoutError:
        return False, None, "timeout"
    except (OSError, socket.gaierror) as e:
        return False, None, str(e)


async def test_configs(
    configs: list[VpnConfig],
    override_ip: Optional[str] = None,
    timeout: float = DEFAULT_TIMEOUT,
    concurrency: int = DEFAULT_CONCURRENCY,
    min_ping_ms: Optional[int] = None,
    on_result: Optional[Callable[[TestResult], None]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
) -> list[TestResult]:
    """
    Tests every config concurrently (bounded by `concurrency`).
    If min_ping_ms is set, only results with ping_ms <= min_ping_ms count as
    'alive' -- slower/dead nodes are still reported (not silently dropped)
    so the UI can show why something was rejected.
    """
    sem = asyncio.Semaphore(concurrency)
    results: list[TestResult] = []

    async def run_one(cfg: VpnConfig):
        if should_stop and should_stop():
            return
        async with sem:
            if should_stop and should_stop():
                return
            alive, ping_ms, err = await _tcp_ping(cfg.host, cfg.port, override_ip, timeout)
            if alive and min_ping_ms is not None and ping_ms is not None and ping_ms > min_ping_ms:
                alive = False
                err = f"over threshold ({ping_ms}ms > {min_ping_ms}ms)"
            result = TestResult(config=cfg, alive=alive, ping_ms=ping_ms, error=err)
            results.append(result)
            if on_result:
                on_result(result)

    await asyncio.gather(*(run_one(c) for c in configs))
    return results
