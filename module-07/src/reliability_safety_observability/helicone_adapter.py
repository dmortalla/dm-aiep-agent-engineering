"""Story 7 Helicone gateway evidence adapter: transport and evidence, never authority.

Application-owned wire protocol, implemented and documented at implementation
time against the actually supported Helicone HTTP protocol:

- Gateway routing path: the adapter produces ``HeliconeGatewayRoutingSpec`` —
  allowlisted composed headers onto the caller's provider request mapping, in
  the Helicone gateway proxy pattern (gateway origin plus required headers).
  The provider call itself is executed by the application's provider-call
  lanes, never by this adapter. Required headers: ``Helicone-Auth``
  (Bearer credential), ``Helicone-Request-Id`` (application UUID of record),
  ``Helicone-Session-Id`` (trace UUID), ``Helicone-Target-URL``
  (application-owned validated provider target) and the fixed
  ``Helicone-Property-*`` set. ``Helicone-User-Id`` is never sent.
  Gateway-side fallback ROUTING is not adopted; gateway-side fallback is
  observed as untrusted evidence only.
- Evidence export path: ``POST {evidence_api_base_url}/custom/v1/log`` with
  ``Authorization: Bearer <key>`` (vendor-required for the custom log API)
  plus ``Helicone-Auth: Bearer <key>``, ``Helicone-Request-Id`` and
  ``Helicone-Session-Id``; body ``{"_type": "data", "log": {...}}`` carrying
  only the allowlisted primitive fields built from the export specification.
  The Story 7 live check performs exactly one such synthetic non-model log
  write (zero billable model calls).
- Evidence readback path: ``GET {evidence_api_base_url}/api/v1/request/{id}``,
  returning one gateway request-log record parsed strictly over the bounded
  allowlisted projection keys (``helicone_request_id``/``request_id``,
  ``session_id``/``trace_id``, ``cost_usd``/``costUSD``, ``fallback``/
  ``_fallback``/``provider_fallback``, ``fallback_to``/``fallbackTo``). Cost
  fields are consumed as bounded finite nonnegative USD values in the
  canonical unit the gateway documents; unknown fields are always dropped.

Security-critical owned machinery (never-refunded ledger, origin-pinned
zero-retry boundary with redirect refusal, response-size cap, handoff clock,
secret shapes) is reused by import from the accepted Story 6 LangSmith adapter
so it exists exactly once in Module 7; a thin dual-origin mount serves the
two distinct protocol origins of this vendor protocol. Everything returned by
Helicone is untrusted; nothing can authorize, retry, fall back, refund,
mutate Story 3 accounting, mint provenance or upgrade its own evidence class.
The single ``live_vendor`` mint lives inside the owned
``run_live_helicone_verification`` wrapper behind the complete gate chain.
"""

import asyncio
import json
import logging
import math
import os
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Final
from urllib.parse import urlsplit
from uuid import UUID

import requests

from .domain import EvidenceClass
from .errors import ConfigurationError, ModuleSevenError
from .evaluation_contracts import identity_uuid
from .helicone_config import HeliconeSettings, require_live_helicone
from .langsmith_adapter import (
    _MONOTONIC_CLOCK,
    _SECRET_PATTERNS,
    _OwnedHttpBoundary,
    _RequestLedger,
    _run_bounded,
    _seam_origin,
)
from .langsmith_config import qualify_https_endpoint

_LIVE_OPT_IN_ENV: Final = "MODULE7_HELICONE_LIVE_VERIFICATION"
_LIVE_VERIFICATION_LABEL: Final = "module7_live_verification"
_MAX_META_ENTRIES: Final = 16
_MAX_STRING_VALUE: Final = 256
_MAX_TIMESTAMPED_COST_USD: Final = 1_000_000_000.0

HELICONE_AUTH_HEADER: Final = "Helicone-Auth"
HELICONE_REQUEST_ID_HEADER: Final = "Helicone-Request-Id"
HELICONE_SESSION_ID_HEADER: Final = "Helicone-Session-Id"
HELICONE_TARGET_URL_HEADER: Final = "Helicone-Target-URL"
HELICONE_PROPERTY_WORKFLOW_HEADER: Final = "Helicone-Property-Module7-Workflow"
HELICONE_PROPERTY_ACTION_HEADER: Final = "Helicone-Property-Module7-Action"
HELICONE_PROPERTY_EVIDENCE_HEADER: Final = "Helicone-Property-Module7-Evidence"

_COMPOSED_HEADER_ALLOWLIST: Final[frozenset[str]] = frozenset({
    HELICONE_AUTH_HEADER,
    HELICONE_REQUEST_ID_HEADER,
    HELICONE_SESSION_ID_HEADER,
    HELICONE_TARGET_URL_HEADER,
    HELICONE_PROPERTY_WORKFLOW_HEADER,
    HELICONE_PROPERTY_ACTION_HEADER,
    HELICONE_PROPERTY_EVIDENCE_HEADER,
})

_EVIDENCE_LOG_TYPE: Final = "data"
_CUSTOM_LOG_PATH: Final = "/custom/v1/log"
_REQUEST_QUERY_PATH: Final = "/api/v1/request/"


class RefusalSource:
    """Fixed, secret-free reason identifiers for bounded refusals."""

    CLOSED = "adapter_closed"
    TRANSPORT = "transport_rejected"
    BUDGET = "budget_refused"
    READBACK_MISMATCH = "readback_correlation_mismatch"
    OVERSIZED_RESPONSE = "response_too_large"
    MALFORMED_EVIDENCE = "malformed_evidence"
    REDIRECT = "redirect_refused"
    ENDPOINT = "endpoint_refused"
    DEADLINE = "live_deadline_exhausted"
    REPEAT_EXPORT = "request_already_exported"
    GATEWAY_REFUSED = "gateway_refused"
    CALLER_HEADER_OVERRIDE = "caller_helicone_header_override"


class HeliconeEvidenceError(ModuleSevenError):
    """Fixed-message bounded refusal; never carries gateway or record content."""

    def __init__(self, reason: str) -> None:
        """Create a refusal.

        Args:
            reason: A fixed secret-free reason identifier.
        """
        super().__init__(f"Helicone gateway evidence refused ({reason}).")
        self.reason = reason


def _translate_boundary_error(exc: Exception) -> HeliconeEvidenceError:
    """Map the shared accepted boundary's fixed refusals onto Story 7 reasons.

    Args:
        exc: The raised boundary error carrying a fixed reason identifier.

    Returns:
        An equivalent fixed Story 7 refusal; never vendor or record content.
    """
    reason = getattr(exc, "reason", None)
    mapped = reason if isinstance(reason, str) and reason else RefusalSource.TRANSPORT
    return HeliconeEvidenceError(mapped)


class _HeliconeLogFilter(logging.Filter):
    """Containment for vendor-adjacent log records; never reproduces vendor text.

    Records emitted through Helicone-adjacent logger names are collapsed to
    one fixed application-owned safe representation: no vendor message text,
    formatting arguments or exception content is retained or rendered; only
    the record's own application-side severity survives. Ordinary application
    records emitted during containment render normally, with configured-value
    and bounded secret-shape redaction as defense in depth. Tracebacks and
    stack content are always stripped.
    """

    _VENDOR_PREFIX: Final = "helicone"
    _ELIDED_MESSAGE: Final = (
        "Helicone log record elided; vendor message text is not rendered."
    )

    def __init__(self, values: Iterable[str]) -> None:
        super().__init__()
        self._values = tuple(value for value in values if value)

    def filter(self, record: logging.LogRecord) -> bool:
        if str(record.name).casefold().startswith(self._VENDOR_PREFIX):
            record.msg, record.args = self._ELIDED_MESSAGE, None
            record.exc_info, record.exc_text, record.stack_info = None, None, None
            return True
        try:
            message = record.getMessage()
        except Exception:
            message = "Application log record could not be formatted safely."
        for value in self._values:
            message = message.replace(value, "[REDACTED]")
        for pattern in _SECRET_PATTERNS:
            message = pattern.sub("[REDACTED]", message)
        record.msg, record.args = message, None
        record.exc_info, record.exc_text, record.stack_info = None, None, None
        return True


def _descendant_helicone_loggers() -> list[logging.Logger]:
    """Enumerate Helicone-adjacent logger names for containment, explicitly."""
    names = {"helicone", "helicone.gateway"}
    for name in logging.Logger.manager.loggerDict:
        if isinstance(name, str) and name.casefold().startswith("helicone"):
            names.add(name)
    return [logging.getLogger(name) for name in sorted(names)]


def _primitive(value: object) -> bool:
    """Return whether a value is a bounded, JSON-safe primitive."""
    return value is None or isinstance(value, (str, int, float, bool))


def _validate_map(name: str, mapping: Mapping[str, object]) -> None:
    """Validate a bounded primitive mapping for allowlisted spec fields.

    Args:
        name: The spec field name for error messages, never values.
        mapping: The candidate mapping.

    Raises:
        ValueError: Naming the rejected field, never its values.
    """
    if len(mapping) > _MAX_META_ENTRIES:
        raise ValueError(f"Export field {name} exceeds the bounded entry count.")
    for key, value in mapping.items():
        if not isinstance(key, str) or not key or len(key) > 64:
            raise ValueError(f"Export field {name} uses an unsupported key pattern.")
        if not _primitive(value):
            raise ValueError(f"Export field {name} requires bounded primitives.")
        if isinstance(value, str) and len(value) > _MAX_STRING_VALUE:
            raise ValueError(f"Export field {name} exceeds the size bound.")


def _refuse_caller_helicone_headers(base: Mapping[str, object]) -> None:
    """Refuse caller-supplied Helicone-header overrides in a base mapping.

    Args:
        base: The caller-supplied base header mapping being composed.

    Raises:
        HeliconeEvidenceError: For any Helicone-keyed caller override: the
            adapter alone composes the allowlisted Helicone headers, so
            caller, model, provider, retrieval or vendor data can never
            override the composition.
    """
    for key in base:
        if isinstance(key, str) and key.casefold().startswith("helicone"):
            raise HeliconeEvidenceError(RefusalSource.CALLER_HEADER_OVERRIDE)


@dataclass(frozen=True, slots=True)
class HeliconeGatewayRoutingSpec:
    """Immutable application-owned gateway routing specification.

    Attributes:
        action_id: Application request UUID of record (``Helicone-Request-Id``).
        trace_id: Application trace UUID of record (``Helicone-Session-Id``).
        workflow_id: Application workflow UUID of record.
        evidence_class: The application evidence class of record.
    """

    action_id: UUID
    trace_id: UUID
    workflow_id: UUID
    evidence_class: EvidenceClass
    _settings: HeliconeSettings = field(repr=False)

    def compose_headers(self, base: Mapping[str, object]) -> dict[str, str]:
        """Compose allowlisted Helicone headers onto a caller-supplied base mapping.

        The credential is unwrapped from validated settings only at composition
        time and is never stored, logged, repr'd or exported. Caller-supplied
        Helicone-header keys are refused outright, so no caller, model,
        provider, retrieval or vendor data can override the composition.

        Args:
            base: The caller-supplied base header mapping.

        Returns:
            A new mapping of only the base and allowlisted Helicone headers.

        Raises:
            HeliconeEvidenceError: For a Helicone-keyed caller override.
            ConfigurationError: For incomplete settings.
        """
        _refuse_caller_helicone_headers(base)
        key = self._settings.api_key
        if key is None:
            raise ConfigurationError("Helicone routing requires complete settings.")
        helicone_headers: dict[str, str] = {
            HELICONE_AUTH_HEADER: f"Bearer {key.get_secret_value()}",
            HELICONE_REQUEST_ID_HEADER: str(self.action_id),
            HELICONE_SESSION_ID_HEADER: str(self.trace_id),
            HELICONE_TARGET_URL_HEADER: self._settings.provider_target_url or "",
            HELICONE_PROPERTY_WORKFLOW_HEADER: str(self.workflow_id),
            HELICONE_PROPERTY_ACTION_HEADER: str(self.action_id),
            HELICONE_PROPERTY_EVIDENCE_HEADER: self.evidence_class.value,
        }
        return {**dict(base), **helicone_headers}


def build_gateway_routing_spec(
    runtime: object,
    settings: HeliconeSettings,
    *,
    action_id: UUID,
    trace_id: UUID,
    workflow_id: UUID,
    evidence_class: EvidenceClass,
) -> HeliconeGatewayRoutingSpec | None:
    """Build the routing spec under the complete application-owned gate.

    Args:
        runtime: Accepted Story 1 live runtime settings.
        settings: Validated Helicone settings.
        action_id: Application request UUID of record.
        trace_id: Application trace UUID of record.
        workflow_id: Application workflow UUID of record.
        evidence_class: The application evidence class of record.

    Returns:
        None when Helicone is disabled (deterministic startup constructs no
        routing), otherwise the fully gated routing specification.

    Raises:
        ConfigurationError: When enabled outside the activated live gate.
        ValueError: For non-canonical application identity inputs.
    """
    if not settings.enabled:
        return None
    if not require_live_helicone(runtime, settings):
        raise ConfigurationError("Helicone gateway routing requires the live gate.")
    for name, value in (
        ("action_id", action_id), ("trace_id", trace_id),
        ("workflow_id", workflow_id),
    ):
        if not isinstance(value, UUID):
            raise ValueError(f"{name} requires a canonical application UUID.")
    if not isinstance(evidence_class, EvidenceClass):
        raise ValueError("evidence_class requires an application-owned class.")
    return HeliconeGatewayRoutingSpec(
        action_id=action_id,
        trace_id=trace_id,
        workflow_id=workflow_id,
        evidence_class=evidence_class,
        _settings=settings,
    )


_EVIDENCE_KEYS: Final = (
    "classification", "attempts", "fallback_used", "fallbacks", "replayed",
    "effect_count", "authorization", "safety", "budget_outcome",
)


@dataclass(frozen=True, slots=True)
class HeliconeEvidenceExportSpec:
    """Immutable, application-owned export specification, primitives only.

    Attributes:
        request_id: Application request UUID string of record.
        session_id: Application trace UUID string of record.
        workflow_id: Application workflow UUID string of record.
        evidence_label: Fixed application evidence label of record.
        provider_request_intent: Bounded provider-request intent primitives.
        application_meta: Bounded application facts of record.
        observed_evidence: Bounded untrusted observed-response summary.
        timing: Bounded documented timing anchors.
    """

    request_id: str
    session_id: str
    workflow_id: str
    evidence_label: str
    provider_request_intent: dict[str, object]
    application_meta: dict[str, object]
    observed_evidence: dict[str, object]
    timing: dict[str, object]

    def worst_case_requests(self) -> int:
        """Return the worst-case HTTP request count for this bounded spec.

        Returns:
            One custom-log submit plus one bounded readback request.
        """
        return 2

    @staticmethod
    def build(
        *,
        request_id: str,
        session_id: str,
        workflow_id: str,
        evidence_label: str,
        application_meta: Mapping[str, object],
        provider_request_intent: Mapping[str, object] | None = None,
        observed_evidence: Mapping[str, object] | None = None,
        timing: Mapping[str, object] | None = None,
    ) -> "HeliconeEvidenceExportSpec":
        """Build and fully validate one export specification.

        Args:
            request_id: Application request UUID string of record.
            session_id: Application trace UUID string of record.
            workflow_id: Application workflow UUID string of record.
            evidence_label: Fixed application evidence label of record.
            application_meta: The allowlisted facts summary of record.
            provider_request_intent: Optional bounded intent primitives.
            observed_evidence: Optional bounded observed response summary.
            timing: Optional bounded timing anchors.

        Returns:
            The validated, immutable export specification (primitives only).

        Raises:
            ValueError: Naming the rejected field, never its values.
        """
        application_meta = dict(application_meta)
        unknown = set(application_meta) - set(_EVIDENCE_KEYS)
        if unknown:
            raise ValueError("application_meta uses an unsupported key pattern.")
        spec = HeliconeEvidenceExportSpec(
            request_id=str(request_id),
            session_id=str(session_id),
            workflow_id=str(workflow_id),
            evidence_label=str(evidence_label),
            provider_request_intent=dict(provider_request_intent or {}),
            application_meta=application_meta,
            observed_evidence=dict(observed_evidence or {}),
            timing=dict(timing or {}),
        )
        for name in ("request_id", "session_id", "workflow_id"):
            _ = UUID(getattr(spec, name))
        if not spec.evidence_label or len(spec.evidence_label) > 64:
            raise ValueError("evidence_label uses an unsupported value pattern.")
        _validate_map("provider_request_intent", spec.provider_request_intent)
        _validate_map("application_meta", spec.application_meta)
        _validate_map("observed_evidence", spec.observed_evidence)
        _validate_map("timing", spec.timing)
        return spec


def custom_log_body(spec: HeliconeEvidenceExportSpec) -> dict[str, object]:
    """Build the fixed, allowlisted synthetic custom-log request body.

    Args:
        spec: The validated export specification.

    Returns:
        A new primitives-only body; contains no secrets, prompts or outputs.
    """
    return {
        "_type": _EVIDENCE_LOG_TYPE,
        "log": {
            "helicone_request_id": spec.request_id,
            "provider": "module7-synthetic-evidence",
            "meta": {
                "action_id": spec.request_id,
                "trace_id": spec.session_id,
                "workflow_id": spec.workflow_id,
                "application_evidence_label": spec.evidence_label,
                "provider_request_intent": spec.provider_request_intent,
                "application_meta": spec.application_meta,
                "observed_evidence": spec.observed_evidence,
                "timing": spec.timing,
            },
        },
    }


_ROW_ID_FIELDS: Final = (
    "helicone_request_id", "request_id", "Helicone-Request-Id",
)
_ROW_SESSION_FIELDS: Final = ("session_id", "trace_id", "Helicone-Session-Id")
_ROW_COST_FIELDS: Final = ("cost_usd", "costUSD")
_ROW_FALLBACK_FIELDS: Final = ("fallback", "_fallback", "provider_fallback")
_ROW_FALLBACK_TARGET_FIELDS: Final = ("fallback_to", "fallbackTo")


def _row_field(row: Mapping[str, object], names: tuple[str, ...]) -> object | None:
    """Return the first allowlisted present field value in a projected row."""
    for name in names:
        if name in row and row[name] is not None:
            return row[name]
    return None


def _trustworthy_fallback_used(value: object) -> bool | None:
    """Parse a gateway fallback-used field as trustworthy state only.

    Args:
        value: The raw field value.

    Returns:
        True/False when the value is a usable boolean; None when absent,
        non-primitive or otherwise untrusted (unknown).
    """
    if isinstance(value, bool):
        return value
    return None


def _trustworthy_fallback_target(value: object) -> str | None:
    """Parse a gateway fallback target field into usable identity only."""
    if not isinstance(value, str) or not value or len(value) > _MAX_STRING_VALUE:
        return None
    return value


def _finite_nonnegative_cost(value: object) -> float | None:
    """Parse a bounded finite nonnegative USD cost value or return None."""
    if isinstance(value, bool) or not _primitive(value):
        return None
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed) or parsed < 0.0 or parsed > _MAX_TIMESTAMPED_COST_USD:
        return None
    return parsed


@dataclass(frozen=True, slots=True)
class HeliconeReadbackResult:
    """Bounded readback correlation result over projected gateway rows.

    Attributes:
        request_id: The compared application request identity.
        session_id: The compared application trace identity.
        usable_rows: Rows matching the application-owned correlation identity.
        unrelated_rows: Rows with a non-matching identity (contributed nothing).
        stale_rows: Rows with a matching request but a non-matching session.
        ambiguous_rows: Extra duplicate usable rows (ambiguity).
        conflicting_rows: Conflicting matching-row sets beyond one resolution.
        malformed_rows: Rows dropped for non-dict unusable shape.
        confirmed_correlation: True only for exactly one clean matching row.
        unresolved: True when ambiguity or conflict prevents clean correlation.
    """

    request_id: str
    session_id: str
    usable_rows: tuple[dict[str, object], ...]
    unrelated_rows: int
    stale_rows: int
    ambiguous_rows: int
    conflicting_rows: int
    malformed_rows: int
    confirmed_correlation: bool
    unresolved: bool

    @staticmethod
    def project(
        rows: object,
        *,
        request_id: str,
        session_id: str,
    ) -> "HeliconeReadbackResult":
        """Project raw readback rows with the bounded correlation rules.

        Rows that do not match the application-owned request/correlation
        identity contribute nothing. Rows with a matching request but a
        non-matching session are stale or replayed and can never establish
        confirmation. More than one usable row is an ambiguous duplicate set
        that can never establish confirmed provenance; conflicting matching
        rows fail safe. Unknown or ambiguous correlations stay unresolved.

        Args:
            rows: Raw parsed rows (an iterable of primitive dicts or one dict).
            request_id: The application request identity of record.
            session_id: The application trace identity of record.

        Returns:
            The bounded projected result.
        """
        usable: list[dict[str, object]] = []
        unrelated = stale = malformed = 0
        candidate_rows: object = rows
        if isinstance(candidate_rows, Mapping):
            candidate_rows = [candidate_rows]
        if not isinstance(candidate_rows, (list, tuple)):
            malformed += 1
            candidate_rows = []
        for raw in candidate_rows:
            if not isinstance(raw, Mapping) or any(
                not isinstance(key, str) for key in raw
            ):
                malformed += 1
                continue
            raw_id = _row_field(raw, _ROW_ID_FIELDS)
            raw_session = _row_field(raw, _ROW_SESSION_FIELDS)
            if raw_id is None or str(raw_id) != request_id:
                unrelated += 1
                continue
            if raw_session is None or str(raw_session) != session_id:
                stale += 1
                continue
            projected: dict[str, object] = {}
            if _row_field(raw, _ROW_ID_FIELDS) is not None:
                projected["helicone_request_id"] = str(raw_id)
            if _row_field(raw, _ROW_SESSION_FIELDS) is not None:
                projected["session_id"] = str(raw_session)
            if _row_field(raw, _ROW_COST_FIELDS) is not None:
                projected["cost_usd"] = _row_field(raw, _ROW_COST_FIELDS)
            if _row_field(raw, _ROW_FALLBACK_FIELDS) is not None:
                projected["fallback"] = _row_field(raw, _ROW_FALLBACK_FIELDS)
            if _row_field(raw, _ROW_FALLBACK_TARGET_FIELDS) is not None:
                projected["fallback_to"] = _row_field(
                    raw, _ROW_FALLBACK_TARGET_FIELDS
                )
            usable.append(projected)
        conflicting = _conflicting_row_count(usable)
        confirmed = len(usable) == 1 and conflicting == 0
        return HeliconeReadbackResult(
            request_id=request_id,
            session_id=session_id,
            usable_rows=tuple(usable),
            unrelated_rows=unrelated,
            stale_rows=stale,
            ambiguous_rows=max(0, len(usable) - 1),
            conflicting_rows=conflicting,
            malformed_rows=malformed,
            confirmed_correlation=confirmed,
            unresolved=not confirmed,
        )


def _conflicting_row_count(usable: list[dict[str, object]]) -> int:
    """Return whether usable rows conflict beyond a single resolution.

    Args:
        usable: The projected rows matching the correlation identity.

    Returns:
        0 when the rows are mutually consistent; 1 when any field disagrees
        between rows (fail-safe conflict) or when parsed values are unusable.
    """
    if len(usable) < 2:
        return 0
    costs = {
        _finite_nonnegative_cost(_row_field(row, _ROW_COST_FIELDS)) for row in usable
    }
    fallbacks = {
        _trustworthy_fallback_used(_row_field(row, _ROW_FALLBACK_FIELDS))
        for row in usable
    }
    targets = {
        _trustworthy_fallback_target(_row_field(row, _ROW_FALLBACK_TARGET_FIELDS))
        for row in usable
    }
    if len(costs) > 1 or len(fallbacks) > 1 or len(targets) > 1:
        return 1
    return 0


COST_STATES: Final[frozenset[str]] = frozenset(
    {"match", "disagree", "missing", "malformed"}
)


@dataclass(frozen=True, slots=True)
class HeliconeCostEvidenceState:
    """Classified cost evidence state; evidence, never budget authority.

    Attributes:
        state: One of match/disagree/missing/malformed.
        gateway_cost_usd: The bounded parsed gateway-observed cost, or None.
        app_cost_usd: The application cost of record used for comparison.
        malformed_rows: Count of dropped malformed rows.
    """

    state: str
    gateway_cost_usd: float | None
    app_cost_usd: float
    malformed_rows: int


def classify_cost_evidence(
    app_cost_usd: object,
    readback: HeliconeReadbackResult,
    *,
    tolerance: float,
) -> HeliconeCostEvidenceState:
    """Classify gateway-observed cost against the application cost of record.

    Exactly one valid unambiguous matching record may classify normally.
    Duplicate, conflicting or ambiguous cost evidence fails safe into already
    defined non-authoritative states under the accepted taxonomy (never
    ``match``); no new state and no new authority class exists. Observed cost
    is recorded evidence and never refunds, credits, increases budget,
    authorizes another request or mutates Story 3 accounting.

    Args:
        app_cost_usd: The application cost of record (finite, nonnegative).
        readback: The bounded projected readback result.
        tolerance: Finite nonnegative absolute tolerance for ``match``.

    Returns:
        The classified bounded cost evidence state.

    Raises:
        ValueError: For a non-finite/negative application cost or tolerance.
    """
    app_cost = _finite_nonnegative_cost(app_cost_usd)
    if app_cost is None:
        raise ValueError("Application cost of record must be finite and nonnegative.")
    if not math.isfinite(tolerance) or tolerance < 0.0:
        raise ValueError("Cost tolerance must be finite and nonnegative.")
    if len(readback.usable_rows) == 0:
        state = "malformed" if readback.malformed_rows else "missing"
        return HeliconeCostEvidenceState(
            state=state, gateway_cost_usd=None,
            app_cost_usd=app_cost, malformed_rows=readback.malformed_rows,
        )
    if readback.unresolved:
        # Duplicate/ambiguous/conflicting rows fail safe, never ``match``.
        return HeliconeCostEvidenceState(
            state="malformed", gateway_cost_usd=None,
            app_cost_usd=app_cost, malformed_rows=readback.malformed_rows,
        )
    observed = _finite_nonnegative_cost(
        _row_field(readback.usable_rows[0], _ROW_COST_FIELDS)
    )
    if observed is None:
        return HeliconeCostEvidenceState(
            state="malformed", gateway_cost_usd=None,
            app_cost_usd=app_cost, malformed_rows=readback.malformed_rows + 1,
        )
    state = "match" if abs(observed - app_cost) <= tolerance else "disagree"
    return HeliconeCostEvidenceState(
        state=state, gateway_cost_usd=observed,
        app_cost_usd=app_cost, malformed_rows=readback.malformed_rows,
    )


FALLBACK_STATES: Final[frozenset[str]] = frozenset(
    {"agree", "disagree", "gateway_only", "app_only", "unknown"}
)
FALLBACK_OBSERVED_STATES: Final[frozenset[str]] = frozenset(
    {"none", "observed", "unknown"}
)


@dataclass(frozen=True, slots=True)
class HeliconeFallbackEvidenceState:
    """Classified fallback evidence state; evidence classification only.

    Attributes:
        state: One of agree/disagree/gateway_only/app_only/unknown.
        gateway_fallback_observed: One of none/observed/unknown.
        fallback_target: The bounded gateway fallback target, or None.
    """

    state: str
    gateway_fallback_observed: str
    fallback_target: str | None


def classify_fallback_evidence(
    app_fallback_used: object,
    app_fallback_targets: object,
    readback: HeliconeReadbackResult,
) -> HeliconeFallbackEvidenceState:
    """Classify the exact accepted application/gateway fallback truth table.

    ``unknown`` is mandatory whenever either side lacks sufficient trustworthy
    evidence. The table is evidence classification only: it can never trigger,
    schedule, veto, strengthen or authorize any application fallback, retry,
    timeout or idempotency decision, and cannot create a new application
    action or effect. When both sides record fallback, a known-and-detailed
    target mismatch classifies ``disagree``; otherwise boolean-level
    fallback agreement classifies ``agree``.

    Args:
        app_fallback_used: The authoritative Story 3 ``fallback_used`` decision.
        app_fallback_targets: The authoritative Story 3 fallback targets.
        readback: The bounded projected readback result.

    Returns:
        The classified bounded fallback evidence state.
    """
    app_known = isinstance(app_fallback_used, bool)
    app_used = bool(app_fallback_used) if app_known else False
    app_targets: tuple[str, ...] | None = None
    if isinstance(app_fallback_targets, (list, tuple)) and all(
        isinstance(value, str) for value in app_fallback_targets
    ):
        app_targets = tuple(app_fallback_targets)  # type: ignore[arg-type]
    if len(readback.usable_rows) != 1:
        # No or multiple usable matching rows: the gateway side is unknown.
        return HeliconeFallbackEvidenceState(
            state="unknown", gateway_fallback_observed="unknown",
            fallback_target=None,
        )
    row = readback.usable_rows[0]
    gateway_used = _trustworthy_fallback_used(_row_field(row, _ROW_FALLBACK_FIELDS))
    gateway_target = _trustworthy_fallback_target(
        _row_field(row, _ROW_FALLBACK_TARGET_FIELDS)
    )
    gateway_state = (
        "unknown" if gateway_used is None
        else "observed" if gateway_used else "none"
    )
    if not app_known or gateway_state == "unknown":
        return HeliconeFallbackEvidenceState(
            state="unknown", gateway_fallback_observed=gateway_state,
            fallback_target=gateway_target,
        )
    if not app_used and not gateway_used:
        return HeliconeFallbackEvidenceState(
            state="agree", gateway_fallback_observed="none", fallback_target=None,
        )
    if not app_used and gateway_used:
        return HeliconeFallbackEvidenceState(
            state="gateway_only", gateway_fallback_observed="observed",
            fallback_target=gateway_target,
        )
    if app_used and not gateway_used:
        return HeliconeFallbackEvidenceState(
            state="app_only", gateway_fallback_observed="none",
            fallback_target=None,
        )
    detailed = gateway_target is not None and bool(app_targets)
    if detailed and app_targets is not None and gateway_target not in app_targets:
        return HeliconeFallbackEvidenceState(
            state="disagree", gateway_fallback_observed="observed",
            fallback_target=gateway_target,
        )
    return HeliconeFallbackEvidenceState(
        state="agree", gateway_fallback_observed="observed",
        fallback_target=gateway_target,
    )


@dataclass(frozen=True, slots=True)
class HeliconeEvidenceSnapshot:
    """Application-owned evidence snapshot assembled from bounded readback.

    Attributes:
        request_id: Application request identity of record.
        session_id: Application trace identity of record.
        workflow_id: Application workflow identity of record.
        correlation_matched: True only for exactly one matching usable row.
        cost_state: The classified cost state.
        gateway_cost_usd: The bounded observed cost or None.
        fallback_state: The classified fallback evidence state.
        gateway_fallback_observed: The projected gateway fallback state.
        unrelated_rows/stale_rows/ambiguous_rows/conflicting_rows/malformed_rows:
            Correlation count evidence of record.
    """

    request_id: str
    session_id: str
    workflow_id: str
    correlation_matched: bool
    cost_state: str
    gateway_cost_usd: float | None
    fallback_state: str
    gateway_fallback_observed: str
    unrelated_rows: int
    stale_rows: int
    ambiguous_rows: int
    conflicting_rows: int
    malformed_rows: int


def build_evidence_snapshot(
    spec: HeliconeEvidenceExportSpec,
    readback: HeliconeReadbackResult,
    *,
    app_cost_usd: object,
    app_fallback_used: object,
    app_fallback_targets: object,
    tolerance: float,
) -> HeliconeEvidenceSnapshot:
    """Assemble the bounded evidence snapshot from readback and app facts.

    Args:
        spec: The export specification carrying correlation identity.
        readback: The bounded projected readback result.
        app_cost_usd: The application cost of record.
        app_fallback_used: The authoritative Story 3 fallback decision.
        app_fallback_targets: The authoritative Story 3 fallback targets.
        tolerance: The finite nonnegative cost tolerance.

    Returns:
        The frozen snapshot; evidence only, never an authority upgrade.
    """
    cost = classify_cost_evidence(app_cost_usd, readback, tolerance=tolerance)
    fallback = classify_fallback_evidence(
        app_fallback_used, app_fallback_targets, readback
    )
    return HeliconeEvidenceSnapshot(
        request_id=spec.request_id,
        session_id=spec.session_id,
        workflow_id=spec.workflow_id,
        correlation_matched=readback.confirmed_correlation,
        cost_state=cost.state,
        gateway_cost_usd=cost.gateway_cost_usd,
        fallback_state=fallback.state,
        gateway_fallback_observed=fallback.gateway_fallback_observed,
        unrelated_rows=readback.unrelated_rows,
        stale_rows=readback.stale_rows,
        ambiguous_rows=readback.ambiguous_rows,
        conflicting_rows=readback.conflicting_rows,
        malformed_rows=readback.malformed_rows,
    )


class HeliconeEvidenceTransport:
    """Typed transport surface implemented by fakes and the HTTP transport."""

    evidence_class: EvidenceClass | None = None

    def submit_evidence(self, spec: HeliconeEvidenceExportSpec) -> None:
        """Execute the bounded evidence submit; raise on any refusal."""
        raise NotImplementedError

    def read_back(self, spec: HeliconeEvidenceExportSpec) -> list[dict[str, object]]:
        """Bounded readback of the gateway record for the spec's request."""
        raise NotImplementedError

    def close(self) -> bool:
        """Close the transport exactly once, reporting failure as False."""
        raise NotImplementedError


class FakeHeliconeEvidenceTransport(HeliconeEvidenceTransport):
    """Deterministic fake transport for contract tests; never live evidence.

    Captures submitted specifications and returns configured rows; it never
    performs I/O, environment reads or waits, and it never upgrades evidence.
    """

    evidence_class = EvidenceClass.MOCKED_PROVIDER_CONTRACT

    def __init__(
        self,
        *,
        failure: str | None = None,
        rows: list[dict[str, object]] | None = None,
        readback_failure: str | None = None,
    ) -> None:
        self._failure = failure
        self._readback_failure = readback_failure
        self._rows = list(rows or [])
        self._closed = False
        self._exported: set[str] = set()
        self.submitted: list[HeliconeEvidenceExportSpec] = []
        self.readback_calls = 0
        self.close_calls = 0

    def submit_evidence(self, spec: HeliconeEvidenceExportSpec) -> None:
        """Record one spec or raise the configured fixed failure.

        Args:
            spec: The validated export specification.

        Raises:
            HeliconeEvidenceError: When configured to fail or repeated.
        """
        if self._failure is not None:
            raise HeliconeEvidenceError(self._failure)
        if spec.request_id in self._exported:
            raise HeliconeEvidenceError(RefusalSource.REPEAT_EXPORT)
        self._exported.add(spec.request_id)
        self.submitted.append(spec)

    def read_back(
        self, spec: HeliconeEvidenceExportSpec
    ) -> list[dict[str, object]]:
        """Return the configured deterministic rows.

        Args:
            spec: The compared export specification.

        Returns:
            The configured rows; configured failures raise fixed refusals.
        """
        self.readback_calls += 1
        if self._readback_failure is not None:
            raise HeliconeEvidenceError(self._readback_failure)
        return [dict(row) for row in self._rows]

    def close(self) -> bool:
        """Close the fake; idempotent."""
        self.close_calls += 1
        closed = not self._closed
        self._closed = True
        return closed


@dataclass(frozen=True, slots=True)
class _OriginEndpointView:
    """Minimal settings view satisfying the accepted boundary's duck contract."""

    api_url: str
    request_timeout_seconds: float


def _origin_key(url: str) -> tuple[str, str, int]:
    """Return the normalized (scheme, host, port) origin key of a base URL."""
    parts = urlsplit(url)
    port = parts.port or (443 if parts.scheme == "https" else 80)
    return (parts.scheme, parts.hostname or "", port)


def loopback_http_origin(url: str) -> bool:
    """Return whether the URL is an explicit loopback HTTP origin."""
    parts = urlsplit(url)
    return (
        parts.scheme == "http"
        and parts.hostname is not None
        and parts.hostname in {"127.0.0.1", "::1", "localhost"}
    )


class _DualOriginBoundary:
    """Mount of the accepted single-origin boundary for one filled origin set.

    The accepted boundary exists exactly once in Module 7; this mount routes
    each prepared request to the accepted boundary instance registered for
    its exact origin and refuses unknown origins without any request.
    """

    def __init__(
        self,
        boundaries: dict[tuple[str, str, int], _OwnedHttpBoundary],
    ) -> None:
        self._boundaries = boundaries

    def send(self, request: object, **kwargs: object) -> requests.Response:
        """Route one prepared request to its exact origin boundary.

        Args:
            request: The prepared request.
            **kwargs: Forwarded to the accepted boundary mount.

        Returns:
            A fully read bounded response.

        Raises:
            HeliconeEvidenceError: For an unregistered origin (without charge).
        """
        parsed = urlsplit(getattr(request, "url", ""))
        origin = (
            parsed.scheme,
            parsed.hostname or "",
            parsed.port or (443 if parsed.scheme == "https" else 80),
        )
        boundary = self._boundaries.get(origin)
        if boundary is None:
            raise HeliconeEvidenceError(RefusalSource.TRANSPORT)
        try:
            return boundary.send(request, **kwargs)
        except ModuleSevenError as exc:
            raise _translate_boundary_error(exc) from None

    def close(self) -> None:
        """Own nothing at session-close time (accepted boundary mirroring)."""
        return None

    def set_deadline(self, deadline: float | None) -> None:
        """Bind the whole-run live deadline onto every origin boundary."""
        for boundary in self._boundaries.values():
            boundary._live_deadline = deadline

    @property
    def deadline_refused(self) -> bool:
        """Return whether any origin boundary refused on the deadline."""
        return any(
            boundary._deadline_refused for boundary in self._boundaries.values()
        )


class HeliconeHttpEvidenceTransport(HeliconeEvidenceTransport):
    """Real HTTP-backed evidence transport over a strictly owned session.

    Blocking operations run on the shared tracked worker lane. The owned
    boundary mount enforces exact origins, zero retries, redirect refusal,
    bounded responses and timeout forwarding; every actual HTTP request is
    charged to the shared never-refunded ledger, including failures. The
    session is ``trust_env=False`` and transport verification stays on; no
    ambient proxy or configuration authority is accepted.
    """

    evidence_class = EvidenceClass.MOCKED_PROVIDER_CONTRACT

    def __init__(
        self,
        settings: HeliconeSettings,
        *,
        runtime: object | None = None,
        in_process_seam: Callable[
            [list[dict[str, object]], object], bytes | None
        ] | None = None,
        opt_in: bool = False,
    ) -> None:
        """Construct the HTTP-backed transport.

        Args:
            settings: Validated, enabled, budgeted Helicone settings.
            runtime: Required live runtime settings for real construction.
            in_process_seam: Optional documented test seam; reserved for the
                non-routable test origin and never reachable by the live
                verification branch, which accepts no caller-supplied anything.
            opt_in: Explicit live-call opt-in, required for real construction.

        Raises:
            ConfigurationError: Without explicit live settings, explicit
                opt-in or a qualifying endpoint set.
        """
        if settings.gateway_base_url is None or settings.evidence_api_base_url is None:
            raise ConfigurationError(
                "Helicone transport requires complete validated base URLs."
            )
        seam_on_reserved = in_process_seam is not None and (
            _seam_origin(settings.gateway_base_url)
            and _seam_origin(settings.evidence_api_base_url)
        )
        if in_process_seam is not None and not seam_on_reserved:
            raise ConfigurationError(
                "The in-process seam is reserved for the non-routable test origin."
            )
        fails_gate = (
            runtime is None or not require_live_helicone(runtime, settings)
        )
        if fails_gate or not opt_in:
            raise ConfigurationError(
                "Network Helicone evidence requires explicit live settings "
                "and explicit opt-in."
            )
        self._settings = settings
        self._seam = in_process_seam
        self._exported: set[str] = set()
        self._ledger = _RequestLedger(
            max_requests=settings.max_http_requests,
            reservation_per_request_usd=settings.reservation_per_request_usd,
            run_cost_limit_usd=settings.run_cost_limit_usd,
        )
        self._initialize(settings)

    def _initialize(self, settings: HeliconeSettings) -> None:
        """Qualify endpoints and construct the strictly owned session boundary.

        Args:
            settings: The validated Helicone settings of record.

        Raises:
            ConfigurationError: Without qualifying endpoints or credentials.
        """
        if settings.api_key is None:
            raise ConfigurationError(
                "Helicone transport requires enabled, complete settings."
            )
        self._live_qualified = False
        for url in (settings.gateway_base_url, settings.evidence_api_base_url):
            parts = urlsplit(url or "")
            reserved = _seam_origin(url)
            if reserved and self._seam is not None:
                continue  # The documented non-routable test seam origin only.
            if reserved:
                raise ConfigurationError(
                    "Helicone transport requires a qualifying endpoint."
                )
            if parts.scheme == "https":
                qualify_https_endpoint(url or "")
                self._live_qualified = settings.is_remote_https_endpoint() and (
                    settings.is_remote_evidence_https_endpoint()
                )
            elif not loopback_http_origin(url or ""):
                raise ConfigurationError(
                    "Helicone transport requires a qualifying endpoint."
                )
        session = requests.Session()
        session.trust_env = False
        self._session = session
        self._log_filter = _HeliconeLogFilter((settings.api_key.get_secret_value(),))
        self._loggers = _descendant_helicone_loggers()
        for logger in self._loggers:
            logger.addFilter(self._log_filter)
        self._adapter = requests.adapters.HTTPAdapter(max_retries=0)
        boundaries: dict[tuple[str, str, int], _OwnedHttpBoundary] = {}
        for url in (settings.gateway_base_url, settings.evidence_api_base_url):
            key = _origin_key(url or "")
            if key not in boundaries:
                boundaries[key] = _OwnedHttpBoundary(
                    _OriginEndpointView(
                        api_url=url or "",
                        request_timeout_seconds=settings.request_timeout_seconds,
                    ),
                    self._ledger,
                    self._adapter,
                    seam=self._seam,
                )
        self._boundary = _DualOriginBoundary(boundaries)
        session.mount("http://", self._boundary)
        session.mount("https://", self._boundary)
        self._closed = False
        self._close_attempted = False
        self._close_result = False

    def _detach(self) -> None:
        for logger in self._loggers:
            logger.removeFilter(self._log_filter)

    def _evidence_headers(self, spec: HeliconeEvidenceExportSpec) -> dict[str, str]:
        """Compose the exact allowlisted evidence request headers.

        Credentials are unwrapped at composition time only; they never enter
        logs, evidence bodies or exception text.

        Args:
            spec: The export specification carrying correlation identity.

        Returns:
            The header mapping for the vendor-required transport.

        Raises:
            ConfigurationError: For incomplete settings.
        """
        key = self._settings.api_key
        if key is None:
            raise ConfigurationError(
                "Helicone transport requires enabled, complete settings."
            )
        return {
            "Authorization": f"Bearer {key.get_secret_value()}",
            HELICONE_AUTH_HEADER: f"Bearer {key.get_secret_value()}",
            HELICONE_REQUEST_ID_HEADER: spec.request_id,
            HELICONE_SESSION_ID_HEADER: spec.session_id,
        }

    def submit_evidence(self, spec: HeliconeEvidenceExportSpec) -> None:
        """Blocking strict execution of one bounded custom-log submit.

        Args:
            spec: The validated export specification.

        Raises:
            HeliconeEvidenceError: With a fixed refusal reason, never content.
        """
        if self._closed:
            raise HeliconeEvidenceError(RefusalSource.CLOSED)
        if spec.request_id in self._exported:
            raise HeliconeEvidenceError(RefusalSource.REPEAT_EXPORT)
        url = f"{self._settings.evidence_api_base_url}{_CUSTOM_LOG_PATH}"
        body = custom_log_body(spec)
        prepared = requests.Request(
            "POST", url, json=body, headers=self._evidence_headers(spec)
        ).prepare()
        try:
            response = self._session.send(prepared)
        except ModuleSevenError as exc:
            raise _translate_boundary_error(exc) from None
        except Exception:
            raise HeliconeEvidenceError(RefusalSource.TRANSPORT) from None
        if response.status_code < 200 or response.status_code >= 300:
            raise HeliconeEvidenceError(RefusalSource.GATEWAY_REFUSED)
        self._exported.add(spec.request_id)

    def read_back(self, spec: HeliconeEvidenceExportSpec) -> list[dict[str, object]]:
        """Bounded readback of the gateway record for the application request.

        Args:
            spec: The export specification carrying correlation identity.

        Returns:
            The parsed primitive rows (the one-record endpoint wrapped as a
            single row; zero rows when the record is absent).

        Raises:
            HeliconeEvidenceError: With a fixed refusal reason, never content.
        """
        if self._closed:
            raise HeliconeEvidenceError(RefusalSource.CLOSED)
        url = (
            f"{self._settings.evidence_api_base_url}"
            f"{_REQUEST_QUERY_PATH}{spec.request_id}"
        )
        prepared = requests.Request(
            "GET", url, headers=self._evidence_headers(spec)
        ).prepare()
        try:
            response = self._session.send(prepared)
        except ModuleSevenError as exc:
            raise _translate_boundary_error(exc) from None
        except Exception:
            raise HeliconeEvidenceError(RefusalSource.TRANSPORT) from None
        if response.status_code == 404:
            return []
        if response.status_code < 200 or response.status_code >= 300:
            raise HeliconeEvidenceError(RefusalSource.GATEWAY_REFUSED)
        try:
            payload = json.loads(response.text)
        except (ValueError, TypeError):
            raise HeliconeEvidenceError(RefusalSource.MALFORMED_EVIDENCE) from None
        if isinstance(payload, Mapping):
            return [dict(payload)]
        if isinstance(payload, list):
            return [
                dict(row)
                for row in payload
                if isinstance(row, Mapping)
            ]
        raise HeliconeEvidenceError(RefusalSource.MALFORMED_EVIDENCE)

    def close(self) -> bool:
        """Close the owned session through public APIs; safe to repeat."""
        if self._close_attempted:
            return self._close_result
        self._close_attempted = True
        try:
            self._session.close()
        except Exception:
            self._close_result = False
        else:
            self._closed = True
            self._detach()
            self._close_result = True
        return self._close_result

    def accounting(self) -> dict[str, float | int]:
        """Return the application-owned request/cost accounting of record."""
        return self._ledger.accounting()


async def submit_evidence_bounded(
    transport: HeliconeEvidenceTransport,
    spec: HeliconeEvidenceExportSpec,
    timeout: float,
) -> tuple[str, None, threading.Thread]:
    """Submit one spec on the tracked lane, bounded by the caller.

    Args:
        transport: Trusted transport (HTTP-backed or deterministic fake).
        spec: The validated export specification.
        timeout: Whole-submit wait bound in seconds.

    Returns:
        ("ok", None, thread), ("timeout", None, thread) (ownership retained,
        never upgraded to complete), ("failed", None, thread) or
        ("busy", None, thread) per the shared lane.
    """
    return await _run_bounded(
        lambda: transport.submit_evidence(spec), timeout, owner=transport
    )


async def read_back_bounded(
    transport: HeliconeEvidenceTransport,
    spec: HeliconeEvidenceExportSpec,
    timeout: float,
) -> tuple[str, list[dict[str, object]] | None, threading.Thread]:
    """Read back one spec on the tracked lane, bounded by the caller.

    Args:
        transport: Trusted transport.
        spec: The validated export specification.
        timeout: Whole-readback wait bound in seconds.

    Returns:
        ("ok", rows, thread), ("timeout", None, thread), ("failed", None,
        thread) or ("busy", None, thread).
    """
    return await _run_bounded(
        lambda: transport.read_back(spec), timeout, owner=transport
    )


async def close_bounded(
    transport: HeliconeEvidenceTransport, timeout: float
) -> tuple[str, bool | None, threading.Thread]:
    """Close a transport on the tracked lane, bounded by the caller.

    Args:
        transport: Trusted transport.
        timeout: Close wait bound in seconds.

    Returns:
        ("ok", True, thread) when cleanly closed; ("timeout"/"busy", None,
        thread) leaves ownership unresolved and reports close_busy;
        ("failed", False, thread).
    """
    return await _run_bounded(transport.close, timeout, owner=transport)


@dataclass(frozen=True, slots=True)
class HeliconeLiveVerificationResult:
    """Live verification evidence; live_vendor only after the confirmed chain.

    Attributes:
        outcome: Fixed outcome label of record.
        evidence_class: live_vendor only from the owned confirmed chain.
        request_id: Application request identity of record.
        session_id: Application trace identity of record.
        workflow_id: Application workflow identity of record.
        confirmed_readback: The bounded readback correlation confirmation.
        close_state: Bounded close state of record.
        evidence: Credential-free evidence fragment; never a live claim.
    """

    outcome: str
    evidence_class: EvidenceClass | None
    request_id: str
    session_id: str
    workflow_id: str
    confirmed_readback: bool
    close_state: str
    evidence: dict[str, object] = field(default_factory=dict)


def _helicone_provenance_qualification(transport: object) -> bool:
    """Return whether this transport may carry ``live_vendor`` provenance.

    Qualification is application-owned and independent of any caller, provider
    or transport claim: only the exact owned HTTP transport class, constructed
    through its own qualification paths that passed full bounded endpoint
    qualification, without any mounted seam, on syntactically remote HTTPS
    endpoints, can ever qualify. Fakes, seams, local servers, subclasses,
    caller-supplied flags and matching IDs can never satisfy it.

    Args:
        transport: The transport whose provenance is being judged.

    Returns:
        True only for a fully provenance-qualified owned live transport.
    """
    if type(transport) is not HeliconeHttpEvidenceTransport:
        return False
    if getattr(transport, "_live_qualified", False) is not True:
        return False
    if transport._seam is not None:
        return False
    settings = transport._settings
    if not settings.is_remote_https_endpoint():
        return False
    if not settings.is_remote_evidence_https_endpoint():
        return False
    return not (
        _seam_origin(settings.gateway_base_url)
        or _seam_origin(settings.evidence_api_base_url)
    )


def _live_plan_requests(settings: HeliconeSettings) -> int:
    """Return the finite worst-case live request count (submit + readbacks)."""
    return 1 + settings.readback_attempts


def build_live_verification_spec() -> HeliconeEvidenceExportSpec:
    """Build the fixed synthetic custom-log export spec for the live check.

    Returns:
        The deterministic bounded specification: a synthetic non-model log
        record with zero billable model calls and fixed application-owned
        correlation identity derived from the Story 7 namespace.
    """
    request_id = str(identity_uuid(
        ("helicone-live-verification", "request", _LIVE_VERIFICATION_LABEL)
    ))
    session_id = str(identity_uuid(
        ("helicone-live-verification", "session", _LIVE_VERIFICATION_LABEL)
    ))
    workflow_id = str(identity_uuid(
        ("helicone-live-verification", "workflow", _LIVE_VERIFICATION_LABEL)
    ))
    return HeliconeEvidenceExportSpec.build(
        request_id=request_id,
        session_id=session_id,
        workflow_id=workflow_id,
        evidence_label=_LIVE_VERIFICATION_LABEL,
        application_meta={
            "classification": "bounded_live_verification",
            "attempts": 0,
            "replayed": False,
            "effect_count": 0,
            "budget_outcome": "none",
        },
        provider_request_intent={"model": "none"},
        observed_evidence={},
        timing={"duration_ms": 0.0},
    )


def run_live_helicone_verification(
    runtime: object,
    settings: HeliconeSettings,
    *,
    opt_in: bool,
) -> HeliconeLiveVerificationResult:
    """Run the complete owned Helicone live verification branch.

    Everything is constructed inside this boundary: no caller-supplied
    transport, session, adapter, client or factory is accepted. Loopback and
    seam origins and non-remote HTTPS endpoints cannot proceed; the bounded
    budget plan must fit before the first request; a timeout of a required
    operation unresolves the run (never confirmed). The bounded operation
    performs exactly one synthetic non-model custom-log write plus bounded
    readback; gateway-routed meaningful use and provider-cost evidence belong
    to the separately authorized live run, never to this branch.

    Args:
        runtime: Accepted Story 1 live runtime settings.
        settings: Enabled, complete, budgeted Helicone settings.
        opt_in: Explicit live-call opt-in, separate from configuration.

    Returns:
        Verification evidence; ``live_vendor`` only when the owned chain
        completes with a confirmed matching readback on qualifying endpoints.

    Raises:
        ConfigurationError: Without explicit opt-in, the explicit opt-in
            variable, complete activation gates or qualifying endpoints.
    """
    if not opt_in:
        raise ConfigurationError(
            "Live Helicone verification requires explicit opt-in."
        )
    if os.environ.get(_LIVE_OPT_IN_ENV) != "1":
        raise ConfigurationError(
            f"Live Helicone verification requires the explicit "
            f"{_LIVE_OPT_IN_ENV}=1 opt-in variable."
        )
    if not require_live_helicone(runtime, settings):
        raise ConfigurationError(
            "Live Helicone verification requires enabled settings."
        )
    if not (
        settings.is_remote_https_endpoint()
        and settings.is_remote_evidence_https_endpoint()
    ):
        raise ConfigurationError(
            "Live Helicone verification requires non-loopback HTTPS endpoints."
        )
    if _seam_origin(settings.gateway_base_url) or _seam_origin(
        settings.evidence_api_base_url
    ):
        # The reserved non-routable test seam origin can never feed the live
        # branch: this refusal is deterministic and precedes qualification.
        raise ConfigurationError(
            "Live Helicone verification refuses the reserved test seam origin."
        )
    qualify_https_endpoint(settings.gateway_base_url or "")
    qualify_https_endpoint(settings.evidence_api_base_url or "")

    # Whole-run live deadline: begins at this accepted live-operation
    # boundary and covers submit, readback and wait behavior below.
    deadline: float | None = _MONOTONIC_CLOCK() + settings.live_deadline_seconds

    spec = build_live_verification_spec()
    ledger = _RequestLedger(
        max_requests=settings.max_http_requests,
        reservation_per_request_usd=settings.reservation_per_request_usd,
        run_cost_limit_usd=settings.run_cost_limit_usd,
    )
    if not ledger.plan_requests(_live_plan_requests(settings)):
        return HeliconeLiveVerificationResult(
            outcome=RefusalSource.BUDGET,
            evidence_class=None,
            request_id=spec.request_id,
            session_id=spec.session_id,
            workflow_id=spec.workflow_id,
            confirmed_readback=False,
            close_state="not_started",
            evidence=ledger.accounting(),
        )
    transport = HeliconeHttpEvidenceTransport(settings, runtime=runtime, opt_in=opt_in)
    transport._boundary.set_deadline(deadline)
    result = _execute_live(transport, spec, deadline=deadline)
    close_label = asyncio.run(
        _close_state(transport, settings.lifecycle_timeout_seconds)
    )
    if close_label == "busy":
        close_label = "close_busy"
    if result.outcome != "confirmed" or close_label != "closed":
        result = HeliconeLiveVerificationResult(
            outcome=result.outcome,
            evidence_class=None,
            request_id=result.request_id,
            session_id=result.session_id,
            workflow_id=result.workflow_id,
            confirmed_readback=result.confirmed_readback,
            close_state=close_label,
        )
    elif _helicone_provenance_qualification(transport):
        # The only live_vendor mint in the application: the owned chain,
        # after qualification, confirmed behavior and cleanly closed close,
        # upgrades the confirmed execution to live_vendor provenance here.
        result = HeliconeLiveVerificationResult(
            outcome=result.outcome,
            evidence_class=EvidenceClass.LIVE_VENDOR,
            request_id=result.request_id,
            session_id=result.session_id,
            workflow_id=result.workflow_id,
            confirmed_readback=result.confirmed_readback,
            close_state=close_label,
            evidence=result.evidence,
        )
    # Confirmed behavior on an unqualified transport stays capped at the
    # mocked/provider contract as produced by ``_execute_live``.
    return result


def _deadline_timeout_result(
    transport: HeliconeHttpEvidenceTransport,
    spec: HeliconeEvidenceExportSpec,
) -> HeliconeLiveVerificationResult:
    """Build the fixed ``timeout_unresolved`` whole-run deadline result.

    Args:
        transport: The owned HTTP transport whose accounting is retained.
        spec: The validated export specification of record.

    Returns:
        Unresolved evidence; the deadline never mints ``live_vendor`` and the
        request ledger is never refunded.
    """
    return HeliconeLiveVerificationResult(
        outcome="timeout_unresolved",
        evidence_class=None,
        request_id=spec.request_id,
        session_id=spec.session_id,
        workflow_id=spec.workflow_id,
        confirmed_readback=False,
        close_state="unresolved",
        evidence={"request_accounting": transport.accounting()},
    )


def _exhausted(
    transport: HeliconeHttpEvidenceTransport, deadline: float | None
) -> bool:
    """Return whether the whole-run deadline is exhausted (or was refused)."""
    mount = getattr(transport, "_boundary", None)
    if mount is not None and mount.deadline_refused:
        return True
    return deadline is not None and _MONOTONIC_CLOCK() >= deadline


def _execute_live(
    transport: HeliconeHttpEvidenceTransport,
    spec: HeliconeEvidenceExportSpec,
    *,
    deadline: float | None,
) -> HeliconeLiveVerificationResult:
    """Run submit and bounded readback without close ownership decisions.

    Args:
        transport: The owned HTTP transport (constructed inside the branch).
        spec: The validated export specification.
        deadline: Whole-run live deadline (monotonic reading), or None.

    Returns:
        Verification evidence with close_state deliberately left unresolved;
        closing is decided by the whole-branch owner afterwards. No new
        request may begin after the deadline; exhaustion reports the fixed
        safe ``timeout_unresolved`` status and never mints ``live_vendor``.
    """
    settings = transport._settings
    if _exhausted(transport, deadline):
        return _deadline_timeout_result(transport, spec)
    submit_result, _payload, _thread = asyncio.run(submit_evidence_bounded(
        transport, spec, settings.request_timeout_seconds * 3 + 30,
    ))
    label = "export_failed"
    confirmed_readback = False
    if submit_result == "timeout":
        return HeliconeLiveVerificationResult(
            outcome="timeout_unresolved",
            evidence_class=None,
            request_id=spec.request_id,
            session_id=spec.session_id,
            workflow_id=spec.workflow_id,
            confirmed_readback=False,
            close_state="unresolved",
        )
    if submit_result == "failed" and _exhausted(transport, deadline):
        return _deadline_timeout_result(transport, spec)
    if submit_result == "ok":
        label = "readback_not_confirmed"
        for attempt in range(settings.readback_attempts):
            if _exhausted(transport, deadline):
                return _deadline_timeout_result(transport, spec)
            result, rows, _thread = asyncio.run(read_back_bounded(
                transport, spec, settings.request_timeout_seconds * 3 + 30,
            ))
            if result == "timeout":
                label = "timeout_unresolved"
                break
            if result == "failed" and _exhausted(transport, deadline):
                return _deadline_timeout_result(transport, spec)
            if result == "busy":
                continue
            if result == "ok" and isinstance(rows, list):
                readback = HeliconeReadbackResult.project(
                    rows, request_id=spec.request_id, session_id=spec.session_id
                )
                if readback.confirmed_correlation:
                    confirmed_readback = True
                    label = "confirmed"
                    break
            if attempt + 1 < settings.readback_attempts:
                time.sleep(settings.readback_interval_seconds)
    # The mint cap: confirmed behavior proves limited execution success only.
    # ``_execute_live`` has no authority to mint ``live_vendor``; unqualified
    # execution (fake, seam, mocked, local or otherwise caller-reachable
    # origin) is capped at the mocked/provider contract. Only the owned
    # provenance-qualified live chain upgrades afterwards.
    evidence_class = (
        EvidenceClass.MOCKED_PROVIDER_CONTRACT if label == "confirmed" else None
    )
    return HeliconeLiveVerificationResult(
        outcome=label,
        evidence_class=evidence_class,
        request_id=spec.request_id,
        session_id=spec.session_id,
        workflow_id=spec.workflow_id,
        confirmed_readback=confirmed_readback,
        close_state="unresolved",
        evidence={"request_accounting": transport.accounting()},
    )


async def _close_state(
    transport: HeliconeHttpEvidenceTransport, timeout: float
) -> str:
    """Close within the lifecycle bound and return the fixed close label.

    Args:
        transport: The owned HTTP transport.
        timeout: Close wait bound in seconds.

    Returns:
        closed, close_failed or close_busy; a busy unresolved operation keeps
        its ownership and never reports a completed close.
    """
    outcome, value, _thread = await _run_bounded(
        transport.close, timeout, owner=transport
    )
    if outcome in {"timeout", "busy"}:
        return "close_busy"
    if outcome == "ok" and value is True:
        return "closed"
    return "close_failed"


__all__ = [
    "COST_STATES",
    "FALLBACK_OBSERVED_STATES",
    "FALLBACK_STATES",
    "HELICONE_AUTH_HEADER",
    "HELICONE_PROPERTY_ACTION_HEADER",
    "HELICONE_PROPERTY_EVIDENCE_HEADER",
    "HELICONE_PROPERTY_WORKFLOW_HEADER",
    "HELICONE_REQUEST_ID_HEADER",
    "HELICONE_SESSION_ID_HEADER",
    "HELICONE_TARGET_URL_HEADER",
    "FakeHeliconeEvidenceTransport",
    "HeliconeCostEvidenceState",
    "HeliconeEvidenceError",
    "HeliconeEvidenceExportSpec",
    "HeliconeEvidenceSnapshot",
    "HeliconeEvidenceTransport",
    "HeliconeFallbackEvidenceState",
    "HeliconeGatewayRoutingSpec",
    "HeliconeHttpEvidenceTransport",
    "HeliconeLiveVerificationResult",
    "HeliconeReadbackResult",
    "RefusalSource",
    "build_evidence_snapshot",
    "build_gateway_routing_spec",
    "build_live_verification_spec",
    "classify_cost_evidence",
    "classify_fallback_evidence",
    "close_bounded",
    "custom_log_body",
    "read_back_bounded",
    "run_live_helicone_verification",
    "submit_evidence_bounded",
]
