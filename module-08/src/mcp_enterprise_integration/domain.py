"""Typed foundational contracts for enterprise interoperability."""

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Identifier = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=128),
]


class ClientFramework(StrEnum):
    """Supported client/framework identities."""

    APPLICATION = "application"
    OPENAI = "openai"
    GOOGLE_ADK = "google_adk"


class TransportKind(StrEnum):
    """Transport identities required by the approved architecture."""

    IN_PROCESS = "in_process"
    STREAMABLE_HTTP = "streamable_http"


class AuthorizationDecision(StrEnum):
    """Application-owned authorization outcomes."""

    ALLOW = "allow"
    DENY = "deny"


class InvocationStatus(StrEnum):
    """Validated invocation outcomes."""

    SUCCEEDED = "succeeded"
    DENIED = "denied"
    FAILED = "failed"


class ValidationStatus(StrEnum):
    """Validation outcomes for boundary data."""

    VALID = "valid"
    INVALID = "invalid"


class CapabilityDescriptor(BaseModel):
    """Describe a discoverable enterprise capability without granting authority."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    capability_id: Identifier
    name: Identifier
    description: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
    ]


class InvocationContext(BaseModel):
    """Identify an invocation without embedding authorization authority."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    invocation_id: Identifier
    client_id: Identifier
    client_framework: ClientFramework
    capability_id: Identifier
    transport: TransportKind


class AuthorizationResult(BaseModel):
    """Record an application-owned authorization decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: AuthorizationDecision
    reason: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
    ]


class InvocationResult(BaseModel):
    """Represent sanitized invocation metadata for later evidence generation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    invocation_id: Identifier
    capability_id: Identifier
    status: InvocationStatus
    validation_status: ValidationStatus
    latency_ms: float = Field(ge=0.0, le=300_000.0)
    summary: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=1000),
    ]
