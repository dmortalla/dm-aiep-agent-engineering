"""Layered, fail-closed safety pipeline for untrusted input and output.

The pipeline combines deterministic application checks, prompt-injection
inspection, application-owned moderation, and pluggable safety providers such
as the Guardrails AI adapter. It produces safety evidence only: it holds no
reference to authorization policy and its results cannot grant authority.
"""

import logging
import re
from collections.abc import Sequence
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from .domain import (
    Decision,
    EvidenceClass,
    SafetyDecision,
    UntrustedContent,
    WorkflowIdentity,
)
from .errors import ConfigurationError
from .injection import inspect_for_injection
from .logging import log_event
from .moderation import ModerationPolicy
from .safety_types import SafetyAssessment, SafetyCheckResult, SafetyProvider, SafetyStage

_CONTROL_CHARACTERS: Final = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_BIDI_OVERRIDES: Final = re.compile(r"[\u202a-\u202e\u2066-\u2069]")
_PIPELINE_VALIDATOR: Final = "safety_pipeline"


class SafetyPolicy(BaseModel):
    """Committed deterministic input and output safety limits.

    Attributes:
        max_input_chars: Largest accepted untrusted input.
        max_output_chars: Largest accepted model or tool output.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_input_chars: int = Field(default=8_000, ge=1, le=20_000)
    max_output_chars: int = Field(default=8_000, ge=1, le=20_000)

    def check_input(self, text: str) -> SafetyCheckResult:
        """Apply deterministic input rules.

        Args:
            text: Untrusted input text.

        Returns:
            The deterministic input check result.
        """
        if not text.strip():
            return _deterministic("input_policy", Decision.DENY, "input_empty")
        if len(text) > self.max_input_chars:
            return _deterministic("input_policy", Decision.DENY, "input_too_long")
        if _CONTROL_CHARACTERS.search(text):
            return _deterministic("input_policy", Decision.DENY, "input_control_characters")
        if _BIDI_OVERRIDES.search(text):
            return _deterministic("input_policy", Decision.DENY, "input_bidi_override")
        return _deterministic("input_policy", Decision.ALLOW, "input_permitted")

    def check_output(self, text: str) -> SafetyCheckResult:
        """Apply deterministic output rules.

        Args:
            text: Untrusted model or tool output.

        Returns:
            The deterministic output check result.
        """
        if not text.strip():
            return _deterministic("output_policy", Decision.DENY, "output_empty")
        if len(text) > self.max_output_chars:
            return _deterministic("output_policy", Decision.DENY, "output_too_long")
        if _CONTROL_CHARACTERS.search(text):
            return _deterministic("output_policy", Decision.DENY, "output_control_characters")
        if _BIDI_OVERRIDES.search(text):
            return _deterministic("output_policy", Decision.DENY, "output_bidi_override")
        return _deterministic("output_policy", Decision.ALLOW, "output_permitted")


def _deterministic(check: str, decision: Decision, reason: str) -> SafetyCheckResult:
    """Build a deterministic application check result.

    Args:
        check: Check identifier.
        decision: Check outcome.
        reason: Reason identifier.

    Returns:
        A deterministic_fixture check result.
    """
    return SafetyCheckResult(
        check=check,
        decision=decision,
        reason=reason,
        evidence_class=EvidenceClass.DETERMINISTIC_FIXTURE,
    )


def _injection_check(content: UntrustedContent) -> SafetyCheckResult:
    """Translate injection inspection into a safety check result.

    Args:
        content: Untrusted content.

    Returns:
        A deny result naming the first marker class, or an allow result.
    """
    assessment = inspect_for_injection(content)
    if assessment.detected:
        return _deterministic(
            "prompt_injection", Decision.DENY, f"prompt_injection_{assessment.markers[0]}"
        )
    return _deterministic("prompt_injection", Decision.ALLOW, "no_injection_detected")


def _combined_evidence(checks: Sequence[SafetyCheckResult]) -> EvidenceClass:
    """Return the weakest evidence class among contributing checks.

    Mixed evidence is never upgraded to a live classification.

    Args:
        checks: Contributing check results.

    Returns:
        The aggregate evidence classification.
    """
    classes = {check.evidence_class for check in checks}
    if len(classes) == 1:
        return classes.pop()
    for weaker in (EvidenceClass.MOCKED_PROVIDER_CONTRACT, EvidenceClass.SIMULATED_FAILURE):
        if weaker in classes:
            return weaker
    return EvidenceClass.DETERMINISTIC_FIXTURE


class SafetyPipeline:
    """Application safety boundary for untrusted input and output."""

    def __init__(
        self,
        *,
        providers: Sequence[SafetyProvider],
        policy: SafetyPolicy | None = None,
        moderation: ModerationPolicy | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        """Configure the layered safety pipeline.

        Args:
            providers: Safety providers executed for every assessment.
            policy: Deterministic input and output limits.
            moderation: Application-owned moderation policy.
            logger: Optional logger receiving redacted decision records.

        Raises:
            ConfigurationError: If no safety provider is configured.
        """
        if not providers:
            raise ConfigurationError("Safety pipeline requires at least one safety provider.")
        self._providers = tuple(providers)
        self._policy = policy or SafetyPolicy()
        self._moderation = moderation or ModerationPolicy()
        self._logger = logger

    def assess_input(
        self, content: UntrustedContent, identity: WorkflowIdentity | None = None
    ) -> SafetyAssessment:
        """Assess untrusted input before it reaches a model or tool.

        Args:
            content: Untrusted input.
            identity: Optional workflow correlation for the decision record.

        Returns:
            The aggregated input safety assessment.
        """
        return self._assess(content, SafetyStage.INPUT, identity)

    def assess_output(
        self, content: UntrustedContent, identity: WorkflowIdentity | None = None
    ) -> SafetyAssessment:
        """Assess untrusted model or tool output before it is released.

        Args:
            content: Untrusted output.
            identity: Optional workflow correlation for the decision record.

        Returns:
            The aggregated output safety assessment.
        """
        return self._assess(content, SafetyStage.OUTPUT, identity)

    def _assess(
        self,
        content: UntrustedContent,
        stage: SafetyStage,
        identity: WorkflowIdentity | None,
    ) -> SafetyAssessment:
        """Run every safety layer and derive a fail-closed decision.

        Args:
            content: Untrusted content.
            stage: Assessment boundary.
            identity: Optional workflow correlation.

        Returns:
            The aggregated safety assessment.
        """
        correlation = identity or WorkflowIdentity()
        deterministic = (
            self._policy.check_input(content.value)
            if stage is SafetyStage.INPUT
            else self._policy.check_output(content.value)
        )
        checks = [
            deterministic,
            _injection_check(content),
            self._moderation.moderate(content.value),
        ]
        checks.extend(
            self._run_provider(provider, content.value, stage, correlation)
            for provider in self._providers
        )

        denied = next((check for check in checks if check.decision is Decision.DENY), None)
        decision = (
            SafetyDecision(decision=Decision.DENY, validator=denied.check, reason=denied.reason)
            if denied is not None
            else SafetyDecision(
                decision=Decision.ALLOW, validator=_PIPELINE_VALIDATOR, reason="all_checks_passed"
            )
        )
        assessment = SafetyAssessment(
            stage=stage,
            decision=decision,
            checks=tuple(checks),
            evidence_class=_combined_evidence(checks),
        )
        self._log(
            "safety_decision",
            correlation,
            {
                "stage": stage.value,
                "decision": decision.decision.value,
                "validator": decision.validator,
                "reason": decision.reason,
                "evidence_class": assessment.evidence_class.value,
                "checks": [
                    {"check": check.check, "decision": check.decision.value, "reason": check.reason}
                    for check in checks
                ],
            },
        )
        return assessment

    def _run_provider(
        self,
        provider: SafetyProvider,
        text: str,
        stage: SafetyStage,
        identity: WorkflowIdentity,
    ) -> SafetyCheckResult:
        """Execute one provider at its failure boundary, failing closed.

        Any provider failure or malformed result becomes a deny result. Error
        messages are not recorded because providers may echo inspected content.

        Args:
            provider: Safety provider to execute.
            text: Untrusted text.
            stage: Assessment boundary.
            identity: Workflow correlation.

        Returns:
            The provider's result, or a fail-closed deny result.
        """
        name = provider.name
        try:
            result = provider.check(text, stage)
        # Deliberate failure boundary: an untrusted provider failing in any way
        # must deny rather than propagate or be mistaken for an allow result.
        except Exception as exc:
            self._log(
                "safety_provider_failure",
                identity,
                {"provider": name, "error_type": type(exc).__name__},
            )
            return _deterministic(name, Decision.DENY, "safety_provider_failure")

        if not isinstance(result, SafetyCheckResult) or result.check != name:
            self._log(
                "safety_provider_failure",
                identity,
                {"provider": name, "error_type": "malformed_result"},
            )
            return _deterministic(name, Decision.DENY, "safety_provider_malformed_result")
        return result

    def _log(self, event: str, identity: WorkflowIdentity, fields: dict[str, object]) -> None:
        """Emit a redacted local decision record when logging is configured.

        Args:
            event: Event name.
            identity: Workflow correlation.
            fields: Content-free structured fields.
        """
        if self._logger is not None:
            log_event(
                self._logger,
                event=event,
                workflow_id=identity.workflow_id,
                trace_id=identity.trace_id,
                fields=fields,
            )
