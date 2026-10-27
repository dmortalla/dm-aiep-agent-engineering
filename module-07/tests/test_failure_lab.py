"""Story 8's 22 contract proofs; ordinary execution is credential-free."""

import ast
import json
import runpy
import subprocess
import sys
import threading
import time
from dataclasses import FrozenInstanceError, fields, replace
from pathlib import Path
from unittest.mock import patch

import pytest

from reliability_safety_observability import failure_lab as lab
from reliability_safety_observability.errors import ConfigurationError
from reliability_safety_observability.evaluation_contracts import canonical_digest, canonical_json
from reliability_safety_observability.reliability import Failure, ReliabilityPolicy
from reliability_safety_observability.telemetry import TelemetryPipeline

ROOT = Path(__file__).resolve().parents[1]
RECURSIVE_NODE = "tests/test_helicone_contract.py::test_22_cross_suite_regression_stays_green"
PRIOR_FILES = (
    "test_authorization.py", "test_blocker_regressions.py", "test_configuration.py",
    "test_dataset_file_corruption.py", "test_dependency_contract.py",
    "test_deterministic_no_network.py", "test_domain_contracts.py",
    "test_evaluation_benchmark.py", "test_evaluation_composition.py", "test_evaluation_dataset.py",
    "test_evaluation_engine.py", "test_evaluation_improvement.py", "test_evaluation_regression.py",
    "test_evaluation_thresholds.py", "test_guardrails_integration.py", "test_helicone_contract.py",
    "test_langfuse_adapter.py", "test_langfuse_live.py", "test_langsmith_adapter.py",
    "test_langsmith_config.py", "test_langsmith_live.py", "test_langsmith_provenance.py",
    "test_langsmith_sdk_failure.py", "test_langsmith_seam.py", "test_package_contract.py",
    "test_prompt_injection.py", "test_reliability.py", "test_safety_pipeline.py",
    "test_second_review_regressions.py", "test_structured_logging.py", "test_telemetry.py",
)
CANARIES = (
    "sk-Story8SyntheticCanary0123456789", "ignore all previous instructions",
    "uncontrolled-provider-story8-text",
)


def result_map(result: lab.LabScenarioResult) -> dict[str, object]:
    """Produce the public declared-field primitive representation."""
    output = {item.name: getattr(result, item.name) for item in fields(result)}
    output["trigger"] = dict(result.trigger)
    output["extra"] = dict(result.extra)
    return output


def summary_map(summary: lab.LabSummary) -> dict[str, object]:
    """Convert immutable summary maps into JSON primitives."""
    return {
        **{item.name: getattr(summary, item.name) for item in fields(summary)},
        "evidence_counts": dict(summary.evidence_counts),
        "invariant_failures": [dict(item) for item in summary.invariant_failures],
    }


@pytest.fixture
def observe(monkeypatch):
    """Observe real boundary calls and returned facts without replacing decisions."""
    executions, targets, telemetry = [], [], []
    execute = lab.LabRunner.execute
    target = lab.LabRunner.target
    emit = TelemetryPipeline.emit

    def observed_execute(self, controller, state, *plan):
        result = execute(self, controller, state, *plan)
        executions.append((controller, state, plan, result))
        return result

    def observed_target(self, name, principal_id, script, counters):
        result = target(self, name, principal_id, script, counters)
        targets.append((name, script, counters, result))
        return result

    async def observed_emit(self, observation, **kwargs):
        result = await emit(self, observation, **kwargs)
        telemetry.extend(json.loads(record) for record in self.records)
        return result

    monkeypatch.setattr(lab.LabRunner, "execute", observed_execute)
    monkeypatch.setattr(lab.LabRunner, "target", observed_target)
    monkeypatch.setattr(TelemetryPipeline, "emit", observed_emit)
    return executions, targets, telemetry


def test_01_schema_refusal_and_immutability() -> None:
    """Direct construction cannot bypass finite scripts or fixed result markers."""
    assert len(tuple(lab.ScenarioKind)) == 20
    for value in ("unknown-secret", "x" * 300):
        with pytest.raises(ConfigurationError, match="kind") as caught:
            lab.ScenarioKind(value)
        assert value not in str(caught.value)
    for outcomes in ((), (lab.ScriptedOutcome(),) * 17, (object(),)):
        with pytest.raises(ConfigurationError, match="outcomes"):
            lab.FailureScript(outcomes)
    for kwargs in ({"kind": "ghost"}, {"cost_usd": float("nan")},
                   {"cost_usd": float("inf")}, {"cost_usd": -1}, {"cost_usd": True},
                   {"cost_usd": 2}, {"output_token": "secret"},
                   {"output_token": "x" * 300}):
        with pytest.raises(ConfigurationError):
            lab.ScriptedOutcome(**kwargs)
    for kwargs in ({"max_attempts": 9}, {"timeout_seconds": 0.6},
                   {"timeout_seconds": "secret"}, {"capacity": "secret"}):
        with pytest.raises(ConfigurationError, match="policy") as caught:
            lab.make_policy(**kwargs)
        assert "secret" not in str(caught.value)
    # The narrower fixture envelope never changes the accepted production policy.
    assert ReliabilityPolicy(max_attempts=9).max_attempts == 9
    result = lab.run_scenario(lab.ScenarioKind.S01)
    assert result == lab.run_scenario(lab.ScenarioKind.S01)
    for kwargs in ({"scenario_id": "x" * 300}, {"trigger": {"secret": "value"}},
                   {"passed": 1}, {"evidence_class": "live_vendor"},
                   {"budget_after_usd": float("nan")}, {"effect_count": 9},
                   {"reason_codes": ("secret",)}):
        with pytest.raises(ConfigurationError):
            replace(result, **kwargs)
    with pytest.raises(FrozenInstanceError):
        result.attempts = 8
    with pytest.raises(TypeError):
        result.trigger["target"] = "c"


def test_02_full_matrix_determinism() -> None:
    """All twenty canonical scenarios and digest bytes repeat exactly."""
    started = time.monotonic()
    first, first_summary = lab.run_lab()
    second, second_summary = lab.run_lab()
    assert first == second and first_summary == second_summary
    assert len(first) == 20 and all(item.passed for item in first)
    assert tuple(item.kind for item in first) == tuple(item.value for item in lab.ScenarioKind)
    assert canonical_json(summary_map(first_summary)) == canonical_json(summary_map(second_summary))
    assert first_summary.failed_count == 0 and first_summary.invariant_failures == ()
    assert time.monotonic() - started < 60
    subset = lab.run_full_lab((lab.ScenarioKind.S01, lab.ScenarioKind.S08))
    assert len(subset) == 2
    with pytest.raises(ConfigurationError):
        lab.run_full_lab((lab.ScenarioKind.S01,) * 21)


def test_03_transient_real_controller_and_telemetry(observe) -> None:
    """Recovery uses one stable action key and charges both accepted attempts."""
    result = lab.run_scenario(lab.ScenarioKind.S01)
    executions, targets, telemetry = observe
    controller, before, _, actual = executions[0]
    counters = targets[0][2]
    assert actual.classification == "success" and actual.attempts == 2
    assert counters.keys["a"] == [before.idempotency_key] * 2
    assert controller.sleeper.__self__.waits == [0.0]
    assert actual.history == ("transient", "success")
    assert result.effect_count == 1 and result.budget_after_usd == 0.02
    assert result.evidence_class == "simulated_failure"
    record = telemetry[0]
    assert record["workflow_id"] == str(before.identity.workflow_id)
    assert record["fields"]["attempts"] == 2
    assert record["fields"]["action_id"] == str(before.idempotency_key)


def test_04_terminal_default_and_explicit_authorized_fallback(observe) -> None:
    """Terminal fallback occurs solely through the accepted explicit policy."""
    result = lab.run_scenario(lab.ScenarioKind.S02)
    executions, targets, _ = observe
    assert result.observed_disposition == "terminal_exhausted" and result.effect_count == 0
    assert targets[0][2].consumed == {"a": 1}
    fallback_controller, _, plan, actual = executions[1]
    assert Failure.TERMINAL in fallback_controller.policy.fallback_on
    assert plan[1].decision.decision.value == "allow"
    assert actual.classification == "success" and actual.fallbacks == 1
    assert targets[2][2].effects == 1 and actual.state.budget.cost_used_usd == 0.02


def test_05_real_timeout_retains_honest_uncertainty(observe) -> None:
    """A genuinely pending coroutine times out without claiming completion."""
    threads = set(threading.enumerate())
    started = time.monotonic()
    result = lab.run_scenario(lab.ScenarioKind.S03)
    assert result.observed_disposition == "timeout_unresolved" and result.effect_count == 0
    assert result.attempts == 1 and result.budget_after_usd == 0.01
    assert 0.45 <= time.monotonic() - started < 1.5
    assert set(threading.enumerate()) == threads
    assert observe[0][0][3].output is None


def test_06_virtual_deadline_stops_new_attempts(observe) -> None:
    """Virtual backoff exhausts the deadline before another reservation."""
    result = lab.run_scenario(lab.ScenarioKind.S04)
    controller, _, _, actual = observe[0][0]
    assert result.observed_disposition == "time_exhausted"
    assert actual.attempts == 3 and result.budget_after_usd == 0.03
    assert controller.clock.now == 0.9 and controller.clock.waits == [0.45, 0.45]
    assert observe[1][0][2].consumed["a"] == 3


def test_07_retry_exhaustion_does_not_consume_unused_script(observe) -> None:
    """Attempt limits refuse the unused successful outcome."""
    result = lab.run_scenario(lab.ScenarioKind.S05)
    assert result.observed_disposition == "attempt_exhausted" and result.attempts == 1
    assert len(observe[1][0][1].outcomes) == 3
    assert observe[1][0][2].consumed["a"] == 1
    assert observe[2][0]["fields"]["history"] == ["transient"]


def test_08_fallback_success_exact_charge_pattern(observe) -> None:
    """Only the preauthorized fallback adds the single successful effect."""
    result = lab.run_scenario(lab.ScenarioKind.S06)
    assert (result.attempts, result.fallbacks, result.effect_count) == (3, 1, 1)
    assert result.budget_after_usd == 0.03
    assert observe[1][0][2].consumed == {"a": 2, "b": 1}
    assert observe[2][0]["fields"]["fallbacks"] == 1


def test_09_all_targets_exhaust_without_extra_effect(observe) -> None:
    """Exhaustion consumes exactly the permitted target-local attempts."""
    result = lab.run_scenario(lab.ScenarioKind.S07)
    assert result.observed_disposition == "transient_exhausted"
    assert (result.attempts, result.fallbacks, result.effect_count) == (4, 1, 0)
    assert result.budget_after_usd == 0.04
    assert observe[1][0][2].consumed == {"a": 2, "b": 2}


def test_10_replay_suppresses_duplicate_invocation(observe) -> None:
    """Stable identity replays recorded success and never repeats the effect."""
    result = lab.run_scenario(lab.ScenarioKind.S08)
    first, replay = observe[0]
    assert not first[3].replayed and replay[3].replayed
    assert first[1].idempotency_key == replay[1].idempotency_key
    assert result.effect_count == 1 and observe[1][0][2].consumed_total() == 1
    uncertain = lab.run_scenario(lab.ScenarioKind.S09)
    assert uncertain.effect_count <= 1 and uncertain.extra["post_pressure"] == "effect_uncertain"


def test_11_uncertain_pressure_and_ownership_accounting(observe) -> None:
    """Replay pressure cannot upgrade uncertain outcomes or duplicate work."""
    result = lab.run_scenario(lab.ScenarioKind.S09)
    assert result.passed and result.observed_disposition == "effect_uncertain"
    assert result.budget_after_usd == 0.01 and result.effect_count == 0
    first, replay = observe[0]
    assert replay[3].replayed and first[3].state.budget == replay[3].state.budget
    assert observe[1][0][2].consumed_total() == 1
    ownership = lab.run_scenario(lab.ScenarioKind.S20)
    assert ownership.observed_disposition == "close_busy"
    assert ownership.extra["post_resolution"] == "closed"


def test_12_budget_precharge_and_no_refund(observe) -> None:
    """Two reservations consume capacity; the third operation never starts."""
    result = lab.run_scenario(lab.ScenarioKind.S10)
    _, before, _, actual = observe[0][0]
    assert before.budget.cost_used_usd == 0 and before.budget.cost_limit_usd == 0.025
    assert actual.classification == "budget_exhausted" and actual.attempts == 2
    assert result.budget_after_usd == 0.02 and actual.actual_cost_usd == 0
    assert observe[1][0][2].consumed_total() == 2 and result.effect_count == 0


def test_13_authorization_stays_denied_under_recovery(observe) -> None:
    """Denied primary, replay and fallback bindings cannot execute."""
    result = lab.run_scenario(lab.ScenarioKind.S11)
    assert result.authority_outcome == "deny" and result.effect_count == 0
    assert [entry[3].classification for entry in observe[0]] == ["authorization_denied"] * 3
    counters = observe[1][0][2]
    assert counters.effects == 0 and "c" not in counters.keys


def test_14_guardrails_refusal_and_failed_provider_fail_closed(observe) -> None:
    """Real credential rejection and a failing Guardrails provider both deny effects."""
    result = lab.run_scenario(lab.ScenarioKind.S12)
    assert result.safety_outcome == "deny" and result.effect_count == 0
    assert observe[1][0][2].consumed_total() == 0
    assert observe[0][-1][3].classification == "safety_denied"
    assert observe[0][-1][3].state.safety.decision.value == "deny"


def test_15_untrusted_vendor_instructions_cannot_grant_authority(observe) -> None:
    """Injection-shaped and secret-shaped vendor/input fixtures remain inert."""
    result = lab.run_scenario(lab.ScenarioKind.S13)
    assert result.observed_disposition == "authorization_denied"
    assert result.extra["safety_boundary"] == "safety_denied" and result.effect_count == 0
    assert all(marker not in canonical_json(result_map(result)) for marker in CANARIES)


def test_16_malformed_vendor_noise_preserves_workflow(observe) -> None:
    """Both accepted vendor fakes/projections contain malformed/conflicting evidence."""
    result = lab.run_scenario(lab.ScenarioKind.S14)
    assert result.observed_disposition == "contained" and result.passed
    first, second = observe[0][0][3], observe[0][-1][3]
    assert first.classification == second.classification == "success"
    assert first.state.budget == second.state.budget and first.attempts == second.attempts
    gateway = lab.run_scenario(lab.ScenarioKind.S18)
    assert gateway.observed_disposition == "missing" and gateway.effect_count == 1
    assert gateway.budget_after_usd == 0.01


def test_17_failing_telemetry_is_redacted_and_non_authoritative(observe) -> None:
    """The actual NeutralSink.send failure is observed, redacted and isolated."""
    result = lab.run_scenario(lab.ScenarioKind.S15)
    assert result.telemetry_state == "export_failed" and result.effect_count == 1
    assert result.budget_after_usd == 0.01
    assert any(record["delivery"] == "export_failed" for record in observe[2])
    encoded = canonical_json(observe[2])
    assert all(marker not in encoded for marker in CANARIES)


def test_18_offline_vendors_leave_local_regression_unchanged() -> None:
    """Offline refusal preserves benchmark and committed-baseline comparison."""
    for kind in (lab.ScenarioKind.S16, lab.ScenarioKind.S17):
        result = lab.run_scenario(kind)
        assert result.observed_disposition == "offline_refused"
        assert result.effect_count == 1 and result.budget_after_usd == 0.01
        assert result.evidence_class == "mocked_provider_contract"


def test_19_lifecycle_busy_release_and_cleanup() -> None:
    """Close failures/idempotence/send-after-close and lane release use real adapters."""
    before = set(threading.enumerate())
    failed = lab.run_scenario(lab.ScenarioKind.S19)
    busy = lab.run_scenario(lab.ScenarioKind.S20)
    assert failed.observed_disposition == "close_failed" and failed.passed
    assert busy.observed_disposition == "close_busy" and busy.extra["post_resolution"] == "closed"
    assert set(threading.enumerate()) == before


def test_20_schema_evidence_and_digest_secret_containment(monkeypatch) -> None:
    """Every emitted primitive and exact digest input is bounded and secret-free."""
    inputs = []
    digest = lab.canonical_digest

    def capture(value):
        inputs.append(canonical_json(value))
        return digest(value)

    monkeypatch.setattr(lab, "canonical_digest", capture)
    results, summary = lab.run_lab()
    assert len(inputs) == 1
    for item in results:
        values = result_map(item)
        assert len(values) <= 32 and len(item.trigger) <= 16
        assert item.evidence_class in {"simulated_failure", "deterministic_fixture",
                                       "mocked_provider_contract"}
        assert item.passed is True and not item.reason_codes
        assert len(canonical_json(values).encode()) < 65536
    assert summary.digest == canonical_digest({
        "lab_version": 1, "results": [result_map(item) for item in results],
    })
    reversed_summary = lab.build_lab_summary(tuple(reversed(results)))
    assert reversed_summary == summary
    emitted = canonical_json([result_map(item) for item in results]) + canonical_json(
        summary_map(summary)
    ) + "".join(inputs)
    assert len(emitted.encode()) < 65536
    forbidden = (*CANARIES, "live_vendor", "production_observed")
    assert all(marker not in emitted for marker in forbidden)
    with pytest.raises(TypeError):
        summary.evidence_counts["live_vendor"] = 20
    with pytest.raises(ConfigurationError):
        lab.build_lab_summary((results[0], results[0]))


NETWORK_SCRIPT = r"""
import os, socket, sys, threading, time
for name in ("LANGSMITH_API_KEY", "LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2",
             "MODULE7_LANGSMITH_ENABLED", "MODULE7_LANGFUSE_ENABLED", "MODULE7_HELICONE_ENABLED"):
    os.environ[name] = "ambient-story8-secret"
attempts = []
original = socket.socket
class Guarded(original):
    def connect(self, address):
        if isinstance(address, tuple) and address[0] not in {"127.0.0.1", "::1"}:
            attempts.append(address)
            raise AssertionError("nonloopback_connect")
        return super().connect(address)
    def connect_ex(self, address):
        return self.connect(address)
socket.socket = Guarded
sys.path.insert(0, os.path.join(os.getcwd(), "src"))
before = set(threading.enumerate())
started = time.monotonic()
from reliability_safety_observability.failure_lab import run_lab
results, summary = run_lab()
assert summary.passed_count == 20 and not attempts
assert time.monotonic() - started < 60
assert set(threading.enumerate()) == before
# The real local Guardrails chain (Story 2) legitimately pulls langchain_core
# transitively; the lab imports no vendor client and the Langfuse vendor
# package never appears in the zero-network path.
assert not any(name.startswith("langfuse") for name in sys.modules)
assert "helicone" not in sys.modules
print("STORY8_ZERO_NETWORK_OK", summary.digest)
"""


def test_21_subprocess_zero_network_and_resources() -> None:
    """Ambient credential/configuration cannot activate a vendor client or network call."""
    completed = subprocess.run([sys.executable, "-c", NETWORK_SCRIPT], cwd=ROOT,
                               capture_output=True, text=True, timeout=90)
    assert completed.returncode == 0, completed.stdout[-2000:] + completed.stderr[-2000:]
    assert "STORY8_ZERO_NETWORK_OK" in completed.stdout


def cross_suite_command(root: Path) -> list[str]:
    """Fail closed on drift; explicit accepted files exclude both recursive routes."""
    if not PRIOR_FILES or len(set(PRIOR_FILES)) != len(PRIOR_FILES):
        raise AssertionError("prior_files requires a nonempty distinct selection")
    if any(not (root / "tests" / name).is_file() for name in PRIOR_FILES):
        raise AssertionError("prior_files missing accepted test file")
    path, node = RECURSIVE_NODE.split("::")
    module = ast.parse((root / path).read_text(encoding="utf-8"))
    if not any(isinstance(item, ast.FunctionDef) and item.name == node for item in module.body):
        raise AssertionError("recursive_node missing accepted node")
    return [sys.executable, "-m", "pytest", "-q", "-x",
            *(f"tests/{name}" for name in PRIOR_FILES), "--deselect", RECURSIVE_NODE]


def test_22_bounded_cross_suite_regression(tmp_path) -> None:
    """Explicitly bounded regression cannot recurse to a third pytest generation."""
    command = cross_suite_command(ROOT)
    selected = command[5:-2]
    assert selected == [f"tests/{name}" for name in PRIOR_FILES]
    assert "tests/test_failure_lab.py" not in selected
    assert "tests/test_helicone_contract.py" in selected
    assert command[-2:] == ["--deselect", RECURSIVE_NODE]
    with pytest.raises(AssertionError, match="prior_files"):
        cross_suite_command(tmp_path)
    # Exercise the unchanged Story 7 launcher mechanically. Its child includes
    # this test; our child excludes this file and its sole recursive Story 7 node.
    prior = runpy.run_path(str(ROOT / "tests/test_helicone_contract.py"))
    with patch("subprocess.run") as launched:
        launched.return_value = subprocess.CompletedProcess([], 0, "", "")
        prior["test_22_cross_suite_regression_stays_green"]()
    ancestor_command = launched.call_args.args[0]
    assert any(str(value).endswith("test_failure_lab.py") for value in ancestor_command)
    assert not any(str(value).endswith("test_helicone_contract.py") for value in ancestor_command)
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=900)
    assert completed.returncode == 0, completed.stdout[-5000:] + completed.stderr[-2000:]
    assert "passed" in completed.stdout and "1 deselected" in completed.stdout
