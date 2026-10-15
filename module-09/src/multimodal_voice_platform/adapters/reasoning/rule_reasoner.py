"""Deterministic rule-based ``ReasoningPort`` adapter (Story 9.5).

``DeterministicCrossModalReasoner`` reads the canonical observation documents carried by a
``ReasoningRequest``, applies the fixed rules in ``rules.py``, and streams back one
``ReasonerOutput`` JSON document in bounded chunks. It runs in-process with no network, key, or
spend, so its execution mode is ``deterministic``. It is rule-based inference, not a language model,
and its output is ``untrusted_model_output`` like every provider result (ADR-009-007).
"""

from collections.abc import AsyncIterator
from typing import Final

from pydantic import ValidationError

from multimodal_voice_platform.adapters.reasoning.errors import ReasoningInputError
from multimodal_voice_platform.adapters.reasoning.rules import reason
from multimodal_voice_platform.contracts.limits import MAX_DELTA_CHARS
from multimodal_voice_platform.contracts.providers import (
    ProviderDescriptor,
    ProviderPort,
    ReasoningChunk,
    ReasoningRequest,
)
from multimodal_voice_platform.contracts.reasoning import MAX_FINDINGS, ObservationView
from multimodal_voice_platform.contracts.session import ExecutionMode

RULE_REASONER_ID: Final = "deterministic-rule-reasoner"


class DeterministicCrossModalReasoner:
    """``ReasoningPort`` adapter that relates observations with fixed, inspectable rules."""

    def __init__(self, *, max_findings: int = MAX_FINDINGS) -> None:
        """Create the adapter.

        Args:
            max_findings: Most findings to report, from application configuration.
        """
        self._max_findings = max_findings
        self._descriptor = ProviderDescriptor(
            provider_id=RULE_REASONER_ID,
            port=ProviderPort.REASONING,
            mode=ExecutionMode.DETERMINISTIC,
        )

    @property
    def descriptor(self) -> ProviderDescriptor:
        """Describe the adapter: its ID, the reasoning port, and deterministic execution."""
        return self._descriptor

    async def stream_reason(self, request: ReasoningRequest) -> AsyncIterator[ReasoningChunk]:
        """Reason over the request's observations and stream the findings document.

        Every part is parsed before the first chunk is yielded, so unreadable input fails before
        any output is produced. ``request.task`` and ``request.history`` do not change the rules.

        Args:
            request: Validated reasoning request whose parts are observation documents.

        Yields:
            Chunks of the findings JSON document, ending with exactly one final chunk.

        Raises:
            ReasoningInputError: If a part is not a valid observation document or does not match
                its declared modality and input.
        """
        views = []
        for part in request.parts:
            try:
                view = ObservationView.model_validate_json(part.content)
            except ValidationError as exc:
                raise ReasoningInputError(
                    "reasoning part is not a valid observation document"
                ) from exc
            if view.modality is not part.modality or view.input_id != part.source_input_id:
                raise ReasoningInputError("reasoning part does not match its observation")
            views.append(view)
        document = reason(views, max_findings=self._max_findings).model_dump_json()
        pieces = [
            document[start : start + MAX_DELTA_CHARS]
            for start in range(0, len(document), MAX_DELTA_CHARS)
        ]
        for index, piece in enumerate(pieces):
            yield ReasoningChunk(
                provider=self._descriptor, text=piece, is_final=index == len(pieces) - 1
            )
