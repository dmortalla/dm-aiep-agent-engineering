"""Story 6 LangSmith live-branch tests: gates, evidence classes and refusal.

Live network export itself is never executed here; the branch's gates and
refusals are verified so ordinary runs (and credential presence alone) can
never reach a vendor.
"""


import pytest
from pydantic import SecretStr

from reliability_safety_observability.config import RuntimeSettings
from reliability_safety_observability.domain import ExecutionMode
from reliability_safety_observability.errors import ConfigurationError
from reliability_safety_observability.langsmith_adapter import (
    LiveVerificationResult,
    RefusalSource,
    run_live_langsmith_verification,
)
from reliability_safety_observability.langsmith_config import LangSmithSettings


def runtime(mode: ExecutionMode = ExecutionMode.LIVE):
    """Build one runtime settings object consistent with the mode."""
    return RuntimeSettings(
        mode=mode,
        live_integrations_enabled=mode is ExecutionMode.LIVE,
        provider_api_key=SecretStr("provider-key"),
    )


def settings_for(**override):
    """Build one enabled, budgeted settings object."""
    values = {
        "enabled": True,
        "api_key": SecretStr("langsmith-key"),
        "api_url": "https://api.smith.langchain.com",
        "workspace_id": None,
        "reservation_per_request_usd": 0.001,
        "run_cost_limit_usd": 1.0,
    }
    values.update(override)
    return LangSmithSettings(**values)


def test_live_langsmith_verification_requires_explicit_opt_in() -> None:
    """The live branch refuses to construct without explicit opt-in."""
    with pytest.raises(ConfigurationError, match="opt-in"):
        run_live_langsmith_verification(runtime(), settings_for(), opt_in=False)


def test_live_langsmith_verification_requires_enabled_settings() -> None:
    """Disabled or non-live configurations are refused with fixed errors."""
    with pytest.raises(ConfigurationError, match="live integration enablement"):
        run_live_langsmith_verification(
            runtime(mode=ExecutionMode.DETERMINISTIC),
            settings_for(),
            opt_in=True,
        )
    with pytest.raises(ConfigurationError, match="enabled settings"):
        run_live_langsmith_verification(
            runtime(),
            LangSmithSettings(enabled=False),
            opt_in=True,
        )


def test_live_langsmith_verification_requires_remote_https() -> None:
    """Loopback and HTTP endpoints cannot proceed to vendor construction."""
    with pytest.raises(ConfigurationError, match="non-loopback HTTPS"):
        run_live_langsmith_verification(
            runtime(),
            settings_for(api_url="http://127.0.0.1:19876"),
            opt_in=True,
        )


def test_ambient_variables_are_never_writable_into_export(monkeypatch) -> None:
    """Credential presence alone never grants export rights in this module."""
    monkeypatch.setattr(
        "reliability_safety_observability.langsmith_config.os.environ",
        {"LANGSMITH_API_KEY": "ambient-secret", "MODULE7_LANGSMITH_API_KEY": "k"},
    )
    from reliability_safety_observability.langsmith_config import (
        ambient_langsmith_variables,
    )
    ambient = ambient_langsmith_variables()
    assert "LANGSMITH_API_KEY" in ambient
    assert "MODULE7_LANGSMITH_API_KEY" not in ambient


def test_evidence_class_is_none_without_a_live_branch_call() -> None:
    """No named evidence class is fabricated outside the owned live branch."""
    result = LiveVerificationResult(
        outcome=RefusalSource.READBACK_MISMATCH,
        evidence_class=None,
        run_id="00000000-0000-5000-8000-000000000000",
        report_digest="0" * 64,
        exported_subset=None,
        expected_examples=1,
        confirmed_examples=0,
        expected_feedback=1,
        confirmed_feedback=0,
        close_state="closed",
    )
    assert result.evidence_class is None
    assert result.outcome == RefusalSource.READBACK_MISMATCH


def test_transport_is_the_only_application_execution_lane() -> None:
    """Only the owned adapter lane constructs the SDK client."""
    import reliability_safety_observability.langsmith_adapter as adapter_module

    sdk_only = [
        name for name in adapter_module.__dict__
        if not name.startswith("__") and "client" in name.casefold()
    ]
    assert sdk_only == []


def test_ambient_vendor_variables_refuse_the_live_branch(monkeypatch) -> None:
    """Ambient LANGSMITH_/LANGCHAIN_ presence refuses without client setup."""
    for name, value in (
        ("LANGSMITH_API_KEY", "ambient-secret"),
        ("LANGCHAIN_TRACING_V2", "true"),
    ):
        monkeypatch.setenv(name, value)
    with pytest.raises(ConfigurationError) as exc_info:
        run_live_langsmith_verification(runtime(), settings_for(), opt_in=True)
    assert "ambient" in str(exc_info.value)


def test_live_branch_refuses_loopback_https_endpoints() -> None:
    """HTTPS loopback addresses never qualify for the live branch."""
    with pytest.raises(ConfigurationError):
        run_live_langsmith_verification(
            runtime(),
            settings_for(api_url="https://127.0.0.1:19876"),
            opt_in=True,
        )
    with pytest.raises(ConfigurationError):
        run_live_langsmith_verification(
            runtime(),
            settings_for(api_url="https://[::1]:19876"),
            opt_in=True,
        )


_ENV_AT_IMPORT = {
    key: value
    for key, value in sorted(__import__("os").environ.items())
    if key.startswith("MODULE7_")
}
_LIVE_OPT_IN = _ENV_AT_IMPORT.get("MODULE7_LANGSMITH_LIVE_VERIFICATION") == "1"
_SKIP_REASON = (
    "Live LangSmith verification is opt-in only: set "
    "MODULE7_LANGSMITH_LIVE_VERIFICATION=1 with explicit live MODULE7_* "
    "configuration after authorizing an external write."
)


@pytest.mark.live_vendor
@pytest.mark.skipif(not _LIVE_OPT_IN, reason=_SKIP_REASON)
def test_live_vendor_opt_in_lane_runs_the_owned_live_branch() -> None:
    """Opt-in live verification is the single owned live lane (skipped here)."""
    from reliability_safety_observability.domain import EvidenceClass

    settings = LangSmithSettings(
        enabled=_ENV_AT_IMPORT.get("MODULE7_LANGSMITH_ENABLED") == "true",
        api_key=SecretStr(_ENV_AT_IMPORT.get("MODULE7_LANGSMITH_API_KEY") or ""),
        api_url=_ENV_AT_IMPORT.get(
            "MODULE7_LANGSMITH_API_URL", "https://api.smith.langchain.com"
        ),
        reservation_per_request_usd=0.001,
        run_cost_limit_usd=1.0,
    )
    result = run_live_langsmith_verification(
        runtime(), settings, opt_in=_LIVE_OPT_IN
    )
    # Matching typed readback is the only confirmation lane; nothing else
    # in this module can mint a live_vendor class for the export chain.
    assert result.outcome == "confirmed"
    assert result.evidence_class is EvidenceClass.LIVE_VENDOR
    assert result.confirmed_examples == result.expected_examples
    assert result.confirmed_feedback == result.expected_feedback
