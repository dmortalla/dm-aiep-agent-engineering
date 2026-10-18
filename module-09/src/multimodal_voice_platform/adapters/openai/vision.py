"""OpenAI vision adapter behind the ``VisionPort`` (Story 9.8).

The image has already passed Module 9 ingestion and local analysis. The adapter reads its bytes
from the run's content store, enforces the live image byte bound, and sends it inline (base64 data
URL) with a fixed application question to the Responses API with strict structured output. The
model's description is untrusted output: it is parsed into ``VisionResult`` and never replaces the
local measurements.
"""

import asyncio
import base64
import json
import time
from typing import Final

import httpx2
from pydantic import SecretStr, ValidationError

from multimodal_voice_platform.adapters.deterministic.content_store import SessionContentStore
from multimodal_voice_platform.adapters.deterministic.errors import ContentNotFoundError
from multimodal_voice_platform.adapters.openai.client import (
    OpenAIAdapter,
    output_refused,
    safe_request_id,
    usage_from,
)
from multimodal_voice_platform.contracts.live import LiveCapability
from multimodal_voice_platform.contracts.providers import ProviderPort, VisionRequest, VisionResult
from multimodal_voice_platform.live.config import LiveProviderConfig
from multimodal_voice_platform.live.errors import (
    LiveBudgetError,
    ProviderOutputError,
    ProviderRefusalError,
)
from multimodal_voice_platform.live.prompts import (
    VISION_INSTRUCTIONS,
    VISION_QUESTION,
    VISION_SCHEMA,
    json_schema_format,
)

MAX_OBSERVATIONS: Final = 6
MAX_DESCRIPTION_CHARS: Final = 2_000
MAX_OBSERVATION_CHARS: Final = 300


class OpenAIVisionProvider(OpenAIAdapter):
    """Model-backed image understanding through the Responses API."""

    capability = LiveCapability.VISION
    port = ProviderPort.VISION

    def __init__(
        self,
        credential: SecretStr,
        store: SessionContentStore,
        config: LiveProviderConfig,
        *,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        """Create the adapter for one operation.

        Args:
            credential: The live session's key.
            store: The run's content store holding the validated image.
            config: Live configuration.
            transport: Trusted test transport; makes the adapter a contract test double.
        """
        super().__init__(credential, config, transport=transport)
        self._store = store

    async def analyze(self, request: VisionRequest) -> VisionResult:
        """Describe one validated image.

        Args:
            request: Vision request for a validated image input.

        Returns:
            The model's structured description, attributed to this adapter.

        Raises:
            LiveProviderError: A sanitized provider, budget, refusal, or output failure.
        """
        image = request.image
        if image.content_ref is None:
            raise ProviderOutputError("the image has no stored content to send")
        try:
            data = self._store.read(image.session_id, image.content_ref)
        except ContentNotFoundError as exc:
            raise ProviderOutputError("the image content is no longer available") from exc
        if len(data) > self._config.max_image_bytes:
            raise LiveBudgetError("the image exceeds the live vision byte budget")
        self._check_budget()
        model = self._config.vision_model
        url = f"data:{image.media_type};base64,{base64.b64encode(data).decode('ascii')}"
        started = time.perf_counter()
        try:
            async with asyncio.timeout(self._config.max_operation_s), self._client() as client:
                raw = await client.responses.with_raw_response.create(
                    model=model,
                    instructions=VISION_INSTRUCTIONS,
                    input=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "input_text", "text": request.question or VISION_QUESTION},
                                {
                                    "type": "input_image",
                                    "image_url": url,
                                    "detail": self._config.image_detail,
                                },
                            ],
                        }
                    ],
                    text={"format": json_schema_format("image_description", VISION_SCHEMA)},
                    max_output_tokens=self._config.max_vision_output_tokens,
                    reasoning={"effort": self._config.reasoning_effort},
                    store=False,
                )
                response = raw.parse()
            result = self._result(response)
        except Exception as exc:  # Translated and recorded; never re-raised raw.
            self._fail(model, started, exc)
        self._record(
            model,
            started,
            request_id=safe_request_id(getattr(response, "id", None)) or raw.request_id,
            usage=usage_from(getattr(response, "usage", None)),
        )
        return result

    def _result(self, response: object) -> VisionResult:
        if output_refused(response):
            raise ProviderRefusalError("the live provider refused to describe the image")
        if getattr(response, "status", None) != "completed":
            raise ProviderOutputError("the live provider returned an incomplete description")
        try:
            document = json.loads(getattr(response, "output_text", "") or "")
            description = str(document["description"]).strip()
            observations = tuple(
                str(item).strip()[:MAX_OBSERVATION_CHARS]
                for item in document["observations"][:MAX_OBSERVATIONS]
                if str(item).strip()
            )
            if len(description) > MAX_DESCRIPTION_CHARS:
                raise ValueError("description too long")
            return VisionResult(
                provider=self.descriptor, description=description, observations=observations
            )
        except (ValueError, KeyError, TypeError, ValidationError) as exc:
            raise ProviderOutputError("the live provider returned a malformed description") from exc
