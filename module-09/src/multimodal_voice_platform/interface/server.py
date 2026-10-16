"""Local hosting process for the WebSocket gateway (Story 9.7).

``build_server`` hosts the ASGI application with Uvicorn, using the sans-I/O ``websockets``
protocol implementation for RFC 6455 framing. Story 9.7 binds loopback addresses only: there is no
authentication or TLS yet, so exposing the gateway beyond the local machine is a deployment
decision for Story 9.10. Protocol-level bounds mirror the application's: a frame larger than the
inbound message bound plus a small margin is refused by the protocol layer before it reaches the
application, per-message compression is off, and the inbound frame queue is bounded.
"""

from typing import Any, Final

import uvicorn

from multimodal_voice_platform.streaming.limits import ENVELOPE_BYTES, StreamingLimits

LOOPBACK_HOSTS: Final = frozenset({"127.0.0.1", "::1", "localhost"})
WS_QUEUE_FRAMES: Final = 8
"""Inbound frames the protocol layer buffers before it stops reading from the socket."""


class NonLoopbackHostError(ValueError):
    """Raised when the gateway is asked to listen on a non-loopback address."""


def build_server(
    app: Any,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    limits: StreamingLimits | None = None,
) -> uvicorn.Server:
    """Configure a Uvicorn server for the gateway on a loopback address.

    Args:
        app: The ASGI application from ``create_app`` (it exposes ``state.gateway``).
        host: Loopback address to bind.
        port: TCP port; ``0`` picks a free ephemeral port.
        limits: Streaming bounds. Defaults to the coordinator's limits on ``app.state.gateway``.

    Returns:
        The configured server. Run it with ``await server.serve()`` or ``server.run()``.

    Raises:
        NonLoopbackHostError: If ``host`` is not a loopback address.
    """
    if host not in LOOPBACK_HOSTS:
        raise NonLoopbackHostError("Story 9.7 serves loopback addresses only")
    bounds = limits if limits is not None else app.state.gateway.limits
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        ws="websockets-sansio",
        ws_max_size=bounds.max_inbound_message_bytes + ENVELOPE_BYTES,
        ws_max_queue=WS_QUEUE_FRAMES,
        ws_per_message_deflate=False,
        lifespan="off",
        log_level="warning",
        access_log=False,
        server_header=False,
        timeout_graceful_shutdown=5,
    )
    return uvicorn.Server(config)


def bound_port(server: uvicorn.Server) -> int:
    """Return the TCP port a started server is listening on.

    Args:
        server: A server whose ``started`` flag is set.

    Returns:
        The bound port.

    Raises:
        RuntimeError: If the server is not listening.
    """
    for listener in getattr(server, "servers", []):
        for sock in listener.sockets:
            return int(sock.getsockname()[1])
    raise RuntimeError("the server is not listening")
