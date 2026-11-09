"""Pure fail-closed structural validation of the Step 73 signed recovery grant.

Human-approved Step 73 architecture: an exact 23 signed payload field set with
issuer key identity carried by the payload AND the separately versioned signature
envelope, locked to RSA-PSS-SHA256 with a 384-byte signature shape (RSA-3072
bindings are syntactically bounded; authenticity is out-of-band and NEVER
claimed here).

This module stays structurally incapable of authorisation: it never verifies
signatures, touches keys, issues grants, binds approval stores or replay
ledgers, or executes recovery. Every diagnostic is fixed application text.
"""

import base64
import binascii
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from module10_ai.azure_verification import VerificationError, resource_id

GRANT_SCHEMA = "taie.module10.recovery-grant.v1"
ENVELOPE_SCHEMA = "taie.module10.signed-grant-envelope.v1"
ENVELOPE_VERSION = 1
GRANT_VERSION = 1
ENVELOPE_KEYS = frozenset({"envelope_version", "schema", "issuer_key_id",
                           "payload_base64", "payload_sha256", "signature"})
PAYLOAD_KEYS = frozenset({
    "schema", "issuer_key_id", "grant_id", "experiment_id", "subscription_id",
    "resource_group", "container_app", "authorized_action", "restore_min_replicas",
    "restore_max_replicas", "issued_at_utc", "expires_at_utc", "experiment_deadline_utc",
    "issuer_sid", "approval_reference", "tenant_id", "expected_resource_id",
    "expected_pre_recovery_state", "approval_version", "approval_digest",
    "not_before_utc", "maximum_execution_attempts", "recovery_policy_version"})
APPROVED_ISSUER_KEY_ID = "TAIE-M10-Recovery-Grant-Issuer-v1"
AUTHORIZED_ACTIONS = ("restore_azure_container_app_scale",)
ACCEPTED_ALGORITHM = "rsa-pss-sha256"
ACCEPTED_PRE_RECOVERY_STATE = "scaled-to-zero"
APPROVAL_DIGEST_PATTERN = re.compile(r"sha256:[a-f0-9]{64}")
KEY_ID_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{2,64}")
TIME_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
STAMP = "%Y-%m-%dT%H:%M:%SZ"
UUID_PATTERN = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
WINDOWS_SID_PATTERN = re.compile(r"S-1-[0-9]{1,10}(-[0-9]{1,10}){1,14}")
CONTAINER_APP_PATTERN = re.compile(r"m10-api-[a-z][a-z0-9]{5,11}")
ROOT_NAME_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{2,63}")
REFERENCE_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{3,127}")
MAXIMUM_WINDOW = 900
MAXIMUM_EXECUTION_ATTEMPTS = 3
MAXIMUM_ENVELOPE_BYTES = 16384
CONTAINER_APP_PROVIDER = "Microsoft.App/containerApps"
RSA_3072_SIGNATURE_BYTES = 384


class RecoveryGrantError(VerificationError):
    """Fixed fail-closed diagnostics; parsing or signature shape is not authority."""


@dataclass(frozen=True)
class GrantStructure:
    """Validated structural projection; never execution authority."""
    grant_id: str
    experiment_id: str
    key_id: str
    issuer_sid: str
    subscription_id: str
    tenant_id: str
    resource_group: str
    container_app: str
    expected_resource_id: str
    authorized_action: str
    expected_pre_recovery_state: str
    approval_reference: str
    approval_version: str
    approval_digest: str
    issued_at_utc: str
    not_before_utc: str
    expires_at_utc: str
    experiment_deadline_utc: str
    window_seconds: int
    maximum_execution_attempts: int
    recovery_policy_version: int


def _need(condition: bool, message: str) -> None:
    """Fail closed with one fixed application-owned diagnostic."""
    if not condition:
        raise RecoveryGrantError(message)


def _reject_duplicates(pairs: list[tuple[str, object]]) -> object:
    """Reject duplicate JSON keys with the controlled recovery-grant error."""
    result: dict[str, object] = {}
    for key, value in pairs:
        _need(key not in result, "Grant JSON contains duplicate keys.")
        result[key] = value
    return result


def _reject_constant(token: str) -> None:
    """Reject nonstandard JSON constants (NaN/Infinity forms)."""
    raise RecoveryGrantError("Grant JSON contains NaN/Infinity constants.")


def _strict_json(raw: bytes, message: str) -> dict:
    """Decode strict UTF-8 JSON without duplicates or NaN/Infinity constants."""
    try:
        text = raw.decode("utf-8", errors="strict")
    except (UnicodeError, ValueError, AttributeError) as exc:
        raise RecoveryGrantError(message) from exc
    try:
        parsed = json.loads(text, object_pairs_hook=_reject_duplicates,
                            parse_constant=_reject_constant)
    except RecoveryGrantError:
        raise
    except (json.JSONDecodeError, ValueError) as exc:
        raise RecoveryGrantError(message) from exc
    _need(isinstance(parsed, dict), message)
    return parsed


def _instant(value: object, message: str) -> datetime:
    """Require second-precision canonical UTC timestamps; reject naive forms."""
    _need(type(value) is str and TIME_PATTERN.fullmatch(value) is not None, message)
    try:
        return datetime.strptime(str(value), STAMP).replace(tzinfo=UTC)
    except (ValueError, TypeError) as exc:
        raise RecoveryGrantError(message) from exc


def _canonical_uuid(value: object, message: str) -> str:
    """Require canonical nonzero lowercase UUID strings with a fixed diagnostic."""
    _need(type(value) is str and UUID_PATTERN.fullmatch(str(value)) is not None, message)
    try:
        parsed = UUID(value)
    except (ValueError, TypeError, AttributeError) as exc:
        raise RecoveryGrantError(message) from exc
    _need(str(parsed) == value and parsed.int != 0, message)
    return str(parsed)


def _resource_identity(value: object) -> str:
    """Normalize a complete subscription-scoped Azure identity or fail controlled."""
    try:
        return resource_id(value)
    except (VerificationError, ValueError, TypeError, AttributeError) as exc:
        raise RecoveryGrantError(
            "Expected resource identity is not bounded and internally consistent.") from exc


def _canonical_base64(value: object, message: str) -> bytes:
    """Require exactly canonical standard-alphabet base64 with padding, no whitespace."""
    _need(type(value) is str, message)
    text = str(value)
    _need(text != "" and not any(character.isspace() for character in text), message)
    try:
        decoded = base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError, UnicodeError) as exc:
        raise RecoveryGrantError(message) from exc
    _need(base64.b64encode(decoded) == text.encode("utf-8"), message)
    return decoded


def validate_recovery_grant(raw: bytes, now: datetime | None = None) -> GrantStructure:
    """Validate the Step 73 structure of a signed recovery grant offline.

    Args:
        raw: Exact operator-supplied envelope bytes.
        now: Optional trusted timezone-aware evaluation instant; defaults to
            current UTC. Non-datetime and naive values fail closed.

    Returns:
        Structural projection never carrying execution authority. The signature
        is carried syntactically with the RSA-3072 byte-length shape; cryptographic
        authenticity, approval binding and recovery execution remain separately
        owned and this parse authorizes nothing by itself.

    Raises:
        RecoveryGrantError: Malformed, duplicate-keyed, NaN/Infinity-bearing,
            missing, extra, noncanonical-byte, naive/non-datetime evaluation,
            wrong-schema/action/key-binding, wrong-scale, inconsistent-resource
            or malformed-identifier grants fail closed with fixed text.
    """
    _need(type(raw) is bytes and 0 < len(raw) <= MAXIMUM_ENVELOPE_BYTES,
          "Grant envelope transport size is not bounded.")
    envelope = _strict_json(raw, "Grant envelope is not strict UTF-8 JSON.")
    _need(set(envelope) == ENVELOPE_KEYS, "Grant envelope fields differ from the schema.")
    _need(type(envelope["envelope_version"]) is int
          and envelope["envelope_version"] == ENVELOPE_VERSION,
          "Grant envelope is not the accepted versioned form.")
    _need(type(envelope["schema"]) is str and envelope["schema"] == ENVELOPE_SCHEMA,
          "Grant envelope schema differs from the approved signed-grant-envelope schema.")
    key_id = str(envelope["issuer_key_id"])
    _need(type(envelope["issuer_key_id"]) is str
          and KEY_ID_PATTERN.fullmatch(key_id) is not None,
          "Envelope issuer key identity is not a bounded application identifier.")
    signature = _canonical_base64(envelope["signature"],
                                  "Grant signature is not canonical base64 transport.")
    _need(len(signature) == RSA_3072_SIGNATURE_BYTES,
          "Grant signature byte length differs from the accepted RSA-3072 shape.")
    payload_raw = _canonical_base64(envelope["payload_base64"],
                                    "Grant payload is not canonical base64 transport.")
    _need(type(envelope["payload_sha256"]) is str
          and re.fullmatch(r"[0-9a-f]{64}", envelope["payload_sha256"]) is not None,
          "Grant payload digest must be a lowercase SHA-256 projection.")
    _need(hashlib.sha256(payload_raw).hexdigest() == envelope["payload_sha256"],
          "Grant envelope does not carry the exact payload bytes it declares.")
    payload = _strict_json(payload_raw, "Grant payload is not strict UTF-8 JSON.")
    _need(payload_raw == json.dumps(payload, sort_keys=True,
                                    separators=(",", ":")).encode("utf-8"),
          "Grant payload representation is not canonical.")
    _need(set(payload) == PAYLOAD_KEYS, "Grant payload fields differ from the schema.")
    return _payload(payload, key_id, now)


def _payload(payload: dict, envelope_key_id: str, trusted_now: datetime | None) -> GrantStructure:
    """Validate the 23-field grant body with bounded types and internal consistency."""
    _need(type(payload["schema"]) is str and payload["schema"] == GRANT_SCHEMA,
          "Grant schema differs from the accepted recovery-grant schema.")
    payload_key_id = str(payload["issuer_key_id"])
    _need(type(payload["issuer_key_id"]) is str
          and KEY_ID_PATTERN.fullmatch(payload_key_id) is not None,
          "Issuer key identity is not a bounded application identifier.")
    _need(payload_key_id == APPROVED_ISSUER_KEY_ID,
          "Issuer key identity differs from the approved recovery-grant issuer.")
    _need(envelope_key_id == payload_key_id,
          "Envelope issuer key identity differs from the signed grant.")
    _need(type(payload["recovery_policy_version"]) is int
          and payload["recovery_policy_version"] == GRANT_VERSION,
          "Recovery policy version differs from the accepted policy version.")
    grant_id = _canonical_uuid(payload["grant_id"],
                               "Grant identifier is not a canonical UUID.")
    experiment_id = _canonical_uuid(payload["experiment_id"],
                                    "Experiment identifier is not a canonical UUID.")
    issuer_sid = str(payload["issuer_sid"])
    _need(type(issuer_sid) is str
          and WINDOWS_SID_PATTERN.fullmatch(issuer_sid) is not None,
          "Issuer security identifier does not match the bounded Windows SID form.")
    tenant_id = _canonical_uuid(payload["tenant_id"],
                                "Tenant identifier is not a canonical UUID.")
    subscription_id = _canonical_uuid(payload["subscription_id"],
                                      "Subscription identifier is not a canonical UUID.")
    group = payload["resource_group"]
    app = payload["container_app"]
    _need(type(group) is str and ROOT_NAME_PATTERN.fullmatch(group) is not None,
          "Resource-group identity is not a bounded external name.")
    _need(type(app) is str and CONTAINER_APP_PATTERN.fullmatch(app) is not None,
          "Container-app identity is not a bounded verifier application name.")
    expected_resource_id = str(payload["expected_resource_id"])
    expected_id = (f"/subscriptions/{subscription_id}/resourceGroups/{group}/"
                   f"providers/{CONTAINER_APP_PROVIDER}/{app}")
    _need(_resource_identity(expected_resource_id).lower() == expected_id.lower(),
          "Expected resource identity is not bounded and internally consistent.")
    actions = payload["authorized_action"]
    _need(type(actions) is str and actions in AUTHORIZED_ACTIONS,
          "Grant operation is not an approved action.")
    replicas = payload["restore_min_replicas"], payload["restore_max_replicas"]
    _need(type(replicas[0]) is int and type(replicas[1]) is int and replicas == (0, 2),
          "Grant scale bounds differ from the accepted deployment contract.")
    state = payload["expected_pre_recovery_state"]
    _need(type(state) is str and state == ACCEPTED_PRE_RECOVERY_STATE,
          "Expected pre-recovery state differs from the bounded acceptance.")
    approval_version = payload["approval_version"]
    _need(type(approval_version) is str
          and KEY_ID_PATTERN.fullmatch(approval_version) is not None,
          "Approval version is not a bounded application identifier.")
    _need(type(payload["approval_reference"]) is str
          and REFERENCE_PATTERN.fullmatch(str(payload["approval_reference"])) is not None,
          "Approval reference is not a bounded application identifier.")
    _need(type(payload["approval_digest"]) is str
          and APPROVAL_DIGEST_PATTERN.fullmatch(str(payload["approval_digest"])) is not None,
          "Approval digest is not a bounded SHA-256 binding.")
    attempts = payload["maximum_execution_attempts"]
    _need(type(attempts) is int and 1 <= attempts <= MAXIMUM_EXECUTION_ATTEMPTS,
          "Maximum execution attempts differ from the bounded allowance.")
    if trusted_now is not None:
        _need(type(trusted_now) is datetime,
              "Evaluation instant must be a timezone-aware datetime.")
        _need(trusted_now.tzinfo is not None,
              "Evaluation instant must be timezone-aware, not a naive datetime.")
    issued = _instant(payload["issued_at_utc"], "Grant issuance timestamp is not canonical UTC.")
    before = _instant(payload["not_before_utc"], "Grant start timestamp is not canonical UTC.")
    expires = _instant(payload["expires_at_utc"], "Grant expiry timestamp is not canonical UTC.")
    deadline = _instant(payload["experiment_deadline_utc"],
                        "Experiment deadline timestamp is not canonical UTC.")
    trusted = (trusted_now if trusted_now is not None else datetime.now(UTC))
    _need(issued <= before < expires, "Grant time ordering is not operational.")
    _need((expires - before).total_seconds() <= MAXIMUM_WINDOW,
          "Grant experiment window exceeds the bounded allowance.")
    _need(expires <= deadline,
          "Grant expiration must not exceed the experiment deadline.")
    _need(before <= trusted <= expires,
          "Grant is expired or not yet effective at the evaluation instant.")
    return GrantStructure(grant_id=grant_id, experiment_id=experiment_id,
                          key_id=payload_key_id, issuer_sid=issuer_sid,
                          subscription_id=subscription_id, tenant_id=tenant_id,
                          resource_group=group, container_app=app,
                          expected_resource_id=_resource_identity(
                              expected_resource_id).lower(),
                          authorized_action=str(actions),
                          expected_pre_recovery_state=str(state),
                          approval_reference=str(payload["approval_reference"]),
                          approval_version=str(approval_version),
                          approval_digest=str(payload["approval_digest"]),
                          issued_at_utc=str(payload["issued_at_utc"]),
                          not_before_utc=str(payload["not_before_utc"]),
                          expires_at_utc=str(payload["expires_at_utc"]),
                          experiment_deadline_utc=str(payload["experiment_deadline_utc"]),
                          window_seconds=int((expires - before).total_seconds()),
                          maximum_execution_attempts=int(attempts),
                          recovery_policy_version=int(payload["recovery_policy_version"]))
