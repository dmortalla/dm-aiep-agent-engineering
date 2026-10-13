"""Integrated deterministic Story 4 exit evidence for REQ-LAB-003."""

import json
import socket
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import replace

import pytest
from pydantic import BaseModel, ValidationError

from harness_engineering.capabilities import CapabilityRegistry
from harness_engineering.domain import EvidenceClass, RuntimeBudget
from harness_engineering.errors import ContractValidationError, ToolExecutionError
from harness_engineering.execution import (
    BoundedToolExecutor,
    ExecutionContext,
    ExecutionLimits,
    ToolHandler,
)
from harness_engineering.permission_lab import (
    SCENARIOS,
    LabOutcome,
    LabScenario,
    PermissionLabResult,
    SearchInput,
    SearchOutput,
    main,
    render_permission_lab,
    run_permission_lab,
)
from harness_engineering.permissions import (
    ActionProposal,
    AuthorizationDecision,
    CapabilityAuthorizer,
)


def test_all_required_scenarios_and_determinism() -> None:
    first = run_permission_lab()
    assert {item.scenario.scenario_id for item in first} == {
        "allow",
        "missing-permission",
        "scope",
        "malformed-input",
        "payload-bound",
        "self-authorization",
        "context-injection",
        "blocklist",
        "approval-required",
        "decision-token",
    }
    assert first == run_permission_lab()
    assert all(item.matches_expectation for item in first)
    assert all(item.evidence_class is EvidenceClass.DETERMINISTIC for item in first)


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda scenario: scenario.scenario_id)
def test_observed_outcome_and_real_handler_calls(
    scenario: LabScenario,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    original = BoundedToolExecutor.__init__

    def instrument(
        self: BoundedToolExecutor,
        registry: CapabilityRegistry,
        authorizer: CapabilityAuthorizer,
        handlers: Mapping[str, ToolHandler],
        limits: Mapping[str, ExecutionLimits],
        budget: RuntimeBudget,
    ) -> None:
        wrapped: dict[str, ToolHandler] = {}
        for key, handler in handlers.items():

            def observed(
                inputs: BaseModel,
                context: ExecutionContext,
                handler: ToolHandler = handler,
            ) -> object:
                calls.append(context.proposal.resource_id)
                return handler(inputs, context)

            wrapped[key] = observed
        original(self, registry, authorizer, wrapped, limits, budget)

    monkeypatch.setattr(BoundedToolExecutor, "__init__", instrument)
    (result,) = run_permission_lab(scenario.scenario_id)
    assert result.outcome is scenario.expected_outcome
    assert result.handler_calls == len(calls) == scenario.expected_handler_calls
    if scenario.scenario_id == "allow":
        assert calls == ["doc-a"]
        assert isinstance(result.output, SearchOutput)
        assert result.output.matched is True
        assert result.output.excerpt == "Application-level sandbox bounds tool execution."
    else:
        assert result.output is None


def test_real_authorizer_runs_at_execution_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    proposals: list[ActionProposal] = []
    original = CapabilityAuthorizer.authorize

    def observed(self: CapabilityAuthorizer, proposal: ActionProposal) -> AuthorizationDecision:
        proposals.append(proposal)
        return original(self, proposal)

    monkeypatch.setattr(CapabilityAuthorizer, "authorize", observed)
    (result,) = run_permission_lab("allow")
    assert result.outcome is LabOutcome.EXECUTED
    assert len(proposals) == 1
    assert proposals[0].resource_id == "doc-a"


@pytest.mark.parametrize(
    "scenario,reason",
    [
        ("missing-permission", "no matching permission"),
        ("scope", "outside policy scope"),
        ("context-injection", "no matching permission"),
        ("blocklist", "action blocked"),
        ("approval-required", "human approval required"),
    ],
)
def test_displayed_refusal_reason_is_actual_policy_result(scenario: str, reason: str) -> None:
    (result,) = run_permission_lab(scenario)
    assert result.reason == f"Tool execution refused: {reason}."
    assert result.error_type == "AuthorityViolationError"
    assert result.selected_capabilities == ("documents.search",)
    assert result.handler_calls == 0


def test_malformed_input_uses_registered_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    failures: list[ContractValidationError] = []
    original = BoundedToolExecutor.execute

    def observed(self: BoundedToolExecutor, proposal: ActionProposal, inputs: object) -> BaseModel:
        try:
            return original(self, proposal, inputs)
        except ContractValidationError as exc:
            failures.append(exc)
            raise

    monkeypatch.setattr(BoundedToolExecutor, "execute", observed)
    (result,) = run_permission_lab("malformed-input")
    assert result.reason == "Tool input violates registered schema."
    assert isinstance(failures[0].__cause__, ValidationError)
    assert failures[0].__cause__.errors()[0]["loc"] == ("query",)


def test_payload_bound_uses_executor_on_schema_valid_input() -> None:
    assert SearchInput.model_validate({"query": "x" * 100}).query == "x" * 100
    (result,) = run_permission_lab("payload-bound")
    assert result.max_input_bytes == 32
    assert result.reason == "Tool payload exceeds configured byte limit."
    assert result.error_type == "BudgetExceededError"
    assert result.handler_calls == 0


@pytest.mark.parametrize("scenario", ["self-authorization", "decision-token"])
def test_authority_attempt_reaches_real_invocation_contract(
    scenario: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failures: list[ContractValidationError] = []
    original = BoundedToolExecutor.execute

    def observed(self: BoundedToolExecutor, proposal: ActionProposal, inputs: object) -> BaseModel:
        try:
            return original(self, proposal, inputs)
        except ContractValidationError as exc:
            failures.append(exc)
            raise

    monkeypatch.setattr(BoundedToolExecutor, "execute", observed)
    (result,) = run_permission_lab(scenario)
    assert isinstance(failures[0].__cause__, ValidationError)
    assert result.reason == "Invalid tool invocation proposal."
    assert result.handler_calls == 0


def test_renderer_reports_actual_results_and_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    original = BoundedToolExecutor.execute

    def fail(self: BoundedToolExecutor, proposal: ActionProposal, inputs: object) -> BaseModel:
        original(self, proposal, inputs)
        raise ToolExecutionError("Injected execution failure for evidence test.")

    monkeypatch.setattr(BoundedToolExecutor, "execute", fail)
    (result,) = run_permission_lab("allow")
    rendered = render_permission_lab((result,))
    assert result.outcome is LabOutcome.EXECUTION_FAILED
    assert result.handler_calls == 1
    assert result.output is None
    assert result.reason in rendered
    assert "Observed: execution_failed; handler calls=1" in rendered
    assert "Expectation check: FAIL" in rendered
    assert main(["--scenario", "allow"]) == 1


def test_no_credentials_or_network_required(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("Permission lab attempted network access.")

    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "AZURE_OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    results = run_permission_lab()
    assert all(result.matches_expectation for result in results)
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-test-value")
    assert run_permission_lab() == results


def test_cli_json_matches_service_results(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--json"]) == 0
    observed = json.loads(capsys.readouterr().out)
    results = run_permission_lab()
    for displayed, result in zip(observed["results"], results, strict=True):
        assert displayed["outcome"] == result.outcome.value
        assert displayed["reason"] == result.reason
        assert displayed["handler_calls"] == result.handler_calls
        assert displayed["output"] == (result.output.model_dump() if result.output else None)
    assert "No OS/container/VM/kernel" in observed["sandbox"]
    assert observed["evidence_class"] == "deterministic"


def test_cli_guidance_and_actual_module_entry_point() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "harness_engineering.permission_lab"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    text = completed.stdout
    assert text.count("Expectation check: PASS") == len(SCENARIOS)
    assert "deterministic local fixtures" in text
    assert "cannot forcibly stop Python handlers" in text
    for scenario in SCENARIOS:
        assert scenario.instruction in text
        assert scenario.expected in text
        assert scenario.demonstrates in text


def test_unknown_scenario_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown permission lab scenario"):
        run_permission_lab("arbitrary-executable")
    with pytest.raises(SystemExit) as error:
        main(["--scenario", "arbitrary-executable"])
    assert error.value.code == 2


def test_renderer_is_only_a_projection() -> None:
    (result,) = run_permission_lab("allow")
    changed: PermissionLabResult = replace(result, reason="Observed replacement reason")
    assert "Observed replacement reason" in render_permission_lab((changed,))


def test_registered_output_is_really_validated(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: list[object] = []
    original = SearchOutput.model_validate

    def validate(cls: type[SearchOutput], value: object, **kwargs: object) -> SearchOutput:
        observed.append(value)
        return original(value, **kwargs)

    monkeypatch.setattr(SearchOutput, "model_validate", classmethod(validate))
    (result,) = run_permission_lab("allow")
    assert observed == [
        {
            "resource_id": "doc-a",
            "matched": True,
            "excerpt": "Application-level sandbox bounds tool execution.",
        }
    ]
    assert result.output == SearchOutput.model_validate(observed[0])
