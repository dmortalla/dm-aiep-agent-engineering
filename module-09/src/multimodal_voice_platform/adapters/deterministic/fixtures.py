"""Committed deterministic fixtures and their integrity-checked catalog.

Fixtures are small, project-generated files committed under ``fixture_data/``. The manifest is
committed application configuration: it records each fixture's media type, size, SHA-256 digest,
and the scripted output the deterministic adapters replay for it. Scripted output is fixed
annotation written for this project. It is not produced by any model.
"""

import hashlib
from collections.abc import Mapping
from importlib import resources
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Annotated, Final, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

from multimodal_voice_platform.adapters.deterministic.errors import (
    DeterministicInputError,
    FixtureIntegrityError,
    UnknownFixtureError,
)
from multimodal_voice_platform.contracts.limits import MAX_AUDIO_DURATION_MS, MAX_TRANSCRIPT_CHARS
from multimodal_voice_platform.contracts.modality import (
    MAX_INPUT_BYTES,
    MEDIA_TYPES,
    Identifier,
    Modality,
)
from multimodal_voice_platform.contracts.providers import BoundedText, DocumentSection

FIXTURE_PACKAGE: Final = "multimodal_voice_platform.adapters.deterministic.fixture_data"
MANIFEST_NAME: Final = "manifest.json"
MAX_FIXTURE_BYTES: Final = 64 * 1024
"""Repository ceiling for any committed fixture, far below the per-modality hard ceilings."""

FileName = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,62}\.[a-z0-9]{1,8}$")]
Sha256Hex = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class ScriptedSegment(BaseModel):
    """One scripted transcript segment replayed by the deterministic speech-to-text adapter."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str = Field(max_length=MAX_TRANSCRIPT_CHARS)
    is_final: bool
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0, le=MAX_AUDIO_DURATION_MS)


class VisionScript(BaseModel):
    """Scripted image annotation replayed by the deterministic vision adapter."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    description: BoundedText
    observations: tuple[BoundedText, ...] = Field(default=(), max_length=20)


class DocumentScript(BaseModel):
    """Scripted document structure replayed by the deterministic document adapter."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str | None = Field(default=None, max_length=300)
    sections: tuple[DocumentSection, ...] = Field(min_length=1, max_length=200)


class TranscriptScript(BaseModel):
    """Scripted transcript replayed by the deterministic speech-to-text adapter."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    segments: tuple[ScriptedSegment, ...] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def validate_segments(self) -> Self:
        """Require ordered spans with exactly one final segment, in last position.

        Returns:
            The validated script.

        Raises:
            ValueError: If spans are unordered or the final segment is missing or misplaced.
        """
        finals = [segment.is_final for segment in self.segments]
        if finals.count(True) != 1 or not finals[-1]:
            raise ValueError("transcript script must end with exactly one final segment")
        previous_start = 0
        for segment in self.segments:
            if segment.end_ms < segment.start_ms or segment.start_ms < previous_start:
                raise ValueError("transcript script spans must be ordered")
            previous_start = segment.start_ms
        return self


class FixtureSpec(BaseModel):
    """Manifest entry for one committed deterministic fixture."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    fixture_id: Identifier
    modality: Modality
    media_type: str
    file_name: FileName
    display_name: str = Field(min_length=1, max_length=128)
    size_bytes: int = Field(gt=0, le=MAX_FIXTURE_BYTES)
    sha256: Sha256Hex
    duration_ms: int | None = Field(default=None, gt=0, le=MAX_AUDIO_DURATION_MS)
    page_count: int | None = Field(default=None, gt=0)
    provenance: str = Field(min_length=1, max_length=500)
    vision: VisionScript | None = None
    document: DocumentScript | None = None
    transcript: TranscriptScript | None = None

    @model_validator(mode="after")
    def validate_spec(self) -> Self:
        """Bind media type, extension, metadata, and script to the fixture's modality.

        Returns:
            The validated spec.

        Raises:
            ValueError: If the media type, extension, metadata, or script does not fit the
                modality.
        """
        allowed = MEDIA_TYPES[self.modality]
        if self.media_type not in allowed:
            raise ValueError(f"media type {self.media_type!r} is not allowed for {self.modality}")
        for name in (self.file_name, self.display_name):
            if PurePosixPath(name).suffix.lower() not in allowed[self.media_type]:
                raise ValueError("fixture extension does not match media type")
        if self.size_bytes > MAX_INPUT_BYTES[self.modality]:
            raise ValueError("fixture exceeds the modality hard size ceiling")
        if (self.modality is Modality.AUDIO) != (self.duration_ms is not None):
            raise ValueError("duration_ms is required for, and only for, audio fixtures")
        if self.page_count is not None and self.modality is not Modality.DOCUMENT:
            raise ValueError("page_count applies only to document fixtures")
        expected_script = {
            Modality.TEXT: None,
            Modality.IMAGE: "vision",
            Modality.AUDIO: "transcript",
            Modality.DOCUMENT: "document",
        }[self.modality]
        present = [
            name for name in ("vision", "document", "transcript") if getattr(self, name) is not None
        ]
        if present != ([expected_script] if expected_script else []):
            raise ValueError(f"{self.modality} fixture has the wrong scripted output")
        transcript_end = self.transcript.segments[-1].end_ms if self.transcript else 0
        if self.duration_ms is not None and transcript_end > self.duration_ms:
            raise ValueError("transcript script extends beyond the audio duration")
        return self


class FixtureManifest(BaseModel):
    """The committed fixture manifest."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    fixtures: tuple[FixtureSpec, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def validate_fixtures(self) -> Self:
        """Require unique IDs, unique files, and coverage of every modality.

        Returns:
            The validated manifest.

        Raises:
            ValueError: If IDs or files repeat, or a modality has no fixture.
        """
        ids = [spec.fixture_id for spec in self.fixtures]
        files = [spec.file_name for spec in self.fixtures]
        if len(set(ids)) != len(ids) or len(set(files)) != len(files):
            raise ValueError("fixture IDs and file names must be unique")
        if {spec.modality for spec in self.fixtures} != set(Modality):
            raise ValueError("the manifest must cover every modality")
        return self


class FixtureCatalog:
    """Integrity-checked, read-only catalog of committed deterministic fixtures.

    Fixtures are looked up by ID only. No caller-supplied value is ever used as a path.
    """

    def __init__(self, manifest: FixtureManifest, contents: Mapping[str, bytes]) -> None:
        """Verify every fixture's bytes against the manifest and build the catalog.

        Args:
            manifest: The validated fixture manifest.
            contents: Fixture bytes keyed by manifest file name.

        Raises:
            FixtureIntegrityError: If a file is missing, unexpected, or does not match its recorded
                size or SHA-256 digest.
        """
        expected = {spec.file_name for spec in manifest.fixtures}
        if set(contents) != expected:
            raise FixtureIntegrityError("fixture files do not match the manifest")
        specs: dict[str, FixtureSpec] = {}
        data: dict[str, bytes] = {}
        by_digest: dict[tuple[Modality, str], FixtureSpec] = {}
        for spec in manifest.fixtures:
            content = contents[spec.file_name]
            digest = hashlib.sha256(content).hexdigest()
            if len(content) != spec.size_bytes or digest != spec.sha256:
                raise FixtureIntegrityError(f"fixture {spec.fixture_id} failed its integrity check")
            specs[spec.fixture_id] = spec
            data[spec.fixture_id] = content
            by_digest[(spec.modality, digest)] = spec
        self._specs = MappingProxyType(specs)
        self._data = MappingProxyType(data)
        self._by_digest = MappingProxyType(by_digest)

    @classmethod
    def load_default(cls) -> Self:
        """Load the committed manifest and fixtures packaged with this module.

        Returns:
            The verified catalog.

        Raises:
            FixtureIntegrityError: If the manifest is malformed or any fixture fails verification.
        """
        root = resources.files(FIXTURE_PACKAGE)
        try:
            manifest = FixtureManifest.model_validate_json(
                root.joinpath(MANIFEST_NAME).read_bytes()
            )
        except ValidationError as exc:
            raise FixtureIntegrityError("the fixture manifest is malformed") from exc
        contents: dict[str, bytes] = {}
        for spec in manifest.fixtures:
            try:
                contents[spec.file_name] = root.joinpath(spec.file_name).read_bytes()
            except FileNotFoundError as exc:
                raise FixtureIntegrityError(f"fixture {spec.fixture_id} is missing") from exc
        return cls(manifest, contents)

    @property
    def fixture_ids(self) -> tuple[str, ...]:
        """Return every fixture ID in manifest order."""
        return tuple(self._specs)

    def get(self, fixture_id: str) -> FixtureSpec:
        """Return the spec for a fixture.

        Args:
            fixture_id: Fixture ID from the manifest.

        Returns:
            The fixture spec.

        Raises:
            UnknownFixtureError: If the ID is not in the catalog.
        """
        try:
            return self._specs[fixture_id]
        except KeyError as exc:
            raise UnknownFixtureError("fixture ID is not in the deterministic catalog") from exc

    def content(self, fixture_id: str) -> bytes:
        """Return a fixture's verified bytes.

        Args:
            fixture_id: Fixture ID from the manifest.

        Returns:
            The fixture bytes.

        Raises:
            UnknownFixtureError: If the ID is not in the catalog.
        """
        self.get(fixture_id)
        return self._data[fixture_id]

    def match(self, modality: Modality, content: bytes) -> FixtureSpec:
        """Identify which committed fixture some content is, by exact digest.

        Deterministic adapters only replay scripts for known fixtures. They never guess.

        Args:
            modality: Modality the content was submitted as.
            content: The content bytes.

        Returns:
            The matching fixture spec.

        Raises:
            DeterministicInputError: If the content is not a committed fixture of that modality.
        """
        digest = hashlib.sha256(content).hexdigest()
        try:
            return self._by_digest[(modality, digest)]
        except KeyError as exc:
            raise DeterministicInputError(
                "content does not match any deterministic fixture for this modality"
            ) from exc
