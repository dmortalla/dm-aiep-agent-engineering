"""Committed voice-conversation fixtures for the deterministic voice assistant (Story 9.6).

The Story 9.2 catalog holds one fixture per modality. A conversation needs several utterances, so
Story 9.6 commits its own small set of audio fixtures, each with a scripted transcript, and extends
the verified Story 9.2 catalog with them. The combined catalog is integrity-checked by the same
``FixtureCatalog`` and replayed by the same fixture-playback speech-to-text adapter.

Each fixture's audio is a generated placeholder tone, not recorded speech, and its transcript is a
scripted utterance replayed by digest match. Fixture playback is not speech recognition.
"""

from importlib import resources
from typing import Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from multimodal_voice_platform.adapters.deterministic.errors import FixtureIntegrityError
from multimodal_voice_platform.adapters.deterministic.fixtures import (
    MANIFEST_NAME,
    FixtureCatalog,
    FixtureManifest,
    FixtureSpec,
)
from multimodal_voice_platform.contracts.modality import Modality

VOICE_FIXTURE_PACKAGE: Final = "multimodal_voice_platform.voice.fixture_data"
VOICE_FIXTURE_IDS: Final = ("voice-remember", "voice-recall", "voice-injection")
"""The committed conversation: remember a value, recall it, and an injection-like utterance."""


class VoiceFixtureManifest(BaseModel):
    """The committed voice-conversation fixture manifest. Audio fixtures with transcripts only."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    fixtures: tuple[FixtureSpec, ...] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def validate_fixtures(self) -> Self:
        """Require scripted audio fixtures only.

        Returns:
            The validated manifest.

        Raises:
            ValueError: If a fixture is not audio with a scripted transcript.
        """
        if any(spec.modality is not Modality.AUDIO for spec in self.fixtures):
            raise ValueError("voice-conversation fixtures are audio fixtures")
        return self


def load_voice_catalog(base: FixtureCatalog | None = None) -> FixtureCatalog:
    """Return the Story 9.2 catalog extended with the committed voice-conversation fixtures.

    Args:
        base: Verified base catalog. Defaults to the packaged Story 9.2 fixtures.

    Returns:
        The verified combined catalog.

    Raises:
        FixtureIntegrityError: If either manifest is malformed, a file is missing, an ID or file
            name collides, or any fixture fails its size or SHA-256 check.
    """
    base = base if base is not None else FixtureCatalog.load_default()
    root = resources.files(VOICE_FIXTURE_PACKAGE)
    try:
        voice = VoiceFixtureManifest.model_validate_json(root.joinpath(MANIFEST_NAME).read_bytes())
    except ValidationError as exc:
        raise FixtureIntegrityError("the voice fixture manifest is malformed") from exc
    specs = [base.get(fixture_id) for fixture_id in base.fixture_ids]
    contents = {spec.file_name: base.content(spec.fixture_id) for spec in specs}
    for spec in voice.fixtures:
        if spec.file_name in contents:
            raise FixtureIntegrityError("a voice fixture collides with a base fixture file")
        try:
            contents[spec.file_name] = root.joinpath(spec.file_name).read_bytes()
        except FileNotFoundError as exc:
            raise FixtureIntegrityError(f"fixture {spec.fixture_id} is missing") from exc
    try:
        manifest = FixtureManifest(schema_version=1, fixtures=(*specs, *voice.fixtures))
    except ValidationError as exc:
        raise FixtureIntegrityError("the combined fixture manifest is invalid") from exc
    return FixtureCatalog(manifest, contents)
