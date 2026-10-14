"""Typed HTTP schemas and explicit domain conversions."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from module10_ai.contracts import InferenceRequest, InferenceResult


class HttpModel(BaseModel):
    """Reject extra fields and implicit scalar coercion at the HTTP boundary."""

    model_config = ConfigDict(extra="forbid", strict=True)


class InferenceInput(HttpModel):
    """Bounded lexical input; instruction-like text has no privileged authority."""

    text: str = Field(min_length=1, max_length=4096, repr=False)
    keyword_limit: int = Field(default=5, ge=1, le=10)

    @field_validator("text")
    @classmethod
    def nonblank(cls, value: str) -> str:
        """Reject blank input without echoing its content."""
        if not value.strip():
            raise ValueError("Text must contain non-whitespace characters.")
        return value

    def to_domain(self) -> InferenceRequest:
        """Convert validated HTTP data into the accepted application contract."""
        return InferenceRequest(self.text, self.keyword_limit)


class InferenceOutput(HttpModel):
    """Deterministic data only, with transport correlation metadata."""

    word_count: int = Field(ge=0, le=4096)
    keywords: list[Annotated[str, Field(min_length=1, max_length=4096)]] = Field(
        max_length=10,
        repr=False,
    )
    evidence: Literal["deterministic"]
    request_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")

    @classmethod
    def from_domain(cls, result: InferenceResult, request_id: str) -> "InferenceOutput":
        """Convert application output without adding inference behavior."""
        return cls(
            word_count=result.word_count,
            keywords=list(result.keywords),
            evidence=result.evidence.value,
            request_id=request_id,
        )


class ErrorOutput(HttpModel):
    """Small stable error envelope without raw validation or exception details."""

    code: str
    message: str
    request_id: str


class HealthOutput(HttpModel):
    """Process or deterministic application health; never cloud readiness."""

    status: Literal["alive", "ready", "not-ready"]
    mode: Literal["deterministic"] = "deterministic"
