"""Run the deterministic WebSocket gateway on 127.0.0.1:8765 (Story 9.7).

``python -m multimodal_voice_platform.interface`` serves ``ws://127.0.0.1:8765/ws/voice`` with the
deterministic adapters: no key, no network beyond loopback, no spend. Turns are recorded as
``deterministic_demo`` evidence.
"""

from multimodal_voice_platform.interface.server import build_server
from multimodal_voice_platform.interface.websocket import create_app

if __name__ == "__main__":
    build_server(create_app()).run()
