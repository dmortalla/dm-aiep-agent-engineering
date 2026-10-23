"""Story 6 LangSmith adapter: minimized evaluation evidence, never authority.

Data path: deterministic run result -> application-owned ``LangSmithExportPlan``
(allowlisted fields only, deterministic IDs, no raw scenario text, no canaries)
-> ``LangSmithTransport`` -> LangSmith. Everything the SDK or any response
returns is untrusted and discarded except the bounded identifier/score
comparison in the opt-in live verification branch.

This is the only Module 7 file that imports the ``langsmith`` SDK (lazily)
and ``requests``. The SDK client runs on an adapter-owned zero-retry,
origin-checking ``requests`` session; retries are exactly zero at the adapter,
session and SDK call levels. Response bodies are read with a fixed 1 MiB
ceiling. OpenTelemetry providers, prompt caching and batch tracing threads are
never created. Vendor output is never authoritative for any application
decision; the complete confirmed chain over a non-loopback HTTPS endpoint
inside the owned live branch is the only path to ``live_vendor``.
"""

import asyncio
import contextlib
import logging
import re
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Final
from urllib.parse import urlsplit
from uuid import UUID

import requests

from .domain import EvidenceClass
from .errors import ConfigurationError, ModuleSevenError
from .evaluation_contracts import RunResult, identity_uuid
from .evaluation_dataset import DatasetView, scenario_input_digest
from .langsmith_config import (
    LangSmithSettings,
    qualify_https_endpoint,
    require_live_langsmith,
)

LANGSMITH_NAMESPACE: Final = UUID("7cc2a8e6-6d2c-5eb1-884f-c309ac2ca5c5")
MAX_RESPONSE_BODY_BYTES: Final = 1_048_576
_RESERVED_TEST_ORIGIN_HOST: Final = "198.51.100.1"
_MONOTONIC_CLOCK: Final = time.monotonic



_SECRET_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    # LangSmith/LangChain-style key prefixes and common authorization shapes.
    re.compile(r"lsv2_[A-Za-z0-9_\-]+"),
    re.compile(r"(?i)bearer\s+\S+"),
    re.compile(r"(?i)api[_\-]?key[\"'\s:=]+[^\s\"']+"),
    re.compile(r"(?i)password[\"'\s:=]+[^\s\"']+"),
    re.compile(r"(?i)authorization[\"'\s:=]+[^\s\"']+"),
    re.compile(r"(?i)secret[\w\-]*[\"'\s:=]+[^\s\"']+"),
)


class _SecretLogFilter(logging.Filter):
    """Containment for SDK-owned log records; never reproduces vendor text.

    SDK/vendor records (any record emitted through the ``langsmith`` logger
    names) are collapsed to one fixed application-owned safe representation:
    no vendor message text, formatting arguments or exception content is
    retained or rendered; only the record's own application-side severity
    survives. Ordinary application records emitted during containment render
    normally, with configured-value and bounded secret-shape redaction as
    defense in depth. Tracebacks and stack content are always stripped.
    """

    _SDK_PREFIX: Final = "langsmith"
    _ELIDED_MESSAGE: Final = (
        "LangSmith SDK log record elided; vendor message text is not rendered."
    )

    def __init__(self, values: Iterable[str]) -> None:
        super().__init__()
        self._values = tuple(value for value in values if value)

    def filter(self, record: logging.LogRecord) -> bool:
        if str(record.name).casefold().startswith(self._SDK_PREFIX):
            # SDK lane: collapse to the fixed safe representation only.
            record.msg, record.args = self._ELIDED_MESSAGE, None
            record.exc_info, record.exc_text, record.stack_info = None, None, None
            return True
        try:
            message = record.getMessage()
        except Exception:
            # Unformattable third-party log record: keep only a fixed message.
            message = "LangSmith-owned log record could not be formatted safely."
        for value in self._values:
            message = message.replace(value, "[REDACTED]")
        for pattern in _SECRET_PATTERNS:
            message = pattern.sub("[REDACTED]", message)
        record.msg, record.args = message, None
        record.exc_info, record.exc_text, record.stack_info = None, None, None
        return True


_LIVE_OPERATIONS: Final[dict[int, threading.Thread]] = {}
_LIVE_OPERATIONS_LOCK: Final = threading.Lock()


def _operation_busy(owner: object) -> bool:
    """Return whether the adapter owner already holds a live operation."""
    with _LIVE_OPERATIONS_LOCK:
        return id(owner) in _LIVE_OPERATIONS


async def _run_bounded[T](
    call: Callable[[], T], timeout: float, *, owner: object
) -> tuple[str, T | None, threading.Thread]:
    """Run a blocking call on a daemon thread, bounded by ``timeout``.

    Returns:
        ("ok", value, thread), ("failed", None, thread), ("busy", None, thread)
        or ("timeout", None, thread). Ownership is registered before start;
        timeout and cancellation never kill or unregister the underlying call.
    """
    loop = asyncio.get_running_loop()
    future: asyncio.Future[tuple[str, T | None]] = loop.create_future()

    def deliver(result: tuple[str, T | None]) -> None:
        if not future.done():
            future.set_result(result)

    def worker() -> None:
        result: tuple[str, T | None]
        try:
            result = ("ok", call())
        except Exception:
            # Vendor lifecycle boundary: failure is recorded without its text.
            result = ("failed", None)
        with _LIVE_OPERATIONS_LOCK:
            _LIVE_OPERATIONS.pop(id(owner), None)
        with contextlib.suppress(RuntimeError):
            loop.call_soon_threadsafe(deliver, result)

    thread = threading.Thread(
        target=worker, name="module7-langsmith-lifecycle", daemon=True
    )
    with _LIVE_OPERATIONS_LOCK:
        if id(owner) in _LIVE_OPERATIONS:
            return "busy", None, _LIVE_OPERATIONS[id(owner)]
        _LIVE_OPERATIONS[id(owner)] = thread
        try:
            thread.start()
        except RuntimeError:
            _LIVE_OPERATIONS.pop(id(owner), None)
            return "failed", None, thread
    try:
        outcome, value = await asyncio.wait_for(asyncio.shield(future), timeout)
    except TimeoutError:
        return "timeout", None, thread
    return outcome, value, thread


class RefusalSource:
    """Fixed, secret-free reason identifiers for bounded refusals."""

    CLOSED = "adapter_closed"
    TRANSPORT = "transport_rejected"
    DATASET_MISMATCH = "existing_dataset_mismatch"
    BUDGET = "budget_refused"
    READBACK_MISMATCH = "feedback_readback_mismatch"
    OVERSIZED_RESPONSE = "response_too_large"
    MALFORMED_PLAN = "malformed_export_plan"
    REDIRECT = "redirect_refused"
    ENDPOINT = "endpoint_refused"
    DEADLINE = "live_deadline_exhausted"
    REPEAT_EXPORT = "run_already_exported"


class LangSmithExportError(ModuleSevenError):
    """Fixed-message export refusal; never carries vendor or record content."""

    def __init__(self, reason: str) -> None:
        """Create a refusal.

        Args:
            reason: A fixed secret-free reason identifier.
        """
        super().__init__(f"LangSmith export refused ({reason}).")
        self.reason = reason


@dataclass(frozen=True, slots=True)
class LangSmithExampleFragment:
    """Allowlisted example fragment; contains no raw untrusted text."""

    example_id: str
    inputs: dict[str, str]
    outputs: dict[str, object]
    metadata: dict[str, object]


@dataclass(frozen=True, slots=True)
class LangSmithRunFragment:
    """Allowlisted run fragment for one scenario's evaluation batch."""

    run_id: str
    trace_id: str
    name: str
    inputs: dict[str, str]
    outputs: dict[str, object]
    metadata: dict[str, object]
    reference_example_id: str


@dataclass(frozen=True, slots=True)
class LangSmithFeedbackFragment:
    """Allowlisted feedback fragment carrying the local A evaluation identity."""

    feedback_id: str
    run_id: str
    key: str
    score: float
    source_info: dict[str, str]


@dataclass(frozen=True, slots=True)
class LangSmithExportPlan:
    """The deterministic, application-owned export plan.

    Attributes:
        dataset_name: Deterministic dataset name for the export.
        dataset_description: Digest-bearing fixed description.
        dataset_metadata: Dataset identity metadata.
        project_name: Deterministic project name for the export.
        run_id: The local run identifier of record.
        report_digest: Digest of the canonical local benchmark report.
        exported_subset: Declared exported scenario selection; None is full.
        examples: One example per exported scenario.
        runs: One run per exported scenario.
        feedback: One feedback per (scenario, evaluator) pair.
    """

    dataset_name: str
    dataset_description: str
    dataset_metadata: dict[str, object]
    project_name: str
    run_id: str
    report_digest: str
    exported_subset: tuple[str, ...] | None
    examples: tuple[LangSmithExampleFragment, ...]
    runs: tuple[LangSmithRunFragment, ...]
    feedback: tuple[LangSmithFeedbackFragment, ...]

    def worst_case_requests(self) -> int:
        """Return the upper-bound HTTP request count for this plan.

        Returns:
            Setup, export and readback worst case, counted at the adapter-owned
            HTTP adapter: dataset existence check, dataset create or read, one
            example upsert, one project create, one delayed info fetch, one
            run and one feedback per fragment, plus two readback requests.
        """
        return 2 + 1 + 1 + 1 + len(self.runs) + len(self.feedback) + 2


_FACT_KEYS: Final = (
    "classification", "attempts", "fallbacks", "replayed", "effect_count",
    "authorization", "safety", "budget_outcome",
)


def _facts_summary(values: dict[str, object]) -> dict[str, object]:
    """Project a fixed allowlisted facts summary without canary content."""
    return {key: values[key] for key in _FACT_KEYS}


def build_export_plan(
    result: RunResult,
    dataset: DatasetView,
    settings: LangSmithSettings,
    *,
    report_digest: str,
    exported_subset: tuple[str, ...] | None,
    namespace: UUID = LANGSMITH_NAMESPACE,
) -> LangSmithExportPlan:
    """Build the deterministic export plan from already-decided local facts.

    Args:
        result: The bounded class A run result of record.
        dataset: The committed dataset view the run used.
        settings: Validated LangSmith settings (prefix and export limit).
        report_digest: Digest of the canonical local benchmark report.
        exported_subset: The declared exported scenario selection or None.

    Returns:
        The plan with exactly the allowlisted fields.

    Raises:
        ValueError: When the exported subset exceeds the configured limit.
    """
    if exported_subset is not None and len(exported_subset) > settings.max_exported_scenarios:
        raise ValueError("Exported subset exceeds the configured limit.")
    chosen = (
        tuple(dataset.scenario_ids) if exported_subset is None else tuple(exported_subset)
    )
    prefix = settings.export_name_prefix
    run_id = str(result.run_id)
    rows_by_scenario: dict[str, list] = {}
    for row in result.evaluations:
        rows_by_scenario.setdefault(row.scenario_id, []).append(row)
    examples: list[LangSmithExampleFragment] = []
    runs: list[LangSmithRunFragment] = []
    feedback: list[LangSmithFeedbackFragment] = []
    for scenario_id in chosen:
        scenario = dataset.get(scenario_id)
        digest = scenario_input_digest(scenario.spec)
        rows = rows_by_scenario.get(scenario_id, [])
        example_id = str(identity_uuid(("example", run_id, scenario_id)))
        examples.append(
            LangSmithExampleFragment(
                example_id=example_id,
                inputs={"scenario_id": scenario_id, "input_digest": digest},
                outputs=_facts_summary(scenario.expected.model_dump()),
                metadata={
                    "category": str(scenario.category),
                    "coverage": scenario.coverage,
                    "dataset_version": dataset.dataset_version,
                    "dataset_digest": dataset.digest,
                },
            )
        )
        scenario_run_id = str(identity_uuid(("run", run_id, scenario_id)))
        trace_id = str(rows[0].trace_id) if rows else str(
            identity_uuid((run_id, scenario_id, "trace"))
        )
        runs.append(
            LangSmithRunFragment(
                run_id=scenario_run_id,
                trace_id=trace_id,
                name=f"{prefix}:{scenario_id}",
                inputs={"scenario_id": scenario_id, "input_digest": digest},
                outputs=(
                    _facts_summary(rows[0].observed.model_dump())
                    if rows else {"outcome": "missing"}
                ),
                metadata={
                    "run_id": run_id,
                    "trace_id": trace_id,
                    "scenario_id": scenario_id,
                    "workflow_id": str(rows[0].workflow_id) if rows
                    else str(identity_uuid((run_id, scenario_id, "workflow"))),
                    "action_id": str(rows[0].action_id) if rows
                    else str(identity_uuid((run_id, scenario_id, "action"))),
                    "dataset_id": dataset.dataset_id,
                    "dataset_version": dataset.dataset_version,
                    "dataset_digest": dataset.digest,
                    "report_digest": report_digest,
                    "evaluator_suite_version": result.identity.evaluator_suite_version,
                    "threshold_policy_version": result.identity.threshold_policy_version,
                    "target_id": result.identity.target_id,
                    "target_version": result.identity.target_version,
                    "evaluation_ids": [str(row.evaluation_id) for row in rows],
                },
                reference_example_id=example_id,
            )
        )
        for row in rows:
            feedback.append(
                LangSmithFeedbackFragment(
                    feedback_id=str(row.evaluation_id),
                    run_id=scenario_run_id,
                    key=f"{row.evaluator_id}.{row.metric}",
                    score=row.score,
                    source_info={
                        "evaluation_id": str(row.evaluation_id),
                        "evaluator_version": str(row.evaluator_version),
                        "threshold": f"{row.threshold[0]}/{row.threshold[1]}",
                        "passed": str(row.passed),
                        "critical": str(row.critical),
                        "status": row.status.value,
                        "origin": "application_deterministic",
                        "local_evidence_class": (
                            EvidenceClass.DETERMINISTIC_FIXTURE.value
                        ),
                    },
                )
            )
    return LangSmithExportPlan(
        dataset_name=f"{prefix}-benchmark-v{dataset.dataset_version}",
        dataset_description=(
            f"Module7 committed benchmark v{dataset.dataset_version}, "
            f"dataset digest {dataset.digest}"
        ),
        dataset_metadata={
            "dataset_id": dataset.dataset_id,
            "dataset_version": dataset.dataset_version,
            "dataset_digest": dataset.digest,
        },
        project_name=f"{prefix}-{str(identity_uuid(('project', run_id)))[:8]}",
        run_id=run_id,
        report_digest=report_digest,
        exported_subset=exported_subset,
        examples=tuple(examples),
        runs=tuple(runs),
        feedback=tuple(feedback),
    )


class LangSmithTransport:
    """Typed transport surface implemented by fakes and the SDK transport."""

    evidence_class: EvidenceClass | None = None

    def submit_plan(self, plan: LangSmithExportPlan) -> None:
        """Execute the whole deterministic plan; raise on any refusal."""
        raise NotImplementedError

    def read_back(self, plan: LangSmithExportPlan) -> dict[str, int]:
        """Read back exported identifiers with typed equality requirements."""
        raise NotImplementedError

    def close(self) -> bool:
        """Close the transport exactly once, reporting failure as False."""
        raise NotImplementedError


class FakeLangSmithSdkTransport(LangSmithTransport):
    """Deterministic fake transport for contract tests; never live evidence.

    Captures submitted plans and can be configured to fail, return malformed
    or mismatching readback; it never performs I/O, environment reads or waits.
    """

    evidence_class = EvidenceClass.MOCKED_PROVIDER_CONTRACT

    def __init__(
        self, *,
        failure: str | None = None,
        malformed_readback: bool = False,
        mismatched_readback: bool = False,
    ) -> None:
        self._failure = failure
        self._malformed_readback = malformed_readback
        self._mismatched_readback = mismatched_readback
        self._closed = False
        self._exported_runs: set[str] = set()
        self.submitted: list[LangSmithExportPlan] = []
        self.readback_calls = 0
        self.close_calls = 0

    def submit_plan(self, plan: LangSmithExportPlan) -> None:
        """Record one plan or raise the configured fixed failure.

        Args:
            plan: The plan to submit.

        Raises:
            LangSmithExportError: When configured to fail or repeated.
        """
        if self._failure is not None:
            raise LangSmithExportError(self._failure)
        if plan.run_id in self._exported_runs:
            raise LangSmithExportError(RefusalSource.REPEAT_EXPORT)
        self._exported_runs.add(plan.run_id)
        self.submitted.append(plan)

    def read_back(self, plan: LangSmithExportPlan) -> dict[str, int]:
        """Return a deterministic typed readback over submitted expectations.

        Args:
            plan: The compared plan.

        Returns:
            Matched example and feedback counts, or configured mismatches.
        """
        self.readback_calls += 1
        if self._malformed_readback:
            raise LangSmithExportError(RefusalSource.MALFORMED_PLAN)
        if self._mismatched_readback:
            return {
                "examples": len(plan.examples) - 1,
                "feedback": len(plan.feedback) - 1,
            }
        return {"examples": len(plan.examples), "feedback": len(plan.feedback)}

    def close(self) -> bool:
        """Close the fake; idempotent."""
        self.close_calls += 1
        closed = not self._closed
        self._closed = True
        return closed


class _RequestLedger:
    """Application-owned never-refunded reservation and request budget.

    A reservation is charged before the request is sent and is never refunded,
    including for failed, timed-out and refused-by-vendor requests.
    """

    def __init__(
        self, *,
        max_requests: int,
        reservation_per_request_usd: float | None,
        run_cost_limit_usd: float | None,
    ) -> None:
        self.max_requests = max_requests
        self.reservation = reservation_per_request_usd
        self.run_cost_limit = run_cost_limit_usd
        self.requests_sent = 0
        self.requests_refused = 0
        self.cost_used_usd = 0.0

    def plan_requests(self, count: int) -> bool:
        """Pre-run plan check against both limits before the first request.

        Args:
            count: Worst-case request count for the planned work.

        Returns:
            True when the count and its worst-case reservation fit; False
            records an application-budget refusal with no request sent.
        """
        if count < 0:
            raise ValueError("Planned request count must be nonnegative.")
        reservation = self.reservation or 0.0
        fits = (
            count <= self.max_requests
            and self.reservation is not None
            and count * reservation <= (self.run_cost_limit or 0.0) + 1e-9
        )
        if not fits:
            self.requests_refused += count
            return False
        return True

    def charge(self) -> bool:
        """Charge one never-refunded reservation before a request is sent.

        Returns:
            True to send; False when the request budget or cost limit no
            longer admits the reservation (the request is not sent), or when
            no reservation is configured at all (a missing reservation rings
            every request, never a free one).
        """
        if self.reservation is None:
            self.requests_refused += 1
            return False
        if self.requests_sent >= self.max_requests:
            self.requests_refused += 1
            return False
        reservation = self.reservation
        if self.cost_used_usd + reservation > (self.run_cost_limit or 0.0) + 1e-9:
            self.requests_refused += 1
            return False
        self.requests_sent += 1
        self.cost_used_usd += reservation
        return True

    def accounting(self) -> dict[str, float | int]:
        """Return the application-observed budget accounting of record."""
        return {
            "cost_limit_usd": self.run_cost_limit or 0.0,
            "cost_used_usd": self.cost_used_usd,
            "reservation_per_request_usd": self.reservation or 0.0,
            "requests_sent": self.requests_sent,
            "requests_refused": self.requests_refused,
            "basis": "configured_reservation",
        }


class _OwnedHttpBoundary:
    """Owned HTTP adapter: origin check, zero retries, bounded bodies.

    Args:
        settings: Validated settings providing the configured origin.
        ledger: Budget ledger charged before every actual HTTP request.
        adapter: The inner zero-retry transport adapter performing real I/O.
        seam: Optional documented test seam; never reachable from the live
            verification branch.
    """

    def __init__(
        self,
        settings: LangSmithSettings,
        ledger: _RequestLedger,
        adapter: requests.adapters.HTTPAdapter,
        *,
        seam: Callable[[list[dict[str, object]], object], bytes | None] | None,
    ) -> None:
        self._settings = settings
        self._ledger = ledger
        self._adapter = adapter
        self._seam = seam
        self._live_deadline: float | None = None
        self._deadline_refused = False
        parts = urlsplit(settings.api_url or "")
        port = parts.port or (443 if parts.scheme == "https" else 80)
        self._origin = (parts.scheme, parts.hostname or "", port)
        self.observed: list[dict[str, object]] = []

    def close(self) -> None:
        """Own nothing at session-close time; operations close their own socket.

        The session's public close loop iterates mounted adapters; this
        boundary holds no pooled connection, so closing it is a no-op and the
        SDK's exit hook performs no network work.
        """
        return None

    def send(self, request: object, **kwargs: object) -> requests.Response:
        """Run one request through the strict owned boundary.

        Args:
            request: Prepared request.
            **kwargs: Ignored; send policy is entirely owned here.

        Returns:
            A fully-read bounded response.

        Raises:
            LangSmithExportError: For refused origins, budget violations,
                redirects, oversized bodies and transport failures; retries
                are zero because the mounted adapter has none and this
                boundary never repeats a request.
        """
        parsed = urlsplit(getattr(request, "url", ""))
        request_port = parsed.port or (443 if parsed.scheme == "https" else 80)
        deadline = self._live_deadline
        if deadline is not None and _MONOTONIC_CLOCK() >= deadline:
            # Whole-run deadline: no new request may begin after exhaustion.
            self._deadline_refused = True
            raise LangSmithExportError(RefusalSource.DEADLINE)
        if ((parsed.scheme, parsed.hostname, request_port) != self._origin
                or "@" in (parsed.netloc or "")):
            raise LangSmithExportError(RefusalSource.TRANSPORT)
        if not self._ledger.charge():
            raise LangSmithExportError(RefusalSource.BUDGET)
        if self._seam is not None:
            self.observed.append({
                "method": getattr(request, "method", ""),
                "url": getattr(request, "url", ""),
                "headers": dict(getattr(request, "headers", {}) or {}),
                "body": getattr(request, "body", None),
            })
            content = self._seam(self.observed, request)
            return self._canned_response(request, content)
        # ``requests.adapters.HTTPAdapter.send`` takes no allow_redirects
        # argument; the boundary owns redirect policy here: any 3xx is
        # returned by urllib3 un-followed and refused outright, so no redirect
        # — including one toward loopback — is ever followed.
        # The per-request timeout is forwarded explicitly on every send.
        send_kwargs = {
            "stream": True, "timeout": self._settings.request_timeout_seconds,
            "verify": True,
        }
        try:
            response = self._adapter.send(request, **send_kwargs)
        except Exception:
            # Reservations are never refunded, including after failures.
            raise LangSmithExportError(RefusalSource.TRANSPORT) from None
        status = getattr(response, "status_code", 0)
        if isinstance(status, int) and 300 <= status < 400:
            response.close()
            raise LangSmithExportError(RefusalSource.REDIRECT)
        return self._read_bounded(response)

    def _canned_response(
        self, prepared: object, content: bytes | None
    ) -> requests.Response:
        """Deterministic in-process response for the reserved test origin."""
        response = requests.Response()
        response.status_code = 200
        response._content = b"{}" if content is None else content
        response.headers["Content-Type"] = "application/json"
        response.request = prepared
        return response

    def _read_bounded(self, response: requests.Response) -> requests.Response:
        """Read one response body up to the fixed response-size ceiling."""
        header = response.headers.get("Content-Length")
        if header is not None and int(header) > MAX_RESPONSE_BODY_BYTES:
            response.close()
            raise LangSmithExportError(RefusalSource.OVERSIZED_RESPONSE)
        data = b""
        while len(data) <= MAX_RESPONSE_BODY_BYTES:
            try:
                chunk = response.raw.read(65_536, decode_content=True)
            except Exception:
                response.close()
                raise LangSmithExportError(RefusalSource.TRANSPORT) from None
            if not chunk:
                break
            data += chunk
        if len(data) > MAX_RESPONSE_BODY_BYTES:
            response.close()
            raise LangSmithExportError(RefusalSource.OVERSIZED_RESPONSE)
        response._content = data
        response._content_consumed = True
        response.raw.release_conn()
        return response


class LangSmithSdkTransport(LangSmithTransport):
    """Real SDK-backed transport over a strictly owned HTTP session.

    Blocking operations (submit, readback, close) run on the shared tracked
    worker lane; construction starts no SDK/provider tracing worker. The owned
    HTTP boundary enforces the configured origin, zero retries and bounded
    responses; every actual HTTP request is charged to the ledger, including
    SDK-internal requests such as server-info lookups.
    """

    evidence_class = EvidenceClass.MOCKED_PROVIDER_CONTRACT

    def __init__(
        self,
        settings: LangSmithSettings,
        *,
        runtime: object | None = None,
        in_process_seam: Callable[[list[dict[str, object]], object], bytes | None] | None = None,
        opt_in: bool = False,
    ) -> None:
        """Construct the SDK transport.

        Args:
            settings: Validated, enabled, budgeted LangSmith settings.
            runtime: Required live runtime settings for real construction.
            in_process_seam: Optional documented test seam; receives the
                observed-request log and each prepared request, and may return
                canned response bytes. Only mountable for the reserved
                non-routable test origin and never reached by the live
                verification branch, which accepts no caller-supplied anything.
            opt_in: Explicit live-call opt-in, required for real construction
                and forwarded to the activation gate unmodified.

        Raises:
            ConfigurationError: Without explicit live settings, SDK binding,
                explicit opt-in or a qualifying endpoint.
        """
        if in_process_seam is not None and not _seam_origin(settings.api_url):
            raise ConfigurationError(
                "The in-process seam is reserved for the non-routable test origin."
            )
        if in_process_seam is not None:
            require_live_langsmith(runtime, settings, opt_in=opt_in)
        elif runtime is None or not require_live_langsmith(runtime, settings, opt_in=opt_in):
            raise ConfigurationError(
                "Network LangSmith export requires explicit live settings."
            )
        self._settings = settings
        self._seam = in_process_seam
        self._exported_runs: set[str] = set()
        self._ledger = _RequestLedger(
            max_requests=settings.max_http_requests,
            reservation_per_request_usd=settings.reservation_per_request_usd,
            run_cost_limit_usd=settings.run_cost_limit_usd,
        )
        self._initialize(settings)

    def _initialize(self, settings: LangSmithSettings) -> None:
        """Import the SDK lazily and construct the strictly owned boundary."""
        import langsmith.utils as langsmith_utils
        from langsmith import Client

        if (
            not settings.enabled
            or settings.api_key is None
            or settings.api_url is None
        ):
            raise ConfigurationError(
                "LangSmith transport requires enabled, complete settings."
            )
        # Endpoint qualification precedes anything: no client construction and
        # no credential is unwrapped before the URL itself qualifies. HTTPS
        # endpoints pass full bounded qualification; loopback HTTP endpoints
        # are permitted only as documented test origins (never by the live
        # verification branch, which qualifies before constructing anything).
        parts = urlsplit(settings.api_url)
        reserved_seam_origin = _seam_origin(settings.api_url)
        # Live-provenance qualification: only the owned, non-seam HTTPS
        # construction path that passed full bounded endpoint qualification
        # may carry the flag that grants live_vendor mint authority.
        self._live_qualified = False
        if reserved_seam_origin:
            pass  # The documented non-routable test seam origin only.
        elif parts.scheme == "https":
            qualify_https_endpoint(settings.api_url)
            # Qualification succeeded on a syntactically remote HTTPS origin.
            self._live_qualified = settings.is_remote_https_endpoint()
        elif not (
            parts.scheme == "http"
            and parts.hostname is not None
            and parts.hostname in {"127.0.0.1", "::1"}
        ):
            raise ConfigurationError(
                "LangSmith transport requires a qualifying endpoint."
            )
        session = requests.Session()
        session.trust_env = False
        self._session = session
        self._log_filter = _SecretLogFilter((settings.api_key.get_secret_value(),))
        self._loggers = _descendant_langsmith_loggers()
        for logger in self._loggers:
            logger.addFilter(self._log_filter)
        zero_retry = langsmith_utils.Retry(
            total=0, connect=0, read=0, redirect=0, status=0, other=0,
            raise_on_status=False, raise_on_redirect=False,
        )
        self._adapter = requests.adapters.HTTPAdapter(max_retries=0)
        self._boundary = _OwnedHttpBoundary(
            settings, self._ledger, self._adapter, seam=self._seam,
        )
        try:
            self._client = Client(
                api_url=settings.api_url,
                api_key=settings.api_key.get_secret_value(),
                retry_config=zero_retry,
                timeout_ms=settings.request_timeout_seconds * 1000,
                session=session,
                auto_batch_tracing=False,
                disable_prompt_cache=True,
                workspace_id=str(settings.workspace_id)
                if settings.workspace_id is not None else None,
            )
        except Exception:
            self._detach()
            raise ConfigurationError("LangSmith client construction failed.") from None
        # The SDK mounts its own retrying adapter after ours; re-mounting the
        # owned zero-retry, origin-checking boundary makes it the last mount
        # at the same prefix, and therefore the adapter the session uses.
        session.mount("http://", self._boundary)
        session.mount("https://", self._boundary)
        self._closed = False
        self._close_attempted = False
        self._close_result = False

    def _detach(self) -> None:
        for logger in self._loggers:
            logger.removeFilter(self._log_filter)

    def submit_plan(self, plan: LangSmithExportPlan) -> None:
        """Blocking strict execution of one plan; retries are exactly zero.

        Args:
            plan: The deterministic export plan.

        Raises:
            LangSmithExportError: With a fixed refusal reason, never content.
        """
        if self._closed:
            raise LangSmithExportError(RefusalSource.CLOSED)
        if plan.run_id in self._exported_runs:
            # A repeated export of the same run is refused without requests.
            raise LangSmithExportError(RefusalSource.REPEAT_EXPORT)
        try:
            self._execute_plan(plan)
        except LangSmithExportError:
            raise
        except Exception:
            raise LangSmithExportError(RefusalSource.TRANSPORT) from None
        self._exported_runs.add(plan.run_id)

    def _execute_plan(self, plan: LangSmithExportPlan) -> None:
        """Run the dataset/project/run/feedback request sequence exactly once."""
        client = self._client
        existing = client.has_dataset(dataset_name=plan.dataset_name)
        fetched = (
            client.read_dataset(dataset_name=plan.dataset_name)
            if existing else client.create_dataset(
                plan.dataset_name,
                description=plan.dataset_description,
                metadata=dict(plan.dataset_metadata),
            )
        )
        if existing:
            metadata = getattr(fetched, "metadata", None)
            digest = metadata.get("dataset_digest") if isinstance(metadata, dict) else None
            if digest is not None and digest != plan.dataset_metadata["dataset_digest"]:
                raise LangSmithExportError(RefusalSource.DATASET_MISMATCH)
        dataset_id = getattr(fetched, "id", None)
        if not dataset_id:
            raise LangSmithExportError(RefusalSource.MALFORMED_PLAN)
        client.create_examples(
            dataset_id=dataset_id,
            examples=[
                {
                    "id": example.example_id,
                    "inputs": dict(example.inputs),
                    "outputs": dict(example.outputs),
                    "metadata": dict(example.metadata),
                }
                for example in plan.examples
            ],
        )
        client.create_project(
            plan.project_name,
            reference_dataset_id=dataset_id,
            description="Module7 evaluation evidence export",
        )
        for fragment in plan.runs:
            client.create_run(
                fragment.name,
                dict(fragment.inputs),
                "chain",
                project_name=plan.project_name,
                outputs=dict(fragment.outputs),
                metadata=dict(fragment.metadata),
                id=fragment.run_id,
                trace_id=fragment.trace_id,
                reference_example_id=fragment.reference_example_id,
            )
        for fragment in plan.feedback:
            client.create_feedback(
                run_id=fragment.run_id,
                key=fragment.key,
                score=fragment.score,
                feedback_id=fragment.feedback_id,
                source_info=dict(fragment.source_info),
                stop_after_attempt=1,
            )

    def read_back(self, plan: LangSmithExportPlan) -> dict[str, int]:
        """Bounded readback of exported examples and feedback.

        Args:
            plan: The compared plan.

        Returns:
            Typed matched counts for the caller's deterministic comparison
            against the local A values.

        Raises:
            LangSmithExportError: With a fixed refusal reason.
        """
        if self._closed:
            raise LangSmithExportError(RefusalSource.CLOSED)
        try:
            dataset = self._client.read_dataset(dataset_name=plan.dataset_name)
            dataset_id = dataset.id
            examples = list(self._client.list_examples(dataset_id=dataset_id, limit=128))
            feedbacks = list(
                self._client.list_feedback(run_ids=[f.run_id for f in plan.runs], limit=128)
            )
        except LangSmithExportError:
            raise
        except Exception:
            raise LangSmithExportError(RefusalSource.TRANSPORT) from None
        matches: dict[str, str] = {
            example.example_id: example.inputs["input_digest"]
            for example in plan.examples
        }
        found_examples = sum(
            1 for row in examples
            if isinstance(row.inputs, dict)
            and row.inputs.get("input_digest") == matches.get(str(row.id))
        )
        expected: dict[str, tuple[str, str, float, str]] = {
            fragment.feedback_id: (
                fragment.run_id, fragment.key, fragment.score,
                fragment.source_info["evaluation_id"],
            )
            for fragment in plan.feedback
        }
        found_feedback = 0
        for row in feedbacks:
            source = row.feedback_source
            info = source.metadata if source is not None else None
            if not isinstance(info, dict):
                continue
            recorded = expected.get(str(row.id))
            if (
                recorded is not None
                and str(row.run_id) == recorded[0]
                and row.key == recorded[1]
                and row.score == recorded[2]
                and str(info.get("evaluation_id", "")) == recorded[3]
            ):
                found_feedback += 1
        return {"examples": found_examples, "feedback": found_feedback}
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


def _seam_origin(api_url: str | None) -> bool:
    """Return whether the endpoint is the reserved non-routable test origin."""
    if api_url is None:
        return False
    parts = urlsplit(api_url)
    return parts.hostname == _RESERVED_TEST_ORIGIN_HOST


def _descendant_langsmith_loggers() -> list[logging.Logger]:
    """Enumerate the LangSmith logger tree for containment, explicitly.

    Returns:
        Handles of the ``langsmith`` root logger, every enumerated
        ``langsmith.*`` descendant and the explicit ``langsmith.client``
        logger, so records emitted by descendant loggers cannot bypass
        sanitization by being logged to a child rather than the parent.
    """
    names = {"langsmith", "langsmith.client"}
    for name in logging.Logger.manager.loggerDict:
        if isinstance(name, str) and name.startswith("langsmith"):
            names.add(name)
    return [logging.getLogger(name) for name in sorted(names)]


async def submit_plan_bounded(
    transport: LangSmithTransport,
    plan: LangSmithExportPlan,
    timeout: float,
) -> tuple[str, None, threading.Thread]:
    """Submit one plan on the tracked lane, bounded by the caller.

    Args:
        transport: Trusted transport (SDK-backed or deterministic fake).
        plan: The deterministic export plan.
        timeout: Whole-submit wait bound in seconds.

    Returns:
        ("ok", None, thread) when completed; ("timeout", None, thread) leaves
        ownership retained and never upgrades the operation to complete;
        ("failed", None, thread) and ("busy", None, thread) per the shared
        lane. The thread handle is returned for lifecycle observation.
    """
    return await _run_bounded(lambda: transport.submit_plan(plan), timeout, owner=transport)


async def read_back_bounded(
    transport: LangSmithTransport,
    plan: LangSmithExportPlan,
    timeout: float,
) -> tuple[str, dict[str, int] | None, threading.Thread]:
    """Read back one plan on the tracked lane, bounded by the caller.

    Args:
        transport: Trusted transport.
        plan: The exported plan; guides typed readback expectations.
        timeout: Whole-readback wait bound in seconds.

    Returns:
        ("ok", counts, thread), ("timeout", None, thread),
        ("failed", None, thread) or ("busy", None, thread).
    """
    return await _run_bounded(lambda: transport.read_back(plan), timeout, owner=transport)


async def close_bounded(
    transport: LangSmithTransport, timeout: float
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
class LiveVerificationResult:
    """Live verification evidence; live_vendor only after the confirmed chain.

    Attributes:
        outcome: Fixed outcome label of record.
        evidence_class: live_vendor only from the owned confirmed chain.
        run_id: Local run identifier of record.
        report_digest: Digest of the canonical local benchmark report.
        exported_subset: The declared exported scenario selection.
        expected_examples/confirmed_examples: Readback comparison counts.
        expected_feedback/confirmed_feedback: Readback comparison counts.
        close_state: Bounded close state of record.
        evidence: Credential-free evidence fragment; never a live claim.
    """

    outcome: str
    evidence_class: EvidenceClass | None
    run_id: UUID
    report_digest: str
    exported_subset: tuple[str, ...] | None
    expected_examples: int
    confirmed_examples: int
    expected_feedback: int
    confirmed_feedback: int
    close_state: str
    evidence: dict[str, object] = field(default_factory=dict)


def _qualified_live_provenance(transport: object) -> bool:
    """Return whether this transport may carry ``live_vendor`` provenance.

    Qualification is application-owned and independent of any caller,
    provider or transport claim: only the exact owned SDK transport class,
    constructed through its own HTTPS path that passed full bounded endpoint
    qualification, without any mounted seam, on a syntactically remote
    endpoint, can ever qualify. Fakes, seams, local servers, subclasses and
    caller-supplied evidence labels can never satisfy it.

    Args:
        transport: The transport whose provenance is being judged.

    Returns:
        True only for a fully provenance-qualified owned live transport.
    """
    if type(transport) is not LangSmithSdkTransport:
        return False
    if getattr(transport, "_live_qualified", False) is not True:
        return False
    if transport._seam is not None:
        return False
    settings = transport._settings
    if not settings.is_remote_https_endpoint():
        return False
    return not _seam_origin(settings.api_url)


def run_live_langsmith_verification(
    runtime: object,
    settings: LangSmithSettings,
    *,
    opt_in: bool,
) -> LiveVerificationResult:
    """Run the complete owned LangSmith live verification branch.

    Everything is constructed inside this boundary: no caller-supplied
    transport, session, adapter, client or factory is accepted. Loopback and
    HTTP endpoints cannot proceed; the deterministic benchmark runs locally
    first; the worst-case budget plan must fit before the first request; a
    timeout of a required operation unresolves the run (never confirmed).

    Args:
        runtime: Accepted Story 1 live runtime settings.
        settings: Enabled, complete, budgeted LangSmith settings.
        opt_in: Explicit live-call opt-in, separate from configuration.

    Returns:
        Verification evidence; ``live_vendor`` only when the owned chain
        completes with matching typed readback on a qualifying endpoint.

    Raises:
        ConfigurationError: Without explicit opt-in, complete activation gates
            or a qualifying non-loopback HTTPS endpoint.
    """
    if not opt_in:
        raise ConfigurationError("Live LangSmith verification requires explicit opt-in.")
    if not require_live_langsmith(runtime, settings, opt_in=opt_in):
        raise ConfigurationError("Live LangSmith verification requires enabled settings.")
    if not settings.is_remote_https_endpoint():
        raise ConfigurationError(
            "Live LangSmith verification requires a non-loopback HTTPS endpoint."
        )
    qualify_https_endpoint(settings.api_url)

    # Whole-run live deadline: begins at this accepted live-operation
    # boundary and covers submission, readback and wait behavior below.
    deadline: float | None = (
        _MONOTONIC_CLOCK() + settings.live_deadline_seconds
    )

    from .evaluation_benchmark import BenchmarkRunner, benchmark_report
    from .evaluation_contracts import canonical_digest
    from .evaluation_dataset import load_benchmark_dataset
    from .evaluation_engine import EvaluationEngine
    from .evaluation_target import ReferenceTarget

    dataset = load_benchmark_dataset()
    runner = BenchmarkRunner(EvaluationEngine())
    benchmark = asyncio.run(runner.run_full(
        dataset,
        target_factory=ReferenceTarget.build,
        target_id="reference_default",
        target_version=1,
    ))
    digest = canonical_digest(benchmark_report(benchmark.run, None, None))
    subset: tuple[str, ...] | None = None
    if len(dataset.scenario_ids) > settings.max_exported_scenarios:
        subset = tuple(sorted(dataset.scenario_ids)[: settings.max_exported_scenarios])
    plan = build_export_plan(
        benchmark.run.result, dataset, settings,
        report_digest=digest, exported_subset=subset,
    )
    ledger = _RequestLedger(
        max_requests=settings.max_http_requests,
        reservation_per_request_usd=settings.reservation_per_request_usd,
        run_cost_limit_usd=settings.run_cost_limit_usd,
    )
    if not ledger.plan_requests(plan.worst_case_requests()):
        return LiveVerificationResult(
            outcome=RefusalSource.BUDGET,
            evidence_class=None,
            run_id=benchmark.run.result.run_id,
            report_digest=digest,
            exported_subset=subset,
            expected_examples=len(plan.examples),
            confirmed_examples=0,
            expected_feedback=len(plan.feedback),
            confirmed_feedback=0,
            close_state="not_started",
            evidence=ledger.accounting(),
        )
    transport = LangSmithSdkTransport(settings, runtime=runtime, opt_in=opt_in)
    transport._boundary._live_deadline = deadline
    result = _execute_live(
        transport, plan, benchmark, digest, subset, deadline=deadline
    )
    close_label = asyncio.run(
        _close_state(transport, settings.lifecycle_timeout_seconds)
    )
    if close_label == "busy":
        close_label = "close_busy"
    if result.outcome != "confirmed" or close_label != "closed":
        result = LiveVerificationResult(
            outcome=result.outcome,
            evidence_class=None,
            run_id=result.run_id,
            report_digest=result.report_digest,
            exported_subset=result.exported_subset,
            expected_examples=result.expected_examples,
            confirmed_examples=result.confirmed_examples,
            expected_feedback=result.expected_feedback,
            confirmed_feedback=result.confirmed_feedback,
            close_state=close_label,
        )
    elif _qualified_live_provenance(transport):
        # The only live_vendor mint in the application: the owned chain,
        # after qualification, confirmed behave and cleanly closed, upgrades
        # the confirmed execution to live_vendor provenance here.
        result = LiveVerificationResult(
            outcome=result.outcome,
            evidence_class=EvidenceClass.LIVE_VENDOR,
            run_id=result.run_id,
            report_digest=result.report_digest,
            exported_subset=result.exported_subset,
            expected_examples=result.expected_examples,
            confirmed_examples=result.confirmed_examples,
            expected_feedback=result.expected_feedback,
            confirmed_feedback=result.confirmed_feedback,
            close_state=close_label,
            evidence=result.evidence,
        )
    # Confirmed behavior on an unqualified transport stays capped at the
    # mocked/provider contract as produced by ``_execute_live``.
    return result


def _deadline_timeout_result(
    transport: LangSmithSdkTransport,
    plan: LangSmithExportPlan,
    digest: str,
    subset: tuple[str, ...] | None,
) -> LiveVerificationResult:
    """Build the fixed ``timeout_unresolved`` whole-run deadline result.

    Args:
        transport: The owned SDK transport whose accounting is retained.
        plan: The deterministic export plan (expected counts).
        digest: Canonical local benchmark report digest.
        subset: The declared exported scenario selection.

    Returns:
        Unresolved evidence; the deadline never mints ``live_vendor`` and the
        request ledger is never refunded.
    """
    return LiveVerificationResult(
        outcome="timeout_unresolved",
        evidence_class=None,
        run_id=plan.run_id,
        report_digest=digest,
        exported_subset=subset,
        expected_examples=len(plan.examples),
        confirmed_examples=0,
        expected_feedback=len(plan.feedback),
        confirmed_feedback=0,
        close_state="unresolved",
        evidence={"request_accounting": transport.accounting()},
    )


def _exhausted(transport: LangSmithSdkTransport, deadline: float | None) -> bool:
    """Return whether the whole-run deadline is exhausted (or was refused)."""
    boundary = getattr(transport, "_boundary", None)
    if boundary is not None and boundary._deadline_refused:
        return True
    return deadline is not None and _MONOTONIC_CLOCK() >= deadline


def _execute_live(
    transport: LangSmithSdkTransport,
    plan: LangSmithExportPlan,
    benchmark: object,
    digest: str,
    subset: tuple[str, ...] | None,
    *,
    deadline: float | None,
) -> LiveVerificationResult:
    """Run submit and bounded readback without close ownership decisions.

    Args:
        transport: The owned SDK transport (constructed inside the branch).
        plan: The deterministic export plan.
        benchmark: The local benchmark output of record.
        digest: Canonical local benchmark report digest.
        subset: The declared exported scenario selection.
        deadline: Whole-run live deadline (monotonic reading), or None.

    Returns:
        Verification evidence with close_state deliberately left unresolved;
        closing is decided by the whole-branch owner afterwards. No new
        request may begin after the deadline; exhaustion reports the fixed
        safe ``timeout_unresolved`` status and never mints ``live_vendor``.
    """
    run_id = benchmark.run.result.run_id  # type: ignore[union-attr]
    expected_examples = len(plan.examples)
    expected_feedback = len(plan.feedback)
    settings = transport._settings
    if _exhausted(transport, deadline):
        transport._boundary._deadline_refused = True
        return _deadline_timeout_result(transport, plan, digest, subset)
    submit_result, _payload, _thread = asyncio.run(submit_plan_bounded(
        transport, plan, settings.request_timeout_seconds * 3 + 30,
    ))
    confirmed_examples = 0
    confirmed_feedback = 0
    label = "export_failed"
    if submit_result == "timeout":
        return LiveVerificationResult(
            outcome="timeout_unresolved",
            evidence_class=None,
            run_id=run_id,
            report_digest=digest,
            exported_subset=subset,
            expected_examples=expected_examples,
            confirmed_examples=0,
            expected_feedback=expected_feedback,
            confirmed_feedback=0,
            close_state="unresolved",
        )
    if submit_result == "failed" and _exhausted(transport, deadline):
        return _deadline_timeout_result(transport, plan, digest, subset)
    if submit_result == "ok":
        label = "readback_not_confirmed"
        for attempt in range(settings.readback_attempts):
            if _exhausted(transport, deadline):
                transport._boundary._deadline_refused = True
                return _deadline_timeout_result(transport, plan, digest, subset)
            result, counts, _thread = asyncio.run(read_back_bounded(
                transport, plan, settings.request_timeout_seconds * 3 + 30,
            ))
            if result == "timeout":
                label = "timeout_unresolved"
                break
            if result == "failed" and _exhausted(transport, deadline):
                return _deadline_timeout_result(transport, plan, digest, subset)
            if result == "busy":
                continue
            if result == "ok" and isinstance(counts, dict):
                confirmed_examples = min(counts.get("examples", 0), expected_examples)
                confirmed_feedback = min(counts.get("feedback", 0), expected_feedback)
                if (confirmed_examples == expected_examples
                        and confirmed_feedback == expected_feedback):
                    label = "confirmed"
                    break
            if attempt + 1 < settings.readback_attempts:
                time.sleep(settings.readback_interval_seconds)
    # The mint cap: confirmed behavior proves limited execution success only.
    # ``_execute_live`` has no authority to mint ``live_vendor``; unqualified
    # execution (transport-injected, seam, fake, mocked, local or otherwise
    # caller-reachable origin) is capped at the mocked/provider contract.
    # Only the owned provenance-qualified live chain upgrades afterwards.
    evidence_class = (
        EvidenceClass.MOCKED_PROVIDER_CONTRACT if label == "confirmed" else None
    )
    return LiveVerificationResult(
        outcome=label,
        evidence_class=evidence_class,
        run_id=run_id,
        report_digest=digest,
        exported_subset=subset,
        expected_examples=expected_examples,
        confirmed_examples=confirmed_examples,
        expected_feedback=expected_feedback,
        confirmed_feedback=confirmed_feedback,
        close_state="unresolved",
        evidence={"request_accounting": transport.accounting()},
    )


async def _close_state(transport: LangSmithSdkTransport, timeout: float) -> str:
    """Close within the lifecycle bound and return the fixed close label.

    Args:
        transport: The owned SDK transport.
        timeout: Close wait bound in seconds.

    Returns:
        closed, close_failed or close_busy; a busy unresolved operation keeps
        its ownership and never reports a completed close.
    """
    outcome, value, _thread = await _run_bounded(transport.close, timeout, owner=transport)
    if outcome == "timeout" or outcome == "busy":
        return "close_busy"
    if outcome == "ok" and value is True:
        return "closed"
    return "close_failed"


__all__ = [
    "LANGSMITH_NAMESPACE",
    "FakeLangSmithSdkTransport",
    "LangSmithExampleFragment",
    "LangSmithExportError",
    "LangSmithExportPlan",
    "LangSmithFeedbackFragment",
    "LangSmithRunFragment",
    "LangSmithSdkTransport",
    "LangSmithTransport",
    "LiveVerificationResult",
    "RefusalSource",
    "build_export_plan",
    "close_bounded",
    "read_back_bounded",
    "run_live_langsmith_verification",
    "submit_plan_bounded",
]
