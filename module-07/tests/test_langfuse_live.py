"""Story 5 opt-in live Langfuse verification (group 18); skipped by default.

Runs only when ``MODULE7_LANGFUSE_LIVE_VERIFICATION=1`` and complete live
configuration are supplied externally, and only after the human has authorized
writing one synthetic fixture trace to their Langfuse project. Ordinary CI never
sets these variables. Configuration is snapshotted at import because the shared
hermetic fixture clears ``MODULE7_*`` variables before each test.
"""

import asyncio
import os

import pytest
from pydantic import SecretStr

from reliability_safety_observability.config import RuntimeSettings
from reliability_safety_observability.domain import EvidenceClass, ExecutionMode
from reliability_safety_observability.langfuse_adapter import LiveOutcome, run_live_verification
from reliability_safety_observability.langfuse_config import LangfuseSettings

_ENV = {key: value for key, value in os.environ.items() if key.startswith("MODULE7_")}
LIVE_OPT_IN = _ENV.get("MODULE7_LANGFUSE_LIVE_VERIFICATION") == "1"
SKIP_REASON = (
    "Live Langfuse verification is opt-in: set MODULE7_LANGFUSE_LIVE_VERIFICATION=1 with "
    "explicit live MODULE7_* configuration after authorizing an external write."
)


@pytest.mark.live_vendor
@pytest.mark.skipif(not LIVE_OPT_IN, reason=SKIP_REASON)
def test_live_langfuse_export_is_confirmed_by_bounded_readback() -> None:
    """Export one synthetic trace and require confirmed read-back for live_vendor."""
    api_key = _ENV.get("MODULE7_PROVIDER_API_KEY")
    runtime = RuntimeSettings(
        mode=ExecutionMode(_ENV.get("MODULE7_MODE", "deterministic")),
        live_integrations_enabled=_ENV.get("MODULE7_LIVE_INTEGRATIONS_ENABLED") == "true",
        provider_api_key=SecretStr(api_key) if api_key else None,
    )
    settings = LangfuseSettings(
        enabled=_ENV.get("MODULE7_LANGFUSE_ENABLED") == "true",
        public_key=_ENV.get("MODULE7_LANGFUSE_PUBLIC_KEY"),
        secret_key=_ENV.get("MODULE7_LANGFUSE_SECRET_KEY"),
        host=_ENV.get("MODULE7_LANGFUSE_HOST"),
    )

    result = asyncio.run(run_live_verification(runtime, settings, opt_in=LIVE_OPT_IN))

    assert result.outcome is LiveOutcome.CONFIRMED, result.outcome.value
    assert result.evidence_class is EvidenceClass.LIVE_VENDOR
    assert result.confirmed_observations == result.expected_observations
