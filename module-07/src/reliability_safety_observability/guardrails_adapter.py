"""Guardrails AI safety provider executed inside the application safety boundary.

The adapter registers an application-owned validator through the supported
``guardrails.validators.register_validator`` API and executes it through a real
``guardrails.Guard``. No Hub validator installation, remote inference, Guardrails
server, LLM, credential, or network call is used. Hub usage metrics and
Guardrails OpenTelemetry tracing are disabled before every execution.

Guardrails results are safety evidence only. This module has no access to the
authorization policy and its results cannot grant authority.
"""

import os
import re
from typing import Any, Final

from guardrails import Guard, OnFailAction, settings
from guardrails.classes.rc import RC
from guardrails.validators import (
    FailResult,
    PassResult,
    ValidationResult,
    Validator,
    register_validator,
)

from .domain import Decision, EvidenceClass
from .errors import SafetyProviderError
from .safety_types import SafetyCheckResult, SafetyStage

VALIDATOR_ALIAS: Final = "module7/credential-leak"
_FAILURE_MESSAGE: Final = "credential_pattern_detected"

# Credential shapes that must never cross the input or output boundary.
_CREDENTIAL_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{16,}=*"),
    re.compile(r"(?i)\b(api[_-]?key|secret|password|passwd|token)\s*[:=]\s*\S{8,}"),
)


@register_validator(name=VALIDATOR_ALIAS, data_type="string")
class CredentialLeakValidator(Validator):
    """Guardrails validator rejecting text that contains credential material.

    The failure message is a fixed identifier so that the matched credential is
    never copied into Guardrails results, errors, or Module 7 evidence.
    """

    def _validate(self, value: Any, metadata: dict[str, Any]) -> ValidationResult:
        """Validate one string value.

        Args:
            value: Text supplied by the Guard.
            metadata: Guardrails call metadata; unused.

        Returns:
            A Guardrails pass or fail result.
        """
        text = value if isinstance(value, str) else ""
        if any(pattern.search(text) for pattern in _CREDENTIAL_PATTERNS):
            return FailResult(error_message=_FAILURE_MESSAGE)
        return PassResult()


def apply_deterministic_runtime_policy() -> None:
    """Force the local, telemetry-free Guardrails execution mode.

    Guardrails defaults to sending anonymous Hub usage metrics when no
    ``~/.guardrailsrc`` disables them, and constructing a ``Guard`` reloads that
    file. The policy is therefore re-applied around every execution.
    """
    os.environ["GUARDRAILS_RUN_SYNC"] = "true"
    settings.rc = RC(enable_metrics=False, use_remote_inferencing=False)
    settings.disable_tracing = True
    settings.use_server = False


class GuardrailsCredentialProvider:
    """Safety provider backed by real Guardrails validator execution."""

    def __init__(self) -> None:
        """Build a local Guard around the registered credential validator."""
        apply_deterministic_runtime_policy()
        validator = CredentialLeakValidator(on_fail=OnFailAction.NOOP, use_local=True)
        self._guard = Guard(use_server=False, history_max_length=1).use(validator)
        self._guard.configure(allow_metrics_collection=False)
        apply_deterministic_runtime_policy()

    @property
    def name(self) -> str:
        """Return the stable check identifier for Guardrails results."""
        return "guardrails_credential_leak"

    @property
    def evidence_class(self) -> EvidenceClass:
        """Return the evidence class of a real local Guardrails execution."""
        return EvidenceClass.DETERMINISTIC_FIXTURE

    def check(self, text: str, stage: SafetyStage) -> SafetyCheckResult:
        """Execute the Guardrails validator and translate its outcome.

        Args:
            text: Untrusted text to validate.
            stage: Boundary at which the text is validated.

        Returns:
            An allow or deny result attributable to Guardrails.

        Raises:
            SafetyProviderError: If Guardrails fails, does not execute the
                validator, or returns an unrecognized outcome.
        """
        apply_deterministic_runtime_policy()
        failure: str | None = None
        try:
            outcome = self._guard.validate(text)
            executed = self._executed_validator_outcomes()
        except Exception as exc:
            # Vendor failure boundary. Library errors may embed the validated
            # value, so only the error type survives; the exception is neither
            # chained nor retained as implicit context.
            failure = type(exc).__name__
        finally:
            self._guard.history.clear()

        if failure is not None:
            raise SafetyProviderError(f"Guardrails validation failed to execute ({failure}).")
        if executed != [_outcome_name(outcome.validation_passed)]:
            raise SafetyProviderError(
                "Guardrails did not execute the credential validator exactly once."
            )
        failures = [
            summary
            for summary in outcome.validation_summaries or []
            if summary.validator_name == CredentialLeakValidator.__name__
            and summary.validator_status == "fail"
        ]
        if outcome.validation_passed is True and not failures:
            reason = "guardrails_validation_passed"
            decision = Decision.ALLOW
        elif outcome.validation_passed is False and len(failures) == 1:
            reason = "guardrails_credential_detected"
            decision = Decision.DENY
        else:
            raise SafetyProviderError("Guardrails returned an unrecognized validation outcome.")

        return SafetyCheckResult(
            check=self.name,
            decision=decision,
            reason=f"{reason}_{stage.value}",
            evidence_class=self.evidence_class,
        )

    def _executed_validator_outcomes(self) -> list[str]:
        """Return the outcomes Guardrails logged for this validator's last run.

        Returns:
            The recorded ``pass``/``fail`` outcomes of the credential validator.
        """
        last_call = self._guard.history.last
        if last_call is None or last_call.iterations.last is None:
            return []
        return [
            str(getattr(log.validation_result.outcome, "value", log.validation_result.outcome))
            for log in last_call.iterations.last.validator_logs
            if log.registered_name == VALIDATOR_ALIAS and log.validation_result is not None
        ]


def _outcome_name(passed: bool | None) -> str:
    """Map a Guard pass flag to the validator outcome Guardrails records.

    Args:
        passed: The Guard's overall validation flag.

    Returns:
        ``pass`` when validation passed, otherwise ``fail``.
    """
    return "pass" if passed is True else "fail"
