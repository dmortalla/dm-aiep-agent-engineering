"""OpenAI live adapters behind the Module 9 provider ports (Story 9.8).

OpenAI is an adapter, not the architecture: every OpenAI-specific concern (client creation, request
construction, model identifiers, response parsing, streaming translation, usage extraction, and
exception translation) stays in this package. Application code receives only Module 9 contracts.

Importing this package creates no client and makes no network call. ``openai_bindings`` returns
live bindings for the application services; with ``transport`` set (tests only) every adapter is a
contract test double whose runs can only be ``automated_test`` evidence.
"""

from dataclasses import dataclass
from typing import Any

import httpx2
from pydantic import SecretStr

from multimodal_voice_platform.adapters.deterministic.content_store import SessionContentStore
from multimodal_voice_platform.adapters.openai.client import OPENAI_API_BASE, translate
from multimodal_voice_platform.adapters.openai.reasoning import (
    OpenAIConversationReasoner,
    OpenAICrossModalReasoner,
)
from multimodal_voice_platform.adapters.openai.speech import (
    OpenAISpeechToText,
    OpenAITextToSpeech,
    pcm16_wav,
)
from multimodal_voice_platform.adapters.openai.vision import OpenAIVisionProvider
from multimodal_voice_platform.audio.limits import AudioLimits
from multimodal_voice_platform.contracts.providers import ProviderPort
from multimodal_voice_platform.live.bindings import LiveBinding, LiveSpeechBindings
from multimodal_voice_platform.live.config import LiveProviderConfig


@dataclass(frozen=True)
class OpenAIBindings:
    """Every live binding the application services accept, for one configuration.

    Attributes:
        vision: For ``UnderstandingService(live_vision=...)``.
        speech: For ``SpeechService(live=...)``.
        cross_modal: For ``CrossModalWorkflow(live_reasoning=...)``.
        conversation: For ``VoiceAssistant(live_reasoning=...)`` and
            ``StreamingVoiceCoordinator(live_reply=...)``.
    """

    vision: LiveBinding[Any]
    speech: LiveSpeechBindings
    cross_modal: LiveBinding[Any]
    conversation: LiveBinding[Any]


def openai_bindings(
    config: LiveProviderConfig | None = None,
    *,
    transport: httpx2.AsyncBaseTransport | None = None,
) -> OpenAIBindings:
    """Build the OpenAI live bindings.

    Args:
        config: Live configuration. Defaults to ``LiveProviderConfig()``.
        transport: Trusted test transport. When set, the bindings are contract test doubles.

    Returns:
        The bindings. No client exists until an operation runs.
    """
    settings = config if config is not None else LiveProviderConfig()
    real = transport is None

    def vision(key: SecretStr, store: SessionContentStore) -> OpenAIVisionProvider:
        return OpenAIVisionProvider(key, store, settings, transport=transport)

    def stt(key: SecretStr, store: SessionContentStore) -> OpenAISpeechToText:
        return OpenAISpeechToText(key, store, settings, transport=transport)

    def tts(key: SecretStr, store: SessionContentStore, limits: AudioLimits) -> OpenAITextToSpeech:
        return OpenAITextToSpeech(key, store, limits, settings, transport=transport)

    def cross_modal(key: SecretStr) -> OpenAICrossModalReasoner:
        return OpenAICrossModalReasoner(key, settings, transport=transport)

    def conversation(key: SecretStr) -> OpenAIConversationReasoner:
        return OpenAIConversationReasoner(key, settings, transport=transport)

    return OpenAIBindings(
        vision=LiveBinding(vision, ProviderPort.VISION, real),
        speech=LiveSpeechBindings(
            speech_to_text=LiveBinding(stt, ProviderPort.SPEECH_TO_TEXT, real),
            text_to_speech=LiveBinding(tts, ProviderPort.TEXT_TO_SPEECH, real),
        ),
        cross_modal=LiveBinding(cross_modal, ProviderPort.REASONING, real),
        conversation=LiveBinding(conversation, ProviderPort.REASONING, real),
    )


__all__ = [
    "OPENAI_API_BASE",
    "OpenAIBindings",
    "OpenAIConversationReasoner",
    "OpenAICrossModalReasoner",
    "OpenAISpeechToText",
    "OpenAITextToSpeech",
    "OpenAIVisionProvider",
    "openai_bindings",
    "pcm16_wav",
    "translate",
]
