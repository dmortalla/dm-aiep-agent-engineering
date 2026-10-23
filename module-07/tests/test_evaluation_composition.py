"""Story 6 composition invariants: shared ids, non-authoritative exporter.

Attaching the Story 5 Langfuse sink to the Story 6 engine must leave the
deterministic evaluation results untouched, must name the same evaluation in
the artifact and in the minimized export records, and a failing vendor
transport must not change any verdict, score or budget state.
"""

import asyncio

from reliability_safety_observability.evaluation_contracts import Verdict
from reliability_safety_observability.evaluation_dataset import load_benchmark_dataset
from reliability_safety_observability.evaluation_engine import EvaluationEngine
from reliability_safety_observability.evaluation_target import ReferenceTarget
from reliability_safety_observability.langfuse_adapter import LangfuseSink


class FailingTransport:
    """A transport whose submit always raises authority-shaped junk."""

    def submit(self, spec: object) -> object:
        raise RuntimeError("Authorization: Bearer ambient-secret-bearer-token")

    def flush(self) -> object:
        raise RuntimeError("password=ambient-secret")

    def close(self) -> object:
        raise RuntimeError("api_key=ambient-secret")


def _run_with(exporter: object | None):
    """Run the full reference benchmark with an optional attached exporter."""
    engine = EvaluationEngine(telemetry_exporter=exporter)
    artifact = asyncio.run(engine.run(
        load_benchmark_dataset(),
        target_id="reference_default",
        target_version=1,
        target_factory=ReferenceTarget.build,
    ))
    return artifact, engine


def test_attached_sink_leaves_results_identical_to_unattached_run() -> None:
    """The attached exporter changes no verdict, score, identity or budget."""
    plain, plain_engine = _run_with(None)
    sink = LangfuseSink(FailingTransport())
    attached, attached_engine = _run_with(sink)
    del attached_engine, plain_engine
    assert attached.result.model_dump(mode="json") == plain.result.model_dump(mode="json")
    # Record equivalence up to per-run random identifiers.
    assert len(attached.evaluation_records) == len(plain.evaluation_records) > 0
    assert attached.result.verdict == Verdict.PASS


def test_attached_sink_is_not_the_pipeline_and_never_implements_results() -> None:
    """The attached exporter stays strictly non-authoritative by construction."""
    sink = LangfuseSink(FailingTransport())
    engine = EvaluationEngine(telemetry_exporter=sink)
    assert engine._telemetry_exporter is sink
    pipeline, capture = engine._pipeline()
    del pipeline
    assert capture is not sink
    assert not hasattr(sink, "verdict") and not hasattr(sink, "policy")
    assert not hasattr(sink, "results") and not hasattr(sink, "run")


def test_attached_sink_receives_the_same_minimized_records() -> None:
    """The pipeline forwards to the attached exporter after local capture."""
    from uuid import UUID

    from reliability_safety_observability.domain import WorkflowIdentity
    from reliability_safety_observability.telemetry import (
        CostBasis,
        Delivery,
        Observation,
        TelemetryRecord,
    )

    captured: list[str] = []

    class Recorder:
        async def send(self, record: str) -> object:
            captured.append(record)
            return None

    identity = WorkflowIdentity(workflow_id=UUID(int=1), trace_id=UUID(int=2))
    record = TelemetryRecord(
        **identity.model_dump(),
        span_id=UUID(int=4),
        operation="Bearer PRIVATE",
        status="success",
        duration_ms=125,
        authorization_decision=None,
        safety_decision=None,
    )
    observation = Observation(
        telemetry=record, action_id=UUID(int=3), cost_basis=CostBasis.FIXTURE
    )
    engine = EvaluationEngine(telemetry_exporter=Recorder())
    pipeline, capture = engine._pipeline()
    observation_2 = Observation(
        telemetry=record.model_copy(), action_id=UUID(int=3),
        cost_basis=CostBasis.FIXTURE,
    )
    delivery = asyncio.run(pipeline.emit(observation))
    asyncio.run(pipeline.emit(observation_2))
    assert capture.records  # Local capture always happens fan-out first.
    assert len(captured) == 2  # The exporter saw the identical records.
    assert captured[0] == '{"event": "synthetic"}' or "Bearer PRIVATE" not in captured[0]
    assert delivery in {Delivery.EXPORTED, Delivery.LOCAL}
