"""Trusted local effect declarations and strictly validated verification observations.

Callbacks must implement bounded, quiescent observations: NOT_COMMITTED means
no earlier invocation can subsequently commit. An eventually consistent absence
is UNKNOWN. Identity and timeout are data, never authorization. Adapters retain
independent permissions. Synchronous callbacks must honor the supplied timeout.
"""

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from math import isfinite
from typing import Annotated, Literal, Self

from pydantic import Field, ValidationError, model_validator

from harness_engineering.errors import ContractValidationError, HarnessError
from harness_engineering.orchestration import StepResult
from harness_engineering.persistence import (
    CheckpointIdentity,
    EffectIdentity,
    Reference,
    SnapshotData,
)


class EffectVerificationError(HarnessError):
    """Effect observation cannot establish safe commitment or noncommitment."""


class EffectSpec(SnapshotData):
    """Trusted bootstrap's exact application, operation, and accepted-input digest."""

    application: Reference
    work_id: Reference
    operation: Reference
    input_digest: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$", strict=True)]

    def identity(self, workflow: CheckpointIdentity) -> EffectIdentity:
        """Derive a stable key; request, result, and persisted text never select it."""
        checked = EffectSpec.model_validate(self)
        bound = CheckpointIdentity.model_validate(workflow)
        encoded = json.dumps(
            {
                "contract": "effect-v1",
                "workflow": bound.model_dump(mode="json"),
                **checked.model_dump(),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return EffectIdentity(
            application=checked.application,
            workflow=bound,
            work_id=checked.work_id,
            key=hashlib.sha256(encoded).hexdigest(),
        )


class EffectObservation(SnapshotData):
    """Untrusted inert observation requiring exact expected-identity reconciliation."""

    identity: EffectIdentity
    status: Literal["committed", "not_committed", "unknown"]
    result: Annotated[str | None, Field(max_length=4096, strict=True)]

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        """Noncommitted/unknown observations cannot nominate reconstruction data."""
        if self.status != "committed" and self.result is not None:
            raise ValueError("Only committed observations can carry a result.")
        return self


@dataclass(frozen=True)
class EffectDeclaration:
    """Application-owned callbacks, never serialized or loaded from history.

    invoke receives the derived identity and remaining timeout, and operates on
    fixed accepted inputs bound by spec.input_digest. It must use that key for
    its external idempotency contract. verify returns an observation of precisely
    that effect and a validated reconstruction result when committed. Both must
    cooperate with timeout; Python callbacks cannot be forcibly preempted here.
    allow_retry permits re-entry only after conclusive noncommitment, subject to
    the existing retry, backoff, circuit, cancellation, and deadline limits.
    """

    spec: EffectSpec
    invoke: Callable[[EffectIdentity, float], StepResult]
    verify: Callable[[EffectIdentity, float], EffectObservation]
    allow_retry: bool = False
    timeout_seconds: float = 1.0


def checked_observation(value: object, expected: EffectIdentity) -> EffectObservation:
    """Validate external observations and exact identity before influencing execution."""
    try:
        checked = EffectObservation.model_validate(value)
    except ValidationError as exc:
        raise EffectVerificationError("Malformed effect verification observation.") from exc
    if checked.identity != expected:
        raise EffectVerificationError("Verification identity conflicts with the expected effect.")
    if checked.status == "unknown":
        raise EffectVerificationError("Effect commitment is ambiguous; obtain conclusive evidence.")
    if checked.status == "committed" and checked.result is None:
        raise EffectVerificationError("Committed effect has no safe reconstruction result.")
    return checked


def checked_declarations(
    declarations: tuple[EffectDeclaration, ...],
    work: tuple[str, ...],
) -> tuple[EffectDeclaration, ...]:
    """Snapshot bootstrap declarations, rejecting unsupported callback/configuration data."""
    if type(declarations) is not tuple or len(declarations) > 100:
        raise ContractValidationError("Effects must be a bounded tuple of trusted declarations.")
    result = []
    for item in declarations:
        if type(item) is not EffectDeclaration:
            raise ContractValidationError("Bind application-owned effect declarations.")
        try:
            spec = EffectSpec.model_validate(item.spec)
        except ValidationError as exc:
            raise ContractValidationError("Malformed trusted effect specification.") from exc
        if (
            spec.work_id not in work
            or not callable(item.invoke)
            or not callable(item.verify)
            or type(item.allow_retry) is not bool
            or type(item.timeout_seconds) is not float
            or not isfinite(item.timeout_seconds)
            or not 0 < item.timeout_seconds <= 30
        ):
            raise ContractValidationError("Invalid effect work, callbacks, retry flag, or timeout.")
        result.append(
            EffectDeclaration(
                spec,
                item.invoke,
                item.verify,
                item.allow_retry,
                item.timeout_seconds,
            )
        )
    if len({item.spec.work_id for item in result}) != len(result):
        raise ContractValidationError("One logical effect declaration per work item is required.")
    return tuple(result)
