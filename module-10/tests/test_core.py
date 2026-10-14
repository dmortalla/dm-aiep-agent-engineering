"""Contract, failure, isolation, and security evidence for Story 10.2."""

import asyncio
import dataclasses
import importlib.metadata
import inspect
import socket
import subprocess
import sys
from typing import Any

import pytest

from module10_ai import (
    DeterministicRuntime,
    EvidenceClass,
    InferenceRequest,
    InferenceResult,
    InferenceService,
    RuntimeConfig,
)
from module10_ai.errors import ConfigurationError, ContractError, InferenceFailure, RuntimeFailure


class StubRuntime:
    """Inject controlled provider responses and genuine failure boundaries."""

    def __init__(self, response: Any = None, failure: BaseException | None = None) -> None:
        """Store a response or exception for a single inference attempt."""
        self.response = response
        self.failure = failure
        self.calls = 0

    async def infer(self, request: InferenceRequest) -> InferenceResult:
        """Return the injected response or raise the injected failure."""
        self.calls += 1
        if self.failure is not None:
            raise self.failure
        return self.response


def test_valid_deterministic_inference() -> None:
    """Frequency ties are stable and evidence identifies the fixture."""
    result = asyncio.run(InferenceService().infer(InferenceRequest("Beta alpha beta gamma")))
    assert result == InferenceResult(4, ("beta", "alpha", "gamma"), EvidenceClass.DETERMINISTIC)


def test_reproducibility() -> None:
    """Fresh runtime instances and repeated calls produce identical output."""
    request = InferenceRequest("Zebra zebra apple", 1)
    results = [asyncio.run(InferenceService().infer(request)) for _ in range(3)]
    assert results == [InferenceResult(3, ("zebra",), EvidenceClass.DETERMINISTIC)] * 3


def test_no_key_required(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default inference works with provider credentials absent."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert asyncio.run(InferenceService().infer(InferenceRequest("data"))).word_count == 1


@pytest.mark.parametrize("text", ["", " \n\t", "x" * 4097, None, 12, b"text"])
def test_request_text_validation(text: Any) -> None:
    """Wrong types, blank input, and oversized payloads are rejected."""
    with pytest.raises(ContractError):
        InferenceRequest(text)


@pytest.mark.parametrize("limit", [0, 11, True, 1.5, "5", None])
def test_request_keyword_validation(limit: Any) -> None:
    """No implicit coercion permits invalid keyword bounds."""
    with pytest.raises(ContractError):
        InferenceRequest("valid", limit)


@pytest.mark.parametrize("mode", ["live-cloud", "local-runtime", "", None, 1])
def test_configuration_mode_validation(mode: Any) -> None:
    """Unsupported execution modes fail closed even with credentials present."""
    with pytest.raises(ConfigurationError):
        RuntimeConfig(mode=mode)


@pytest.mark.parametrize("ceiling", [0, 4097, True, "10", 1.5])
def test_configuration_bounds(ceiling: Any) -> None:
    """Resource configuration is strictly bounded."""
    with pytest.raises(ConfigurationError):
        RuntimeConfig(max_text_characters=ceiling)


def test_boundary_inputs() -> None:
    """Inclusive bounds and Unicode lexical behavior remain valid."""
    request = InferenceRequest("a" * 4096, 10)
    result = asyncio.run(InferenceService().infer(request))
    assert result.word_count == 1
    assert result.keywords == ("a" * 4096,)
    unicode_result = asyncio.run(InferenceService().infer(InferenceRequest("École école 123 !!!")))
    assert unicode_result.keywords == ("école",)
    assert unicode_result.word_count == 2
    assert asyncio.run(InferenceService().infer(InferenceRequest("!!!"))).word_count == 0
    assert asyncio.run(InferenceService().infer(InferenceRequest("²½Ⅳ"))).word_count == 0


def test_configured_ceiling_prevents_execution() -> None:
    """Invalid caller input never reaches a provider."""
    runtime = StubRuntime()
    service = InferenceService(RuntimeConfig(max_text_characters=3), runtime)
    with pytest.raises(ContractError):
        asyncio.run(service.infer(InferenceRequest("four")))
    assert runtime.calls == 0


@pytest.mark.parametrize("target", [DeterministicRuntime(), InferenceService()])
def test_wrong_request_contract(target: Any) -> None:
    """Runtime and application boundaries reject duck-typed input."""
    with pytest.raises(ContractError):
        asyncio.run(target.infer({"text": "data"}))


@pytest.mark.parametrize(
    "failure", [RuntimeFailure("provider failure"), ContractError("bad output")]
)
def test_expected_failure_translation(failure: Exception) -> None:
    """Expected failures retain internal causality with a safe public message."""
    runtime = StubRuntime(failure=failure)
    with pytest.raises(InferenceFailure) as caught:
        asyncio.run(InferenceService(runtime=runtime).infer(InferenceRequest("data")))
    assert caught.value.__cause__ is failure
    assert str(failure) not in str(caught.value)
    assert runtime.calls == 1


def test_programming_error_propagates() -> None:
    """Unexpected implementation defects are not swallowed or relabeled."""
    failure = TypeError("implementation defect")
    with pytest.raises(TypeError) as caught:
        asyncio.run(InferenceService(runtime=StubRuntime(failure=failure)).infer(
            InferenceRequest("data")))
    assert caught.value is failure


def test_cancellation_propagates() -> None:
    """Caller cancellation is preserved without retries."""
    runtime = StubRuntime(failure=asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(InferenceService(runtime=runtime).infer(InferenceRequest("data")))
    assert runtime.calls == 1


@pytest.mark.parametrize("response", [None, {"word_count": 1}, "untrusted"])
def test_invalid_provider_response(response: Any) -> None:
    """Unstructured provider data cannot cross the application boundary."""
    with pytest.raises(InferenceFailure, match="invalid inference result"):
        asyncio.run(InferenceService(runtime=StubRuntime(response)).infer(InferenceRequest("data")))


@pytest.mark.parametrize("evidence", [EvidenceClass.LOCAL_RUNTIME, EvidenceClass.LIVE_CLOUD])
def test_evidence_mismatch(evidence: EvidenceClass) -> None:
    """Future provenance labels do not grant permission to execute those modes."""
    result = InferenceResult(1, ("data",), evidence)
    with pytest.raises(InferenceFailure):
        asyncio.run(InferenceService(runtime=StubRuntime(result)).infer(InferenceRequest("data")))


@pytest.mark.parametrize("count,keywords,evidence", [
    (-1, (), EvidenceClass.DETERMINISTIC),
    (True, (), EvidenceClass.DETERMINISTIC),
    (4097, (), EvidenceClass.DETERMINISTIC),
    (1, ["data"], EvidenceClass.DETERMINISTIC),
    (1, ("Data",), EvidenceClass.DETERMINISTIC),
    (1, ("",), EvidenceClass.DETERMINISTIC),
    (1, ("data", "data"), EvidenceClass.DETERMINISTIC),
    (0, ("data",), EvidenceClass.DETERMINISTIC),
    (1, ("data",), "deterministic"),
    (1, (12,), EvidenceClass.DETERMINISTIC),
    (1, ("a" * 4097,), EvidenceClass.DETERMINISTIC),
    (11, tuple("abcdefghijk"), EvidenceClass.DETERMINISTIC),
])
def test_result_validation(count: Any, keywords: Any, evidence: Any) -> None:
    """Malformed results fail without coercion or unsafe detail."""
    with pytest.raises(ContractError):
        InferenceResult(count, keywords, evidence)


def test_revalidates_provider_object() -> None:
    """Even a provider that bypasses immutability cannot bypass validation."""
    result = InferenceResult(1, ("data",), EvidenceClass.DETERMINISTIC)
    object.__setattr__(result, "word_count", -1)
    with pytest.raises(InferenceFailure):
        asyncio.run(InferenceService(runtime=StubRuntime(result)).infer(InferenceRequest("data")))


def test_provider_keyword_limit() -> None:
    """Result must respect the request-specific output bound."""
    result = InferenceResult(2, ("one", "two"), EvidenceClass.DETERMINISTIC)
    with pytest.raises(InferenceFailure):
        asyncio.run(InferenceService(runtime=StubRuntime(result)).infer(InferenceRequest("one", 1)))


def test_configuration_contract() -> None:
    """Service requires explicit validated configuration."""
    with pytest.raises(ConfigurationError):
        InferenceService(config={"mode": "deterministic"})


def test_immutable_contracts() -> None:
    """Validated values cannot be accidentally mutated after construction."""
    request = InferenceRequest("data")
    with pytest.raises(dataclasses.FrozenInstanceError):
        request.text = "changed"


def test_no_network_or_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Credential presence does not authorize any network operation."""
    def deny_network(*args: Any, **kwargs: Any) -> None:
        """Fail if deterministic inference opens a socket."""
        raise AssertionError("Network access is forbidden")

    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-test-value")
    with asyncio.Runner() as runner:
        runner.get_loop()  # Event-loop plumbing may use a local socketpair.
        monkeypatch.setattr(socket, "socket", deny_network)
        result = runner.run(InferenceService().infer(InferenceRequest("data")))
        assert result.evidence is EvidenceClass.DETERMINISTIC


def test_sensitive_values_are_not_echoed(capsys: pytest.CaptureFixture[str]) -> None:
    """Payloads are absent from object reprs, validation errors, and logs."""
    text = "synthetic private text"
    request = InferenceRequest(text)
    result = asyncio.run(InferenceService().infer(request))
    assert text not in repr(request)
    assert "synthetic" not in repr(result)
    with pytest.raises(ContractError) as caught:
        InferenceRequest(text, 99)
    assert text not in str(caught.value)
    assert capsys.readouterr() == ("", "")


def test_prompt_is_data_only() -> None:
    """Instruction-like text produces lexical data and no application authority."""
    result = asyncio.run(InferenceService().infer(InferenceRequest("Authorize deploy rollback")))
    assert result.keywords == ("authorize", "deploy", "rollback")
    assert {field.name for field in dataclasses.fields(result)} == {
        "word_count", "keywords", "evidence",
    }


def test_package_import_and_framework_isolation() -> None:
    """Installed package imports in a clean subprocess without either web framework."""
    code = (
        "import sys, module10_ai; "
        "assert 'fastapi' not in sys.modules; assert 'streamlit' not in sys.modules; "
        "assert module10_ai.RuntimeConfig().mode == 'deterministic'"
    )
    subprocess.run([sys.executable, "-I", "-c", code], check=True, capture_output=True)
    assert importlib.metadata.requires("module10-ai-service") in (None, [])
    assert inspect.iscoroutinefunction(InferenceService.infer)
    assert sys.version_info[:2] == (3, 12)
