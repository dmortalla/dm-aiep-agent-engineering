"""Application interface layer (Story 9.7): the WebSocket streaming gateway and local server.

``create_app`` builds the Starlette ASGI application whose WebSocket route carries the typed
streaming protocol for real-time voice turns; ``build_server`` hosts it with Uvicorn on a loopback
address. Business logic lives in ``streaming.StreamingVoiceCoordinator``, not here.
"""

from multimodal_voice_platform.interface.server import LOOPBACK_HOSTS, bound_port, build_server
from multimodal_voice_platform.interface.websocket import (
    WEBSOCKET_PATH,
    GatewaySettings,
    WebSocketGateway,
    create_app,
)

__all__ = [
    "LOOPBACK_HOSTS",
    "WEBSOCKET_PATH",
    "GatewaySettings",
    "WebSocketGateway",
    "bound_port",
    "build_server",
    "create_app",
]
