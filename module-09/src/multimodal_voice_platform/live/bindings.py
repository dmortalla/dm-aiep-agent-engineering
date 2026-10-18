"""Live adapter bindings: how application services build live adapters (Story 9.8).

Deterministic bindings (Stories 9.4 to 9.7) are unchanged and still refuse model-backed processing
kinds. Live adapters are bound separately, through ``LiveBinding``, so a service can only reach a
live provider when application code explicitly configured one *and* the session is an opted-in live
session.

``real`` states what the binding claims: ``True`` means the adapter talks to the real provider
endpoint and its runs may be ``live_integration`` evidence; ``False`` means a contract test double
(for example the real adapter over a mocked transport) whose runs are ``automated_test`` evidence
only. ``build`` checks the claim against the adapter itself, so a mocked transport can never be
recorded as live.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import SecretStr

from multimodal_voice_platform.contracts.evidence import EvidenceClass
from multimodal_voice_platform.contracts.providers import ProviderPort
from multimodal_voice_platform.contracts.session import ExecutionMode
from multimodal_voice_platform.live.errors import LiveConfigurationError


@dataclass(frozen=True)
class LiveBinding[AdapterT]:
    """A live adapter factory, the port it serves, and whether it claims the real endpoint.

    Attributes:
        factory: ``factory(credential, *context)`` builds the adapter for one operation.
        port: The provider port the adapter implements.
        real: Whether the adapter reaches the real provider endpoint.
    """

    factory: Callable[..., AdapterT]
    port: ProviderPort
    real: bool

    def build(self, credential: SecretStr, *context: Any) -> AdapterT:
        """Build the adapter and verify it is what the binding claims.

        Args:
            credential: The live session's key.
            *context: Service-specific construction context (for example a content store).

        Returns:
            The adapter.

        Raises:
            LiveConfigurationError: If the adapter is not a live adapter for the port, or its
                endpoint does not match the binding's claim.
        """
        adapter = self.factory(credential, *context)
        descriptor = getattr(adapter, "descriptor", None)
        if (
            descriptor is None
            or descriptor.port is not self.port
            or descriptor.mode is not ExecutionMode.LIVE
        ):
            raise LiveConfigurationError(f"the live {self.port} binding built a non-live adapter")
        if getattr(adapter, "real_endpoint", None) is not self.real:
            raise LiveConfigurationError(
                "a live binding's endpoint claim does not match its adapter"
            )
        return adapter

    def check_requested(self, evidence_class: EvidenceClass) -> None:
        """Require the evidence class the binding can honestly produce.

        Args:
            evidence_class: Class requested by application code.

        Raises:
            LiveConfigurationError: If a real binding is not run as ``live_integration`` or a test
                double is not run as ``automated_test``.
        """
        expected = EvidenceClass.LIVE_INTEGRATION if self.real else EvidenceClass.AUTOMATED_TEST
        if evidence_class is not expected:
            raise LiveConfigurationError(
                f"live {self.port} runs over this binding produce {expected} evidence only"
            )


@dataclass(frozen=True)
class LiveSpeechBindings:
    """Live speech adapters for the speech service. Either may be absent.

    Attributes:
        speech_to_text: ``factory(credential, store)`` for the speech-to-text port.
        text_to_speech: ``factory(credential, store, audio_limits)`` for the text-to-speech port.
    """

    speech_to_text: LiveBinding[Any] | None = None
    text_to_speech: LiveBinding[Any] | None = None
