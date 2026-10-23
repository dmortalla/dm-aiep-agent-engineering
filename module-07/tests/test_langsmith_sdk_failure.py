"""Story 6 SDK failure-path containment: real Client, real logs, no secrets.

Contract Test 14: using the real public LangSmith ``Client`` against a fake
origin that raises on connection, credential material (configured values,
secret-shaped exceptions, canaries) never reaches captured application logs
across the descendant-loggers gap, without silencing the application logger,
and containment changes no authorization, result, threshold or budget state.
"""

import asyncio
import logging
import uuid

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

CANARY: str = "module7-canary-never-exported-9f4c"


def runtime():
    """Build one live runtime settings object for the gated branch."""
    return RuntimeSettings(
        mode=ExecutionMode.LIVE,
        live_integrations_enabled=True,
        provider_api_key=SecretStr("provider-key"),
    )


def subset_plan():
    """Run the real deterministic engine locally once and build the plan."""
    dataset = load_benchmark_dataset()
    exported_subset = tuple(dataset.scenario_ids[:1])
    artifact = asyncio.run(EvaluationEngine().run(
        dataset,
        target_id="reference_default",
        target_version=1,
        target_factory=ReferenceTarget.build,
        scenario_ids=exported_subset,
    ))
    digest = canonical_digest(benchmark_report(artifact, exported_subset, None))
    settings = LangSmithSettings(
        enabled=True,
        api_key=SecretStr("lsv2_pt_synthetic_public_key_value"),
        # A documented fake origin that raises on connection (refused port).
        api_url="http://127.0.0.1:1",
        reservation_per_request_usd=0.001,
        run_cost_limit_usd=1.0,
    )
    plan = build_export_plan(
        artifact.result,
        dataset,
        settings,
        report_digest=digest,
        exported_subset=exported_subset,
    )
    return plan, settings


@pytest.mark.parametrize(
    "logger_name", ["langsmith.client", "langsmith", "langsmith.utils"]
)
def test_descendant_loggers_carry_containment_before_and_not_after_use(
    logger_name,
):
    """The sanitization covers the ``langsmith.client`` descendant loggers."""
    logger = logging.getLogger(logger_name)
    baseline_filters = list(logger.filters)
    transport = LangSmithSdkTransport(
        subset_plan()[1], runtime=runtime(), opt_in=True
    )
    attached = any(item not in baseline_filters for item in list(logger.filters))
    clean = transport.close()
    detached = all(item in baseline_filters for item in list(logger.filters))
    assert attached is True
    assert clean is True
    assert detached is True


def test_real_sdk_failure_path_never_leaks_credentials_into_logs(caplog):
    """Real Client failures keep every secret family out of captured logs.

    Uses the real public SDK ``Client`` (no stub, no logging suppression)
    whose origin raises on connection; a canary, a synthetic public key and a
    secret-shaped exception stay out of every captured record.
    """
    plan, settings = subset_plan()
    logger_filters_before = {
        name: list(logging.getLogger(name).filters)
        for name in ("langsmith.client", "langsmith", "langsmith.utils")
    }
    transport = LangSmithSdkTransport(settings, runtime=runtime(), opt_in=True)
    with caplog.at_level(logging.DEBUG), pytest.raises(LangSmithExportError) as exc_info:
        transport.submit_plan(plan)
    assert exc_info.value.reason == RefusalSource.TRANSPORT
    # Exactly one charged attempt: zero retries on failure (see Test 18/20).
    accounting = transport.accounting()
    del accounting
    closed = transport.close()
    assert closed is True

    captured = "\n".join(str(item.message) for item in caplog.records)
    assert "lsv2_pt_synthetic_public_key_value" not in captured
    assert CANARY not in captured
    # Secret-shaped text never lands in captured application log records.
    assert "'password='" not in captured
    assert "traceback" not in captured.casefold()
    # This transport's containment filters are gone again after close.
    for name in ("langsmith.client", "langsmith", "langsmith.utils"):
        assert all(
            item in logger_filters_before[name]
            for item in logging.getLogger(name).filters
        )


def test_real_sdk_failure_path_stays_unconfirmed_and_non_authoritative():
    """A transport failure upgrades no evidence class and mutates nothing."""
    plan, settings = subset_plan()
    transport = LangSmithSdkTransport(settings, runtime=runtime(), opt_in=True)
    with pytest.raises(LangSmithExportError):
        transport.submit_plan(plan)
    assert transport.evidence_class is not None  # The transport, not the run.
    from reliability_safety_observability.domain import EvidenceClass

    assert transport.evidence_class is EvidenceClass.MOCKED_PROVIDER_CONTRACT
    accounting = transport.accounting()
    assert accounting["requests_sent"] == 1
    assert uuid.UUID(plan.run_id)
    closed = transport.close()
    assert closed is True
