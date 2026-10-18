"""Typed reviewer facade over existing services; no Streamlit or provider-specific imports."""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field
from uuid import uuid4

from pydantic import SecretStr

from multimodal_voice_platform.contracts.evidence import EvidenceClass
from multimodal_voice_platform.contracts.modality import Modality
from multimodal_voice_platform.contracts.session import SessionConfig
from multimodal_voice_platform.crossmodal.records import CrossModalRecord
from multimodal_voice_platform.crossmodal.service import CrossModalWorkflow, ModalitySubmission
from multimodal_voice_platform.live.credentials import live_session
from multimodal_voice_platform.live.redaction import redact
from multimodal_voice_platform.speech.service import SpeechService
from multimodal_voice_platform.understanding.records import UnderstandingRecord
from multimodal_voice_platform.understanding.service import UnderstandingService
from multimodal_voice_platform.voice import VoiceAssistant, VoiceTurnRequest, load_voice_catalog
from multimodal_voice_platform.voice.records import VoiceTurnRecord

MAX_UPLOAD_BYTES = 2 * 1024 * 1024


class ReviewerInputError(ValueError):
    """Safe, actionable presentation input rejection."""


@dataclass(frozen=True)
class Upload:
    """Untrusted bytes and declared metadata, validated by existing ingestion services.

    Attributes:
        name: Original display name; never used as a filesystem path.
        media_type: Declared type, checked against content downstream.
        data: Bounded uploaded bytes.
    """

    name: str
    media_type: str
    data: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if not self.data or len(self.data) > MAX_UPLOAD_BYTES:
            raise ReviewerInputError("Choose a non-empty file no larger than 2 MiB.")


def authorize_live(enabled: bool, acknowledged: bool, key: str) -> SecretStr | None:
    """Gate explicit submitted live actions; credential presence alone grants no authority.

    Args:
        enabled: Whether live mode was selected by the user.
        acknowledged: Whether paid provider usage was acknowledged for this submission.
        key: Password value, used only for this operation.

    Returns:
        The ephemeral credential, or None in deterministic mode.

    Raises:
        ReviewerInputError: If a live submission lacks acknowledgement or a credential.
    """
    if not enabled:
        return None
    if not acknowledged or not key:
        raise ReviewerInputError("Acknowledge provider usage and enter a key for this execution.")
    return SecretStr(key)


class Reviewer:
    """One browser session's deterministic facade; live objects never persist here."""

    def __init__(self) -> None:
        self.catalog = load_voice_catalog()
        self.voice = VoiceAssistant(catalog=self.catalog)
        self.session_id = f"ui-{uuid4().hex}"
        self.voice.start_session(SessionConfig(session_id=self.session_id))
        self.turn = 0

    def reset(self) -> None:
        """Release conversation history and start a fresh bounded deterministic session."""
        self.voice.end_session(self.session_id)
        self.session_id = f"ui-{uuid4().hex}"
        self.voice.start_session(SessionConfig(session_id=self.session_id))
        self.turn = 0

    def sample(self) -> tuple[ModalitySubmission, ...]:
        """Return a useful repository-owned text/image/document/audio workflow."""
        return (
            ModalitySubmission(modality=Modality.TEXT, text="The top-left quadrant is red."),
            ModalitySubmission(
                modality=Modality.IMAGE,
                media_type="image/png",
                display_name="quadrants.png",
                data=self.catalog.content("image-quadrants"),
            ),
            ModalitySubmission(
                modality=Modality.DOCUMENT,
                media_type="text/markdown",
                display_name="brief.md",
                data=self.catalog.content("document-brief"),
            ),
            ModalitySubmission(
                modality=Modality.AUDIO,
                media_type="audio/wav",
                display_name="sample.wav",
                data=self.catalog.content("audio-tone"),
                transcribe=True,
            ),
        )

    def _services(
        self, key: SecretStr | None
    ) -> tuple[SessionConfig, UnderstandingService, SpeechService, CrossModalWorkflow]:
        session_id = f"ui-{uuid4().hex}"
        if key is None:
            session = SessionConfig(session_id=session_id)
            understanding = UnderstandingService(self.catalog)
            speech = SpeechService(self.catalog)
            workflow = CrossModalWorkflow(self.catalog)
        else:
            from multimodal_voice_platform.adapters.openai import openai_bindings

            bindings = openai_bindings()
            session = live_session(session_id, key)
            understanding = UnderstandingService(self.catalog, live_vision=bindings.vision)
            speech = SpeechService(self.catalog, live=bindings.speech)
            workflow = CrossModalWorkflow(
                self.catalog,
                understanding=understanding,
                speech=speech,
                live_reasoning=bindings.cross_modal,
            )
        return session, understanding, speech, workflow

    def multimodal(
        self, submissions: Sequence[ModalitySubmission], key: SecretStr | None = None
    ) -> CrossModalRecord:
        """Execute supplied modalities through the existing cross-modal workflow.

        Args:
            submissions: Untrusted normalized UI input shapes.
            key: Explicitly authorized ephemeral key, or None for deterministic execution.

        Returns:
            Authoritative evidence-classified workflow record.
        """
        session, _, _, workflow = self._services(key)
        evidence = EvidenceClass.LIVE_INTEGRATION if key else EvidenceClass.DETERMINISTIC_DEMO
        return asyncio.run(workflow.run(session, submissions, evidence_class=evidence))

    def understand(
        self, modality: Modality, upload: Upload, key: SecretStr | None = None
    ) -> UnderstandingRecord:
        """Run image analysis or document extraction through the understanding service.

        Args:
            modality: Image or document modality selected in the UI.
            upload: Bounded untrusted file bytes.
            key: Authorized ephemeral key for live vision; documents remain local.

        Returns:
            Authoritative understanding record.
        """
        # Local document extraction does not require or authorize any provider call.
        session, service, _, _ = self._services(key if modality is Modality.IMAGE else None)
        evidence = (
            EvidenceClass.LIVE_INTEGRATION
            if key and modality is Modality.IMAGE
            else (EvidenceClass.DETERMINISTIC_DEMO)
        )
        return asyncio.run(
            service.understand_upload(
                session,
                modality=modality,
                media_type=upload.media_type,
                display_name=upload.name,
                data=upload.data,
                evidence_class=evidence,
            )
        )

    def speak(
        self,
        fixture: str = "voice-remember",
        upload: Upload | None = None,
        key: SecretStr | None = None,
    ) -> VoiceTurnRecord:
        """Run one voice turn, preserving only deterministic history across UI submissions.

        Args:
            fixture: Committed fixture ID when no upload is selected.
            upload: Optional bounded microphone/file input; arbitrary speech needs live STT.
            key: Authorized ephemeral credential; live conversations end in finally.

        Returns:
            Authoritative voice record with validated generated audio when successful.
        """
        voice = self.voice
        session_id = self.session_id
        if key:
            from multimodal_voice_platform.adapters.openai import openai_bindings

            bindings = openai_bindings()
            voice = VoiceAssistant(
                catalog=self.catalog,
                speech=SpeechService(self.catalog, live=bindings.speech),
                live_reasoning=bindings.conversation,
            )
            session_id = f"ui-{uuid4().hex}"
            voice.start_session(live_session(session_id, key))
        self.turn += 1
        evidence = EvidenceClass.LIVE_INTEGRATION if key else EvidenceClass.DETERMINISTIC_DEMO
        try:
            if upload:
                request = VoiceTurnRequest(
                    session_id=session_id,
                    turn_id=f"turn-{self.turn}",
                    media_type=upload.media_type,
                    display_name=upload.name,
                    data=upload.data,
                )
                return asyncio.run(voice.run_turn(request, evidence_class=evidence))
            return asyncio.run(
                voice.run_fixture_turn(
                    session_id, f"turn-{self.turn}", fixture, evidence_class=evidence
                )
            )
        finally:
            if key:
                voice.end_session(session_id)


def safe_display(text: str, key: SecretStr | None = None) -> str:
    """Redact known credential and credential-shaped strings before presentation.

    Args:
        text: Untrusted service text or serialized record.
        key: Ephemeral key when available during the execution boundary.

    Returns:
        Redacted plain text, never HTML.
    """
    return redact(text, [key] if key else ())
