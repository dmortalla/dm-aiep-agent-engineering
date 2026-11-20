"""Deterministic Story 10 release-readiness evidence generation.

This module owns neither workflow execution nor provider authority.  It binds
accepted local results to a reviewed candidate and projects only bounded,
redacted semantic facts into RFC 8785-compatible canonical bytes.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from typing import Final

from .domain import EvidenceClass
from .evidence_records import _RECORDING_AUTHORITY, EvidenceError, EvidenceStore, digest, encoded
from .logging import _is_sensitive_key, _sanitize_string

type JsonScalar = str | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]

_INTEGER_KEY: Final = "$integer"
_INTEGER_PATTERN: Final = re.compile(r"^(?:0|[1-9][0-9]*)$")
_EVIDENCE_CLASSES: Final = frozenset(item.value for item in EvidenceClass)
_GATE_DIAGNOSTIC_PATTERN: Final = re.compile(r"^(?:FAILED|ERROR) (tests/[!-~]+)", re.MULTILINE)
_GATE_DIAGNOSTIC_LIMIT: Final = 20
_GATE_DIAGNOSTIC_LENGTH: Final = 300
# REQ-ENG-002: bounded timeout appropriate to the formal gate's failure
# boundary; sized from the measured offline suite duration (Step 266.1,
# 1423.41 s) with headroom, and finite to preserve bounded resources.
_GATE_TIMEOUT_SECONDS: Final = 1800
_CREDENTIAL_SHAPES: Final = re.compile(
    "(?i)\\b(?:"
    "sk-ant-[A-Za-z0-9_-]{8,}"
    "|sk-[A-Za-z0-9_-]{8,}"
    "|ghp_[A-Za-z0-9]{10,}"
    "|AKIA[0-9A-Z]{12,16}"
    "|xox[a-z]-[A-Za-z0-9-]{10,}"
    ")"
)
_BEARER_ADJACENT: Final = re.compile("(?i)\\bbearer[-_:][^\\s\\]]{6,}")
_PARAM_SEGMENT: Final = re.compile("\\[([^\\]]*)\\]")
_KEY_VALUE_PAIR: Final = re.compile(
    "(?i)\\b([A-Za-z][A-Za-z0-9_.-]*?)([:=])([^\\s\\]]+)"
)


_RECONCILIATION_STATES: Final = frozenset({"open", "qualified_historical", "verified", "rejected"})
_IMPLEMENTATION_GROUPS: Final = {
    "REQ-REL-001 REQ-REL-002 REQ-REL-003 REQ-REL-004 "
    "REQ-ENG-001 REQ-ENG-002 REQ-ENG-003 REQ-ENG-004 REQ-ENG-005 REQ-ENG-007 REQ-COST-001": (
        "reliability.py::ReliabilityController",
        "reliability.py::ReliabilityPolicy",
    ),
    "REQ-ENG-006 REQ-SEC-008": (
        "telemetry.py::TelemetryPipeline",
        "reliability.py::ReliabilityController",
    ),
    "REQ-SAFE-001 REQ-SEC-005": (
        "injection.py::inspect_for_injection",
        "safety.py::SafetyPipeline",
    ),
    "REQ-SAFE-002 REQ-SEC-002 REQ-SEC-003 REQ-SEC-004": (
        "authorization.py::AuthorizationPolicy",
        "safety.py::SafetyPipeline",
    ),
    "REQ-SAFE-003 REQ-TOOL-004": ("guardrails_adapter.py::GuardrailsCredentialProvider",),
    "REQ-SAFE-004": ("moderation.py::ModerationPolicy", "safety.py::SafetyPipeline"),
    "REQ-SEC-001": ("domain.py::UntrustedContent", "safety.py::SafetyPipeline"),
    "REQ-SEC-006 REQ-SEC-007": ("logging.py::log_event", "telemetry.py::minimize"),
    "REQ-OBS-001 REQ-OBS-002 REQ-OBS-003 REQ-OBS-004 REQ-OBS-005 REQ-COST-002": (
        "telemetry.py::from_recovery",
        "telemetry.py::TelemetryPipeline",
    ),
    "REQ-EVAL-001 REQ-EVAL-003 REQ-LAB-002 REQ-DEL-002": (
        "evaluation_engine.py::EvaluationEngine",
        "evaluation_benchmark.py::BenchmarkRunner",
    ),
    "REQ-EVAL-002": ("evaluation_regression.py::compare_to_baseline",),
    "REQ-EVAL-004": ("evaluation_improvement.py::improvement_cycle",),
    "REQ-COST-003 REQ-COST-004": (
        "config.py::RuntimeSettings",
        "evidence_records.py::EvidenceStore.record_accepted_tests",
    ),
    "REQ-LAB-001 REQ-DEL-001 REQ-UI-001 REQ-UI-002 REQ-UI-003 REQ-UI-004 REQ-DOD-005 REQ-DOD-006": (
        "@streamlit_app.py::main",
        "console_presenter.py::ConsoleBoundary",
    ),
    "REQ-LAB-003": (
        "failure_lab.py::run_lab",
        "console_presenter.py::ConsoleBoundary.run_full_lab",
    ),
    "REQ-TOOL-001": (
        "langsmith_adapter.py::build_export_plan",
        "langsmith_adapter.py::LangSmithSdkTransport",
    ),
    "REQ-TOOL-002": (
        "langfuse_adapter.py::to_export_spec",
        "langfuse_adapter.py::LangfuseSdkTransport",
    ),
    "REQ-TOOL-003": ("helicone_adapter.py::build_gateway_routing_spec",),
    "REQ-SEC-009 REQ-SEC-010 REQ-QUAL-006": ("@pyproject.toml", "@uv.lock"),
    "REQ-ISO-001 REQ-ISO-002": ("__init__.py", "@pyproject.toml"),
    "REQ-QUAL-001 REQ-QUAL-002 REQ-QUAL-003 REQ-QUAL-004": (
        "evidence_records.py::EvidenceStore",
        "release_readiness.py::ReadinessVerifier",
    ),
    "REQ-QUAL-005": ("config.py::RuntimeSettings",),
    "REQ-SRC-001 REQ-SRC-002": ("@docs/TRACEABILITY.md", "@docs/REQUIREMENTS.md"),
    "REQ-SRC-003 REQ-SRC-004 REQ-DOD-004": (
        "domain.py::EvidenceClass",
        "release_readiness.py::ReadinessVerifier.artifacts",
    ),
    "REQ-OBJ-001 REQ-CLOSE-001 REQ-CLOSE-002 REQ-CLOSE-003 REQ-CLOSE-004 "
    "REQ-CLOSE-005 REQ-DOD-001 REQ-DOD-002 REQ-DOD-003 REQ-DOD-008 "
    "REQ-DOD-009 REQ-DOD-010": ("release_readiness.py::ReadinessVerifier.artifacts",),
    "REQ-QG-001 REQ-QG-002 REQ-QG-003 REQ-QG-004 REQ-QG-005 REQ-QG-006 REQ-DOD-007 REQ-EVD-006": (
        "release_readiness.py::GateExecutor",
    ),
    "REQ-EVD-001 REQ-EVD-002 REQ-EVD-003 REQ-EVD-004 REQ-EVD-005 REQ-EVD-007": (
        "evidence_records.py::EvidenceStore",
        "release_readiness.py::ReadinessVerifier",
    ),
}
# Assertion-bearing node relationships, not story-name inference. All attached
# nodes must also appear as passing reports in the authenticated observer.
_TEST_OBLIGATIONS: Final = {
    "test_deterministic_mode_is_default_without_credentials": (
        "REQ-COST-003",
        "REQ-QUAL-005",
        "REQ-DOD-004",
    ),
    "test_credential_presence_does_not_enable_live_mode": (
        "REQ-COST-004",
        "REQ-DOD-004",
        "REQ-SRC-004",
    ),
    "test_secret_is_not_exposed_in_settings_repr": ("REQ-SEC-006",),
    "test_public_package_imports_independently": ("REQ-ISO-001",),
    "test_source_has_no_sibling_module_imports": ("REQ-ISO-001", "REQ-ISO-002"),
    "test_prohibited_guardrails_version_cannot_satisfy_declared_requirement": ("REQ-SEC-010",),
    "test_prohibited_version_is_rejected_even_if_bounds_widen": ("REQ-SEC-010",),
    "test_locked_and_installed_guardrails_satisfy_the_contract": ("REQ-SEC-010", "REQ-QUAL-006"),
    "test_lockfile_resolves_only_from_the_package_index": ("REQ-SEC-009", "REQ-QUAL-006"),
    "test_05_workflow_click_runs_once_and_rerun_does_not_repeat": (
        "REQ-UI-001",
        "REQ-DEL-001",
        "REQ-DOD-005",
        "REQ-DOD-006",
    ),
    "test_06_workflow_renders_minimized_observation": ("REQ-UI-001", "REQ-SEC-007"),
    "test_13_benchmark_uses_committed_public_composition": (
        "REQ-DEL-002",
        "REQ-LAB-002",
        "REQ-UI-001",
        "REQ-DOD-005",
    ),
    "test_15_regression_result_is_not_promoted_by_presentation": ("REQ-SRC-003", "REQ-SRC-004"),
    "test_20_empty_and_invalid_states_use_safe_messages": ("REQ-UI-004",),
    "test_22_confirmed_live_result_is_not_repeated_on_ordinary_rerun": (
        "REQ-DOD-004",
        "REQ-COST-004",
        "REQ-SRC-004",
    ),
    "test_replay_no_duplicate_effect_or_charge": ("REQ-REL-003", "REQ-ENG-005"),
    "test_safety_provider_failure_never_recovers": ("REQ-SAFE-004", "REQ-SEC-004"),
    "test_pipeline_record_maps_to_one_fixed_specification": ("REQ-TOOL-002",),
    "test_fake_transport_submit_and_readback_succeed": ("REQ-TOOL-001",),
    "test_05_routing_spec_composition_and_refusals": ("REQ-TOOL-003",),
    "test_real_guardrails_validator_executes_and_passes_safe_text": (
        "REQ-TOOL-004",
        "REQ-SAFE-003",
    ),
    # REQ-EVD-001 attribution only: these four selected nodes are the
    # assertion-bearing producer-authority evidence; no other requirement
    # is attributed through them.
    "test_01_producer_projection_jcs_and_integer_contract": ("REQ-EVD-001",),
    "test_07_integrated_acceptance_binding": ("REQ-EVD-001",),
    "test_08_actual_security_outcomes": ("REQ-EVD-001",),
    "test_10_actual_budget_outcomes": ("REQ-EVD-001",),
}


class ReadinessValidationError(ValueError):
    """Raised when release-readiness evidence is malformed or mismatched."""


@dataclass(frozen=True, slots=True)
class CandidateBinding:
    """Immutable candidate and approved-contract identity.

    Args:
        candidate_id: Commit or reviewed-content identity for the candidate.
        contract_sha256: SHA-256 of the approved Story 10 contract.
    """

    candidate_id: str
    contract_sha256: str

    def __post_init__(self) -> None:
        if not self.candidate_id or not _is_sha256(self.contract_sha256):
            raise ReadinessValidationError("Candidate binding is malformed.")


@dataclass(frozen=True, slots=True)
class ProjectionRecord:
    """Candidate-bound actual evidence and its independently verifiable projection."""

    binding: CandidateBinding
    run_reference: str
    source_digest: str
    source: dict[str, object]
    projection: dict[str, JsonValue]
    canonical_bytes: bytes
    projection_sha256: str


@dataclass(frozen=True, slots=True)
class TraceabilityRow:
    """One ordered, candidate-bound requirement reconciliation row."""

    requirement_id: str
    adr_ids: tuple[str, ...]
    story_ids: tuple[str, ...]
    implementation_references: tuple[str, ...]
    test_references: tuple[str, ...]
    evidence_references: tuple[str, ...]
    evidence_class: str | None
    status: str


@dataclass(frozen=True, slots=True)
class GateEntry:
    """One completed gate entry, retained independently of its output text."""

    name: str
    command: str
    result: str
    output_sha256: str


@dataclass(frozen=True, slots=True)
class QualityGateRecord:
    """Candidate-bound final gate record created only after all gates pass."""

    binding: CandidateBinding
    candidate_digest: str
    entries: tuple[GateEntry, ...]
    repair_history: tuple[str, ...] = ()


def tagged_integer(value: object) -> dict[str, str]:
    """Encode one accepted semantic version integer losslessly.

    Args:
        value: Exact source integer from an accepted evidence boundary.

    Returns:
        The projection-schema tagged integer object.

    Raises:
        ReadinessValidationError: If the source is not a positive exact int.
    """
    if type(value) is not int or value < 1:
        raise ReadinessValidationError("Semantic version requires a positive exact integer.")
    return {_INTEGER_KEY: str(value)}


def _validate_tag(value: Mapping[str, object]) -> dict[str, str]:
    if set(value) != {_INTEGER_KEY} or type(value[_INTEGER_KEY]) is not str:
        raise ReadinessValidationError("Malformed tagged semantic integer.")
    decimal = value[_INTEGER_KEY]
    if not _INTEGER_PATTERN.fullmatch(decimal):
        raise ReadinessValidationError("Tagged semantic integer is not canonical decimal.")
    return {_INTEGER_KEY: decimal}


def _validate_json(value: object, *, integer_field: bool = False) -> JsonValue:
    if integer_field:
        return tagged_integer(value)
    if value is None or type(value) is bool or type(value) is str:
        _validate_unicode(value) if type(value) is str else None
        return value
    if isinstance(value, Mapping):
        if _INTEGER_KEY in value:
            raise ReadinessValidationError(
                "Tagged integers are valid only at declared version fields."
            )
        output: dict[str, JsonValue] = {}
        for key, child in value.items():
            if type(key) is not str:
                raise ReadinessValidationError("Projection object keys must be strings.")
            _validate_unicode(key)
            output[key] = _validate_json(child)
        return output
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return [_validate_json(child) for child in value]
    raise ReadinessValidationError("Projection contains an unsupported value.")


def _validate_unicode(value: str) -> None:
    if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
        raise ReadinessValidationError("Projection contains malformed Unicode.")


def _jcs_string(value: str) -> str:
    """Return the RFC 8785 JSON string form for the supported string domain."""
    _validate_unicode(value)
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def jcs_bytes(value: JsonValue) -> bytes:
    """Serialize a validated projection using the RFC 8785 JCS subset.

    The Story 10 projection admits no JSON numbers.  This avoids alternate
    binary64 spellings while retaining JCS recursive UTF-16 member ordering,
    JSON escaping, literal non-ASCII UTF-8, and whitespace rules.


    Args:
        value: Source value within the documented encoding domain.

    Returns:
        Exact canonical UTF-8 bytes for the supported JCS domain.

    Raises:
        ReadinessValidationError: If values violate the supported projection domain.
    """

    def encode(item: JsonValue) -> str:
        if item is None:
            return "null"
        if type(item) is bool:
            return "true" if item else "false"
        if type(item) is str:
            return _jcs_string(item)
        if isinstance(item, list):
            return "[" + ",".join(encode(child) for child in item) + "]"
        if isinstance(item, dict):
            pairs = sorted(item.items(), key=lambda pair: pair[0].encode("utf-16-be"))
            return (
                "{" + ",".join(_jcs_string(key) + ":" + encode(child) for key, child in pairs) + "}"
            )
        raise ReadinessValidationError("Projection contains a non-JCS value.")

    return encode(value).encode("utf-8")


def derive_projection(source: Mapping[str, object]) -> dict[str, JsonValue]:
    """Derive the bounded deterministic projection from recorded accepted facts.

    ``versions`` is the only schema location permitted to carry tagged semantic
    integers.  A caller must construct it from accepted engine/baseline rows,
    never presentation or provider data.


    Args:
        source: Schema-constrained semantic source; not an accepted-run authority.

    Returns:
        The bounded semantic projection with schema-scoped integer tags.

    Raises:
        ReadinessValidationError: If values violate the supported projection domain.
    """
    required = {
        "terminal_status",
        "authorization",
        "safety",
        "replay",
        "reason_codes",
        "dataset_id",
        "versions",
        "verdict",
        "regression",
        "lab",
        "evidence_class",
    }
    if set(source) != required or type(source.get("versions")) is not dict:
        raise ReadinessValidationError("Recorded evidence does not match the projection schema.")
    string_fields = {
        "terminal_status",
        "authorization",
        "safety",
        "dataset_id",
        "verdict",
        "regression",
        "lab",
    }
    if any(type(source[field]) is not str for field in string_fields):
        raise ReadinessValidationError("Recorded semantic text fields must be strings.")
    if type(source["replay"]) is not bool:
        raise ReadinessValidationError("Recorded replay fact must be a boolean.")
    if not isinstance(source["reason_codes"], list) or any(
        type(item) is not str for item in source["reason_codes"]
    ):
        raise ReadinessValidationError("Recorded reason codes must be an ordered string list.")
    evidence_class = source["evidence_class"]
    if evidence_class not in _EVIDENCE_CLASSES:
        raise ReadinessValidationError("Projection has an unknown evidence classification.")
    versions = source["versions"]
    assert isinstance(versions, dict)
    normalized_versions: dict[str, JsonValue] = {}
    for key, value in versions.items():
        if type(key) is not str:
            raise ReadinessValidationError("Semantic version names must be strings.")
        _validate_unicode(key)
        normalized_versions[key] = _validate_json(value, integer_field=True)
    return {
        "authorization": _validate_json(source["authorization"]),
        "dataset_id": _validate_json(source["dataset_id"]),
        "evidence_class": _validate_json(evidence_class),
        "lab": _validate_json(source["lab"]),
        "reason_codes": _validate_json(source["reason_codes"]),
        "regression": _validate_json(source["regression"]),
        "replay": _validate_json(source["replay"]),
        "safety": _validate_json(source["safety"]),
        "terminal_status": _validate_json(source["terminal_status"]),
        "verdict": _validate_json(source["verdict"]),
        "versions": normalized_versions,
    }


def _is_sha256(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-fA-F]{64}", value))


def _redact_sensitive_pair(match: re.Match[str]) -> str:
    """Redact a bracketed assignment pair when its key is canonically sensitive.

    Args:
        match: One bounded ``key=value``/``key:value`` match inside a pytest
            parameter segment.

    Returns:
        The key and separator with ``[REDACTED]`` replacing the value when
        ``logging._is_sensitive_key`` classifies the key as sensitive;
        otherwise the untouched pair.
    """
    key, separator = match[1], match[2]
    if not _is_sensitive_key(key):
        return match[0]
    return key + separator + "[REDACTED]"


def _redact_credential_text(value: str) -> str:
    """Redact recognized credential material embedded in whitespace-free text.

    Space-free bearer values and known token shapes are redacted directly.
    Bounded assignment pairs inside pytest parameter brackets are redacted
    only when the canonical ``logging._is_sensitive_key`` classifies the key
    as sensitive, which covers compound and prefixed keys such as
    ``AWS_SECRET_ACCESS_KEY`` and ``x_api_key``.  The surrounding test-path
    and test-name structure is preserved.

    Args:
        value: Untrusted text such as a captured pytest node identifier.

    Returns:
        Text with recognized credential material replaced by ``[REDACTED]``
        placeholders.  Arbitrary unknown credential formats are not
        guaranteed to be detected.
    """
    redacted = _BEARER_ADJACENT.sub("[REDACTED]", value)
    redacted = _CREDENTIAL_SHAPES.sub("[REDACTED]", redacted)
    return _PARAM_SEGMENT.sub(
        lambda segment: "[" + _KEY_VALUE_PAIR.sub(_redact_sensitive_pair, segment[1]) + "]",
        redacted,
    )


def _gate_diagnostics(text: str) -> list[str]:
    """Extract bounded, sanitized failed-test identifiers from untrusted output.

    Args:
        text: Captured subprocess output text; never trusted.

    Returns:
        At most ``_GATE_DIAGNOSTIC_LIMIT`` unique ``FAILED``/``ERROR`` test
        node identifiers, each credential-redacted before truncation and
        length-bounded.  Error detail text after each identifier is never
        retained.
    """
    seen: list[str] = []
    for node in _GATE_DIAGNOSTIC_PATTERN.findall(text):
        identifier = _redact_credential_text(_sanitize_string(node))[:_GATE_DIAGNOSTIC_LENGTH]
        if identifier not in seen:
            seen.append(identifier)
        if len(seen) == _GATE_DIAGNOSTIC_LIMIT:
            break
    return seen


class ReadinessVerifier:
    """Read-only aggregation of authenticated producer records for one candidate.

    Args:
        root: Module directory containing pyproject and frozen authorities.
        store: Application-owned runtime evidence store.
    """

    def __init__(self, root: Path, store: EvidenceStore) -> None:
        self.root = root.resolve(strict=True)
        self.store = store

    def binding(self) -> CandidateBinding:
        """Derive current candidate identity from actual Git-indexed source paths.

        Returns:
            Current candidate/contract identity derived from actual repository content.

        Raises:
            EvidenceError: If source integrity, origin, schema or binding checks fail.
            OSError: If a required storage or process operation is unavailable.
        """

        def git(*args: str) -> bytes:
            return subprocess.check_output(["git", *args], cwd=self.root)

        paths = git("ls-files", "--cached", "--others", "--exclude-standard", "-z", ".")
        entries = []
        for name in sorted(set(paths.decode().split("\0")) - {""}):
            path = self.root / name
            if path.is_symlink():
                raise EvidenceError("Candidate symlink is unsupported.")
            entries.append([name, digest(path.read_bytes()) if path.exists() else "deleted"])
        identity = digest(
            encoded({"head": git("rev-parse", "HEAD").decode().strip(), "files": entries})
        )
        contract = digest(
            (
                self.root / "docs/stories/STORY-10-integrated-verification-release-readiness.md"
            ).read_bytes()
        )
        return CandidateBinding(identity, contract)

    def record_projection(self, reference: str) -> ProjectionRecord:
        """Reload an accepted engine run and derive its canonical projection.

        Args:
            reference: Content-addressed reference to reload and authenticate.

        Returns:
            Producer-derived projection record; the obsolete module-level API always raises.

        Raises:
            EvidenceError: If source integrity, origin, schema or binding checks fail.
            OSError: If a required storage or process operation is unavailable.
        """
        binding = self.binding()
        envelope = self.store.load(
            reference,
            candidate=binding.candidate_id,
            contract=binding.contract_sha256,
            producer="evaluation_engine",
        )
        payload = envelope["payload"]
        if payload["class"] != "deterministic_fixture":
            raise EvidenceError("Evaluation provenance cannot be promoted.")
        rows = payload["rows"]
        versions = dict(payload["versions"])
        for index, row in enumerate(rows):
            versions[f"scenario:{index}"] = row["version"]
        source = {
            "terminal_status": payload["verdict"],
            "authorization": "engine_observed",
            "safety": "engine_observed",
            "replay": any(row["replayed"] for row in rows),
            "reason_codes": sorted({row["classification"] for row in rows}),
            "dataset_id": payload["dataset"],
            "versions": versions,
            "verdict": payload["verdict"],
            "regression": payload["regression"],
            "lab": "evaluation",
            "evidence_class": "deterministic_fixture",
        }
        projection = derive_projection(source)
        # Preserve actual per-scenario semantics without volatile numeric telemetry.
        projection["outcomes"] = [
            {
                key: row[key]
                for key in (
                    "scenario",
                    "evaluator",
                    "passed",
                    "classification",
                    "authorization",
                    "safety",
                    "replayed",
                )
            }
            for row in rows
        ]
        canonical = jcs_bytes(projection)
        return ProjectionRecord(
            binding,
            reference,
            digest(encoded(envelope)),
            {},
            projection,
            canonical,
            digest(canonical),
        )

    def verify_projection(self, record: ProjectionRecord) -> None:
        """Independently reload source evidence and compare every stored binding.

        Args:
            record: Projection record to compare with independently reloaded source.

        Returns:
            None after successful comparison; the obsolete module-level API always raises.

        Raises:
            EvidenceError: If source integrity, origin, schema or binding checks fail.
            OSError: If a required storage or process operation is unavailable.
        """
        expected = self.record_projection(record.run_reference)
        if expected != record:
            raise EvidenceError("Projection/source/reference/candidate binding mismatch.")

    def policy_outcomes(self, reference: str) -> tuple[dict[str, object], ...]:
        """Reload actual stable policy classifications independently of projection equality.

        Args:
            reference: Content-addressed reference to reload and authenticate.

        Returns:
            Stable scenario policy outcomes, excluding raw volatile numerical telemetry.

        Raises:
            EvidenceError: If source integrity, origin, schema or binding checks fail.
            OSError: If a required storage or process operation is unavailable.
        """
        binding = self.binding()
        payload = self.store.load(
            reference,
            candidate=binding.candidate_id,
            contract=binding.contract_sha256,
            producer="evaluation_engine",
        )["payload"]
        return tuple(
            {
                key: row[key]
                for key in (
                    "scenario",
                    "evaluator",
                    "classification",
                    "budget",
                    "replayed",
                    "effects",
                )
            }
            for row in payload["rows"]
        )

    def reconcile_traceability(
        self,
        evaluation: str,
        *,
        workflow: str | None = None,
        lab: str | None = None,
        accepted_tests: str | None = None,
        audit: str | None = None,
        gate: str | None = None,
    ) -> tuple[dict[str, object], ...]:
        """Load frozen requirement routing without upgrading absent evidence.

        Args:
            evaluation: Authenticated accepted-engine evidence reference.
            workflow: Optional authenticated local workflow reference.
            lab: Optional authenticated failure-lab reference.
            accepted_tests: Optional authenticated accepted-test execution reference.
            audit: Optional authenticated source-audit reference.
            gate: Optional actual gate reference, verified before reconciliation.

        Returns:
            Complete source-derived requirement rows and explicit limitations.

        Raises:
            EvidenceError: If source integrity, origin, schema or binding checks fail.
            OSError: If a required storage or process operation is unavailable.
        """
        record = self.record_projection(evaluation)
        requirements = (self.root / "docs/REQUIREMENTS.md").read_text(encoding="utf-8")
        routing = (self.root / "docs/TRACEABILITY.md").read_text(encoding="utf-8")
        identifiers = sorted(set(re.findall(r"^REQ-[A-Z]+-[0-9]{3}", requirements, re.M)))
        plan = (self.root / "docs/IMPLEMENTATION_PLAN.md").read_text(encoding="utf-8")
        ownership: dict[str, list[dict[str, object]]] = {}
        for section in re.split(r"(?=^## Story [0-9]+)", plan, flags=re.M):
            heading = re.match(r"## Story ([0-9]+)", section)
            if heading is None:
                continue
            assigned = re.search(r"\*\*Requirements:\*\* (.+)", section)
            decisions = re.search(r"\*\*ADRs:\*\* (.+)", section)
            if assigned is None or decisions is None:
                continue
            decision_ids = set(re.findall(r"ADR-007-[0-9]{3}", decisions[1]))
            span = re.search(r"ADR-007-([0-9]{3}) through ADR-007-([0-9]{3})", decisions[1])
            if span:
                decision_ids.update(
                    f"ADR-007-{number:03}" for number in range(int(span[1]), int(span[2]) + 1)
                )
            for identifier in re.findall(r"REQ-[A-Z]+-[0-9]{3}", assigned[1]):
                ownership.setdefault(identifier, []).append(
                    {
                        "story": heading[1],
                        "adrs": sorted(decision_ids),
                        "authority": "docs/IMPLEMENTATION_PLAN.md",
                    }
                )
        source_lines = {
            line.split()[0]: number
            for number, line in enumerate(requirements.splitlines(), 1)
            if re.match(r"^REQ-[A-Z]+-[0-9]{3}\b", line)
        }
        obligations = {}
        for match in re.finditer(r"^(REQ-[A-Z]+-[0-9]{3}) \[([^]]+)\]: (.*)", requirements, re.M):
            continuation = requirements[match.end() :].split("\n\n", 1)[0]
            continuation = continuation.split("\nREQ-", 1)[0]
            obligations[match[1]] = {
                "classification": match[2],
                "text": (match[3] + continuation).strip(),
            }
        missing_proof = {
            "OBJ": (
                "Two-deliverable educational objective demonstration is not "
                "bound to a reviewed outcome."
            ),
            "REL": (
                "Full resilience coverage, including unresolved lifecycle "
                "behavior, lacks sufficient current evidence."
            ),
            "SAFE": (
                "Guardrail/moderation provider outcomes need their own "
                "authenticated behavioral records."
            ),
            "OBS": (
                "Tracing/logging/latency/cost/debugging acceptance requires "
                "requirement-specific workflow and telemetry records."
            ),
            "EVAL": (
                "Regression/improvement decisions need their own accepted "
                "comparison/cycle evidence."
            ),
            "LAB": (
                "Dashboard or full failure-lab acceptance is not established "
                "by the evaluation reference."
            ),
            "TOOL": (
                "Meaningful tool execution needs matching adapter/wrapper "
                "evidence; installed code is insufficient."
            ),
            "DEL": (
                "Reviewable deliverable acceptance is not established by component execution alone."
            ),
            "CLOSE": (
                "Whole-module topic/lab/tool-to-deliverable reconciliation remains incomplete."
            ),
            "SRC": (
                "Independent source-fidelity and evidence-claim audit is not "
                "bound to current records."
            ),
            "ISO": (
                "Current whole-module import/dependency and non-interference audit is not recorded."
            ),
            "GOV": "Governance/approval compliance needs reviewed change and authority records.",
            "UI": (
                "Current session rendering/guidance/ownership evidence is not "
                "bound to this requirement."
            ),
            "ENG": (
                "Required adversarial controller/provider outcomes need "
                "applicable authenticated scenario evidence."
            ),
            "SEC": (
                "The complete stated security scope lacks a "
                "requirement-specific authenticated acceptance record."
            ),
            "COST": (
                "Required limits/accounting/live-separation verification is "
                "not bound to current policy evidence."
            ),
            "QUAL": (
                "Current "
                "interface/documentation/error/configuration/compatibility "
                "audit is not recorded."
            ),
            "QG": "No actual complete candidate-bound formal gate/repair-governance record exists.",
            "DOD": (
                "Required completion/verification prerequisite has not been "
                "established for the current candidate."
            ),
            "EVD": (
                "Producer execution is recorded, but this evidence-store "
                "security/lifecycle obligation lacks its own authenticated "
                "check record."
            ),
        }
        rows = []
        for identifier in identifiers:
            matching = [
                line for line in routing.splitlines() if line.startswith("| " + identifier + " |")
            ]
            owners = ownership.get(identifier, [])
            adrs: list[str] = sorted({adr for owner in owners for adr in owner["adrs"]})
            tests: list[str] = []
            if identifier.startswith("REQ-EVD-"):
                if len(matching) != 1:
                    raise EvidenceError("Frozen evidence requirement routing is incomplete.")
                columns = matching[0].split("|")
                adrs = sorted(set(re.findall(r"ADR-007-[0-9]{3}", columns[2])))
                tests = re.findall(r"[0-9]+", columns[4])
                if any(not 1 <= int(test) <= 20 for test in tests):
                    raise EvidenceError("Frozen routing references an unknown conceptual test.")
                for adr in adrs:
                    if len(tuple((self.root / "docs/adr").glob(adr + "-*.md"))) != 1:
                        raise EvidenceError("Frozen routing references an unknown ADR.")
            rows.append(
                {
                    "requirement": identifier,
                    "source": "docs/REQUIREMENTS.md",
                    "source_line": source_lines[identifier],
                    "obligation": obligations[identifier]["text"],
                    "requirement_class": obligations[identifier]["classification"],
                    "evidence_gap_kind": "unmapped_or_missing_acceptance_proof",
                    "required_proof": missing_proof[identifier.split("-")[1]],
                    "implementing_stories": [owner["story"] for owner in owners]
                    if owners
                    else (["10"] if identifier.startswith("REQ-EVD-") else []),
                    "routing_authorities": owners,
                    "adrs": adrs,
                    "story": "10" if identifier.startswith("REQ-EVD-") else None,
                    "tests": tests,
                    "evidence_reference": evaluation if identifier.startswith("REQ-EVD-") else None,
                    "evidence_class": "deterministic_fixture"
                    if identifier.startswith("REQ-EVD-")
                    else None,
                    "candidate": record.binding.candidate_id,
                    "contract": record.binding.contract_sha256,
                    "status": "open",
                    "reason": missing_proof[identifier.split("-")[1]],
                }
            )
        # The automated-evaluation requirement is directly demonstrated by the
        # authenticated engine-produced evaluation rows, unlike unrelated rows.
        for row in rows:
            if row["requirement"] == "REQ-EVAL-001" and record.projection.get("outcomes"):
                row.update(
                    {
                        "status": "verified",
                        "tests": ["4"],
                        "evidence_reference": evaluation,
                        "evidence_class": "deterministic_fixture",
                        "reason": "authenticated engine execution produced evaluator outcomes",
                    }
                )
        source = self.store.load(
            evaluation,
            candidate=record.binding.candidate_id,
            contract=record.binding.contract_sha256,
            producer="evaluation_engine",
        )["payload"]
        scenario_rows: dict[str, list[dict[str, object]]] = {}
        for result in source["rows"]:
            scenario_rows.setdefault(result["scenario"], []).append(result)
        # These predicates are explicit semantic reviews of the frozen SOURCE
        # requirements, not inference from test names or implementation presence.
        demonstrations = {
            "REQ-REL-001": ("REL-001", "attempts", 2, "success"),
            "REQ-REL-002": ("REL-004", "fallbacks", 1, "success"),
            "REQ-REL-003": ("IDEM-001", "replayed", True, "success"),
            "REQ-SAFE-001": ("SAFE-001", "safety", "deny", "safety_denied"),
            "REQ-SAFE-002": ("AUTH-001", "authorization", "deny", "authorization_denied"),
        }
        for row in rows:
            rule = demonstrations.get(row["requirement"])
            if rule is not None:
                scenario, field, value, classification = rule
                results = scenario_rows.get(scenario, [])
                proven = bool(results) and all(
                    result["passed"]
                    and result[field] == value
                    and result["classification"] == classification
                    for result in results
                )
                if row["requirement"] in {"REQ-SAFE-001", "REQ-SAFE-002"}:
                    proven = proven and all(result["effects"] == 0 for result in results)
                if row["requirement"] == "REQ-REL-003":
                    proven = proven and all(result["effects"] == 1 for result in results)
                if proven:
                    row.update(
                        {
                            "status": "verified",
                            "evidence_reference": evaluation,
                            "evidence_class": "deterministic_fixture",
                            "tests": ["4", "10"],
                            "observed_scenarios": [scenario],
                            "reason": "accepted target outcomes demonstrate source behavior",
                        }
                    )
            if row["requirement"] in {"REQ-EVAL-003", "REQ-LAB-002"} and source["rows"]:
                row.update(
                    {
                        "status": "verified",
                        "evidence_reference": evaluation,
                        "evidence_class": "deterministic_fixture",
                        "tests": ["4"],
                        "reason": "accepted benchmark executed committed dataset and evaluators",
                    }
                )
        if workflow is not None:
            observed = self.observability(workflow)
            source = self.store.load(
                workflow,
                candidate=record.binding.candidate_id,
                contract=record.binding.contract_sha256,
                producer="workflow_observability",
            )["payload"]
            telemetry = source["redacted_records"]
            correlated = bool(telemetry) and all(
                item.get("workflow_id") == source["source_identity"]["workflow_id"]
                and item.get("trace_id") == source["source_identity"]["trace_id"]
                and item.get("span_id")
                for item in telemetry
            )
            latency = correlated and all(
                type(item.get("duration_ms")) in (int, float) and item["duration_ms"] >= 0
                for item in telemetry
            )
            for row in rows:
                identifier = row["requirement"]
                if identifier in {"REQ-OBS-001", "REQ-OBS-002", "REQ-OBS-003"}:
                    sufficient = latency if identifier == "REQ-OBS-003" else correlated
                    if sufficient:
                        row.update(
                            {
                                "status": "verified",
                                "evidence_reference": workflow,
                                "evidence_class": "deterministic_fixture",
                                "tests": ["3"],
                                "reason": "workflow emitted correlated structured telemetry"
                                if identifier != "REQ-OBS-003"
                                else "accepted workflow recorded nonnegative measured duration_ms",
                            }
                        )
                if identifier in {"REQ-OBS-004", "REQ-COST-002"}:
                    row.update(
                        {
                            "status": "open",
                            "evidence_reference": workflow,
                            "evidence_class": "deterministic_fixture",
                            "tests": ["3"],
                            "reason": "fixture accounting only; billable analytics proof absent",
                        }
                    )
            del observed
            for row in rows:
                if row["requirement"] in {"REQ-LAB-001", "REQ-DEL-001"}:
                    row.update(
                        {
                            "status": "open",
                            "evidence_reference": workflow,
                            "evidence_class": "deterministic_fixture",
                            "tests": ["3"],
                            "reason": (
                                "Local backend exercised; complete dashboard/platform "
                                "acceptance record missing."
                            ),
                        }
                    )
        # Bounded Category-A review: qualify only the scope exercised by the
        # authenticated engine run. Broader adversarial proofs remain missing.
        partial_rules = {
            "REQ-ENG-001": (
                "REL-001",
                "Finite retry demonstrated; complete bound/refusal matrix unbound.",
            ),
            "REQ-ENG-002": (
                "REL-003",
                "Timeout outcome demonstrated; every external boundary unverified.",
            ),
            "REQ-ENG-003": (
                "REL-002",
                "Terminal refusal demonstrated; full retryability matrix unbound.",
            ),
            "REQ-ENG-004": (
                "REL-004",
                "Fallback demonstrated; denied fallback combinations unbound.",
            ),
            "REQ-ENG-005": (
                "IDEM-001",
                "Replay has one effect; concurrency/conflict acceptance unbound.",
            ),
            "REQ-ENG-007": (
                "REL-002",
                "Expected failure exercised; full failure taxonomy unbound.",
            ),
            "REQ-REL-004": (
                "REL-004",
                "Recovery demonstrated; S19/S20 reliability risk unresolved.",
            ),
            "REQ-COST-001": (
                "COST-001",
                "Fixture budget refusal observed; billable limits unverified.",
            ),
            "REQ-SEC-001": ("SAFE-001", "Untrusted input contained; other input surfaces unbound."),
            "REQ-SEC-002": (
                "AUTH-002",
                "Forged input authority denied; all privileged surfaces unbound.",
            ),
            "REQ-SEC-003": (
                "AUTH-001",
                "Tool denial observed; complete principal/tool matrix unbound.",
            ),
            "REQ-SEC-004": (
                "AUTH-001",
                "Safety allow cannot override tool denial in the recorded scenario; "
                "complete safety/authorization type-confusion acceptance remains unbound.",
            ),
            "REQ-SEC-005": (
                "SAFE-002",
                "Policy-injection input inert; full attack acceptance unbound.",
            ),
            "REQ-SEC-007": (
                "RED-001",
                "Synthetic redaction case passed; arbitrary payload coverage absent.",
            ),
        }
        for row in rows:
            rule = partial_rules.get(row["requirement"])
            if rule is not None:
                scenario, limitation = rule
                results = scenario_rows.get(scenario, [])
                if results and all(result["passed"] for result in results):
                    row.update(
                        {
                            "status": "open",
                            "evidence_reference": evaluation,
                            "evidence_class": "deterministic_fixture",
                            "observed_scenarios": [scenario],
                            "tests": ["4", "10"],
                            "reason": limitation,
                        }
                    )
            if row["requirement"] == "REQ-EVAL-002" and record.projection["regression"] == "pass":
                row.update(
                    {
                        "status": "verified",
                        "evidence_reference": evaluation,
                        "evidence_class": "deterministic_fixture",
                        "tests": ["4"],
                        "reason": "accepted comparator executed against loader-validated baseline",
                    }
                )
            if row["requirement"] in {"REQ-EVD-001", "REQ-EVD-003", "REQ-EVD-004", "REQ-EVD-005"}:
                row.update(
                    {
                        "status": "open",
                        "evidence_reference": evaluation,
                        "evidence_class": "deterministic_fixture",
                        "tests": ["1", "2", "11"],
                        "reason": (
                            "Producer recording/reload exercised; complete adversarial "
                            "acceptance record unbound."
                        ),
                    }
                )
        if lab is not None:
            failure = self.store.load(
                lab,
                candidate=record.binding.candidate_id,
                contract=record.binding.contract_sha256,
                producer="failure_lab",
            )["payload"]
            diagnostics = [
                result
                for result in failure["results"]
                if result["telemetry"] == "export_failed" and result["passed"]
            ]
            if diagnostics:
                for row in rows:
                    if row["requirement"] == "REQ-OBS-005":
                        row.update(
                            {
                                "status": "open",
                                "evidence_reference": lab,
                                "evidence_class": "simulated_failure",
                                "tests": ["5", "8"],
                                "observed_scenarios": [
                                    result["scenario_id"] for result in diagnostics
                                ],
                                "reason": (
                                    "Export-failure diagnostic observed; complete "
                                    "trace/span failure record missing."
                                ),
                            }
                        )
        if accepted_tests is not None:
            execution = self.store.load(
                accepted_tests,
                candidate=record.binding.candidate_id,
                contract=record.binding.contract_sha256,
                producer="accepted_test_execution",
            )["payload"]
            passed = {
                item["node_id"].split("::")[-1]
                for item in execution["reports"]
                if item["phase"] == "call" and item["outcome"] == "passed"
            }
            rules = {
                "REQ-SEC-010": {
                    "test_prohibited_guardrails_version_cannot_satisfy_declared_requirement",
                    "test_prohibited_version_is_rejected_even_if_bounds_widen",
                    "test_locked_and_installed_guardrails_satisfy_the_contract",
                },
                "REQ-ISO-001": {
                    "test_public_package_imports_independently",
                    "test_source_has_no_sibling_module_imports",
                },
                "REQ-ISO-002": {"test_source_has_no_sibling_module_imports"},
                # REQ-EVD-001: producer-seam authority and anti-forgery
                # behavior, bound to the four non-recursive conceptual nodes
                # fixed in _ACCEPTED_TEST_SELECTION (tests 1, 7, 8, 10).
                "REQ-EVD-001": {
                    "test_01_producer_projection_jcs_and_integer_contract",
                    "test_07_integrated_acceptance_binding",
                    "test_08_actual_security_outcomes",
                    "test_10_actual_budget_outcomes",
                },
            }
            if execution["exit_code"] != 0:
                raise EvidenceError("Accepted test execution failed; no requirement promotion.")
            for row in rows:
                required = rules.get(row["requirement"])
                if required and required <= passed:
                    row.update(
                        {
                            "status": "verified",
                            "evidence_reference": accepted_tests,
                            "evidence_class": "deterministic_fixture",
                            "behavioral_nodes": sorted(required),
                            "reason": "authenticated accepted assertion-bearing test execution",
                        }
                    )
        if audit is not None:
            inspected = self.store.load(
                audit,
                candidate=record.binding.candidate_id,
                contract=record.binding.contract_sha256,
                producer="candidate_audit",
            )["payload"]
            for row in rows:
                relevant = [
                    finding
                    for finding in inspected["findings"]
                    if row["requirement"] in finding["obligations"]
                ]
                if relevant:
                    row["audit_reference"] = audit
                    row["audit_findings"] = relevant
        return self._complete_traceability(
            rows,
            evaluation,
            workflow=workflow,
            lab=lab,
            accepted_tests=accepted_tests,
            audit=audit,
            gate=gate,
        )

    def _source_reference(self, reference: str) -> str:
        """Check a module-relative implementation or test symbol without executing it."""
        import ast

        file, _, symbol = reference.partition("::")
        path = self.root / file
        if not path.resolve().is_relative_to(self.root) or not path.is_file():
            raise EvidenceError("Reconciliation source reference is outside the module or missing.")
        if any(part.is_symlink() or part.is_junction() for part in (path, *path.parents)):
            raise EvidenceError("Reconciliation source reference cannot traverse links.")
        if symbol:
            body = ast.parse(path.read_bytes()).body
            for name in symbol.split("."):
                node = next((node for node in body if getattr(node, "name", None) == name), None)
                if node is None:
                    raise EvidenceError("Reconciliation references an unknown source symbol.")
                body = getattr(node, "body", [])
        return reference

    def _complete_traceability(
        self,
        rows: list[dict[str, object]],
        evaluation: str,
        *,
        workflow: str | None,
        lab: str | None,
        accepted_tests: str | None,
        audit: str | None,
        gate: str | None,
    ) -> tuple[dict[str, object], ...]:
        """Finalize only independently derived relationships and authenticated support."""
        import ast

        binding = self.binding()
        inputs = {
            "evaluation_engine": evaluation,
            "workflow_observability": workflow,
            "failure_lab": lab,
            "accepted_test_execution": accepted_tests,
            "candidate_audit": audit,
            "gate_executor": gate,
        }
        if gate is not None:
            GateExecutor(self).verify(gate)
        envelopes = {
            reference: self.store.load(
                reference,
                candidate=binding.candidate_id,
                contract=binding.contract_sha256,
                producer=producer,
            )
            for producer, reference in inputs.items()
            if reference is not None
        }
        # Fixed authorities supply conceptual obligations; execution reports do
        # not replace this required inventory with whichever subset happened to run.
        frozen = (
            self.root / "docs/stories/STORY-10-integrated-verification-release-readiness.md"
        ).read_text()
        routing = (self.root / "docs/TRACEABILITY.md").read_text()
        concepts: dict[str, set[int]] = {}
        for line in frozen.splitlines():
            match = re.match(r"\| ([0-9]+) \|", line)
            if match is None:
                continue
            number = int(match[1])
            for code in re.finditer(
                r"\b(OBJ|CLOSE|DOD|QG)-([0-9]{3})((?:/-[0-9]{3}|\.\.[0-9]{3})*)", line
            ):
                family, first, suffix = code.groups()
                values = [int(first)]
                if suffix.startswith(".."):
                    values = list(range(int(first), int(suffix[2:]) + 1))
                else:
                    values.extend(int(value) for value in re.findall(r"/-([0-9]{3})", suffix))
                for value in values:
                    concepts.setdefault(f"REQ-{family}-{value:03}", set()).add(number)
        for line in routing.splitlines():
            match = re.match(r"\| (REQ-EVD-[0-9]{3}) \|", line)
            if match:
                concepts[match[1]] = {int(n) for n in re.findall(r"[0-9]+", line.split("|")[4])}
        test_tree = ast.parse((self.root / "tests/test_integrated_acceptance.py").read_bytes())
        conceptual_nodes = {
            int(match[1]): node.name
            for node in test_tree.body
            if isinstance(node, ast.FunctionDef)
            and (match := re.match(r"test_([0-9]{2})_", node.name))
        }
        if set(conceptual_nodes) != set(range(1, 21)):
            raise EvidenceError("Reconciliation requires the exact twenty conceptual tests.")
        implementations = {
            identifier: [
                name[1:] if name.startswith("@") else "src/reliability_safety_observability/" + name
                for name in references
            ]
            for identifiers, references in _IMPLEMENTATION_GROUPS.items()
            for identifier in identifiers.split()
        }
        execution = envelopes[accepted_tests]["payload"] if accepted_tests is not None else None
        observed = {}
        if execution is not None:
            for report in execution["reports"]:
                if report["phase"] == "call" and report["outcome"] == "passed":
                    node = report["node_id"]
                    for identifier in _TEST_OBLIGATIONS.get(node.split("::")[-1], ()):
                        observed.setdefault(identifier, []).append(node)
        failure = envelopes[lab]["payload"] if lab is not None else None
        if failure is not None:
            summary, results = failure["summary"], failure["results"]
            passed = sum(result["passed"] is True for result in results)
            if (
                len(results) != 20
                or summary["scenario_count"] != 20
                or {r["kind"] for r in results} != {f"s{n:02}" for n in range(1, 21)}
                or len({r["scenario_id"] for r in results}) != 20
                or summary["passed_count"] != passed
                or summary["failed_count"] != 20 - passed
                or not _is_sha256(summary["digest"])
            ):
                raise EvidenceError("Failure-lab reconciliation summary contradicts its scenarios.")
            # Authentication binds the observation, not the truth of a claimed
            # aggregate. Validate both maps with the accepted producer schema,
            # then reconcile every class before any finalized claim is emitted.
            from .errors import ConfigurationError
            from .failure_lab import LabSummary

            declared_counts = summary.get("evidence_counts")
            if not isinstance(declared_counts, Mapping):
                raise EvidenceError("Failure-lab classification counts require a mapping.")
            derived_counts: dict[str, int] = {}
            for result in results:
                label = result.get("evidence_class")
                if type(label) is not str:
                    raise EvidenceError("Failure-lab scenario classification is malformed.")
                derived_counts[label] = derived_counts.get(label, 0) + 1
            try:
                LabSummary(**summary)
                LabSummary(**{**summary, "evidence_counts": derived_counts})
            except (ConfigurationError, TypeError, ValueError) as error:
                raise EvidenceError("Failure-lab classification summary is malformed.") from error
            # The producer permits explicit zero entries for unobserved supported
            # classes. Absent and explicit-zero entries denote the same count;
            # unknown labels (including live labels) have already been refused.
            if any(
                declared_counts.get(label, 0) != derived_counts.get(label, 0)
                for label in set(declared_counts) | set(derived_counts)
            ):
                raise EvidenceError("Failure-lab classification counts contradict its scenarios.")
        lab_obligations = {
            "REQ-REL-001": ("s01", "s05"),
            "REQ-REL-002": ("s02", "s06", "s07"),
            "REQ-REL-003": ("s08", "s09"),
            "REQ-ENG-001": ("s04", "s05"),
            "REQ-ENG-002": ("s03", "s04", "s20"),
            "REQ-ENG-003": ("s02", "s05"),
            "REQ-ENG-004": ("s02", "s06", "s07"),
            "REQ-ENG-005": ("s08", "s09"),
            "REQ-ENG-006": ("s14", "s15"),
            "REQ-COST-001": ("s10",),
            "REQ-SAFE-001": ("s13",),
            "REQ-SAFE-002": ("s11",),
            "REQ-SAFE-004": ("s12",),
            "REQ-SEC-002": ("s13",),
            "REQ-SEC-003": ("s11",),
            "REQ-SEC-004": ("s11", "s12"),
            "REQ-SEC-005": ("s13",),
            "REQ-SEC-008": ("s14", "s15"),
            "REQ-OBS-005": ("s15",),
            "REQ-LAB-003": tuple(f"s{n:02}" for n in range(1, 21)),
            "REQ-REL-004": tuple(f"s{n:02}" for n in range(1, 21)),
        }
        checked_references: set[str] = set()
        for row in rows:
            identifier = row["requirement"]
            # A supporting reference is never treated as proof of the full
            # requirement merely because a related producer executed.
            references = {row["evidence_reference"]} - {None}
            if identifier in observed:
                references.add(accepted_tests)
                if row["status"] == "open" and row["evidence_reference"] is None:
                    row["reason"] = (
                        "Scoped passing test observations are bound to this row. "
                        "Those specific assertions do not establish the full obligation: "
                        + row["obligation"]
                    )
            if row.get("audit_findings"):
                references.add(audit)
                if row["status"] == "open":
                    row["reason"] = (
                        "Source-bound audit recorded; its scoped findings do not establish "
                        "the entire obligation: " + row["obligation"]
                    )
            if identifier in {"REQ-LAB-003", "REQ-REL-004"} and failure is not None:
                success = (
                    failure["summary"]["failed_count"] == 0
                    and not failure["summary"]["invariant_failures"]
                )
                row.update(
                    status="verified" if success else "rejected",
                    evidence_reference=lab,
                    evidence_class="simulated_failure",
                    reason="Accepted twenty-scenario recovery matrix "
                    + ("passed." if success else "violated its invariants."),
                )
                references.add(lab)
            if identifier in {"REQ-ENG-006", "REQ-SEC-008"} and failure is not None:
                references.add(lab)
                row["reason"] = (
                    "Recorded S14/S15 containment supports the accepted lab paths; "
                    "the full obligation is not independently reconciled: " + row["obligation"]
                )
            if (
                identifier
                in {"REQ-TOOL-001", "REQ-TOOL-002", "REQ-TOOL-003", "REQ-TOOL-004", "REQ-SAFE-003"}
                and identifier in observed
            ):
                row["reason"] = (
                    "Authenticated assertion-bearing local adapter/validator execution; "
                    "scope is the listed test assertions, with no live-provider claim."
                )
                if identifier in {"REQ-TOOL-004", "REQ-SAFE-003"}:
                    row.update(
                        status="verified",
                        evidence_reference=accepted_tests,
                        evidence_class="deterministic_fixture",
                    )
                else:
                    row["reason"] += " Complete tool-to-deliverable acceptance remains open."
            if identifier in {"REQ-OBS-004", "REQ-COST-002"} and workflow is not None:
                row["reason"] = (
                    "Fixture accounting is recorded; complete cost-analytics acceptance "
                    "beyond these observations is not bound. No live execution is inferred."
                )
            if identifier in {"REQ-LAB-001", "REQ-DEL-001"} and identifier in observed:
                row["reason"] = (
                    "Backend workflow and selected reviewer controls are exercised; "
                    "complete dashboard/platform acceptance remains unbound."
                )
            if identifier.startswith("REQ-QG-") or identifier in {"REQ-DOD-007", "REQ-EVD-006"}:
                if gate is None:
                    row.update(
                        status="open",
                        reason="No authenticated gate reference supplied to this reconciliation.",
                    )
                    if identifier == "REQ-EVD-006":
                        references.discard(evaluation)
                        row.update(evidence_reference=None, evidence_class=None)
                else:
                    references.add(gate)
                    history_scope = (
                        "including recorded retry history"
                        if envelopes[gate]["payload"]["resolved_failures"]
                        else "with no recorded repair episode"
                    )
                    row["reason"] = (
                        "Current gate is verified, "
                        + history_scope
                        + "; the complete policy obligation still needs its own proof: "
                        + row["obligation"]
                    )
                    if identifier in {"REQ-QG-001", "REQ-DOD-007", "REQ-EVD-006"}:
                        row.update(
                            status="verified",
                            evidence_reference=gate,
                            evidence_class=None,
                            reason=(
                                "Authenticated complete Ruff/pytest/compileall attempt verified, "
                                "including bindings, order, outputs and applicable history."
                            ),
                        )
                        if identifier == "REQ-EVD-006":
                            references.discard(evaluation)
            lab_observations = []
            if failure is not None and identifier in lab_obligations:
                references.add(lab)
                lab_observations = [
                    {
                        key: result[key]
                        for key in (
                            "kind",
                            "scenario_id",
                            "evidence_class",
                            "passed",
                            "observed",
                        )
                    }
                    for result in failure["results"]
                    if result["kind"] in lab_obligations[identifier]
                ]
                if any(not result["passed"] for result in lab_observations) and identifier not in {
                    "REQ-LAB-003",
                    "REQ-REL-004",
                }:
                    row.update(
                        status="open",
                        reason="Negative lab evidence requires focused diagnosis.",
                    )
            row["observed_lab_scenarios"] = lab_observations
            if row["status"] not in _RECONCILIATION_STATES:
                raise EvidenceError("Unknown reconciliation status.")
            implementation_refs = sorted(set(implementations.get(identifier, [])))
            required_concepts = concepts.get(identifier, {int(n) for n in row["tests"]})
            if identifier in {"REQ-LAB-003", "REQ-REL-004"}:
                required_concepts = required_concepts | {7}
            test_refs = sorted(
                set(observed.get(identifier, []))
                | {
                    "tests/test_integrated_acceptance.py::" + conceptual_nodes[n]
                    for n in required_concepts
                }
            )
            for reference in implementation_refs + test_refs:
                if reference not in checked_references:
                    self._source_reference(reference)
                    checked_references.add(reference)
            references |= {row["evidence_reference"]} - {None}
            descriptors = [
                {
                    "reference": reference,
                    "producer": envelopes[reference]["producer"],
                    "class": envelopes[reference]["payload"].get("class"),
                    "candidate": envelopes[reference]["candidate"],
                    "contract": envelopes[reference]["contract"],
                }
                for reference in sorted(references)
            ]
            model = TraceabilityRow(
                identifier,
                tuple(row["adrs"]),
                tuple(row["implementing_stories"]),
                tuple(implementation_refs),
                tuple(test_refs),
                tuple(sorted(references)),
                row["evidence_class"],
                row["status"],
            )
            row.update(
                requirement_id=model.requirement_id,
                adr_ids=list(model.adr_ids),
                captured_result_class=model.evidence_class,
                story_ids=list(model.story_ids),
                implementation_references=list(model.implementation_references),
                test_references=list(model.test_references),
                evidence_references=list(model.evidence_references),
                evidence_details=descriptors,
                conceptual_tests=sorted(required_concepts),
                observed_test_references=sorted(set(observed.get(identifier, []))),
                tests=[str(n) for n in sorted(required_concepts)],
                implementation_scope=(
                    (
                        "Listed bounded implementation/configuration/authority contributions; "
                        "existence alone is not acceptance proof."
                    )
                    if implementation_refs
                    else (
                        "Governance/approval obligation: no executable implementation "
                        "relationship asserted."
                    )
                ),
                historical_qualifications=(
                    [
                        "656 passed, 3 skipped, 1 failed: qualified_historical; "
                        "historical S19/S20 intermittent reliability risk remains unresolved."
                    ]
                    if identifier in {"REQ-LAB-003", "REQ-REL-004", "REQ-DOD-003", "REQ-CLOSE-005"}
                    else []
                ),
            )
            gap = None if row["status"] == "verified" else row["reason"]
            row.update(
                remaining_gaps=[] if gap is None else [gap],
                required_proof="" if gap is None else gap,
                evidence_gap_kind=(
                    "none"
                    if gap is None
                    else "contradicted"
                    if row["status"] == "rejected"
                    else "partial_current_support"
                    if references
                    else "missing_acceptance_proof"
                ),
            )
            if row["status"] == "verified" and (not implementation_refs or not references):
                raise EvidenceError("Verified reconciliation lacks implementation or evidence.")
        identifiers = [row["requirement"] for row in rows]
        if identifiers != sorted(set(identifiers)):
            raise EvidenceError("Reconciliation contains duplicate or unordered requirements.")
        if self.binding() != binding:
            raise EvidenceError("Candidate changed during reconciliation.")
        return tuple(rows)

    def verify_traceability_claim(
        self,
        evaluation: str,
        claim: Mapping[str, object],
        *,
        workflow: str | None = None,
        lab: str | None = None,
        accepted_tests: str | None = None,
        audit: str | None = None,
        gate: str | None = None,
    ) -> None:
        """Compare an untrusted relationship claim to independently derived routing.

        Matching an open row does not establish implementation acceptance.


        Args:
            evaluation: Authenticated accepted-engine evidence reference.
            claim: Untrusted relationship proposal, compared with frozen source routing.
            workflow: Authenticated workflow context.
            lab: Authenticated failure-lab context.
            accepted_tests: Authenticated observer context.
            audit: Authenticated source-audit context.
            gate: Authenticated actual gate context.

        Returns:
            None only for a matching independently derived relationship.

        Raises:
            EvidenceError: If source integrity, origin, schema or binding checks fail.
            OSError: If a required storage or process operation is unavailable.
        """
        rows = self.reconcile_traceability(
            evaluation,
            workflow=workflow,
            lab=lab,
            accepted_tests=accepted_tests,
            audit=audit,
            gate=gate,
        )
        if not any(dict(claim) == row for row in rows):
            raise EvidenceError("Traceability relationship differs from authoritative routing.")

    def reconcile_labs(
        self, evaluation: str, lab: str, *, workflow: str | None = None
    ) -> dict[str, object]:
        """Require the actual accepted producer for each asserted lab support.

        Args:
            evaluation: Authenticated accepted-engine evidence reference.
            lab: Optional authenticated failure-lab reference.
            workflow: Optional authenticated local workflow reference.

        Returns:
            Three lab relationships with unsupported links left open.

        Raises:
            EvidenceError: If source integrity, origin, schema or binding checks fail.
            OSError: If a required storage or process operation is unavailable.
        """
        record = self.record_projection(evaluation)
        failure = self.store.load(
            lab,
            candidate=record.binding.candidate_id,
            contract=record.binding.contract_sha256,
            producer="failure_lab",
        )
        return {
            "evaluation": {"reference": evaluation, "deliverables": ["evaluation"]},
            "failure_recovery": {
                "reference": lab,
                "deliverables": ["observability"],
                "summary_digest": failure["payload"]["summary"]["digest"],
            },
            "observability": (
                {**self.observability(workflow), "deliverables": ["observability"]}
                if workflow is not None
                else {"status": "open", "reason": "authenticated workflow reference required"}
            ),
        }

    def observability(self, reference: str) -> dict[str, object]:
        """Reload authenticated accepted workflow evidence and project semantic facts.

        Args:
            reference: Content-addressed reference to reload and authenticate.

        Returns:
            Source-bound canonical local observability projection.

        Raises:
            EvidenceError: If source integrity, origin, schema or binding checks fail.
            OSError: If a required storage or process operation is unavailable.
        """
        binding = self.binding()
        envelope = self.store.load(
            reference,
            candidate=binding.candidate_id,
            contract=binding.contract_sha256,
            producer="workflow_observability",
        )
        payload = envelope["payload"]
        if payload["class"] != "deterministic_fixture":
            raise EvidenceError("Workflow evidence classification mismatch.")
        canonical = jcs_bytes(payload["semantics"])
        return {
            "reference": reference,
            "candidate": binding.candidate_id,
            "contract": binding.contract_sha256,
            "source_identity": payload["source_identity"],
            "semantics": payload["semantics"],
            "canonical_hex": canonical.hex(),
            "digest": digest(canonical),
            "class": payload["class"],
            "status": "verified_local_execution",
        }

    def artifacts(
        self,
        evaluation: str,
        lab: str,
        gate: str | None = None,
        *,
        workflow: str | None = None,
        accepted_tests: str | None = None,
        audit: str | None = None,
    ) -> dict[str, object]:
        """Derive eight bounded artifacts, retaining unsupported closure as open.

        Args:
            evaluation: Authenticated accepted-engine evidence reference.
            lab: Optional authenticated failure-lab reference.
            gate: Optional authenticated completed gate record.
            workflow: Optional authenticated local workflow reference.
            accepted_tests: Optional authenticated accepted-test execution.
            audit: Optional authenticated source-audit record.

        Returns:
            Eight bounded readiness artifacts; missing proof remains explicit.

        Raises:
            EvidenceError: If source integrity, origin, schema or binding checks fail.
            OSError: If a required storage or process operation is unavailable.
        """
        record = self.record_projection(evaluation)
        binding = record.binding
        failure = self.store.load(
            lab,
            candidate=binding.candidate_id,
            contract=binding.contract_sha256,
            producer="failure_lab",
        )
        project = tomllib.loads((self.root / "pyproject.toml").read_text())
        lock = tomllib.loads((self.root / "uv.lock").read_text())
        registry_sources = all(
            item["source"] == {"registry": "https://pypi.org/simple"}
            or (item["name"] == project["project"]["name"] and item["source"] == {"editable": "."})
            for item in lock["package"]
        )
        versions = {item["name"]: item["version"] for item in lock["package"]}
        dependencies = project["project"]["dependencies"]
        pin = "streamlit==1.66.1" in dependencies and versions.get("streamlit") == "1.66.1"
        runtime_matches = version("streamlit") == versions.get("streamlit")
        prohibited = versions.get("guardrails-ai") == "0.10.1"
        if not pin or not runtime_matches or prohibited or not registry_sources:
            raise EvidenceError(
                "Dependency declaration, lock or runtime violates support boundary."
            )

        def load_input(reference: str | None, producer: str) -> dict[str, object] | None:
            if reference is None:
                return None
            return self.store.load(
                reference,
                candidate=binding.candidate_id,
                contract=binding.contract_sha256,
                producer=producer,
            )["payload"]

        execution = load_input(accepted_tests, "accepted_test_execution")
        inspected = load_input(audit, "candidate_audit")
        passed = (
            {
                item["node_id"]
                for item in execution["reports"]
                if item["phase"] == "call" and item["outcome"] == "passed"
            }
            if execution is not None and execution["exit_code"] == 0
            else set()
        )
        tool_checks = (
            (
                "Langfuse",
                "tests/test_langfuse_adapter.py::test_pipeline_record_maps_to_one_fixed_specification",
                "mocked_provider_contract",
                "Local pipeline-to-export mapping.",
            ),
            (
                "LangSmith",
                "tests/test_langsmith_adapter.py::test_fake_transport_submit_and_readback_succeed",
                "mocked_provider_contract",
                "Fake submit and read-back.",
            ),
            (
                "Helicone",
                "tests/test_helicone_contract.py::test_05_routing_spec_composition_and_refusals",
                "deterministic_fixture",
                "Local routing specification and refusal.",
            ),
            (
                "Guardrails",
                "tests/test_guardrails_integration.py::"
                "test_real_guardrails_validator_executes_and_passes_safe_text",
                "deterministic_fixture",
                "Local validator execution.",
            ),
        )
        tool_evidence = [
            {
                "tool": name,
                "node_id": node,
                "scope": scope,
                "class": evidence_class if node in passed else None,
                "reference": accepted_tests if node in passed else None,
                "status": "qualified" if node in passed else "open",
            }
            for name, node, evidence_class, scope in tool_checks
        ]
        traceability = self.reconcile_traceability(
            evaluation,
            workflow=workflow,
            lab=lab,
            accepted_tests=accepted_tests,
            audit=audit,
            gate=gate,
        )
        rows = self.policy_outcomes(evaluation)
        # Frozen authority text is the source, never a caller-authored row.
        requirements = (self.root / "docs/REQUIREMENTS.md").read_text()
        requirement_ids = sorted(set(re.findall(r"^REQ-[A-Z]+-[0-9]{3}", requirements, re.M)))
        authority = {
            str(path.relative_to(self.root)): digest(path.read_bytes())
            for path in sorted((self.root / "docs").rglob("*.md"))
        }
        base = {"candidate": binding.candidate_id, "contract": binding.contract_sha256}
        workflow_record = (
            self.observability(workflow)
            if workflow is not None
            else {"status": "open", "reason": "no authenticated workflow reference supplied"}
        )
        claim_sources = dict(authority)
        for name in ("README.md", "README", "streamlit_app.py"):
            path = self.root / name
            if path.is_file():
                claim_sources[name] = digest(path.read_bytes())
        claim_rows = []
        for name in sorted(claim_sources):
            path = self.root / name
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                lowered = line.lower()
                categories = [
                    word
                    for word in ("deterministic", "live", "deploy", "production")
                    if word in lowered
                ]
                if categories:
                    claim_rows.append(
                        {
                            "source": name,
                            "line": number,
                            "text_digest": digest(line.encode()),
                            "categories": categories,
                            "status": "open",
                            "reason": "source occurrence requires semantic claim review",
                        }
                    )
        semantic_findings = []
        ui_source = self.root / "streamlit_app.py"
        reviewed = {
            "A credential-free, deterministic reviewer console for Module 7.": (
                "qualified",
                "Default local execution only; live lanes need explicit authority.",
            ),
            "The existing controls execute locally and their returned facts are visible.": (
                "qualified" if workflow is not None else "open",
                "Local workflow evidenced; complete UI visibility needs session evidence.",
            ),
            "Pending human review only.": (
                "open",
                "Improvement-cycle review state needs its own behavioral reference.",
            ),
        }
        if ui_source.is_file():
            for number, line in enumerate(ui_source.read_text(encoding="utf-8").splitlines(), 1):
                for claim, (status, scope) in reviewed.items():
                    if claim in line:
                        semantic_findings.append(
                            {
                                "source": "streamlit_app.py",
                                "line": number,
                                "claim": claim,
                                "status": status,
                                "scope": scope,
                                "evidence_reference": (
                                    workflow if "controls execute locally" in claim else None
                                ),
                            }
                        )
        if self.binding() != binding:
            raise EvidenceError("Candidate changed during artifact generation.")
        if gate is not None:
            GateExecutor(self).verify(gate)
        gate_execution = load_input(gate, "gate_executor")
        evaluation_payload = load_input(evaluation, "evaluation_engine")
        evidence_classes = {}
        for source in (evaluation_payload, failure["payload"], execution):
            if source is not None:
                evidence_class = source["class"]
                evidence_classes[evidence_class] = evidence_classes.get(evidence_class, 0) + 1
        execution_reports = execution["reports"] if execution is not None else []
        execution_timing = (
            {
                "started_at_utc": execution["started_at_utc"],
                "finished_at_utc": execution["finished_at_utc"],
                "duration_ns": execution["duration_ns"],
            }
            if execution is not None
            else None
        )
        security_test_reports = [
            item
            for item in execution_reports
            if item["node_id"].startswith(
                (
                    "tests/test_reliability.py::test_safety_",
                    "tests/test_guardrails_integration.py::",
                )
            )
        ]
        security_test_references = (
            [
                item["node_id"]
                for item in security_test_reports
                if item["phase"] == "call" and item["outcome"] == "passed"
            ]
            if execution is not None and execution["exit_code"] == 0
            else []
        )
        return {
            "integrated_acceptance": {
                **base,
                "evaluation": evaluation,
                "lab": lab,
                "accepted_test_reference": accepted_tests,
                "audit_reference": audit,
                "evidence_class_tally": evidence_classes,
                "accepted_test_reports": execution_reports,
                "accepted_test_order": [item["node_id"] for item in execution_reports],
                "accepted_test_timing": execution_timing,
                "observability": workflow_record,
                "lab_reconciliation": self.reconcile_labs(evaluation, lab, workflow=workflow),
                "tool_evidence": tool_evidence,
                "projection": record.projection,
                "canonical_hex": record.canonical_bytes.hex(),
                "digest": record.projection_sha256,
                "status": "open",
                "reliability_risk": {
                    "status": "unresolved_intermittent",
                    "original": "18 passed, 2 errors, 6 warnings in 98.15s",
                    "invariants": [
                        "s19:sink_close_not_idempotent",
                        "s20:release_only_on_resolution",
                    ],
                    "observed_pass": "20 passed, 6 warnings in 127.61s",
                    "cause": "unresolved",
                },
                "qualified_historical": "656 passed, 3 skipped, 1 failed",
            },
            "traceability": {
                **base,
                "authority_digests": authority,
                "requirements": requirement_ids,
                "rows": traceability,
                "status": "open",
                "reason": "individual relationship acceptance requires reconciliation",
            },
            "failure_path": {**base, "reference": lab, "source": failure["payload"]},
            "adversarial_security": {
                **base,
                "reference": evaluation,
                "evidence_class": evaluation_payload["class"],
                "accepted_test_reference": accepted_tests,
                "accepted_test_evidence_class": (
                    execution["class"] if execution is not None else None
                ),
                "test_references": security_test_references,
                "test_reports": security_test_reports,
                "test_status": "qualified" if security_test_references else "open",
                "checks": [row for row in rows if row["scenario"].startswith(("AUTH", "SAFE"))],
            },
            "quality_gate": {
                **base,
                "reference": gate,
                "execution": gate_execution,
                "status": "open" if gate is None else "verified_execution",
            },
            "dependency": {
                **base,
                "declaration_digest": digest((self.root / "pyproject.toml").read_bytes()),
                "lock_digest": digest((self.root / "uv.lock").read_bytes()),
                "streamlit_pin_matches": pin,
                "runtime_matches": runtime_matches,
                "prohibited_present": prohibited,
                "registry_sources_verified": registry_sources,
                "accepted_test_reference": accepted_tests,
                "accepted_test_reports": (
                    [
                        item
                        for item in execution["reports"]
                        if item["node_id"].startswith("tests/test_dependency_contract.py::")
                    ]
                    if execution is not None
                    else []
                ),
            },
            "claim_audit": {
                **base,
                "source_digests": claim_sources,
                "occurrences": claim_rows,
                "semantic_findings": semantic_findings,
                "audit_reference": audit,
                "authenticated_findings": inspected["findings"] if inspected is not None else [],
                "source_absence": [
                    name for name in ("README.md", "README") if name not in claim_sources
                ],
                "qualifications": {
                    "windows_destination_symlink": "platform_unverified",
                    "linux_destination_symlink": "verified_bounded_probe",
                    "loader_source_refusal": "verified_bounded_probe",
                    "arbitrary_accepted_provider_payload_redaction": "not_established",
                },
                "status": "open",
                "reason": "live/deployment claims lack qualifying execution evidence",
            },
            "live_claim_ledger": {
                **base,
                "lanes": [
                    {
                        "provider": name,
                        "status": "open",
                        "live_evidence": None,
                        "contract_source": source,
                        "contract_source_digest": authority[str(Path(source))],
                    }
                    for name, source in (
                        ("Langfuse", "docs/stories/STORY-05-langfuse-integration-boundary.md"),
                        (
                            "LangSmith",
                            "docs/stories/STORY-06-automated-evaluation-regression-benchmarking-langsmith.md",
                        ),
                        ("Helicone", "docs/stories/STORY-07-helicone-gateway-evidence-boundary.md"),
                    )
                ],
            },
        }


class GateExecutor:
    """Execute the fixed formal sequence and record actual process observations.

    Synthetic tests may replace subprocess execution, but such tests must use a
    separate synthetic store and must never serve as the actual gate-of-record.
    """

    def __init__(self, verifier: ReadinessVerifier) -> None:
        self.verifier = verifier
        self._failed_gate: int | None = None
        self._history: list[str] = []
        self._recover()

    def _recover(self) -> str | None:
        """Validate each candidate's history and recover the current obligations."""
        binding = self.verifier.binding()
        pending_by_candidate: dict[str, list[str]] = {}
        failed_gate_by_candidate: dict[str, int] = {}
        latest = None
        for reference, envelope in self.verifier.store.gate_attempts(binding.contract_sha256):
            candidate = envelope["candidate"]
            if type(candidate) is not str or not _is_sha256(candidate):
                raise EvidenceError("Invalid candidate in durable gate history.")
            if candidate == binding.candidate_id:
                latest = reference
            pending = pending_by_candidate.setdefault(candidate, [])
            failed_gate = failed_gate_by_candidate.get(candidate)
            expected = [(0, False), (1, False), (2, False)]
            if failed_gate is not None:
                expected.insert(0, (failed_gate, True))
            try:
                payload = envelope["payload"]
                entries = payload["entries"]
                order = [(entry["gate"], entry["retry"]) for entry in entries]
                codes = [entry["exit_code"] for entry in entries]
                if (
                    not order
                    or any(
                        type(gate) is not int or type(retry) is not bool for gate, retry in order
                    )
                    or any(type(code) is not int for code in codes)
                ):
                    raise EvidenceError("Invalid durable gate entries.")
                if envelope["producer"] == "gate_executor_failure":
                    if order != expected[: len(order)] or any(codes[:-1]) or not codes[-1]:
                        raise EvidenceError("Invalid failed gate order or outcome.")
                    if payload["prior_failures"] != pending:
                        raise EvidenceError("Gate failure chain is inconsistent for its candidate.")
                    pending.append(reference)
                    failed_gate_by_candidate[candidate] = order[-1][0]
                else:
                    if order != expected or any(codes):
                        raise EvidenceError("Invalid completed gate order or required retry.")
                    if payload["resolved_failures"] != pending:
                        raise EvidenceError("Success does not resolve its own candidate history.")
                    pending.clear()
                    failed_gate_by_candidate.pop(candidate, None)
            except (KeyError, TypeError) as error:
                raise EvidenceError("Malformed authenticated gate attempt.") from error
        self._history = pending_by_candidate.get(binding.candidate_id, [])
        self._failed_gate = failed_gate_by_candidate.get(binding.candidate_id)
        return latest

    def _commands(self) -> tuple[tuple[str, ...], ...]:
        executable = str(self.verifier.root / ".venv" / "Scripts" / "python.exe")
        if os.name != "nt":
            executable = str(self.verifier.root / ".venv" / "bin" / "python")
        return (
            (executable, "-m", "ruff", "check", "."),
            (executable, "-m", "pytest", "-m", "not live_vendor"),
            (executable, "-m", "compileall", "src", "tests", "streamlit_app.py"),
        )

    @staticmethod
    def _environment(store_root: Path) -> dict[str, str]:
        # Select operating-system inputs by name. Provider settings and pytest
        # overrides never cross this subprocess boundary, even at collection.
        names = ("PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "SYSTEMDRIVE")
        environment = {name: os.environ[name] for name in names if name in os.environ}
        runtime = store_root / "gate-runtime"
        if runtime.is_symlink() or runtime.is_junction():
            raise EvidenceError("Gate runtime cannot use a linked directory.")
        runtime.mkdir(exist_ok=True)
        runtime = runtime.resolve()
        if runtime.parent != store_root.resolve():
            raise EvidenceError("Gate runtime must remain inside the evidence store.")
        environment.update(
            dict.fromkeys(
                ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP", "TMPDIR"),
                str(runtime),
            )
        )
        environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        return environment

    def execute(self) -> str:
        """Run failed-gate retry if needed, then the entire formal sequence.

        Returns:
            Reference to the authenticated actual observation record. Failed
            attempts are retained and raise EvidenceError before later gates.


        Raises:
            EvidenceError: If source integrity, origin, schema or binding checks fail.
            OSError: If a required storage or process operation is unavailable.
        """
        binding = self.verifier.binding()
        commands = self._commands()
        self._recover()
        environment = self._environment(self.verifier.store.root)
        entries = []
        indices = list(range(3))
        if self._failed_gate is not None:
            indices.insert(0, self._failed_gate)
        for position, index in enumerate(indices):
            start = time.time_ns()
            failure_kind = None
            try:
                completed = subprocess.run(
                    commands[index],
                    cwd=self.verifier.root,
                    env=environment,
                    capture_output=True,
                    timeout=_GATE_TIMEOUT_SECONDS,
                    check=False,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
            except subprocess.TimeoutExpired:
                failure_kind = "subprocess_timeout"
                completed = subprocess.CompletedProcess(commands[index], -1, b"", b"")
            except OSError:
                failure_kind = "subprocess_launch_failed"
                completed = subprocess.CompletedProcess(commands[index], -1, b"", b"")
            end = time.time_ns()
            output = completed.stdout + completed.stderr
            entry = {
                "gate": index,
                "command": list(commands[index]),
                "started_ns": start,
                "ended_ns": end,
                "exit_code": completed.returncode,
                "output_digest": digest(output),
                "retry": self._failed_gate is not None and position == 0,
                "failure_kind": failure_kind,
            }
            # Failed gates retain only bounded sanitized test identifiers from
            # the untrusted output.  Recognized credential material is
            # redacted before retention.  Raw traceback and failure-message
            # content are not retained.  Arbitrary unknown credential formats
            # are not guaranteed to be detected.  No extra execution occurs.
            if completed.returncode and failure_kind is None:
                diagnostics = _gate_diagnostics(output.decode(errors="replace"))
                if diagnostics:
                    entry["diagnostics"] = diagnostics
            entries.append(entry)
            # Subprocess diagnostics are untrusted and can contain test canaries.
            # Keep only bounded counts plus integrity, never arbitrary raw text.
            counts = re.findall(
                r"\b([0-9]{1,8}) (passed|failed|skipped|errors?|warnings?|xfailed|xpassed)\b",
                output.decode(errors="replace"),
            )[-8:]
            print(
                {
                    "gate": index,
                    "exit_code": completed.returncode,
                    "output_digest": digest(output),
                    "counts": counts,
                },
                flush=True,
            )
            if completed.returncode:
                reference = self.verifier.store._publish(
                    "gate_executor_failure",
                    binding.candidate_id,
                    binding.contract_sha256,
                    {"entries": entries, "prior_failures": list(self._history)},
                    _authority=_RECORDING_AUTHORITY,
                )
                self._history.append(reference)
                self._failed_gate = index
                raise EvidenceError("Formal gate failed; immutable failure reference: " + reference)
        if self.verifier.binding() != binding:
            raise EvidenceError("Candidate changed during formal execution; gates are stale.")
        reference = self.verifier.store._publish(
            "gate_executor",
            binding.candidate_id,
            binding.contract_sha256,
            {"entries": entries, "resolved_failures": list(self._history)},
            _authority=_RECORDING_AUTHORITY,
        )
        self._failed_gate = None
        self.verify(reference)
        return reference

    def verify(self, reference: str) -> None:
        """Reload actual execution evidence and reject altered or stale gates.

        Args:
            reference: Content-addressed reference to reload and authenticate.

        Returns:
            None after gate integrity, results, order and freshness are validated.

        Raises:
            EvidenceError: If source integrity, origin, schema or binding checks fail.
            OSError: If a required storage or process operation is unavailable.
        """
        binding = self.verifier.binding()
        envelope = self.verifier.store.load(
            reference,
            candidate=binding.candidate_id,
            contract=binding.contract_sha256,
            producer="gate_executor",
        )
        latest = self._recover()
        if self._history or latest != reference:
            raise EvidenceError("Gate success is superseded by later authenticated history.")
        payload = envelope["payload"]
        entries = payload["entries"]
        formal = [entry for entry in entries if not entry["retry"]]
        if [entry["gate"] for entry in formal] != [0, 1, 2]:
            raise EvidenceError("Missing or reordered actual gates.")
        commands = self._commands()
        previous_end = 0
        for entry in entries:
            if (
                entry["exit_code"] != 0
                or entry["command"] != list(commands[entry["gate"]])
                or entry["started_ns"] < previous_end
                or entry["ended_ns"] < entry["started_ns"]
                or not _is_sha256(entry["output_digest"])
            ):
                raise EvidenceError("Contradictory actual gate evidence.")
            previous_end = entry["ended_ns"]
        for failed in payload["resolved_failures"]:
            history = self.verifier.store.load_failure(failed)
            if not any(row["exit_code"] != 0 for row in history["payload"]["entries"]):
                raise EvidenceError("Fabricated failure history.")
        if payload["resolved_failures"]:
            latest = self.verifier.store.load_failure(payload["resolved_failures"][-1])
            failed_index = latest["payload"]["entries"][-1]["gate"]
            retries = [entry for entry in entries if entry["retry"]]
            if len(retries) != 1 or retries[0]["gate"] != failed_index:
                raise EvidenceError("Required failed-gate rerun is missing.")


def record_projection(*_args: object, **_kwargs: object) -> ProjectionRecord:
    """Reject the removed caller-mapping authority; use ReadinessVerifier.

    Args:
        *_args: Obsolete positional inputs; never accepted evidence.
        **_kwargs: Obsolete keyword inputs; never producer authority.

    Returns:
        Producer-derived projection record; the obsolete module-level API always raises.

    Raises:
        EvidenceError: If source integrity, origin, schema or binding checks fail.
        OSError: If a required storage or process operation is unavailable.
    """
    raise EvidenceError("Caller mappings cannot establish accepted run provenance.")


def verify_projection(*_args: object, **_kwargs: object) -> None:
    """Reject self-authentication; a verifier must reload the producer record.

    Args:
        *_args: Obsolete positional inputs; always refused.
        **_kwargs: Obsolete keyword inputs; always refused.

    Returns:
        None after successful comparison; the obsolete module-level API always raises.

    Raises:
        EvidenceError: If source integrity, origin, schema or binding checks fail.
        OSError: If a required storage or process operation is unavailable.
    """
    raise EvidenceError("Verification requires an authoritative store and current candidate.")
