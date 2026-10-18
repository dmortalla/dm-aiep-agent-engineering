"""Bounded, application-owned live provider configuration (Story 9.8).

Model identifiers, the voice, timeouts, output limits, and per-adapter call budgets are application
configuration. They never come from content, model output, or client messages, and there is no
base-URL setting: the provider endpoint is fixed inside the adapter. Defaults are conservative.
"""

from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from multimodal_voice_platform.contracts.limits import (
    MAX_IMAGE_BYTES,
    MAX_OUTPUT_TOKENS,
    MAX_REQUEST_TIMEOUT_S,
)
from multimodal_voice_platform.contracts.live import ModelId

MAX_LIVE_OPERATION_S: Final = 120.0
MAX_CALLS_PER_ADAPTER: Final = 4
MAX_SPEECH_CHARS: Final = 4_096
"""The provider's documented text-to-speech input ceiling."""

BuiltInVoice = Literal[
    "alloy",
    "ash",
    "ballad",
    "coral",
    "echo",
    "fable",
    "onyx",
    "nova",
    "sage",
    "shimmer",
    "verse",
    "marin",
    "cedar",
]


class LiveProviderConfig(BaseModel):
    """Live provider settings. Every field has a hard ceiling; none is user-controlled.

    Attributes:
        provider_family: The live provider family. Only ``openai`` is implemented.
        reasoning_model: Model for multimodal and conversational reasoning (Responses API).
        vision_model: Model for image understanding (Responses API with image input).
        transcription_model: Speech-to-text model (audio transcriptions API).
        speech_model: Text-to-speech model (audio speech API).
        voice: Built-in text-to-speech voice.
        reasoning_effort: Reasoning effort requested from reasoning models.
        image_detail: Image input detail level; ``low`` bounds image token cost.
        request_timeout_s: Timeout for one provider request.
        max_operation_s: Ceiling on one live operation, including streaming.
        max_output_tokens: Output token ceiling for reasoning requests (includes reasoning tokens).
        max_vision_output_tokens: Output token ceiling for vision requests.
        max_speech_chars: Longest text sent to text-to-speech.
        max_image_bytes: Largest image sent to the vision model.
        max_calls_per_adapter: Provider calls one adapter instance (one operation) may make.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_family: Literal["openai"] = "openai"
    reasoning_model: ModelId = "gpt-5.4-mini"
    vision_model: ModelId = "gpt-5.4-mini"
    transcription_model: ModelId = "gpt-4o-mini-transcribe"
    speech_model: ModelId = "gpt-4o-mini-tts"
    voice: BuiltInVoice = "alloy"
    reasoning_effort: Literal["minimal", "low", "medium"] = "low"
    image_detail: Literal["low", "auto", "high"] = "low"
    request_timeout_s: float = Field(default=30.0, gt=0, le=MAX_REQUEST_TIMEOUT_S)
    max_operation_s: float = Field(default=60.0, gt=0, le=MAX_LIVE_OPERATION_S)
    max_output_tokens: int = Field(default=1_200, ge=64, le=MAX_OUTPUT_TOKENS)
    max_vision_output_tokens: int = Field(default=800, ge=64, le=MAX_OUTPUT_TOKENS)
    max_speech_chars: int = Field(default=600, gt=0, le=MAX_SPEECH_CHARS)
    max_image_bytes: int = Field(default=2 * 1024 * 1024, gt=0, le=MAX_IMAGE_BYTES)
    max_calls_per_adapter: int = Field(default=1, ge=1, le=MAX_CALLS_PER_ADAPTER)
