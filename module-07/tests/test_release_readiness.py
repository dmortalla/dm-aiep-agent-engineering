"""Bounded formal-gate diagnostic retention for failed gates.

A controlled process seam tests the retention mechanism; it never certifies
pytest, never serves as the gate-of-record, and never triggers execution.
"""

import subprocess
from pathlib import Path

import pytest

from reliability_safety_observability.evidence_records import EvidenceError, EvidenceStore
from reliability_safety_observability.release_readiness import (
    _GATE_DIAGNOSTIC_LENGTH,
    GateExecutor,
    ReadinessVerifier,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def verifier(tmp_path):
    """Provide a verifier over an isolated runtime evidence store."""
    store = EvidenceStore(tmp_path / "records")
    return ReadinessVerifier(ROOT, store)


def _gate_seam(monkeypatch, calls, pytest_output=b"", pytest_exit=1):
    """Replace gate subprocess execution with a controlled canned outcome.

    Args:
        monkeypatch: Pytest patch context.
        calls: List receiving every non-git command tuple actually executed.
        pytest_output: Captured stdout bytes returned by the pytest gate.
        pytest_exit: Exit code returned by the pytest gate.

    Returns:
        The patched subprocess.run replacement function.
    """
    original_run = subprocess.run

    def fake(command, **kwargs):
        if command[0] == "git":
            return original_run(command, **kwargs)
        calls.append(tuple(command))
        if any(str(part).endswith("pytest") for part in command):
            return subprocess.CompletedProcess(command, pytest_exit, pytest_output, b"")
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(subprocess, "run", fake)
    return fake


def test_failed_gate_retains_bounded_diagnostics(verifier, monkeypatch):
    """Actionable failed-test identifiers are retained, deduplicated, and ordered."""
    calls = []
    output = (
        b"============================= FAILURES =============================\n"
        b"_________________________ test_alpha ____________________________\n"
        b"E       assert 1 == 2\n"
        b"========================= short test summary info =================\n"
        b"FAILED tests/test_release_readiness.py::test_alpha - assert 1 == 2\n"
        b"FAILED tests/test_release_readiness.py::test_alpha - assert 1 == 2\n"
        b"ERROR tests/test_other.py::TestBeta::test_gamma - RuntimeError: boom\n"
    )
    _gate_seam(monkeypatch, calls, pytest_output=output)
    executor = GateExecutor(verifier)
    with pytest.raises(EvidenceError, match="immutable failure reference"):
        executor.execute()
    assert calls == [executor._commands()[0], executor._commands()[1]]
    reference = executor._history[0]
    entry = verifier.store.load_failure(reference)["payload"]["entries"][-1]
    assert entry["gate"] == 1 and entry["exit_code"] == 1 and entry["retry"] is False
    assert entry["failure_kind"] is None
    assert entry["diagnostics"] == [
        "tests/test_release_readiness.py::test_alpha",
        "tests/test_other.py::TestBeta::test_gamma",
    ]
    restarted = GateExecutor(verifier)
    assert restarted._failed_gate == 1 and restarted._history == [reference]
    recovered = verifier.store.load_failure(restarted._history[0])
    assert recovered["payload"]["entries"][-1]["diagnostics"] == entry["diagnostics"]


def test_secret_containing_output_is_sanitized(verifier, monkeypatch):
    """Recognized credential material is redacted before retention.

    Raw traceback and failure-message content are not retained.  Arbitrary
    unknown credential formats are not guaranteed to be detected.
    """
    calls = []
    canary = "sk-credential-canary-never-persist"
    output = (
        f"FAILED tests/test_leak.py::test_bearer Bearer {canary}\n"
        f"Authorization: Bearer {canary}\n"
        f"FAILED tests/test_leak.py::test_token - Bearer {canary}\n"
    ).encode()
    _gate_seam(monkeypatch, calls, pytest_output=output)
    executor = GateExecutor(verifier)
    with pytest.raises(EvidenceError):
        executor.execute()
    reference = executor._history[0]
    record = (verifier.store.root / (reference + ".json")).read_text(encoding="utf-8")
    assert canary not in record
    assert "Authorization" not in record
    assert "FAILURES" not in record
    entry = verifier.store.load_failure(reference)["payload"]["entries"][-1]
    assert entry["diagnostics"] == [
        "tests/test_leak.py::test_bearer",
        "tests/test_leak.py::test_token",
    ]


def test_diagnostics_are_bounded(verifier, monkeypatch):
    """Diagnostic count and per-item length are hard-bounded for huge outputs."""
    calls = []
    long_node = "tests/test_bounds.py::test_" + "x" * 4000
    lines = [f"FAILED tests/test_bounds.py::test_case_{index:03}" for index in range(50)]
    lines.append(f"FAILED {long_node}")
    _gate_seam(monkeypatch, calls, pytest_output=("\n".join(lines) + "\n").encode())
    executor = GateExecutor(verifier)
    with pytest.raises(EvidenceError):
        executor.execute()
    reference = executor._history[0]
    entry = verifier.store.load_failure(reference)["payload"]["entries"][-1]
    diagnostics = entry["diagnostics"]
    assert len(diagnostics) == 20
    assert all(len(node) <= 300 for node in diagnostics)
    assert not any(node.startswith("tests/test_bounds.py::test_case_02") for node in diagnostics)
    assert len((verifier.store.root / (reference + ".json")).read_bytes()) < 16_000


def test_success_records_carry_no_diagnostics(verifier, monkeypatch):
    """Successful gates keep the exact prior evidence shape without diagnostics."""
    _gate_seam(monkeypatch, [], pytest_exit=0)
    executor = GateExecutor(verifier)
    reference = executor.execute()
    executor.verify(reference)
    binding = verifier.binding()
    payload = verifier.store.load(
        reference,
        candidate=binding.candidate_id,
        contract=binding.contract_sha256,
        producer="gate_executor",
    )["payload"]
    assert [entry["gate"] for entry in payload["entries"]] == [0, 1, 2]
    assert all("diagnostics" not in entry for entry in payload["entries"])


def test_diagnostic_evidence_is_authenticated(verifier, monkeypatch):
    """Retained diagnostics reload through the authenticated store only."""
    calls = []
    _gate_seam(monkeypatch, calls, pytest_output=b"FAILED tests/test_seal.py::test_tamper - x\n")
    executor = GateExecutor(verifier)
    with pytest.raises(EvidenceError):
        executor.execute()
    reference = executor._history[0]
    binding = verifier.binding()
    entry = verifier.store.load_failure(reference)["payload"]["entries"][-1]
    assert entry["diagnostics"] == ["tests/test_seal.py::test_tamper"]
    verifier.store.load(
        reference,
        candidate=binding.candidate_id,
        contract=binding.contract_sha256,
        producer="gate_executor_failure",
    )
    path = verifier.store.root / (reference + ".json")
    original = path.read_bytes()
    try:
        path.write_bytes(original.replace(b"test_tamper", b"test_forged"))
        with pytest.raises(EvidenceError):
            verifier.store.load_failure(reference)
        with pytest.raises(EvidenceError):
            verifier.store.load(
                reference,
                candidate=binding.candidate_id,
                contract=binding.contract_sha256,
                producer="gate_executor_failure",
            )
    finally:
        path.write_bytes(original)


def test_recovery_performs_only_the_governed_retry(verifier, monkeypatch):
    """Diagnostic retention adds no subprocess execution to failure or recovery."""
    calls = []
    fail_once = [True]
    failure_output = b"FAILED tests/test_retry.py::test_once - ValueError: no\n"
    original_run = subprocess.run

    def flaky(command, **kwargs):
        if command[0] == "git":
            return original_run(command, **kwargs)
        calls.append(tuple(command))
        if any(str(part).endswith("pytest") for part in command) and fail_once.pop(0):
            return subprocess.CompletedProcess(command, 1, failure_output, b"")
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(subprocess, "run", flaky)
    commands = GateExecutor(verifier)._commands()
    with pytest.raises(EvidenceError):
        GateExecutor(verifier).execute()
    assert calls == [commands[0], commands[1]]
    del calls[:]
    fail_once[:] = [False] * 4
    executor = GateExecutor(verifier)
    reference = executor.execute()
    executor.verify(reference)
    assert calls == [commands[1], commands[0], commands[1], commands[2]]
    binding = verifier.binding()
    payload = verifier.store.load(
        reference,
        candidate=binding.candidate_id,
        contract=binding.contract_sha256,
        producer="gate_executor",
    )["payload"]
    assert all("diagnostics" not in entry for entry in payload["entries"])


def test_credential_shapes_inside_identifiers_are_redacted(verifier, monkeypatch):
    """Token-shaped secrets embedded inside node IDs never persist verbatim."""
    calls = []
    canaries = (
        "sk-ant-api03-SUPERSECRET-CANARY-01",
        "sk-OPENAICANARY-0123456789",
        "ghp_0123456789abcdefghijklmnopqrstuvwxyz",
        "AKIAIOSFODNN7EXAMPLE",
        "xoxb-123456789012-abcdefghij",
    )
    output = (
        f"FAILED tests/test_leak.py::test_openai[{canaries[0]}]\n"
        f"FAILED tests/test_leak.py::test_openai_generic[{canaries[1]}]\n"
        f"FAILED tests/test_leak.py::test_github[{canaries[2]}]\n"
        f"FAILED tests/test_leak.py::test_aws[AZ={canaries[3]}]\n"
        f"FAILED tests/test_leak.py::test_slack[{canaries[4]}]\n"
    ).encode()
    _gate_seam(monkeypatch, calls, pytest_output=output)
    executor = GateExecutor(verifier)
    with pytest.raises(EvidenceError):
        executor.execute()
    reference = executor._history[0]
    record = (verifier.store.root / (reference + ".json")).read_text(encoding="utf-8")
    assert all(canary not in record for canary in canaries)
    diagnostics = verifier.store.load_failure(reference)["payload"]["entries"][-1][
        "diagnostics"
    ]
    assert diagnostics == [
        "tests/test_leak.py::test_openai[[REDACTED]]",
        "tests/test_leak.py::test_openai_generic[[REDACTED]]",
        "tests/test_leak.py::test_github[[REDACTED]]",
        "tests/test_leak.py::test_aws[AZ=[REDACTED]]",
        "tests/test_leak.py::test_slack[[REDACTED]]",
    ]


def test_sensitive_key_values_inside_identifiers_are_redacted(verifier, monkeypatch):
    """Sensitive key/value pairs inside node IDs are redacted, keys preserved."""
    calls = []
    canaries = (
        "OPENAIPLAINCANARY123",
        "plain-secret-canary-99",
        "hunter2canary",
        "abc123session-canary",
        "eyJhbGciOiJIUzI1NiJ9.e30.canarysignature",
        "postgres://user:canary@host",
    )
    output = (
        f"FAILED tests/test_leak.py::test_auth[api_key={canaries[0]}]\n"
        f"FAILED tests/test_leak.py::test_b[authToken={canaries[1]}]\n"
        f"FAILED tests/test_leak.py::test_c[password={canaries[2]}]\n"
        f"FAILED tests/test_leak.py::test_d[session={canaries[3]}]\n"
        f"FAILED tests/test_leak.py::test_e[jwt={canaries[4]}]\n"
        f"FAILED tests/test_leak.py::test_f[dsn={canaries[5]}]\n"
    ).encode()
    _gate_seam(monkeypatch, calls, pytest_output=output)
    executor = GateExecutor(verifier)
    with pytest.raises(EvidenceError):
        executor.execute()
    reference = executor._history[0]
    record = (verifier.store.root / (reference + ".json")).read_text(encoding="utf-8")
    assert all(canary not in record for canary in canaries)
    diagnostics = verifier.store.load_failure(reference)["payload"]["entries"][-1][
        "diagnostics"
    ]
    assert diagnostics == [
        "tests/test_leak.py::test_auth[api_key=[REDACTED]]",
        "tests/test_leak.py::test_b[authToken=[REDACTED]]",
        "tests/test_leak.py::test_c[password=[REDACTED]]",
        "tests/test_leak.py::test_d[session=[REDACTED]]",
        "tests/test_leak.py::test_e[jwt=[REDACTED]]",
        "tests/test_leak.py::test_f[dsn=[REDACTED]]",
    ]


def test_compound_key_values_inside_identifiers_are_redacted(verifier, monkeypatch):
    """Compound and prefixed keys are canonically classified and their values redacted."""
    calls = []
    canaries = (
        "AWSCOMPOUNDCANARY0123456789",
        "XAPIKEYCANARY-0123456789",
        "AUTHTOKENCANARY0123456789",
        "MYAPIKEYCANARY0123456789",
        "AWSSECRETCANARY0123456789",
    )
    output = (
        f"FAILED tests/test_leak.py::test_aws[AWS_SECRET_ACCESS_KEY={canaries[0]}]\n"
        f"FAILED tests/test_leak.py::test_x[x_api_key={canaries[1]}]\n"
        f"FAILED tests/test_leak.py::test_t[auth_token={canaries[2]}]\n"
        f"FAILED tests/test_leak.py::test_m[MY_API_KEY={canaries[3]}]\n"
        f"FAILED tests/test_leak.py::test_lower[aws_secret_access_key={canaries[4]}]\n"
    ).encode()
    _gate_seam(monkeypatch, calls, pytest_output=output)
    executor = GateExecutor(verifier)
    with pytest.raises(EvidenceError):
        executor.execute()
    reference = executor._history[0]
    record = (verifier.store.root / (reference + ".json")).read_text(encoding="utf-8")
    assert all(canary not in record for canary in canaries)
    diagnostics = verifier.store.load_failure(reference)["payload"]["entries"][-1][
        "diagnostics"
    ]
    assert diagnostics == [
        "tests/test_leak.py::test_aws[AWS_SECRET_ACCESS_KEY=[REDACTED]]",
        "tests/test_leak.py::test_x[x_api_key=[REDACTED]]",
        "tests/test_leak.py::test_t[auth_token=[REDACTED]]",
        "tests/test_leak.py::test_m[MY_API_KEY=[REDACTED]]",
        "tests/test_leak.py::test_lower[aws_secret_access_key=[REDACTED]]",
    ]


def test_space_free_bearer_values_are_redacted(verifier, monkeypatch):
    """Whitespace-free bearer values inside node IDs are redacted."""
    calls = []
    output = b"FAILED tests/test_leak.py::test_g[Bearer_Zx9Qw2Rt5Yu7I8]\n"
    _gate_seam(monkeypatch, calls, pytest_output=output)
    executor = GateExecutor(verifier)
    with pytest.raises(EvidenceError):
        executor.execute()
    reference = executor._history[0]
    record = (verifier.store.root / (reference + ".json")).read_text(encoding="utf-8")
    assert "Zx9Qw2Rt5Yu7I8" not in record
    diagnostics = verifier.store.load_failure(reference)["payload"]["entries"][-1][
        "diagnostics"
    ]
    assert diagnostics == ["tests/test_leak.py::test_g[[REDACTED]]"]


def test_redaction_precedes_truncation(verifier, monkeypatch):
    """A secret inside the length-cap window leaves no partial value behind."""
    calls = []
    canary = "sk-truncation-0123456789abcdef"
    node = "tests/test_truncation.py::test[" + canary + "]" + "a" * 260
    assert len(node) > _GATE_DIAGNOSTIC_LENGTH
    assert canary in node[:_GATE_DIAGNOSTIC_LENGTH]
    _gate_seam(monkeypatch, calls, pytest_output=f"FAILED {node}\n".encode())
    executor = GateExecutor(verifier)
    with pytest.raises(EvidenceError):
        executor.execute()
    reference = executor._history[0]
    record = (verifier.store.root / (reference + ".json")).read_text(encoding="utf-8")
    assert canary not in record
    diagnostic = verifier.store.load_failure(reference)["payload"]["entries"][-1][
        "diagnostics"
    ][0]
    assert len(diagnostic) == _GATE_DIAGNOSTIC_LENGTH
    assert "[REDACTED]" in diagnostic
    assert canary not in diagnostic


def test_ordinary_identifiers_remain_useful(verifier, monkeypatch):
    """Benign identifiers containing sensitive-key words keep their full structure."""
    calls = []
    output = (
        b"FAILED tests/test_password_strength.py::test_policies - assert 1 == 2\n"
        b"FAILED tests/test_session.py::test_expiry[timeout=30] - ValueError\n"
        b"FAILED tests/test_sk_handling.py::test_rejects_empty - OSError\n"
        b"FAILED tests/test_regions.py::test_quotas[aws_region=us-east-1] - OSError\n"
        b"FAILED tests/test_secret.py::test_quiet - OSError\n"
        b"ERROR tests/test_other.py::TestBeta::test_gamma - RuntimeError: boom\n"
    )
    _gate_seam(monkeypatch, calls, pytest_output=output)
    executor = GateExecutor(verifier)
    with pytest.raises(EvidenceError):
        executor.execute()
    entry = verifier.store.load_failure(executor._history[0])["payload"]["entries"][-1]
    diagnostics = entry["diagnostics"]
    assert "[REDACTED]" not in "".join(diagnostics)
    assert diagnostics == [
        "tests/test_password_strength.py::test_policies",
        "tests/test_session.py::test_expiry[timeout=30]",
        "tests/test_sk_handling.py::test_rejects_empty",
        "tests/test_regions.py::test_quotas[aws_region=us-east-1]",
        "tests/test_secret.py::test_quiet",
        "tests/test_other.py::TestBeta::test_gamma",
    ]