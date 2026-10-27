"""Second live-run compatibility: genuine SDKs over mocked HTTP, never live-provider evidence.

The fixtures reconstruct the sanitized structures observed in the second authorized
live exercise (OpenAI reasoning item plus final message; Anthropic end_turn text) and
prove the repaired adapters accept them while returning only untrusted final text,
and that every adversarial deviation still fails closed with a content-free code.
"""

import copy
import socket
import traceback
from decimal import Decimal
from typing import Any

import pytest

from harness_engineering.domain import RuntimeBudget
from harness_engineering.providers import (
    ModelResult,
    ProviderOutputRejected,
    RejectionPoint,
)
from harness_engineering.usage import UsageState
from tests.live_seam import ENV_NAME, live_runtime
from tests.live_seam import authorization as live_authorization
from tests.test_story13_dual_mode import patch_sdk
from tests.test_vendor_providers import setup

ANSWER_OPENAI = "F" * 36
ANSWER_ANTHROPIC = "A" * 108
REASONING_SECRET = "REASONING-CONTENT-MARKER-DO-NOT-RETURN"
ENCRYPTED_SECRET = "ENCRYPTED-REASONING-MARKER-DO-NOT-RETURN"
CREDENTIAL = "controlled-dummy-not-a-real-key"
P = RejectionPoint
BUDGET = RuntimeBudget(max_context_tokens=512, max_output_tokens=256, max_output_bytes=4096,
                       action_timeout_seconds=20.0)


@pytest.fixture(autouse=True)
def sealed(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        monkeypatch.delenv(name, raising=False)

    def forbidden(*args: object, **kwargs: object) -> Any:
        pytest.fail("No network or provider access is permitted")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)


def reasoning(**overrides: Any) -> dict[str, Any]:
    item: dict[str, Any] = {"id": "rs_second_run", "type": "reasoning", "status": None,
                            "summary": [], "content": [], "encrypted_content": "ENC"}
    return item | overrides


def message(text: str = ANSWER_OPENAI, **overrides: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": "msg_second_run", "type": "message", "status": "completed",
        "role": "assistant", "phase": "final_answer",
        "content": [{"type": "output_text", "text": text, "annotations": [], "logprobs": []}],
    }
    return item | overrides


def openai_body(output: list[dict[str, Any]] | None = None, **top: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": "resp_second_run", "object": "response", "created_at": 1.0, "model": "gpt-6-luna",
        "status": "completed", "error": None, "incomplete_details": None, "metadata": {},
        "output": [reasoning(), message()] if output is None else output,
        "usage": {"input_tokens": 20, "output_tokens": 34, "total_tokens": 54,
                  "input_tokens_details": {"cached_tokens": 0},
                  "output_tokens_details": {"reasoning_tokens": 12}},
    }
    return data | top


def anthropic_body(text: str = ANSWER_ANTHROPIC, **top: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": "msg_second_run", "type": "message", "role": "assistant",
        "model": "claude-haiku-5-5",
        "content": [{"type": "text", "text": text, "citations": None}],
        "stop_reason": "end_turn", "stop_sequence": None,
        "usage": {"input_tokens": 35, "output_tokens": 33, "cache_creation_input_tokens": 0,
                  "cache_read_input_tokens": 0},
    }
    return data | top


def refused(vendor: str, data: dict[str, Any]) -> tuple[ProviderOutputRejected, Any]:
    runtime, _ = setup(vendor, data, budget=BUDGET)
    with pytest.raises(ProviderOutputRejected) as caught:
        runtime.generate({"prompt": "One short sentence."})
    return caught.value, runtime


def usage_of(runtime: Any) -> tuple[UsageState, int | None, int | None]:
    facts = runtime.usage_receipts[0].usage
    return facts.state, facts.input_tokens, facts.output_tokens


# ---- Observed second-run shapes ---------------------------------------------------------


def test_observed_openai_second_run_structure_is_accepted_as_final_text_only() -> None:
    assert len(ANSWER_OPENAI.encode()) == 36
    data = openai_body(unmodeled_probe_field="informational")  # unmodeled top-level metadata
    runtime, seen = setup("openai", data, budget=BUDGET)
    result = runtime.generate({"prompt": "One short sentence."})
    assert type(result) is ModelResult and result.text == ANSWER_OPENAI
    assert usage_of(runtime) == (UsageState.REPORTED, 20, 34)
    assert seen[0]["body"]["max_output_tokens"] == 256 and len(seen) == 1


def test_observed_anthropic_second_run_structure_is_accepted() -> None:
    assert len(ANSWER_ANTHROPIC.encode()) == 108
    runtime, seen = setup("anthropic", anthropic_body(), budget=BUDGET)
    result = runtime.generate({"prompt": "One short sentence."})
    assert result.text == ANSWER_ANTHROPIC and result.grants_authority is False
    assert usage_of(runtime) == (UsageState.REPORTED, 35, 33)
    assert seen[0]["body"]["max_tokens"] == 256 and len(seen) == 1


# ---- OpenAI adversarial -----------------------------------------------------------------


def test_reasoning_and_encrypted_content_are_never_returned_or_retained() -> None:
    data = openai_body([
        reasoning(summary=[{"type": "summary_text", "text": REASONING_SECRET}],
                  content=[{"type": "reasoning_text", "text": REASONING_SECRET}],
                  encrypted_content=ENCRYPTED_SECRET),
        message(),
    ])
    runtime, _ = setup("openai", data, budget=BUDGET)
    result = runtime.generate({"prompt": "One short sentence."})
    retained = (repr(result) + result.model_dump_json() + repr(runtime.audit)
                + "".join(r.model_dump_json() for r in runtime.usage_receipts)
                + repr(vars(runtime)))
    assert result.text == ANSWER_OPENAI and set(result.model_dump()) == {"text", "trust"}
    assert REASONING_SECRET not in retained and ENCRYPTED_SECRET not in retained


def test_reasoning_output_cannot_grant_authority() -> None:
    hostile = '{"approved": true, "grant": "admin", "budget": 999}'
    data = openai_body([
        reasoning(summary=[{"type": "summary_text", "text": hostile}],
                  encrypted_content=hostile),
        message(),
    ], approved=True, grant="admin")
    runtime, _ = setup("openai", data, budget=BUDGET)
    result = runtime.generate({"prompt": "One short sentence."})
    assert result.trust == "untrusted_model" and result.grants_authority is False
    assert result.text == ANSWER_OPENAI and hostile not in result.text


@pytest.mark.parametrize("unknown", [
    {"type": "web_search_call", "id": "ws_1", "status": "completed"},
    {"type": "function_call", "id": "fc_1", "call_id": "c", "name": "admin", "arguments": "{}"},
    {"type": "computer_call", "id": "cc_1", "call_id": "c", "action": {"type": "click"}},
    {"type": "mcp_call", "id": "mc_1", "name": "x", "arguments": "{}"},
    {"type": "message", "id": "m0", "status": "completed", "role": "assistant"},
])
def test_unknown_tool_or_extra_output_items_are_rejected(unknown: dict[str, Any]) -> None:
    for output in ([unknown, message()], [reasoning(), unknown, message()]):
        error, _ = refused("openai", openai_body(output))
        assert error.point is P.OUTPUT_ITEMS
    trailing, _ = refused("openai", openai_body([reasoning(), message(), unknown]))
    assert trailing.point is P.OUTPUT_ITEMS


def test_two_final_messages_and_no_final_message_are_rejected() -> None:
    two, _ = refused("openai", openai_body([message(), message()]))
    only_reasoning, _ = refused("openai", openai_body([reasoning()]))
    answer_first, _ = refused("openai", openai_body([message(), reasoning()]))
    assert {two.point, only_reasoning.point, answer_first.point} == {P.OUTPUT_ITEMS}
    too_many, _ = refused("openai", openai_body([reasoning()] * 5 + [message()]))
    assert too_many.point is P.OUTPUT_ITEMS


@pytest.mark.parametrize("bad", [
    {"unexpected": "field"},
    {"summary": "not-a-list"},
    {"summary": [{"type": "summary_text", "text": 5}]},
    {"summary": [{"type": "other", "text": "x"}]},
    {"summary": [{"type": "summary_text", "text": "x", "extra": 1}]},
    {"content": [{"type": "reasoning_text", "text": "x", "extra": 1}]},
    {"content": [{"type": "summary_text", "text": "x"}]},
    {"summary": [{"type": "summary_text", "text": "x"}] * 9},
    {"status": "in_progress"},
    {"id": "bad id with spaces"},
    {"id": 7},
    {"encrypted_content": 12345},
    {"type": "reasoning_summary"},
])
def test_malformed_reasoning_item_is_rejected(bad: dict[str, Any]) -> None:
    error, _ = refused("openai", openai_body([reasoning(**bad), message()]))
    assert error.point is P.OUTPUT_ITEMS


def test_opaque_reasoning_field_has_an_explicit_separate_bound() -> None:
    accepted = openai_body([reasoning(encrypted_content="E" * 32_768), message()])
    runtime, _ = setup("openai", accepted, budget=BUDGET)
    assert runtime.generate({"prompt": "One short sentence."}).text == ANSWER_OPENAI
    over, _ = refused("openai", openai_body([reasoning(encrypted_content="E" * 32_769),
                                             message()]))
    assert over.point is P.PAYLOAD_LIMITS
    # Opaque allowance is only for that field; any other string keeps the generic cap.
    other, _ = refused("openai", openai_body([reasoning(
        summary=[{"type": "summary_text", "text": "S" * 16_385}]), message()]))
    assert other.point is P.PAYLOAD_LIMITS


def test_oversized_total_payload_oversized_text_and_token_overrun_are_rejected() -> None:
    parts = [{"type": "summary_text", "text": "S" * 10_000}] * 8  # 80,000 B total
    total, _ = refused("openai", openai_body([reasoning(summary=parts), message()]))
    assert total.point is P.PAYLOAD_LIMITS
    big, _ = refused("openai", openai_body([reasoning(), message("t" * 4097)]))
    assert big.point is P.TEXT_BYTES
    usage = dict(openai_body()["usage"], output_tokens=257, total_tokens=277)
    over, runtime = refused("openai", openai_body(usage=usage))
    assert over.point is P.USAGE_BOUNDS and usage_of(runtime)[0] is UsageState.MALFORMED


@pytest.mark.parametrize("patch", [
    {"output_tokens": True}, {"output_tokens": -1}, {"output_tokens": None},
    {"input_tokens": "20"}, {"total_tokens": 55}, {"total_tokens": None},
])
def test_malformed_openai_usage_is_rejected_and_recorded_malformed(
    patch: dict[str, Any],
) -> None:
    usage = dict(openai_body()["usage"]) | patch
    error, runtime = refused("openai", openai_body(usage=usage))
    assert error.point is P.USAGE_SHAPE
    assert usage_of(runtime) == (UsageState.MALFORMED, None, None)


def test_missing_openai_usage_is_recorded_missing_not_zero() -> None:
    error, runtime = refused("openai", openai_body(usage=None))
    assert error.point is P.USAGE_SHAPE
    assert usage_of(runtime) == (UsageState.MISSING, None, None)


# ---- Anthropic adversarial --------------------------------------------------------------


@pytest.mark.parametrize("patch", [
    {"input_tokens": None}, {"output_tokens": None},
])
def test_required_anthropic_token_fields_missing_are_rejected(patch: dict[str, Any]) -> None:
    usage = dict(anthropic_body()["usage"]) | patch
    error, runtime = refused("anthropic", anthropic_body(usage=usage))
    assert error.point is P.USAGE_SHAPE
    assert usage_of(runtime) == (UsageState.MALFORMED, None, None)


def test_anthropic_usage_key_removed_entirely_is_rejected() -> None:
    for key in ("input_tokens", "output_tokens"):
        usage = dict(anthropic_body()["usage"])
        del usage[key]
        # The SDK model requires both counts, so this fails at SDK validation or ours.
        runtime, _ = setup("anthropic", anthropic_body(usage=usage), budget=BUDGET)
        with pytest.raises(ProviderOutputRejected):
            runtime.generate({"prompt": "One short sentence."})


@pytest.mark.parametrize("patch", [
    {"input_tokens": "35"}, {"output_tokens": True}, {"input_tokens": 3.5},
    {"input_tokens": -1}, {"output_tokens": -1},
    {"input_tokens": 513}, {"output_tokens": 257}, {"input_tokens": 12_001},
    {"cache_read_input_tokens": 5}, {"cache_creation_input_tokens": 1},
    {"cache_read_input_tokens": "5"}, {"cache_creation_input_tokens": 2**40},
])
def test_wrong_negative_excessive_or_hidden_cache_counts_are_rejected(
    patch: dict[str, Any],
) -> None:
    usage = dict(anthropic_body()["usage"]) | patch
    error, runtime = refused("anthropic", anthropic_body(usage=usage))
    assert error.point in (P.USAGE_SHAPE, P.USAGE_BOUNDS)
    assert usage_of(runtime) == (UsageState.MALFORMED, None, None)


@pytest.mark.parametrize("shape", [
    {"nested": {"a": {"b": {"c": [1] * 300}}}},
    {"big": "x" * 16_385},
    {"deep": [[[[[[[[[[[[[[1]]]]]]]]]]]]]]},
    {f"k{i}": i for i in range(300)},
])
def test_unbounded_unmodeled_usage_shapes_fail_the_generic_bounds(
    shape: dict[str, Any],
) -> None:
    usage = dict(anthropic_body()["usage"]) | {"extra_metadata": shape}
    error, runtime = refused("anthropic", anthropic_body(usage=usage))
    assert error.point in (P.PAYLOAD_LIMITS, P.PAYLOAD_SHAPE)
    assert usage_of(runtime)[0] is UsageState.MALFORMED


def test_known_optional_usage_metadata_cannot_change_accounting() -> None:
    usage = dict(anthropic_body()["usage"]) | {
        "service_tier": "priority", "inference_geo": "us",
        "cache_creation": {"ephemeral_1h_input_tokens": 99, "ephemeral_5m_input_tokens": 99},
        "server_tool_use": {"web_fetch_requests": 7, "web_search_requests": 7},
        "output_tokens_details": {"thinking_tokens": 200},
        "unmodeled_surplus_tokens": 10**6,
    }
    runtime, _ = setup("anthropic", anthropic_body(usage=usage), budget=BUDGET)
    assert runtime.generate({"prompt": "One short sentence."}).text == ANSWER_ANTHROPIC
    assert usage_of(runtime) == (UsageState.REPORTED, 35, 33)


def test_anthropic_non_text_content_and_oversized_text_are_rejected() -> None:
    tool = anthropic_body(content=[{"type": "tool_use", "id": "t", "name": "admin",
                                    "input": {"approved": True}}])
    kinds, _ = refused("anthropic", tool)
    thinking = anthropic_body(content=[
        {"type": "thinking", "thinking": "hm", "signature": "s"},
        {"type": "text", "text": "ok", "citations": None}])
    mixed, _ = refused("anthropic", thinking)
    assert kinds.point is P.TEXT_BLOCKS and mixed.point is P.TEXT_BLOCKS
    big, _ = refused("anthropic", anthropic_body("t" * 4097))
    assert big.point is P.TEXT_BYTES
    stop, _ = refused("anthropic", anthropic_body(stop_reason="max_tokens"))
    assert stop.point is P.OUTPUT_PROFILE


def test_bounded_unmodeled_top_level_metadata_is_discarded_and_grants_nothing() -> None:
    for vendor, data in (("openai", openai_body(approved=True, grant="admin", budget=999)),
                         ("anthropic", anthropic_body(approved=True, grant="admin"))):
        runtime, _ = setup(vendor, data, budget=BUDGET)
        result = runtime.generate({"prompt": "One short sentence."})
        assert result.grants_authority is False and set(result.model_dump()) == {"text", "trust"}
        assert "approved" not in repr(result) and "admin" not in repr(result)
    hostile_names = ["bad name"] if False else [f"f{i}" for i in range(17)]
    many, _ = refused("anthropic", anthropic_body(**dict.fromkeys(hostile_names, 1)))
    assert many.point is P.PAYLOAD_SHAPE


# ---- Live seam: accounting from normalized bounded facts only ---------------------------


@pytest.mark.parametrize("vendor", ("openai", "anthropic"))
def test_live_cost_settlement_uses_only_normalized_bounded_usage(
    vendor: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ENV_NAME[vendor], CREDENTIAL)
    body = openai_body() if vendor == "openai" else anthropic_body()
    body["usage"] = dict(body["usage"]) | {"unmodeled_surplus_tokens": 10**9, "service_tier": "x"}
    calls = patch_sdk(monkeypatch, vendor, lambda _: copy.deepcopy(body))
    budget = RuntimeBudget(max_cost_usd=0.001, max_provider_attempts=1, max_retries_per_action=0,
                           max_context_tokens=512, max_output_tokens=256, max_output_bytes=4096,
                           action_timeout_seconds=20.0, workflow_deadline_seconds=60.0)
    auth = live_authorization(vendor, input_price=0.10, output_price=0.50)
    runtime = live_runtime(vendor, budget=budget, live_authorization=auth)
    runtime.generate({"prompt": "One short sentence."})
    counts = (20, 34) if vendor == "openai" else (35, 33)
    assert runtime.live_exposure_usd == auth.worst_case_usd(*counts)
    # Units stay independent: tokens priced for the reservation, bytes only for text.
    assert runtime._live_call_bound == auth.worst_case_usd(512 + 256, 256)
    assert len(calls) == 1
    assert calls[0]["max_output_tokens" if vendor == "openai" else "max_tokens"] == 256
    assert runtime.live_exposure_usd < Decimal("0.001")


# ---- Rejection-point diagnostics never carry content or credentials ----------------------


def test_rejection_points_are_finite_content_free_codes() -> None:
    assert {p.value for p in RejectionPoint} == {
        "sdk_validation", "malformed_json", "response_type", "payload_shape", "payload_limits",
        "usage_shape", "usage_bounds", "output_profile", "output_items", "text_blocks",
        "text_bytes", "result_shape", "output_filter", "guardrails",
    }


@pytest.mark.parametrize(("vendor", "data", "expected"), [
    ("openai", openai_body([message(), message()]), P.OUTPUT_ITEMS),
    ("openai", openai_body(status="incomplete"), P.OUTPUT_PROFILE),
    ("openai", openai_body([reasoning(), message("t" * 4097)]), P.TEXT_BYTES),
    ("openai", openai_body([reasoning(encrypted_content="E" * 40_000), message()]),
     P.PAYLOAD_LIMITS),
    ("anthropic", anthropic_body(stop_reason="refusal"), P.OUTPUT_PROFILE),
    ("anthropic", anthropic_body(content=[]), P.TEXT_BLOCKS),
    ("anthropic", anthropic_body(usage=None), P.USAGE_SHAPE),
])
def test_rejection_point_is_exact_and_leaks_no_provider_content(
    vendor: str, data: dict[str, Any], expected: RejectionPoint,
) -> None:
    marker = "SECRET-PROVIDER-TEXT-MARKER"
    if vendor == "openai":
        data["output"][-1]["content"][0]["text"] = marker + data["output"][-1]["content"][0][
            "text"]
    else:
        data["content"] = data["content"] or []
    runtime, _ = setup(vendor, data, budget=BUDGET)
    with pytest.raises(ProviderOutputRejected) as caught:
        runtime.generate({"prompt": "One short sentence."})
    error = caught.value
    assert error.point is expected
    rendered = (str(error) + repr(error) + repr(error.point)
                + "".join(traceback.format_exception(error)))
    assert marker not in rendered and CREDENTIAL not in rendered
    assert str(error) in {
        "Vendor response violates the supported text-only profile.",
        "Provider text is empty or exceeds the application bound.",
    }


def test_usage_shape_diagnostic_reports_names_and_types_only() -> None:
    from harness_engineering.vendor_providers import describe_usage_shape

    leak = "PROVIDER-STRING-CONTENT-MUST-NOT-APPEAR"
    usage = {"input_tokens": 35, "output_tokens": 33, "cache_read_input_tokens": 0,
             "service_tier": leak, "cache_creation": {"k": leak}, "tags": [leak],
             "unmodeled": None, "bad name!": 1, "flag": True}
    shape = describe_usage_shape(usage)
    assert shape == {
        "input_tokens": "int=35", "output_tokens": "int=33", "cache_read_input_tokens": "int",
        "service_tier": "str", "cache_creation": "dict", "tags": "list", "unmodeled": "null",
        "<invalid-name>": "int", "flag": "bool",
    }
    assert leak not in repr(shape) and describe_usage_shape("not a dict") == {}

# ---- Unknown usage-metadata policy: identical to the unknown top-level policy ------------

VENDORS = ("openai", "anthropic")
COUNTS = {"openai": (20, 34), "anthropic": (35, 33)}


def with_usage(vendor: str, extra: dict[str, Any]) -> dict[str, Any]:
    data = openai_body() if vendor == "openai" else anthropic_body()
    data["usage"] = dict(data["usage"]) | extra
    return data


def accepted_counts(vendor: str, extra: dict[str, Any]) -> tuple[Any, ...]:
    runtime, _ = setup(vendor, with_usage(vendor, extra), budget=BUDGET)
    result = runtime.generate({"prompt": "One short sentence."})
    assert result.grants_authority is False and set(result.model_dump()) == {"text", "trust"}
    return usage_of(runtime)


@pytest.mark.parametrize("vendor", VENDORS)
def test_unknown_usage_keys_accepted_up_to_sixteen_and_rejected_beyond(vendor: str) -> None:
    expected = (UsageState.REPORTED, *COUNTS[vendor])
    for count in (0, 1, 16):
        assert accepted_counts(vendor, {f"unknown_{i}": i for i in range(count)}) == expected
    for count in (17, 40):
        error, runtime = refused(vendor, with_usage(
            vendor, {f"unknown_{i}": i for i in range(count)}))
        assert error.point is P.USAGE_SHAPE
        assert usage_of(runtime) == (UsageState.MALFORMED, None, None)


@pytest.mark.parametrize("vendor", VENDORS)
def test_known_usage_keys_do_not_count_toward_the_unknown_limit(vendor: str) -> None:
    known = ({"total_tokens": 54, "input_tokens_details": {"cached_tokens": 0},
              "output_tokens_details": {"reasoning_tokens": 1}} if vendor == "openai" else
             {"cache_creation": None, "inference_geo": "us", "server_tool_use": None,
              "service_tier": "standard", "output_tokens_details": {"thinking_tokens": 1}})
    extra = known | {f"unknown_{i}": i for i in range(16)}
    assert accepted_counts(vendor, extra) == (UsageState.REPORTED, *COUNTS[vendor])
    error, _ = refused(vendor, with_usage(vendor, known | {f"u{i}": i for i in range(17)}))
    assert error.point is P.USAGE_SHAPE


@pytest.mark.parametrize("vendor", VENDORS)
@pytest.mark.parametrize("name", ["a", "Unknown_Field_9", "_", "x" * 64, "0"])
def test_valid_identifier_style_unknown_usage_names_are_accepted(vendor: str, name: str) -> None:
    assert accepted_counts(vendor, {name: 1}) == (UsageState.REPORTED, *COUNTS[vendor])


@pytest.mark.parametrize("vendor", VENDORS)
@pytest.mark.parametrize("name", [
    "bad name / ü", "ü", "with space", "dash-name", "dot.name", "", "x" * 65, "y" * 200,
    "new\nline", "slash/name",
])
def test_malformed_or_overlong_unknown_usage_names_are_rejected(vendor: str, name: str) -> None:
    error, runtime = refused(vendor, with_usage(vendor, {name: 1}))
    assert error.point is P.USAGE_SHAPE
    assert usage_of(runtime) == (UsageState.MALFORMED, None, None)
    assert not name or name not in str(error) + repr(error)  # key names never echoed


@pytest.mark.parametrize("vendor", VENDORS)
def test_hostile_unknown_usage_values_stay_inert_and_cannot_change_accounting(
    vendor: str,
) -> None:
    hostile = {"approved": True, "grant": "admin", "model": "gpt-9", "tool": "shell",
               "budget": 999, "input_tokens": 1}
    extra = {"extra_a": hostile, "extra_b": [hostile], "extra_c": "approved=true",
             "extra_d": 10**9, "extra_e": -5, "extra_f": None}
    assert accepted_counts(vendor, extra) == (UsageState.REPORTED, *COUNTS[vendor])
    for oversized in ({"big": "x" * 16_385}, {"wide": list(range(300))},
                      {"deep": [[[[[[[[[[[[[[1]]]]]]]]]]]]]]}):
        error, _ = refused(vendor, with_usage(vendor, {"extra_a": oversized}))
        assert error.point in (P.PAYLOAD_LIMITS, P.PAYLOAD_SHAPE)


@pytest.mark.parametrize("vendor", VENDORS)
def test_required_usage_still_strictly_enforced_alongside_unknown_keys(vendor: str) -> None:
    unknown = {"unknown_0": 1}
    for patch in ({"input_tokens": True}, {"output_tokens": "3"}, {"input_tokens": 513},
                  {"output_tokens": 257}, {"output_tokens": -1}):
        usage = with_usage(vendor, unknown)["usage"] | patch
        if vendor == "openai":
            usage["total_tokens"] = 0  # cannot rescue a bad count
        data = (openai_body(usage=usage) if vendor == "openai"
                else anthropic_body(usage=usage))
        error, runtime = refused(vendor, data)
        assert error.point in (P.USAGE_SHAPE, P.USAGE_BOUNDS)
        assert usage_of(runtime) == (UsageState.MALFORMED, None, None)


def test_anthropic_nonzero_cache_counts_remain_rejected_with_unknown_keys() -> None:
    for patch in ({"cache_read_input_tokens": 1}, {"cache_creation_input_tokens": 1}):
        error, runtime = refused("anthropic", with_usage("anthropic", {"unknown_0": 1} | patch))
        assert error.point is P.USAGE_SHAPE
        assert usage_of(runtime) == (UsageState.MALFORMED, None, None)


def test_top_level_and_usage_unknown_policies_share_one_rule() -> None:
    from harness_engineering.vendor_providers import MAX_UNMODELED_FIELDS, _unknown_names_acceptable

    assert MAX_UNMODELED_FIELDS == 16
    assert _unknown_names_acceptable({f"f{i}" for i in range(16)})
    assert not _unknown_names_acceptable({f"f{i}" for i in range(17)})
    assert not _unknown_names_acceptable({"bad name"}) and not _unknown_names_acceptable({7})
    data = anthropic_body(**{f"top_{i}": 1 for i in range(17)})
    top, _ = refused("anthropic", data)
    assert top.point is P.PAYLOAD_SHAPE
    ok = anthropic_body(**{f"top_{i}": 1 for i in range(16)})
    runtime, _ = setup("anthropic", ok, budget=BUDGET)
    assert runtime.generate({"prompt": "One short sentence."}).text == ANSWER_ANTHROPIC
    bad_name, _ = refused("anthropic", anthropic_body(**{"bad name / ü": 1}))
    assert bad_name.point is P.PAYLOAD_SHAPE