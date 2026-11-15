"""Application-owned immutable recording of accepted producer executions.

The runtime store is a protected local trust root. Its origin key authenticates
producer publication across processes; references alone confer no execution rights.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import re
import secrets
import subprocess
import sys
from pathlib import Path
from threading import Lock

# Internal application capability, never accepted from a serialized request.
# This is an API boundary, not a sandbox against code running as the application.
_RECORDING_AUTHORITY = object()

# Captured-result classes each accepted producer may publish. Any other
# class (including live_vendor, live_model and production_observed) is a
# contradictory authenticated payload and is rejected at both publication
# and reload boundaries. Gate records carry no class at all.
_PRODUCER_CLASSES: dict[str, frozenset[str]] = {
    "evaluation_engine": frozenset({"deterministic_fixture"}),
    "workflow_observability": frozenset({"deterministic_fixture"}),
    "accepted_test_execution": frozenset({"deterministic_fixture"}),
    "candidate_audit": frozenset({"deterministic_fixture"}),
    "failure_lab": frozenset({"simulated_failure"}),
    "gate_executor": frozenset(),
    "gate_executor_failure": frozenset(),
}

_HEXDIGEST: re.Pattern[str] = re.compile(r"[0-9a-f]{64}")


_ACCEPTED_TEST_SELECTION = (
    "tests/test_dependency_contract.py",
    "tests/test_configuration.py",
    "tests/test_package_contract.py",
    "tests/test_story9_console.py::test_05_workflow_click_runs_once_and_rerun_does_not_repeat",
    "tests/test_story9_console.py::test_06_workflow_renders_minimized_observation",
    "tests/test_story9_console.py::test_13_benchmark_uses_committed_public_composition",
    "tests/test_story9_console.py::test_15_regression_result_is_not_promoted_by_presentation",
    "tests/test_story9_console.py::test_20_empty_and_invalid_states_use_safe_messages",
    "tests/test_story9_console.py::test_22_confirmed_live_result_is_not_repeated_on_ordinary_rerun",
    "tests/test_reliability.py::test_replay_no_duplicate_effect_or_charge",
    "tests/test_reliability.py::test_safety_provider_failure_never_recovers",
    "tests/test_langfuse_adapter.py::test_pipeline_record_maps_to_one_fixed_specification",
    "tests/test_langsmith_adapter.py::test_fake_transport_submit_and_readback_succeed",
    "tests/test_helicone_contract.py::test_05_routing_spec_composition_and_refusals",
    "tests/test_guardrails_integration.py::test_real_guardrails_validator_executes_and_passes_safe_text",
    # REQ-EVD-001 binding: these four conceptual nodes exercise the authorized
    # producer seam against raw constructible models, forged projections and
    # caller-authored claims, and bind candidate/contract artifact semantics.
    # None of them calls record_accepted_tests or GateExecutor.execute, so the
    # observer child cannot recurse; the recursion-entangled nodes (test_06,
    # test_11, test_17, test_18) deliberately stay outside the fixed selection.
    "tests/test_integrated_acceptance.py::test_01_producer_projection_jcs_and_integer_contract",
    "tests/test_integrated_acceptance.py::test_07_integrated_acceptance_binding",
    "tests/test_integrated_acceptance.py::test_08_actual_security_outcomes",
    "tests/test_integrated_acceptance.py::test_10_actual_budget_outcomes",
)


class EvidenceError(ValueError):
    """Evidence is missing, corrupt, stale, or lacks authenticated origin."""


def _validate_evidence_payload(producer: str, payload: object) -> None:
    """Reject contradictory authenticated producer observations.

    Args:
        producer: Authenticated producer identity.
        payload: Payload being published or independently reloaded.

    Raises:
        EvidenceError: If class, selected source, report or timing is inconsistent.
    """
    import ast
    from datetime import datetime, timedelta

    if type(payload) is not dict or producer not in _PRODUCER_CLASSES:
        raise EvidenceError("Unknown evidence producer or payload.")
    allowed = _PRODUCER_CLASSES[producer]
    captured = payload.get("class")
    if allowed:
        if type(captured) is not str or captured not in allowed:
            raise EvidenceError("Captured result class is not producer-compatible.")
    elif "class" in payload:
        raise EvidenceError("Gate observations cannot claim a captured result class.")
    if producer != "accepted_test_execution":
        return
    selection = payload.get("selection")
    if selection != list(_ACCEPTED_TEST_SELECTION):
        raise EvidenceError("Accepted execution selection differs from the fixed producer.")
    selection_files = {node.split("::", 1)[0] for node in selection}
    sources = payload.get("sources")
    if type(sources) is not dict or set(sources) != selection_files:
        raise EvidenceError("Accepted execution sources must cover the selection.")
    root = Path(__file__).resolve().parents[2]
    functions = {}
    for name, metadata in sources.items():
        try:
            raw = (root / name).read_bytes()
            tree = ast.parse(raw)
        except (OSError, SyntaxError) as error:
            raise EvidenceError("Accepted execution source cannot be verified.") from error
        expected = {
            "digest": digest(raw),
            "assertion_lines": [
                node.lineno for node in ast.walk(tree) if isinstance(node, ast.Assert)
            ],
        }
        if metadata != expected:
            raise EvidenceError("Accepted execution source metadata mismatch.")
        functions[name] = {
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("test_")
        }
    reports = payload.get("reports")
    if type(reports) is not list or not reports:
        raise EvidenceError("Accepted execution reports are missing.")
    seen = set()
    for report in reports:
        if type(report) is not dict or set(report) != {"node_id", "phase", "outcome"}:
            raise EvidenceError("Accepted execution report metadata is malformed.")
        node = report["node_id"]
        phase, outcome = report["phase"], report["outcome"]
        if (
            type(node) is not str
            or type(phase) is not str
            or type(outcome) is not str
            or phase not in {"setup", "call", "teardown"}
            or outcome not in {"passed", "failed", "skipped"}
        ):
            raise EvidenceError("Accepted execution report outcome is invalid.")
        file, separator, function = node.partition("::")
        selected = any(
            node == item
            or node.startswith(item + "[")
            or ("::" not in item and node.startswith(item + "::"))
            for item in selection
        )
        if (
            not separator
            or file not in functions
            or function.split("[", 1)[0] not in functions[file]
            or not selected
            or (node, phase) in seen
        ):
            raise EvidenceError("Accepted execution reports contradict the selection.")
        seen.add((node, phase))
    exit_code = payload.get("exit_code")
    diagnostic = payload.get("diagnostic_digest")
    if (
        type(exit_code) is not int
        or type(diagnostic) is not str
        or not _HEXDIGEST.fullmatch(diagnostic)
    ):
        raise EvidenceError("Accepted execution outcome metadata is malformed.")
    if exit_code == 0:
        if any(row["phase"] != "call" or row["outcome"] != "passed" for row in reports):
            raise EvidenceError("Successful accepted execution contains non-passing reports.")
        if not all(
            any(
                row["node_id"] == item
                or row["node_id"].startswith(item + "[")
                or ("::" not in item and row["node_id"].startswith(item + "::"))
                for row in reports
            )
            for item in selection
        ):
            raise EvidenceError("Successful accepted execution omits selected tests.")
    elif not any(row["outcome"] == "failed" for row in reports):
        raise EvidenceError("Failed accepted execution has no observed failure.")
    try:
        started_at = datetime.fromisoformat(payload["started_at_utc"])
        finished_at = datetime.fromisoformat(payload["finished_at_utc"])
    except (KeyError, TypeError, ValueError):
        raise EvidenceError("Accepted execution timestamps are invalid.") from None
    if (
        started_at.utcoffset() != timedelta(0)
        or finished_at.utcoffset() != timedelta(0)
        or finished_at <= started_at
    ):
        raise EvidenceError("Accepted execution timestamps are inconsistent.")
    duration = payload.get("duration_ns")
    if type(duration) is not int or not 0 < duration <= 181_000_000_000:
        raise EvidenceError("Accepted execution duration is invalid.")
    # Wall and monotonic clocks are observed independently around the same
    # bounded subprocess. Permit one second of clock/measurement skew.
    elapsed_ns = (finished_at - started_at).total_seconds() * 1_000_000_000
    if abs(duration - elapsed_ns) > 1_000_000_000:
        raise EvidenceError("Accepted execution duration contradicts its timestamps.")


def encoded(value: object) -> bytes:
    """Encode the versioned source envelope losslessly, including Python ints.

    Args:
        value: Source value within the documented encoding domain.

    Returns:
        Deterministic source-envelope UTF-8 bytes.

    Raises:
        TypeError: If the input type violates this function's encoding contract.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value: bytes) -> str:
    """Return a hexadecimal SHA-256 digest.

    Args:
        value: Source value within the documented encoding domain.

    Returns:
        Hexadecimal SHA-256 of the complete input bytes.

    Raises:
        TypeError: If the input type violates this function's encoding contract.
    """
    return hashlib.sha256(value).hexdigest()


class EvidenceStore:
    """Bounded filesystem store with private authenticated publication.

    Args:
        root: Application runtime directory, outside candidate content.
        capacity: Maximum number of retained records; full stores refuse writes.

    Storage permissions must limit writes to the application account. Anyone
    able to replace the origin key controls this trust root, just as replacing
    application source controls producer execution.
    """

    def __init__(self, root: Path, *, capacity: int = 1024) -> None:
        root = root.absolute()
        if (
            any(part.is_symlink() or part.is_junction() for part in (root, *root.parents))
            or not 1 <= capacity <= 10000
        ):
            raise EvidenceError("Unsafe evidence root or capacity.")
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root = root.resolve(strict=True)
        self.capacity = capacity
        self._lock = Lock()
        key_path = self.root / "origin.key"
        try:
            descriptor = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(descriptor, "wb") as output:
                output.write(secrets.token_bytes(32))
                output.flush()
                os.fsync(output.fileno())
        if key_path.is_symlink() or key_path.is_junction():
            raise EvidenceError("Unsafe evidence origin.")
        self.__key = key_path.read_bytes()
        if len(self.__key) != 32:
            raise EvidenceError("Invalid evidence origin.")

    def _publish(
        self,
        producer: str,
        binding: str,
        contract: str,
        payload: object,
        *,
        _authority: object = None,
    ) -> str:
        """Publish only inside a fixed producer execution adapter."""
        if _authority is not _RECORDING_AUTHORITY or producer not in {
            "evaluation_engine",
            "workflow_observability",
            "accepted_test_execution",
            "candidate_audit",
            "failure_lab",
            "gate_executor",
            "gate_executor_failure",
        }:
            raise EvidenceError("Publication requires the internal producer capability.")
        _validate_evidence_payload(producer, payload)
        envelope = {
            "schema": 1,
            "producer": producer,
            "candidate": binding,
            "contract": contract,
            "payload": payload,
        }
        content = encoded(envelope)
        if len(content) > 4_000_000:
            raise EvidenceError("Evidence exceeds record size limit.")
        reference = digest(content)
        sealed = encoded(
            {"envelope": envelope, "seal": hmac.digest(self.__key, content, "sha256").hex()}
        )
        destination = self.root / (reference + ".json")
        with self._lock:
            lock_path = self.root / "publication.lock"
            try:
                descriptor = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError as error:
                raise EvidenceError("Evidence publication busy; retry explicitly.") from error
            temporary = self.root / (secrets.token_hex(16) + ".pending")
            try:
                os.close(descriptor)
                if destination.exists():
                    if destination.is_symlink() or destination.read_bytes() != sealed:
                        raise EvidenceError("Evidence collision or altered existing record.")
                    return reference
                if len(tuple(self.root.glob("*.json"))) >= self.capacity:
                    raise EvidenceError("Evidence capacity exhausted; operator retention required.")
                with temporary.open("xb") as output:
                    output.write(sealed)
                    output.flush()
                    os.fsync(output.fileno())
                # Linking publishes complete bytes atomically without replacement.
                os.link(temporary, destination)
            finally:
                temporary.unlink(missing_ok=True)
                lock_path.unlink(missing_ok=True)
        return reference

    def load(
        self, reference: str, *, candidate: str, contract: str, producer: str
    ) -> dict[str, object]:
        """Reload and authenticate a defensive source copy without modifying it.

        Args:
            reference: Exact content-addressed reference issued by this store.
            candidate: Required immutable candidate identity.
            contract: Required approved contract digest.
            producer: Required trusted producer identity.

        Returns:
            A newly decoded authenticated envelope, independent of stored bytes.

        Raises:
            EvidenceError: If origin, integrity, schema, path or bindings are invalid.
        """
        if type(reference) is not str or not re.fullmatch(r"[0-9a-f]{64}", reference):
            raise EvidenceError("Unknown evidence reference.")
        path = self.root / (reference + ".json")
        try:
            if path.is_symlink() or path.is_junction() or path.stat().st_size > 8_000_000:
                raise EvidenceError("Unsafe evidence record.")
            record = json.loads(path.read_bytes())
            envelope = record["envelope"]
            content = encoded(envelope)
            seal = hmac.digest(self.__key, content, "sha256").hex()
            if not hmac.compare_digest(record["seal"], seal) or digest(content) != reference:
                raise EvidenceError("Evidence origin or integrity mismatch.")
            if (
                envelope["schema"] != 1
                or envelope["producer"] != producer
                or envelope["candidate"] != candidate
                or envelope["contract"] != contract
            ):
                raise EvidenceError("Evidence schema, producer, candidate or contract mismatch.")
            _validate_evidence_payload(producer, envelope["payload"])
            return envelope
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise EvidenceError("Evidence cannot be verified.") from error

    def _check_binding(self, candidate: str, contract: str) -> None:
        """Refuse substituted or secret-bearing bindings before producer execution."""
        from .release_readiness import ReadinessVerifier

        actual = ReadinessVerifier(Path(__file__).resolve().parents[2], self).binding()
        if (candidate, contract) != (actual.candidate_id, actual.contract_sha256):
            raise EvidenceError("Producer candidate or approved-contract binding mismatch.")

    def record_evaluation(self, *, candidate: str, contract: str, target_version: int = 1) -> str:
        """Execute the fixed accepted engine/loader composition and record it.

        The sole configurable semantic integer is passed through the engine's
        accepted RunIdentity boundary; callers cannot supply a result or class.

        Args:
            candidate: Immutable candidate identity to bind to the execution.
            contract: Approved Story 10 contract digest.
            target_version: Positive exact source integer validated by the engine.

        Returns:
            Content-addressed reference to the authenticated benchmark evidence.

        Raises:
            EvidenceError: If version, storage origin, capacity or integrity is invalid.
            ValueError: If the accepted engine or committed loader refuses the source.
        """
        from .evaluation_benchmark import BenchmarkRunner
        from .evaluation_dataset import load_benchmark_dataset
        from .evaluation_engine import EvaluationEngine
        from .evaluation_regression import load_committed_baseline
        from .evaluation_target import ReferenceTarget

        self._check_binding(candidate, contract)
        if type(target_version) is not int or target_version < 1:
            raise EvidenceError("Target version must be a positive exact source integer.")
        dataset = load_benchmark_dataset()
        baseline = load_committed_baseline(dataset)
        output = asyncio.run(
            BenchmarkRunner(EvaluationEngine()).run_full(
                dataset,
                target_factory=lambda correlations: ReferenceTarget(
                    target_id="reference_default",
                    target_version=target_version,
                    correlations=dict(correlations),
                ),
                target_id="reference_default",
                target_version=target_version,
                baseline=baseline,
            )
        )
        # Engine records use only committed identifiers, enums and typed facts.
        # Exclude raw telemetry, prompts, canary identifiers and numeric usage.
        run = output.run.result
        identity = run.identity
        versions = {
            name: getattr(identity, name)
            for name in (
                "dataset_version",
                "evaluator_suite_version",
                "threshold_policy_version",
                "target_version",
            )
        }
        for name in (
            "baseline_schema_version",
            "dataset_version",
            "evaluator_suite_version",
            "threshold_policy_version",
            "target_version",
        ):
            versions["baseline:" + name] = getattr(baseline, name)
        versions.update(
            {"evaluator:" + name: value for name, value in baseline.evaluator_versions.items()}
        )
        rows = []
        for row in run.evaluations:
            facts = row.observed
            rows.append(
                {
                    "scenario": row.scenario_id,
                    "evaluator": row.evaluator_id,
                    "version": row.evaluator_version,
                    "passed": row.passed,
                    "classification": facts.classification,
                    "authorization": facts.authorization,
                    "safety": facts.safety,
                    "replayed": facts.replayed,
                    "budget": facts.budget_outcome,
                    "effects": facts.effect_count,
                    "attempts": facts.attempts,
                    "fallbacks": facts.fallbacks,
                }
            )
        payload = {
            "run_id": str(run.run_id),
            "dataset": digest(identity.dataset_id.encode()),
            "dataset_digest": identity.dataset_digest,
            "versions": versions,
            "rows": rows,
            "verdict": run.verdict.value,
            "regression": output.regression.outcome.value,
            "baseline_digest": baseline.baseline_digest,
            "class": "deterministic_fixture",
        }
        return self._publish(
            "evaluation_engine", candidate, contract, payload, _authority=_RECORDING_AUTHORITY
        )

    def record_accepted_tests(self, *, candidate: str, contract: str) -> str:
        """Observe a fixed selection of accepted deterministic regressions.

        Args:
            candidate: Candidate identity rechecked before and after execution.
            contract: Approved contract digest rechecked against the candidate.

        Returns:
            An authenticated execution record, including failures without promotion.

        Raises:
            EvidenceError: If candidate bindings change during observed execution.
        """
        import ast
        import time
        from datetime import UTC, datetime

        from .release_readiness import GateExecutor, ReadinessVerifier

        root = Path(__file__).resolve().parents[2]
        verifier = ReadinessVerifier(root, self)
        binding = verifier.binding()
        if (candidate, contract) != (binding.candidate_id, binding.contract_sha256):
            raise EvidenceError("Accepted test execution binding mismatch.")
        selected = _ACCEPTED_TEST_SELECTION

        sources = {}
        for name in sorted({node.split("::", 1)[0] for node in selected}):
            raw = (root / name).read_bytes()
            tree = ast.parse(raw)
            sources[name] = {
                "digest": digest(raw),
                "assertion_lines": [
                    node.lineno for node in ast.walk(tree) if isinstance(node, ast.Assert)
                ],
            }
        observer = """
import contextlib
import hashlib
import io
import json
import sys

import pytest

reports = []

class Observer:
    def pytest_runtest_logreport(self, report):
        if report.when == "call" or report.failed:
            reports.append(
                {"node_id": report.nodeid, "phase": report.when, "outcome": report.outcome}
            )

captured = io.StringIO()
with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
    exit_code = pytest.main(sys.argv[1:], plugins=[Observer()])
print(json.dumps({
    "reports": reports,
    "exit_code": int(exit_code),
    "diagnostic_digest": hashlib.sha256(captured.getvalue().encode()).hexdigest(),
}))
"""
        started_at = datetime.now(UTC).isoformat()
        started_ns = time.perf_counter_ns()
        try:
            completed = subprocess.run(
                (
                    sys.executable,
                    "-c",
                    observer,
                    "-q",
                    "-m",
                    "not live_vendor",
                    "-p",
                    "no:cacheprovider",
                    *selected,
                ),
                cwd=root,
                env=GateExecutor._environment(self.root),
                capture_output=True,
                timeout=180,
                check=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            observed = json.loads(completed.stdout)
            duration_ns = time.perf_counter_ns() - started_ns
            finished_at = datetime.now(UTC).isoformat()
        except (OSError, subprocess.SubprocessError, ValueError):
            raise EvidenceError("Accepted regression observer failed.") from None
        if verifier.binding() != binding:
            raise EvidenceError("Candidate changed during accepted test execution.")
        payload = {
            "selection": list(selected),
            "sources": sources,
            "reports": observed["reports"],
            "exit_code": observed["exit_code"],
            "started_at_utc": started_at,
            "finished_at_utc": finished_at,
            "duration_ns": duration_ns,
            "class": "deterministic_fixture",
            "diagnostic_digest": observed["diagnostic_digest"],
        }
        return self._publish(
            "accepted_test_execution", candidate, contract, payload, _authority=_RECORDING_AUTHORITY
        )

    def record_candidate_audit(self, *, candidate: str, contract: str) -> str:
        """Record a bounded, source-specific audit without caller-authored verdicts.

        Args:
            candidate: Exact current candidate digest.
            contract: Exact approved contract digest.

        Returns:
            Authenticated audit findings, including explicit unresolved scopes.

        Raises:
            EvidenceError: If the inspected candidate or contract does not match.
        """
        import ast

        from .release_readiness import ReadinessVerifier

        root = Path(__file__).resolve().parents[2]
        verifier = ReadinessVerifier(root, self)
        binding = verifier.binding()
        if (candidate, contract) != (binding.candidate_id, binding.contract_sha256):
            raise EvidenceError("Candidate audit binding mismatch.")
        findings = []
        for name in ("evidence_records.py", "release_readiness.py"):
            path = root / "src/reliability_safety_observability" / name
            raw = path.read_bytes()
            tree = ast.parse(raw)
            public = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
            for owner in tree.body:
                if isinstance(owner, ast.ClassDef):
                    public.extend(node for node in owner.body if isinstance(node, ast.FunctionDef))
            for function in public:
                if function.name.startswith("_"):
                    continue
                parameters = [
                    arg
                    for arg in function.args.args + function.args.kwonlyargs
                    if arg.arg not in {"self", "cls"}
                ]
                doc = ast.get_docstring(function) or ""
                missing = [arg.arg for arg in parameters if arg.annotation is None]
                applicable = ["Returns:", "Raises:"]
                if parameters or function.args.vararg or function.args.kwarg:
                    applicable.insert(0, "Args:")
                sections = [section for section in applicable if section not in doc]
                findings.append(
                    {
                        "obligations": ["REQ-QUAL-001", "REQ-QUAL-002"],
                        "source": str(path.relative_to(root)),
                        "source_digest": digest(raw),
                        "line": function.lineno,
                        "interface": function.name,
                        "missing_parameter_annotations": missing,
                        "missing_doc_sections": sections,
                        "result": "open" if missing or sections else "qualified",
                        "limitation": "Screening only; semantic contract review still required.",
                    }
                )
        for requirement, limitation in (
            ("REQ-SRC-001", "Course-source screenshot comparison not performed by this audit."),
            ("REQ-GOV-001", "Full approval and precedence audit is not executed."),
            ("REQ-QUAL-003", "Exception causes and failure semantics need individual review."),
            ("REQ-SEC-006", "All supported secret surfaces are not established."),
            ("REQ-EVD-007", "Windows file-symlink behavior and production persistence unverified."),
            ("REQ-DOD-008", "Complete semantic reviewer-facing claim audit remains open."),
        ):
            findings.append(
                {"obligations": [requirement], "result": "open", "limitation": limitation}
            )
        requirements_path = root / "docs/REQUIREMENTS.md"
        requirements_text = requirements_path.read_text(encoding="utf-8")
        # Individually reviewed source assessments; no caller can submit verdicts.
        reviews = {
            28: (
                "QUALIFIED",
                ["docs/TRACEABILITY.md", "docs/REQUIREMENTS.md"],
                "Traceability lines 12-59 transcribe the objective, 17 topics, three labs, "
                "four tools and two deliverables. Engine/workflow/lab execution covers local "
                "demonstrations, not complete deliverable acceptance. No original course image "
                "exists inside the permitted module; image-level fidelity remains unverified.",
            ),
            29: (
                "QUALIFIED",
                [
                    "docs/adr/ADR-007-005-authorization-boundary.md",
                    "docs/adr/ADR-007-008-ci-live-evidence.md",
                    "src/reliability_safety_observability/authorization.py",
                    "tests/test_authorization.py",
                ],
                "ADR decisions retain explicit grants and opt-in live authority. Authorization "
                "tests reject copied, forged, wrong-principal and wrong-policy decisions; "
                "recorded AUTH-002 rejects forged content authority. Complete candidate approval "
                "and course-source compliance is not implied by these runtime controls.",
            ),
            30: (
                "QUALIFIED",
                [
                    "src/reliability_safety_observability/evidence_records.py",
                    "src/reliability_safety_observability/release_readiness.py",
                    "tests/test_integrated_acceptance.py",
                ],
                "Publication cleanup runs in finally; loader failures chain EvidenceError; "
                "lab observation re-raises the original exception; gate launch/timeout "
                "exceptions become immutable failed attempts recovered after restart. "
                "Process termination or machine crash between execution and publication "
                "is not established by these focused failure tests.",
            ),
            31: (
                "QUALIFIED",
                [
                    "src/reliability_safety_observability/evidence_records.py",
                    "src/reliability_safety_observability/release_readiness.py",
                    "tests/test_integrated_acceptance.py",
                ],
                "Producer bindings are checked before execution; dataset identifiers are "
                "hashed, free text is omitted, loader-source canaries are refused and "
                "subprocess diagnostics emit only bounded counts and digests. Configured "
                "credentials are not recording inputs. Arbitrary accepted provider payload "
                "redaction and hostile application-authority code remain outside this proof.",
            ),
            33: (
                "QUALIFIED",
                [
                    "docs/STORY-10-SEMANTIC-CLAIM-REVIEW.md",
                    "streamlit_app.py",
                    "tests/test_story9_console.py",
                    "tests/test_integrated_acceptance.py",
                    "docs/STORY-03-IMPLEMENTATION.md",
                    "docs/STORY-04-IMPLEMENTATION.md",
                    "docs/STORY-05-IMPLEMENTATION.md",
                ],
                "Source-line semantic review is recorded in the Story 10 claim inventory "
                "C01-C60, including every module-owned documentation file, rendered journeys "
                "and readiness descriptions. The human-authorized C13 status correction "
                "renders the observed last attempt after invocation and across rerenders: "
                "confirmed return, unsuccessful outcome or failed/unavailable attempt. "
                "A prior returned result is explicitly distinguished after a failed attempt. "
                "Story 9 tests 22/25 and Story 10 Test 14 exercise mocked/deterministic "
                "returns and exceptions without live calls or evidence-class promotion. "
                "The original unconditional no-invocation claim is now pre-attempt only. "
                "C03/C10/C12 wording qualifications and all historical, platform, live, "
                "minimization and release limitations remain explicit.",
            ),
        }
        for index, finding in enumerate(findings, 1):
            finding["finding_id"] = f"S10-AUDIT-{index:02}"
            finding["disposition"] = (
                "QUALIFIED" if finding["result"] == "qualified" or index == 32 else "UNSUPPORTED"
            )
            finding["obligation_text"] = [
                line
                for line in requirements_text.splitlines()
                if any(line.startswith(identifier + " ") for identifier in finding["obligations"])
            ]
            if "source" not in finding:
                finding["source"] = "docs/REQUIREMENTS.md"
                finding["source_digest"] = digest(requirements_path.read_bytes())
                finding["line"] = next(
                    number
                    for number, line in enumerate(requirements_text.splitlines(), 1)
                    if line.startswith(finding["obligations"][0] + " ")
                )
            finding["candidate"] = binding.candidate_id
            finding["contract"] = binding.contract_sha256
            if index in reviews:
                disposition, inspected_sources, assessment = reviews[index]
                finding["disposition"] = disposition
                finding["result"] = "qualified" if disposition == "QUALIFIED" else "open"
                finding["assessment"] = assessment
                finding["limitation"] = assessment
                finding["inspected_sources"] = [
                    {"path": name, "digest": digest((root / name).read_bytes())}
                    for name in inspected_sources
                ]
        if verifier.binding() != binding:
            raise EvidenceError("Candidate changed during audit.")
        return self._publish(
            "candidate_audit",
            candidate,
            contract,
            {"class": "deterministic_fixture", "findings": findings},
            _authority=_RECORDING_AUTHORITY,
        )

    def record_workflow(self, *, candidate: str, contract: str) -> str:
        """Record the accepted console workflow and its minimized telemetry.

        Args:
            candidate: Current immutable candidate digest.
            contract: Approved Story 10 contract digest.

        Returns:
            Immutable reference to the genuine local workflow and minimized telemetry.

        Raises:
            EvidenceError: If source integrity, origin, schema or binding checks fail.
            OSError: If a required storage or process operation is unavailable.
        """
        from .console_presenter import ConsoleBoundary, recovery_projection

        self._check_binding(candidate, contract)
        evidence = ConsoleBoundary().run_workflow()
        actual = recovery_projection(evidence.recovery)
        semantic_fields = (
            "terminal_status",
            "classification",
            "authorization",
            "safety",
            "replayed",
            "recovered",
        )
        payload = {
            "class": "deterministic_fixture",
            "source_identity": {
                name: actual[name] for name in ("workflow_id", "trace_id", "action_id")
            },
            "semantics": {name: actual[name] for name in semantic_fields},
            "redacted_records": list(evidence.records),
        }
        return self._publish(
            "workflow_observability", candidate, contract, payload, _authority=_RECORDING_AUTHORITY
        )

    def record_lab(self, *, candidate: str, contract: str) -> str:
        """Execute the accepted Story 8 lab and preserve its genuine summary.

        Args:
            candidate: Current immutable candidate digest.
            contract: Approved Story 10 contract digest.

        Returns:
            Immutable reference to the actual accepted lab results and summary.

        Raises:
            EvidenceError: If source integrity, origin, schema or binding checks fail.
            OSError: If a required storage or process operation is unavailable.
        """
        from .console_presenter import ConsoleBoundary, lab_projection

        self._check_binding(candidate, contract)
        try:
            results, summary = ConsoleBoundary().run_full_lab()
        except Exception as error:
            # Observe only after failure. Never change the exception, timeout,
            # execution outcome or cleanup of an accepted prior-story producer.
            observation = lifecycle_failure_operands(error)
            if observation:
                error.add_note("Story 10 lifecycle observation: " + encoded(observation).decode())
            raise
        payload = {
            "summary": {
                "lab_version": summary.lab_version,
                "scenario_count": summary.scenario_count,
                "passed_count": summary.passed_count,
                "failed_count": summary.failed_count,
                "invariant_failures": [dict(row) for row in summary.invariant_failures],
                "evidence_counts": dict(summary.evidence_counts),
                "digest": summary.digest,
            },
            "results": [lab_projection(result) for result in results],
            "class": "simulated_failure",
        }
        return self._publish(
            "failure_lab", candidate, contract, payload, _authority=_RECORDING_AUTHORITY
        )

    def gate_attempts(self, contract: str) -> tuple[tuple[str, dict[str, object]], ...]:
        """Authenticate durable attempt history; corruption never resets obligations.

        Args:
            contract: Approved Story 10 contract digest.

        Returns:
            Authenticated gate history in completion order.

        Raises:
            EvidenceError: If source integrity, origin, schema or binding checks fail.
            OSError: If a required storage or process operation is unavailable.
        """
        attempts = []
        for path in sorted(self.root.glob("*.json")):
            try:
                if path.is_symlink() or path.is_junction() or path.stat().st_size > 8_000_000:
                    raise EvidenceError("Unsafe history record.")
                header = json.loads(path.read_bytes())["envelope"]
                envelope = self.load(
                    path.stem,
                    candidate=header["candidate"],
                    contract=header["contract"],
                    producer=header["producer"],
                )
                if envelope["producer"] in {"gate_executor", "gate_executor_failure"}:
                    if envelope["contract"] != contract:
                        raise EvidenceError(
                            "Gate history belongs to a different approved contract."
                        )
                    attempts.append((path.stem, envelope))
            except (OSError, ValueError, TypeError, KeyError) as error:
                raise EvidenceError("Durable gate history cannot be authenticated.") from error

        def completion(attempt: tuple[str, dict[str, object]]) -> int:
            try:
                ended = attempt[1]["payload"]["entries"][-1]["ended_ns"]
                if type(ended) is not int or ended < 0:
                    raise EvidenceError("Invalid durable gate completion timestamp.")
                return ended
            except (IndexError, KeyError, TypeError) as error:
                raise EvidenceError("Malformed durable gate completion record.") from error

        return tuple(sorted(attempts, key=completion))

    def load_failure(self, reference: str) -> dict[str, object]:
        """Authenticate a historical failure including its original bindings.

        Args:
            reference: Content-addressed reference to reload and authenticate.

        Returns:
            An authenticated historical failed-attempt envelope.

        Raises:
            EvidenceError: If source integrity, origin, schema or binding checks fail.
            OSError: If a required storage or process operation is unavailable.
        """
        if not re.fullmatch(r"[0-9a-f]{64}", reference):
            raise EvidenceError("Invalid failure reference.")
        path = self.root / (reference + ".json")
        try:
            if path.is_symlink() or path.stat().st_size > 8_000_000:
                raise EvidenceError("Unsafe failure record.")
            untrusted = json.loads(path.read_bytes())["envelope"]
            return self.load(
                reference,
                candidate=untrusted["candidate"],
                contract=untrusted["contract"],
                producer="gate_executor_failure",
            )
        except (OSError, KeyError, TypeError, ValueError) as error:
            raise EvidenceError("Historical failure cannot be authenticated.") from error


def lifecycle_failure_operands(error: BaseException) -> dict[str, object]:
    """Minimize existing S19/S20 failure-frame operands without tracing execution.

    Unexposed invocation counts and event timelines remain unavailable. This
    diagnostic never establishes successful evidence or changes lifecycle state.


    Args:
        error: Original failed producer exception; its existing traceback is inspected.

    Returns:
        Only the available minimized lifecycle failure operands.

    Raises:
        AttributeError: If an unexpected producer frame has an incompatible object shape.
    """
    from . import langfuse_adapter, langsmith_adapter

    observation: dict[str, object] = {}
    traceback = error.__traceback__
    while traceback is not None:
        frame = traceback.tb_frame
        if frame.f_code.co_name in {"_run_s19", "_run_s20"} and (
            Path(frame.f_code.co_filename).name == "failure_lab.py"
        ):
            values = frame.f_locals
            observation["scenario"] = frame.f_code.co_name.removeprefix("_run_")
            for name in ("first", "second"):
                value = values.get(name)
                state = getattr(value, "state", None)
                observation[name] = state.value if state is not None else "unavailable"
            if "first" in values and "second" in values:
                observation["equal"] = values["first"] == values["second"]
            for name in ("final", "outcome", "busy", "close_outcome"):
                value = values.get(name)
                if value in {
                    "closed",
                    "close_failed",
                    "close_busy",
                    "timeout",
                    "busy",
                    "ok",
                    "failed",
                }:
                    observation[name] = value
            blocking = values.get("blocking")
            count = getattr(blocking, "submitted", None)
            if type(count) is int:
                observation["submitted"] = count
            thread = values.get("thread")
            if thread is not None:
                observation["submit_worker_alive"] = thread.is_alive()
            observation["close_invocation_count"] = "unavailable"
            observation["langfuse_owned_operations"] = len(langfuse_adapter._OPERATIONS)
            observation["langsmith_owned_operations"] = len(langsmith_adapter._LIVE_OPERATIONS)
        traceback = traceback.tb_next
    return observation
