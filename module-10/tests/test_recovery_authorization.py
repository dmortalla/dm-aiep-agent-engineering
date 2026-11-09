"""Adversarial Step 73 conformance for the fail-closed recovery-grant boundary.

No grant issuance, no signing keys, no network: every test constructs a real
RSA-PSS-SHA256-shaped (384-byte) but intentionally UNVERIFIED envelope and
checks exact Step 73 structure only. Synthetic signature carriage is explicitly
distinguished from verified signatures in every assertion path.
"""

import base64
import hashlib
import json
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

import pytest

from module10_ai.recovery_authorization import (
    APPROVED_ISSUER_KEY_ID,
    ENVELOPE_KEYS,
    PAYLOAD_KEYS,
    RSA_3072_SIGNATURE_BYTES,
    GrantStructure,
    RecoveryGrantError,
    validate_recovery_grant,
)

GRANT_ID = str(uuid5(NAMESPACE_URL, "module10.synthetic.recovery-grant"))
EXPERIMENT_ID = str(uuid5(NAMESPACE_URL, "module10.synthetic.recovery-experiment"))
ISSUER_SID = "S-1-5-21-1399661272-2213691258-2789323222-1001"
TENANT_ID = str(uuid5(NAMESPACE_URL, "module10.synthetic.recovery-tenant"))
SUBSCRIPTION_ID = str(uuid5(NAMESPACE_URL, "module10.synthetic.subscription"))
TRUSTED_NOW = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)
LEGACY_STEP82_SCHEMA = "module10-recovery-grant"
LEGACY_STEP82_ACTION = "recover-scale-to-zero"


def payload_fields(**overrides: object) -> dict:
    """Build the exact 23 signed Step 73 fields from bounded defaults."""
    fields: dict = {
        "schema": "taie.module10.recovery-grant.v1",
        "issuer_key_id": APPROVED_ISSUER_KEY_ID,
        "grant_id": GRANT_ID,
        "experiment_id": EXPERIMENT_ID,
        "subscription_id": SUBSCRIPTION_ID,
        "resource_group": "rg-reviewa",
        "container_app": "m10-api-reviewa",
        "authorized_action": "restore_azure_container_app_scale",
        "restore_min_replicas": 0,
        "restore_max_replicas": 2,
        "issued_at_utc": "2026-01-15T11:00:00Z",
        "expires_at_utc": "2026-01-15T12:05:00Z",
        "experiment_deadline_utc": "2026-01-15T12:05:00Z",
        "issuer_sid": ISSUER_SID,
        "approval_reference": "TECHADEMY/approvals/2026/0001",
        "tenant_id": TENANT_ID,
        "expected_resource_id":
            f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/rg-reviewa/providers/"
            "Microsoft.App/containerApps/m10-api-reviewa",
        "expected_pre_recovery_state": "scaled-to-zero",
        "approval_version": "approval-v1",
        "approval_digest": "sha256:" + "a" * 64,
        "not_before_utc": "2026-01-15T12:00:00Z",
        "maximum_execution_attempts": 1,
        "recovery_policy_version": 1,
    }
    fields.update(overrides)
    return fields


def canonical(payload: dict) -> bytes:
    """Serialize a payload with the exact canonical contract encoding."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def envelope_bytes(payload: dict | None = None, **overrides: object) -> bytes:
    """Assemble the signed-grant envelope around canonical payload bytes."""
    payload_overrides = {key: value for key, value in overrides.items()
                         if key not in ENVELOPE_KEYS}
    envelope_overrides = {key: value for key, value in overrides.items()
                          if key in ENVELOPE_KEYS}
    fields = payload if payload is not None else payload_fields(**payload_overrides)
    contents = canonical(fields)
    envelope: dict = {
        "envelope_version": 1,
        "schema": "taie.module10.signed-grant-envelope.v1",
        "issuer_key_id": APPROVED_ISSUER_KEY_ID,
        "payload_base64": base64.b64encode(contents).decode("ascii"),
        "payload_sha256": hashlib.sha256(contents).hexdigest(),
        "signature": base64.b64encode(bytes(RSA_3072_SIGNATURE_BYTES)).decode("ascii"),
    }
    envelope.update(envelope_overrides)
    return json.dumps(envelope).encode("utf-8")


def test_valid_grant_parses_without_authorization() -> None:
    """A structurally valid Step 73 grant yields the bounded projection, never authority."""
    structure = validate_recovery_grant(envelope_bytes(), now=TRUSTED_NOW)
    assert isinstance(structure, GrantStructure)
    assert structure.grant_id == GRANT_ID and structure.experiment_id == EXPERIMENT_ID
    assert structure.tenant_id == TENANT_ID and structure.issuer_sid == ISSUER_SID
    assert structure.authorized_action == "restore_azure_container_app_scale"
    assert structure.expected_resource_id.endswith("m10-api-reviewa")
    assert structure.expected_pre_recovery_state == "scaled-to-zero"
    assert structure.maximum_execution_attempts == 1
    projection = json.dumps(structure.__dict__)
    for authority_token in ('"is_authorized"', '"authorized":true', '"verified"',
                            '"authority_granted"', '"grant_authorized"', '"verification":'):
        assert authority_token not in projection


def test_step73_field_conformance_individually() -> None:
    """Exact schema, action, key ID and SID representation pass, individually."""
    content = payload_fields()
    assert content["schema"] == "taie.module10.recovery-grant.v1"
    assert content["authorized_action"] == "restore_azure_container_app_scale"
    assert content["issuer_key_id"] == APPROVED_ISSUER_KEY_ID
    assert content["issuer_sid"] == ISSUER_SID
    assert content["restore_min_replicas"] == 0 and content["restore_max_replicas"] == 2
    assert validate_recovery_grant(envelope_bytes(), now=TRUSTED_NOW).key_id == \
        APPROVED_ISSUER_KEY_ID


def test_envelope_carries_step73_elements() -> None:
    """The envelope exactly carries schema, key ID, canonical bytes and 384-byte sig."""
    import json as json_module
    envelope = json_module.loads(envelope_bytes())
    assert set(envelope) == ENVELOPE_KEYS
    assert envelope["schema"] == "taie.module10.signed-grant-envelope.v1"
    assert envelope["issuer_key_id"] == APPROVED_ISSUER_KEY_ID
    decoded = base64.b64decode(envelope["payload_base64"])
    assert len(decoded) > 0 and decoded == json.dumps(
        payload_fields(), sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert len(base64.b64decode(envelope["signature"])) == RSA_3072_SIGNATURE_BYTES


def test_synthetic_signature_carriage_is_not_verification() -> None:
    """A zeroed signature decodes to the exact shape without proving authenticity."""
    structure = validate_recovery_grant(envelope_bytes(), now=TRUSTED_NOW)
    assert isinstance(structure, GrantStructure)
    # Any signature-shaped byte block yields the same structural projection:
    # syntactic carriage differs from cryptographic authenticity by design.
    one_adjusted = (bytearray(b"\x00" * RSA_3072_SIGNATURE_BYTES))
    one_adjusted[-1] = 1
    alternative = base64.b64encode(bytes(one_adjusted)).decode("ascii")
    alternative_structure = validate_recovery_grant(
        envelope_bytes(signature=alternative), now=TRUSTED_NOW)
    assert alternative_structure.grant_id == structure.grant_id


def test_all_twenty_three_fields_are_present() -> None:
    """The Step 73 schema is the exact 23 signed payload fields."""
    import json as json_module
    envelope = json_module.loads(envelope_bytes())
    assert set(envelope) == ENVELOPE_KEYS
    content = json_module.loads(base64.b64decode(
        envelope["payload_base64"]).decode("utf-8"))
    assert set(content) == PAYLOAD_KEYS
    assert len(PAYLOAD_KEYS) == 23


def test_expiration_deadline_binding() -> None:
    """Expiration must never exceed the experiment deadline."""
    with pytest.raises(RecoveryGrantError, match="experiment deadline"):
        validate_recovery_grant(envelope_bytes(expires_at_utc="2026-01-15T12:06:00Z",
                                               experiment_deadline_utc="2026-01-15T12:05:00Z",
                                               not_before_utc="2026-01-15T12:00:00Z"),
                                now=TRUSTED_NOW)
    exactly_deadline = payload_fields(expires_at_utc="2026-01-15T12:04:00Z",
                                      experiment_deadline_utc="2026-01-15T12:04:00Z")
    assert validate_recovery_grant(envelope_bytes(payload=exactly_deadline),
                                   now=TRUSTED_NOW).expires_at_utc == \
        "2026-01-15T12:04:00Z"


def test_maximum_window_900_seconds() -> None:
    """Grant experiment windows exceed 900 seconds via reset order and again by gap."""
    stretched = payload_fields(expires_at_utc="2026-01-15T12:16:00Z",
                               experiment_deadline_utc="2026-01-15T12:16:00Z")
    with pytest.raises(RecoveryGrantError, match="exceeds the bounded allowance"):
        validate_recovery_grant(envelope_bytes(payload=stretched), now=TRUSTED_NOW)
    gap = payload_fields(expires_at_utc="2026-01-15T12:20:00Z",
                         experiment_deadline_utc="2026-01-15T12:20:00Z")
    with pytest.raises(RecoveryGrantError, match="exceeds the bounded allowance"):
        validate_recovery_grant(envelope_bytes(payload=gap), now=TRUSTED_NOW)
    assert validate_recovery_grant(envelope_bytes(), now=TRUSTED_NOW).window_seconds == 300


def test_rejected_step82_incompatible_schema() -> None:
    """The former Step 82 schema constant no longer conforms at any level."""
    legacy_payload = payload_fields(schema=LEGACY_STEP82_SCHEMA)
    with pytest.raises(RecoveryGrantError, match="differs from the accepted recovery-grant"):
        validate_recovery_grant(envelope_bytes(payload=legacy_payload), now=TRUSTED_NOW)
    with pytest.raises(RecoveryGrantError, match="differs from the approved signed"):
        validate_recovery_grant(envelope_bytes(schema=LEGACY_STEP82_SCHEMA),
                                now=TRUSTED_NOW)


def test_rejected_step82_incompatible_action() -> None:
    """The former Step 82 action token no longer conforms."""
    with pytest.raises(RecoveryGrantError, match="not an approved action"):
        validate_recovery_grant(envelope_bytes(authorized_action=LEGACY_STEP82_ACTION),
                                now=TRUSTED_NOW)


def test_rejected_step82_uuid_sid() -> None:
    """A UUID-shaped issuer_sid no longer conforms to the approved Windows SID form."""
    with pytest.raises(RecoveryGrantError, match="bounded Windows SID form"):
        validate_recovery_grant(envelope_bytes(issuer_sid=GRANT_ID), now=TRUSTED_NOW)


def test_rejected_wrong_key_issuer_id() -> None:
    """A different issuer key ID is rejected at both envelope and payload level."""
    with pytest.raises(RecoveryGrantError, match="differs from the approved"):
        validate_recovery_grant(envelope_bytes(
            payload=payload_fields(issuer_key_id="other-key-1")), now=TRUSTED_NOW)
    with pytest.raises(RecoveryGrantError, match="Envelope issuer key identity differs"):
        validate_recovery_grant(envelope_bytes(payload=payload_fields(
            issuer_key_id=APPROVED_ISSUER_KEY_ID), issuer_key_id="other-key-1"),
            now=TRUSTED_NOW)


def test_envelope_schema_rejection() -> None:
    """A non-Step-73 envelope schema is rejected independently of the payload."""
    with pytest.raises(RecoveryGrantError, match="differs from the approved signed"):
        validate_recovery_grant(envelope_bytes(schema="module10-recovery-grant-v0"),
                                now=TRUSTED_NOW)


def test_signature_shape_rejections() -> None:
    """Signature byte length is bounded to the accepted RSA-3072 SHA shape."""
    shorts = base64.b64encode(b"\x07" * 383).decode("ascii")
    with pytest.raises(RecoveryGrantError, match="differs from the accepted RSA-3072"):
        validate_recovery_grant(envelope_bytes(signature=shorts), now=TRUSTED_NOW)
    longs = base64.b64encode(b"\x07" * 385).decode("ascii")
    with pytest.raises(RecoveryGrantError, match="differs from the accepted RSA-3072"):
        validate_recovery_grant(envelope_bytes(signature=longs), now=TRUSTED_NOW)
    forced = bytes(range(256)) * 2 + b"\x00" * 128
    standard = base64.b64encode(forced).decode("ascii")
    assert "/" in standard or "+" in standard
    with pytest.raises(RecoveryGrantError, match="canonical base64 transport"):
        validate_recovery_grant(envelope_bytes(signature=
            standard.replace("/", "_").replace("+", "-")), now=TRUSTED_NOW)


def test_nan_and_infinity_constants_fail_controlled() -> None:
    """JSON NaN/Infinity tokens surface the controlled RecoveryGrantError text."""
    for interruption in (b"NaN", b"Infinity", b"-Infinity"):
        rendered = canonical(payload_fields()).replace(
            b'"maximum_execution_attempts":1',
            b'"maximum_execution_attempts":' + interruption)
        envelope = json.loads(envelope_bytes())
        envelope["payload_base64"] = base64.b64encode(rendered).decode("ascii")
        envelope["payload_sha256"] = hashlib.sha256(rendered).hexdigest()
        with pytest.raises(RecoveryGrantError, match="NaN/Infinity"):
            validate_recovery_grant(json.dumps(envelope).encode("utf-8"), now=TRUSTED_NOW)
    raw = (b'{"approval_reference":"x-1","schema":"taie.module10.recovery-grant.v1",'
           b'"maximum_execution_attempts":NaN}')
    with pytest.raises(RecoveryGrantError, match="NaN/Infinity"):
        validate_recovery_grant(envelope_bytes(payload_base64=base64.b64encode(
            raw).decode("ascii"), payload_sha256=hashlib.sha256(raw).hexdigest()),
            now=TRUSTED_NOW)
    with pytest.raises(RecoveryGrantError, match="NaN/Infinity"):
        validate_recovery_grant(b'{"envelope_version":NaN}', now=TRUSTED_NOW)


def test_naive_evaluation_instant_fails_closed() -> None:
    """A naive trusted evaluation instant is bounded out before any comparison."""
    with pytest.raises(RecoveryGrantError, match="timezone-aware"):
        validate_recovery_grant(envelope_bytes(), now=TRUSTED_NOW.replace(tzinfo=None))
    structure = validate_recovery_grant(envelope_bytes(), now=TRUSTED_NOW)
    assert structure.grant_id == GRANT_ID


@pytest.mark.parametrize("instant", ["now", 1, datetime(2026, 1, 15, 12, 0, 0)],
                         ids=["string", "int", "naive-datetime"])
def test_non_datetime_evaluation_instants_fail_controlled(instant: object) -> None:
    """Neither AttributeError nor TypeError may escape for invalid instants."""
    with pytest.raises(RecoveryGrantError, match="timezone-aware"):
        validate_recovery_grant(envelope_bytes(), now=instant)


def test_duplicate_keys_fail_controlled() -> None:
    """Duplicate JSON keys surface the controlled error at envelope level."""
    injected = b'{"envelope_version":1,"envelope_version":1,"algorithm":"rsa-pss-sha256"}'
    with pytest.raises(RecoveryGrantError, match="duplicate keys"):
        validate_recovery_grant(injected, now=TRUSTED_NOW)
    raw = b'{"schema":"taie.module10.recovery-grant.v1","schema":"x"}'
    with pytest.raises(RecoveryGrantError, match="duplicate keys"):
        validate_recovery_grant(envelope_bytes(payload_base64=base64.b64encode(raw).decode(
            "ascii"), payload_sha256=hashlib.sha256(raw).hexdigest()), now=TRUSTED_NOW)


def test_noncanonical_payload_representation_rejected() -> None:
    """Noncanonical JSON byte forms cannot attach to the envelope digest."""
    noncanonical = json.dumps(payload_fields()).encode("utf-8")
    assert noncanonical != canonical(payload_fields())
    with pytest.raises(RecoveryGrantError, match="representation is not canonical"):
        validate_recovery_grant(envelope_bytes(payload_base64=base64.b64encode(
            noncanonical).decode("ascii"),
            payload_sha256=hashlib.sha256(noncanonical).hexdigest()), now=TRUSTED_NOW)


@pytest.mark.parametrize("stamp", [
    "2026-01-15T12:00:00", "2026-01-15T12:00:00+00:00", "2026-01-15 12:00:00Z",
    "2026-1-15T12:00:00Z", "2026-01-15T24:00:00Z", "2026-02-30T12:00:00Z",
    "26-01-15T12:00:00Z", "2026-01-15T12:00:00.500Z", "", 3, None,
])
def test_invalid_utc_timestamp_forms_fail_controlled(stamp: object) -> None:
    """Only second-precision ending-Z canonical stamps survive the timestamp check."""
    with pytest.raises(RecoveryGrantError, match="timestamp is not canonical UTC"):
        validate_recovery_grant(envelope_bytes(issued_at_utc=stamp), now=TRUSTED_NOW)


def test_payload_digest_exact_byte_binding() -> None:
    """The envelope digest must be lowercase 64-hex and equal SHA-256 of the payload."""
    with pytest.raises(RecoveryGrantError, match="lowercase SHA-256 projection"):
        validate_recovery_grant(envelope_bytes(payload_sha256="A" * 64), now=TRUSTED_NOW)
    borrowed = hashlib.sha256(b"other-bytes").hexdigest()
    with pytest.raises(RecoveryGrantError, match="does not carry the exact payload bytes"):
        validate_recovery_grant(envelope_bytes(payload_sha256=borrowed), now=TRUSTED_NOW)
    exact = validate_recovery_grant(envelope_bytes(), now=TRUSTED_NOW)
    assert exact.grant_id == GRANT_ID


def test_time_ordering_and_maximum_window_failures() -> None:
    """Canonical ordering, bounded 900-second windows and deadline containment."""
    with pytest.raises(RecoveryGrantError, match="time ordering"):
        validate_recovery_grant(envelope_bytes(issued_at_utc="2026-01-15T12:30:00Z"),
                                now=TRUSTED_NOW)
    with pytest.raises(RecoveryGrantError, match="time ordering"):
        validate_recovery_grant(envelope_bytes(not_before_utc="2026-01-15T12:10:00Z",
                                               expires_at_utc="2026-01-15T12:05:00Z"),
                                now=TRUSTED_NOW)
    with pytest.raises(RecoveryGrantError, match="experiment deadline"):
        validate_recovery_grant(envelope_bytes(experiment_deadline_utc=
                                               "2026-01-14T12:04:00Z"), now=TRUSTED_NOW)


def test_give_max_execution_attempts_failures() -> None:
    """Budgeting bounds must be 1..3 inclusive."""
    with pytest.raises(RecoveryGrantError, match="bounded allowance"):
        validate_recovery_grant(envelope_bytes(maximum_execution_attempts=0),
                                now=TRUSTED_NOW)
    with pytest.raises(RecoveryGrantError, match="bounded allowance"):
        validate_recovery_grant(envelope_bytes(maximum_execution_attempts=4),
                                now=TRUSTED_NOW)


def test_expiration_and_future_effect_fail_closed() -> None:
    """Expired or not-yet-effective grants fail against a trusted timezone-aware instant."""
    with pytest.raises(RecoveryGrantError, match="expired or not yet effective"):
        validate_recovery_grant(envelope_bytes(), now=TRUSTED_NOW.replace(year=2027))
    future_payload = payload_fields(not_before_utc="2026-02-01T12:00:00Z",
                                    expires_at_utc="2026-02-01T12:04:00Z",
                                    experiment_deadline_utc="2026-02-01T12:04:00Z")
    with pytest.raises(RecoveryGrantError, match="expired or not yet effective"):
        validate_recovery_grant(envelope_bytes(payload=future_payload), now=TRUSTED_NOW)


def test_resource_identity_inconsistency_fails_closed() -> None:
    """Mismatched subscription/group/app resource IDs cannot ride the envelope."""
    with pytest.raises(RecoveryGrantError, match="internally consistent"):
        validate_recovery_grant(envelope_bytes(expected_resource_id="not-an-id"),
                                now=TRUSTED_NOW)
    with pytest.raises(RecoveryGrantError, match="internally consistent"):
        validate_recovery_grant(envelope_bytes(expected_resource_id=
            f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/other-group/providers/"
            "Microsoft.App/containerApps/m10-api-reviewa"), now=TRUSTED_NOW)


def test_missing_payload_and_envelope_fields_fail_closed() -> None:
    """Absent or extra fields never repair themselves."""
    eliminated = payload_fields()
    eliminated.pop("approval_reference")
    with pytest.raises(RecoveryGrantError, match="fields differ from the schema"):
        validate_recovery_grant(envelope_bytes(payload=eliminated), now=TRUSTED_NOW)
    envelope = json.loads(envelope_bytes())
    envelope["extra"] = "stray"
    with pytest.raises(RecoveryGrantError, match="fields differ from the schema"):
        validate_recovery_grant(json.dumps(envelope).encode("utf-8"), now=TRUSTED_NOW)


def test_hostile_identifier_forms_fail_fixed() -> None:
    """Malformed identifiers yield the fixed bounded-identity diagnostics only."""
    for override, message in (
            ({"issuer_sid": "BEARER-opens-door"}, "bounded Windows SID form"),
            ({"issuer_sid": "S-2-5-5"}, "bounded Windows SID form"),
            ({"grant_id": GRANT_ID + "0"}, "canonical UUID"),
            ({"resource_group": ""}, "bounded external name"),
            ({"resource_group": 5}, "bounded external name"),
            ({"container_app": "foreign-something"}, "bounded verifier application"),
            ({"issuer_key_id": "sinister-key\x00"}, "bounded application identifier")):
        with pytest.raises(RecoveryGrantError, match=message):
            validate_recovery_grant(envelope_bytes(payload_fields(**override)),
                                    now=TRUSTED_NOW)


def test_hostile_payload_values_never_enter_diagnostics() -> None:
    """Every error message is fixed text; hostile payload values never reflect."""
    cases = (
        {"resource_group": "hostile-value\r\ninjection"},
        {"approval_reference": "Bearer;rm -rf"},
        {"expected_pre_recovery_state": "hostile\u202evalue"},
        {"schema": "injection--victim"},
    )
    for case in cases:
        with pytest.raises(RecoveryGrantError) as error:
            validate_recovery_grant(envelope_bytes(payload_fields(**case)), now=TRUSTED_NOW)
        message = str(error.value)
        assert "hostile" not in message and "injection" not in message
        assert "\r\n" not in message and "\u202e" not in message


@pytest.mark.parametrize("field", sorted(PAYLOAD_KEYS))
def test_every_signed_field_must_have_a_value(field: str) -> None:
    """All 23 signed fields participate individually: removing one always fails."""
    content = payload_fields()
    content.pop(field)
    with pytest.raises(RecoveryGrantError, match="fields differ from the schema"):
        validate_recovery_grant(envelope_bytes(payload=content), now=TRUSTED_NOW)


def test_missing_related_context_tests() -> None:
    """Extraction of conflicting or malformed context fails closed."""
    over_budget = payload_fields(expires_at_utc="2026-01-15T12:06:00Z",
                                 experiment_deadline_utc="2026-01-15T12:05:00Z")
    with pytest.raises(RecoveryGrantError, match="experiment deadline"):
        validate_recovery_grant(envelope_bytes(payload=over_budget), now=TRUSTED_NOW)
    deadline_is_before = payload_fields(experiment_deadline_utc="2026-01-14T12:04:00Z")
    with pytest.raises(RecoveryGrantError, match="experiment deadline"):
        validate_recovery_grant(envelope_bytes(payload=deadline_is_before), now=TRUSTED_NOW)


def test_oversized_transport_fails_closed() -> None:
    """Beyond the fixed envelope bound the parser fails closed without parsing."""
    bulky = envelope_bytes() + b" " * 20000
    with pytest.raises(RecoveryGrantError, match="transport size"):
        validate_recovery_grant(bulky, now=TRUSTED_NOW)
