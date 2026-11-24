"""Neon PostgreSQL connection resolver and local WebSocket proxy bridge.

When running in environments where outbound TCP port 5432 is blocked (such as
restricted local Wi-Fi or ISP firewalls), this bridge transparently tunnels
PostgreSQL wire traffic over Neon's secure WebSocket endpoint on port 443.

In production environments (like Render or cloud servers) where outbound port 5432
is unrestricted, the bridge is completely bypassed and direct TCP is used.
"""

import asyncio
import logging
import os
import socket
import threading
import time
from typing import Optional
from urllib.parse import urlparse, urlunparse

logger = logging.getLogger("app.core.neon_bridge")

_bridge_lock = threading.Lock()
_bridge_started = False
_bridge_port = 5433
_bridge_host_target = None


def is_port_reachable(host: str, port: int, timeout: float = 1.5) -> bool:
    """Test whether a host and port can accept TCP connections."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


async def _handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, target_host: str) -> None:
    """Relay traffic between local TCP client and Neon secure WebSocket endpoint."""
    import websockets

    uri = f"wss://{target_host}/v2?address={target_host}:5432"
    try:
        async with websockets.connect(uri, subprotocols=["binary"], open_timeout=45) as ws:
            async def tcp_to_ws():
                while True:
                    data = await reader.read(16384)
                    if not data:
                        break
                    await ws.send(data)

            async def ws_to_tcp():
                async for msg in ws:
                    writer.write(msg)
                    await writer.drain()

            await asyncio.gather(tcp_to_ws(), ws_to_tcp())
    except Exception as e:
        logger.debug("Neon bridge client connection closed: %s", str(e))
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def _run_server(local_port: int, target_host: str) -> None:
    """Start local TCP loopback server."""
    server = await asyncio.start_server(
        lambda r, w: _handle_client(r, w, target_host),
        "127.0.0.1",
        local_port,
    )
    logger.info("Neon local WebSocket bridge listening on 127.0.0.1:%d -> wss://%s:443", local_port, target_host)
    async with server:
        await server.serve_forever()


def _start_bridge_thread(local_port: int, target_host: str) -> None:
    """Run bridge asyncio loop in dedicated daemon thread."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_run_server(local_port, target_host))
    except Exception as e:
        logger.error("Neon bridge server error: %s", str(e))


def resolve_database_url(url: str) -> str:
    """Resolve database URL, starting local WebSocket bridge only if port 5432 is blocked.
    
    If the connection target is an external Neon PostgreSQL host:
    1. Checks if target host:5432 is directly reachable.
    2. If reachable, returns the standard URL.
    3. If blocked (local restricted Wi-Fi), spins up a local bridge on 127.0.0.1:5433
       and rewrites the URL to route via the local bridge with sslmode=disable locally.
    """
    if not url or "neon.tech" not in url:
        return url

    # Parse host
    parsed = urlparse(url.replace("postgresql+psycopg://", "postgresql://"))
    target_host = parsed.hostname
    target_port = parsed.port or 5432

    if not target_host:
        return url

    # If already pointing to localhost, do not proxy
    if target_host in ("127.0.0.1", "localhost"):
        return url

    # Check direct reachability
    if is_port_reachable(target_host, target_port, timeout=1.0):
        # Outbound port 5432 is open (Render / Cloud / Open Network)
        return url

    # Outbound port 5432 is blocked by local network. Use local WSS bridge.
    global _bridge_started, _bridge_port, _bridge_host_target
    with _bridge_lock:
        if not _bridge_started or _bridge_host_target != target_host:
            # Pick a free local port
            with socket.socket() as s:
                s.bind(("127.0.0.1", 0))
                _bridge_port = s.getsockname()[1]

            _bridge_host_target = target_host
            t = threading.Thread(
                target=_start_bridge_thread,
                args=(_bridge_port, target_host),
                daemon=True,
                name="NeonWSSBridgeThread",
            )
            t.start()
            _bridge_started = True
            time.sleep(0.5)

        # Rewrite URL to route through local bridge
        # Construct netloc: user:pass@127.0.0.1:port
        auth = ""
        if parsed.username:
            auth = parsed.username
            if parsed.password:
                auth += f":{parsed.password}"
            auth += "@"

        new_netloc = f"{auth}127.0.0.1:{_bridge_port}"
        # For local hop to bridge, sslmode=disable
        query = "sslmode=disable"
        new_url = f"postgresql+psycopg://{new_netloc}{parsed.path}?{query}"
        logger.info("Outbound port 5432 blocked locally. Routing via Neon WebSocket bridge: 127.0.0.1:%d", _bridge_port)
        return new_url
