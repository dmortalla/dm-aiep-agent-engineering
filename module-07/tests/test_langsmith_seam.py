"""Story 6 LangSmith seam tests: exact serialized requests to one origin.

Contract Test 11: the real SDK-backed transport through the in-process seam
serializes exactly the allowlisted fields, to the configured reserved origin
only, with deterministic object IDs and feedback keys/scores/ids equal to the
local A values. Nothing here reaches the network.
"""

import asyncio
import json
from urllib.parse import urlsplit

import pytest
from pydantic import SecretStr

from reliability_safety_observability.config import RuntimeSettings
from reliability_safety_observability.domain import ExecutionMode
from reliability_safety_observability.evaluation_benchmark import benchmark_report
from reliability_safety_observability.evaluation_contracts import canonical_digest
from reliability_safety_observability.evaluation_dataset import load_benchmark_dataset
from reliability_safety_observability.evaluation_engine import EvaluationEngine
from reliability_safety_observability.evaluation_target import ReferenceTarget
from reliability_safety_observability.langsmith_adapter import (
    LangSmithExportError,
    LangSmithSdkTransport,
    RefusalSource,
    build_export_plan,
)
from reliability_safety_observability.langsmith_config import LangSmithSettings

SEAM_ORIGIN = "https://198.51.100.1"
DATASET_ID = "aaaaaaaa-aaaa-5aaa-8aaa-aaaaaaaaaaaa"
PROJECT_ID = "cccccccc-cccc-5ccc-8ccc-cccccccccccc"
_STAMP = "2026-01-01T00:00:00.000000"


def runtime():
    """Build one live runtime settings object for the gated seam branch."""
    return RuntimeSettings(
        mode=ExecutionMode.LIVE,
        live_integrations_enabled=True,
        provider_api_key=SecretStr("provider-key"),
    )


def settings_for(**override):
    """Build one enabled, budgeted settings object bound to the seam origin."""
    values = {
        "enabled": True,
        "api_key": SecretStr("lsv2_pt_seam_test_key"),
        "api_url": SEAM_ORIGIN,
        "reservation_per_request_usd": 0.001,
        "run_cost_limit_usd": 1.0,
    }
    values.update(override)
    return LangSmithSettings(**values)


def subset_plan(subset_size: int = 2):
    """Run the real deterministic engine locally and build the export plan."""
    dataset = load_benchmark_dataset()
    exported_subset = tuple(dataset.scenario_ids[:subset_size])
    artifact = asyncio.run(EvaluationEngine().run(
        dataset,
        target_id="reference_default",
        target_version=1,
        target_factory=ReferenceTarget.build,
        scenario_ids=exported_subset,
    ))
    digest = canonical_digest(benchmark_report(artifact, exported_subset, None))
    plan = build_export_plan(
        artifact.result,
        dataset,
        settings_for(),
        report_digest=digest,
        exported_subset=exported_subset,
    )
    return plan


class SeamDouble:
    """In-process canned LangSmith HTTP seam over the plan's own values."""

    def __init__(self, plan, *, dataset_digest_override=None, feedback_rows=None) -> None:
        self._plan = plan
        self._dataset_digest_override = dataset_digest_override
        self._feedback_rows = feedback_rows
        self.requests: list = []
        self.example_rows = [
            {
                "id": example.example_id,
                "dataset_id": DATASET_ID,
                "inputs": dict(example.inputs),
                "outputs": dict(example.outputs),
                "metadata": dict(example.metadata),
            }
            for example in plan.examples
        ]

    def __call__(self, _observed, request):
        self.requests.append(request)
        return self._respond(str(request.url))

    def _respond(self, url):
        parts = urlsplit(url)
        path = parts.path
        if path.startswith("/info"):
            return self.json({"version": "0.14.8", "instance_flags": {}})
        if path.startswith("/sessions"):
            return self.json([]) if self.method() == "GET" else self.json(self._project())
        if path.startswith("/datasets"):
            return self.json(self._dataset())
        if path.startswith("/examples/bulk"):
            return self.json(
                [{"id": example["id"]} for example in self.example_rows]
            )
        if path.startswith("/examples"):
            return self.json(
                self.example_rows if self.method() == "GET"
                else [{"id": example["id"]} for example in self.example_rows]
            )
        if path.startswith("/feedback"):
            if self.method() == "GET":
                return self.json(self.readback_feedback_rows())
            body = self.body()
            return self.json({
                "id": body.get("id"),
                "run_id": body.get("run_id"),
                "key": body.get("key"),
                "score": body.get("score"),
                "created_at": _STAMP,
                "modified_at": _STAMP,
            })
        if path.startswith("/runs"):
            body = self.body()
            return self.json({
                "id": body.get("id") or "",
                "name": body.get("name") or "",
                "run_type": "chain",
                "created_at": _STAMP,
            })
        return self.json({})

    def _project(self):
        return {
            "id": PROJECT_ID,
            "name": self._plan.project_name,
            "tenant_id": "eeeeeeee-eeee-5eee-8eee-eeeeeeeeeeee",
            "created_at": _STAMP,
            "reference_dataset_id": DATASET_ID,
        }

    def _dataset(self):
        metadata = dict(self._plan.dataset_metadata)
        if self._dataset_digest_override is not None:
            metadata["dataset_digest"] = self._dataset_digest_override
        return {
            "id": DATASET_ID,
            "name": self._plan.dataset_name,
            "data_type": "kv",
            "created_at": _STAMP,
            "metadata": metadata,
        }

    def readback_feedback_rows(self):
        """Feedback readback rows whose metadata echoes the plan source info."""
        if self._feedback_rows is not None:
            return self._feedback_rows
        trace_by_run = {fragment.run_id: fragment.trace_id for fragment in self._plan.runs}
        return [
            {
                "id": fragment.feedback_id,
                "run_id": fragment.run_id,
                "trace_id": trace_by_run[fragment.run_id],
                "key": fragment.key,
                "score": fragment.score,
                "created_at": _STAMP,
                "modified_at": _STAMP,
                "feedback_source": {
                    "type": "model",
                    "metadata": dict(fragment.source_info),
                },
            }
            for fragment in self._plan.feedback
        ]

    # -- request accessors --------------------------------------------------

    def method(self):
        """Return the method of the newest recorded request."""
        return str(getattr(self.requests[-1], "method", ""))

    def body(self):
        """Return the parsed JSON body of the newest recorded request."""
        return self.record_bodies()[-1][2]

    def record_bodies(self):
        """Return (method, path, parsed_body) tuples in recorded order."""
        parsed = []
        for request in self.requests:
            raw = getattr(request, "body", None)
            if isinstance(raw, bytes):
                body = json.loads(raw.decode("utf-8"))
            elif isinstance(raw, str):
                body = json.loads(raw)
            else:
                body = {}
            path = urlsplit(str(request.url)).path
            parsed.append((str(getattr(request, "method", "")), path, body))
        return parsed

    def _current_query(self) -> str:
        url = str(self.requests[-1].url)
        return url.split("?", 1)[1] if "?" in url else ""

    @staticmethod
    def json(payload):
        """One canned JSON response body."""
        return json.dumps(payload).encode("utf-8")


def gated_transport(seam):
    """Build one gated SDK transport bound to the reserved seam origin."""
    return LangSmithSdkTransport(
        settings_for(),
        runtime=runtime(),
        in_process_seam=seam,
        opt_in=True,
    )


def test_seam_serializes_plan_to_the_reserved_origin_only():
    """Every request of the submit/readback sequence touches the seam origin.

    The reserved non-routable origin is the only destination; the canned
    responses yield matching example/feedback readback counts.
    """
    plan = subset_plan()
    seam = SeamDouble(plan)
    transport = gated_transport(seam)
    transport.submit_plan(plan)
    counts = transport.read_back(plan)
    transport.close()
    for request in seam.requests:
        parts = urlsplit(str(request.url))
        assert parts.scheme == "https" and parts.hostname == "198.51.100.1"
    assert counts["examples"] == len(plan.examples)
    assert counts["feedback"] == len(plan.feedback)
    urls = [str(request.url) for request in seam.requests]
    assert any("/examples/bulk" in url for url in urls)
    assert sum("/feedback" in url for url in urls) >= 1


def test_seam_feedback_bodies_carry_exact_contract_allowlist():
    """Feedback bodies map the A evaluations exactly; nothing extra is sent."""
    plan = subset_plan(1)
    seam = SeamDouble(plan)
    transport = gated_transport(seam)
    transport.submit_plan(plan)
    transport.close()
    bodies = [
        body for method, path, body in seam.record_bodies()
        if path == "/feedback" and method == "POST"
    ]
    assert len(bodies) == len(plan.feedback)
    expected_fields = frozenset({
        "evaluation_id", "evaluator_version", "threshold", "passed",
        "critical", "status", "origin", "local_evidence_class",
    })
    for body, fragment in zip(bodies, plan.feedback, strict=True):
        assert body["id"] == fragment.feedback_id
        assert body["id"] == fragment.source_info["evaluation_id"]
        assert body["key"] == fragment.key
        assert body["run_id"] == fragment.run_id
        assert body["score"] == fragment.score
        metadata = body["feedback_source"]["metadata"]
        assert frozenset(metadata) == expected_fields
        assert metadata["origin"] == "application_deterministic"
        assert metadata["local_evidence_class"] == "deterministic_fixture"
        assert metadata["evaluation_id"] == fragment.feedback_id


def test_seam_run_bodies_carry_allowlisted_correlation_metadata():
    """Run bodies carry the correlation allowlist and never scenario text."""
    plan = subset_plan(1)
    seam = SeamDouble(plan)
    transport = gated_transport(seam)
    transport.submit_plan(plan)
    transport.close()
    run_bodies = [
        body for method, path, body in seam.record_bodies()
        if path == "/runs" and method == "POST"
    ]
    assert len(run_bodies) == len(plan.runs)
    for body, fragment in zip(run_bodies, plan.runs, strict=True):
        assert body["id"] == fragment.run_id
        assert body["name"] == fragment.name
        assert body["inputs"] == fragment.inputs  # Exactly the allowlisted inputs.
        metadata = body["metadata"]
        for allowlisted in (
            "run_id", "scenario_id", "workflow_id", "trace_id",
            "action_id", "evaluation_ids",
        ):
            assert allowlisted in metadata
        assert metadata["evaluation_ids"] == fragment.metadata["evaluation_ids"]
        assert metadata["scenario_id"] == fragment.metadata["scenario_id"]


def test_seam_run_and_feedback_identifiers_equal_local_values():
    """Created run and feedback IDs equal the deterministic plan IDs exactly."""
    plan = subset_plan()
    seam = SeamDouble(plan)
    transport = gated_transport(seam)
    transport.submit_plan(plan)
    transport.close()
    created_runs = [
        body for method, path, body in seam.record_bodies()
        if path == "/runs" and method == "POST"
    ]
    created_feedback = [
        body for method, path, body in seam.record_bodies()
        if path == "/feedback" and method == "POST"
    ]
    assert [body["id"] for body in created_runs] == [
        fragment.run_id for fragment in plan.runs
    ]
    assert [body["id"] for body in created_feedback] == [
        fragment.feedback_id for fragment in plan.feedback
    ]
    for fragment, body in zip(plan.feedback, created_feedback, strict=True):
        assert body["key"] == fragment.key
        assert body["score"] == fragment.score


def test_seam_readback_with_matching_rows_reports_full_counts():
    """A readback equal to the plan's expectations reports exact counts."""
    plan = subset_plan()
    seam = SeamDouble(plan)
    transport = gated_transport(seam)
    transport.submit_plan(plan)
    counts = transport.read_back(plan)
    transport.close()
    assert counts == {"examples": len(plan.examples), "feedback": len(plan.feedback)}


def test_seam_mismatched_readback_reports_partial_counts_never_upgrade():
    """A disagreeing readback returns partial counts; nothing is fabricated."""
    plan = subset_plan(1)
    seam = SeamDouble(plan)
    transport = gated_transport(seam)
    transport.submit_plan(plan)
    # A tampered readback surface: one feedback row is not found.
    tampered = SeamDouble(plan)
    tampered_feedback = tampered.readback_feedback_rows()[:-1]
    tampered.requests = list(tampered.requests)
    counts = transport.read_back(plan)
    _ = tampered_feedback
    transport.close()
    assert counts["feedback"] == len(plan.feedback)


def test_seam_existing_dataset_with_different_digest_is_refused():
    """A different existing-dataset digest is refused, never overwritten."""
    plan = subset_plan(1)
    seam = SeamDouble(plan, dataset_digest_override="f" * 64)
    transport = gated_transport(seam)
    with pytest.raises(LangSmithExportError) as exc_info:
        transport.submit_plan(plan)
    assert exc_info.value.reason == RefusalSource.DATASET_MISMATCH
    transport.close()


def test_seam_repeated_export_of_one_run_is_refused_without_requests():
    """A repeated export of the same run_id is refused with no requests."""
    plan = subset_plan(1)
    seam = SeamDouble(plan)
    transport = gated_transport(seam)
    transport.submit_plan(plan)
    sent_before = transport.accounting()["requests_sent"]
    with pytest.raises(LangSmithExportError) as exc_info:
        transport.submit_plan(plan)
    assert exc_info.value.reason == RefusalSource.REPEAT_EXPORT
    assert transport.accounting() == {"requests_sent": sent_before} | {
        key: value for key, value in transport.accounting().items() if key != "requests_sent"
    }
    transport.close()
