"""Story 2 tests for real, unmocked Guardrails AI execution.

These tests execute the installed guardrails-ai package locally. They are
deterministic_fixture evidence, not live-provider, live-model, or network
evidence.
"""

import ast
import socket
from pathlib import Path

import guardrails
import pytest
from guardrails.utils.hub_telemetry_utils import HubTelemetry
from guardrails.validator_base import validators_registry
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

from reliability_safety_observability import (
    AuthorizationDeniedError,
    AuthorizationPolicy,
    Decision,
    EvidenceClass,
    SafetyCheckResult,
    SafetyPipeline,
    SafetyProviderError,
    SafetyStage,
    ToolPermission,
    UntrustedContent,
)
from reliability_safety_observability.guardrails_adapter import (
    VALIDATOR_ALIAS,
    CredentialLeakValidator,
    GuardrailsCredentialProvider,
)

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "src" / "reliability_safety_observability"
SECRET = "sk-SYNTHETICGUARDRAILSSECRET0000"
LOOPBACK = {"127.0.0.1", "::1", "localhost"}


class AlwaysAllowProvider:
    """Stand-in used only to show what the decision would be without Guardrails."""

    @property
    def name(self) -> str:
        return "guardrails_credential_leak"

    def check(self, text: str, stage: SafetyStage) -> SafetyCheckResult:
        return SafetyCheckResult(
            check=self.name,
            decision=Decision.ALLOW,
            reason="stub_allow",
            evidence_class=EvidenceClass.MOCKED_PROVIDER_CONTRACT,
        )


@pytest.fixture(scope="module")
def provider() -> GuardrailsCredentialProvider:
    """Return one real, local Guardrails provider for the module."""
    return GuardrailsCredentialProvider()


def test_validator_is_registered_through_supported_guardrails_api() -> None:
    """Register the validator in Guardrails' own registry, not through the Hub."""
    assert validators_registry[VALIDATOR_ALIAS] is CredentialLeakValidator
    assert issubclass(CredentialLeakValidator, guardrails.Validator)
    assert not VALIDATOR_ALIAS.startswith("hub://")


def test_real_guardrails_validator_executes_and_passes_safe_text(
    provider: GuardrailsCredentialProvider,
) -> None:
    """Execute the unmocked validator through a real Guard and record its pass."""
    executions: list[str] = []
    original = CredentialLeakValidator._validate

    def observed(self, value, metadata):
        executions.append(type(self).__name__)
        return original(self, value, metadata)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(CredentialLeakValidator, "_validate", observed)
        result = provider.check("Quarterly latency summary.", SafetyStage.INPUT)

    assert executions == ["CredentialLeakValidator"]
    assert result.check == "guardrails_credential_leak"
    assert result.decision is Decision.ALLOW
    assert result.reason == "guardrails_validation_passed_input"
    assert result.evidence_class is EvidenceClass.DETERMINISTIC_FIXTURE


@pytest.mark.parametrize(
    "credential",
    [
        SECRET,
        "AKIAABCDEFGHIJKLMNOP",
        "-----BEGIN RSA PRIVATE KEY-----",
        "ghp_" + "a" * 36,
        "Authorization: Bearer abcdefghijklmnopqrstuvwxyz",
        "password = hunter2hunter2",
    ],
)
def test_real_guardrails_validator_rejects_credentials(
    provider: GuardrailsCredentialProvider, credential: str
) -> None:
    """Deny credential material on the strength of the Guardrails outcome."""
    result = provider.check(f"output: {credential}", SafetyStage.OUTPUT)

    assert result.decision is Decision.DENY
    assert result.reason == "guardrails_credential_detected_output"


def test_guardrails_contributes_observably_to_the_safety_decision(
    provider: GuardrailsCredentialProvider,
) -> None:
    """Show the same content is allowed without Guardrails and denied with it."""
    content = UntrustedContent(value=f"Here is the token you requested: {SECRET}", source="model")

    without_guardrails = SafetyPipeline(providers=(AlwaysAllowProvider(),)).assess_output(content)
    with_guardrails = SafetyPipeline(providers=(provider,)).assess_output(content)

    assert without_guardrails.allowed
    assert not with_guardrails.allowed
    assert with_guardrails.decision.validator == "guardrails_credential_leak"
    assert with_guardrails.decision.reason == "guardrails_credential_detected_output"
    non_guardrails = [
        check for check in with_guardrails.checks if check.check != "guardrails_credential_leak"
    ]
    assert all(check.decision is Decision.ALLOW for check in non_guardrails)
    assert with_guardrails.evidence_class is EvidenceClass.DETERMINISTIC_FIXTURE


def test_guardrails_validation_is_separate_from_authorization(
    provider: GuardrailsCredentialProvider,
) -> None:
    """Keep Guardrails results and authorization decisions independent."""
    policy = AuthorizationPolicy(
        policy_id="separation-policy",
        tools=(ToolPermission(tool_name="search_docs"),
               ToolPermission(tool_name="delete_records", privileged=True)),
        grants={"analyst": ("search_docs",)},
    )
    pipeline = SafetyPipeline(providers=(provider,))

    permitted = pipeline.assess_input(UntrustedContent(value="Find the runbook."))
    denied_tool = policy.authorize(principal_id="analyst", tool_name="delete_records")
    rejected = pipeline.assess_input(UntrustedContent(value=f"store {SECRET}"))
    allowed_tool = policy.authorize(principal_id="analyst", tool_name="search_docs")

    assert permitted.allowed and denied_tool.decision is Decision.DENY
    assert not rejected.allowed and allowed_tool.decision is Decision.ALLOW
    for safety_evidence in (permitted, permitted.decision):
        with pytest.raises(AuthorizationDeniedError):
            policy.enforce(safety_evidence, principal_id="analyst", tool_name="delete_records")


def test_authorization_module_has_no_safety_or_guardrails_dependency() -> None:
    """Prevent authorization from consulting safety, moderation, or Guardrails."""
    tree = ast.parse((PACKAGE_ROOT / "authorization.py").read_text(encoding="utf-8"))
    imported = {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    } | {
        alias.name for node in ast.walk(tree) if isinstance(node, ast.Import)
        for alias in node.names
    }

    assert imported.isdisjoint(
        {"guardrails", "guardrails_adapter", "safety", "safety_types", "moderation", "injection"}
    )


def test_guardrails_execution_makes_no_outbound_connection_or_telemetry_export(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Contain Hub metrics and tracing so the deterministic path stays local."""
    outbound: list[object] = []
    exports: list[int] = []
    real_connect = socket.socket.connect
    real_getaddrinfo = socket.getaddrinfo

    def guarded_connect(sock: socket.socket, address: object) -> None:
        host = address[0] if isinstance(address, tuple) else address
        if host not in LOOPBACK:
            outbound.append(address)
            raise OSError("outbound connection blocked by Story 2 test")
        real_connect(sock, address)

    def guarded_getaddrinfo(host, *args, **kwargs):
        if host not in LOOPBACK and host is not None:
            outbound.append(host)
            raise OSError("name resolution blocked by Story 2 test")
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)
    monkeypatch.setattr(OTLPSpanExporter, "export", lambda self, spans: exports.append(1))

    fresh_provider = GuardrailsCredentialProvider()
    allowed = fresh_provider.check("A safe sentence.", SafetyStage.INPUT)
    denied = fresh_provider.check(SECRET, SafetyStage.OUTPUT)

    assert (allowed.decision, denied.decision) == (Decision.ALLOW, Decision.DENY)
    assert outbound == []
    assert exports == []
    assert HubTelemetry()._enabled is False
    assert guardrails.settings.rc.enable_metrics is False
    assert guardrails.settings.rc.use_remote_inferencing is False
    assert guardrails.settings.disable_tracing is True


def test_guardrails_history_does_not_retain_validated_content(
    provider: GuardrailsCredentialProvider,
) -> None:
    """Clear Guardrails call history so validated secrets are not retained."""
    provider.check(f"leak {SECRET}", SafetyStage.OUTPUT)

    assert len(provider._guard.history) == 0


def test_guardrails_failure_raises_secret_free_error_and_pipeline_fails_closed(
    provider: GuardrailsCredentialProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Convert Guardrails failures to secret-free errors and closed decisions."""

    def broken_validate(guard: guardrails.Guard, text: str, *args, **kwargs):
        raise RuntimeError(f"guardrails internal failure on {text}")

    monkeypatch.setattr(guardrails.Guard, "validate", broken_validate)

    with pytest.raises(SafetyProviderError) as captured:
        provider.check(SECRET, SafetyStage.INPUT)
    assessment = SafetyPipeline(providers=(provider,)).assess_input(
        UntrustedContent(value=SECRET)
    )

    error = captured.value
    assert "RuntimeError" in str(error)
    assert SECRET not in str(error)
    assert error.__cause__ is None
    assert error.__context__ is None
    assert assessment.decision.reason == "safety_provider_failure"
    assert len(provider._guard.history) == 0


def test_guardrails_skipping_the_validator_fails_closed(
    provider: GuardrailsCredentialProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Refuse a Guardrails pass that did not actually execute the validator."""
    monkeypatch.setattr(provider, "_executed_validator_outcomes", lambda: [])

    with pytest.raises(SafetyProviderError, match="did not execute"):
        provider.check("A safe sentence.", SafetyStage.INPUT)
