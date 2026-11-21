"""Framework-independent bounded reviewer exercise over accepted application interfaces."""

import asyncio
import json
import re
from collections import deque
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from module10_ai import InferenceRequest, InferenceService
from module10_ai.errors import ContractError
from module10_ai.execution import JobTimeout, LocalExecution, QueueUnavailable
from module10_ai.telemetry import CORRELATION, Telemetry, correlation_id, failure_category

ACCEPTANCE_SCHEMA_VERSION = 1
ACCEPTANCE_CLASSIFICATION = "AZURE CLOUD / DETERMINISTIC INFERENCE"
ACCEPTANCE_TEARDOWN = "human-controlled deletion of the validated dedicated resource group"
ACCEPTANCE_CHECKS = ("inventory", "configuration", "registry_digest", "revision_health",
                     "https_health", "deterministic_inference", "bounded_rejection",
                     "azure_monitor_receipt")
ACCEPTANCE_FIELDS = frozenset({
    "schema_version", "classification", "verified_at", "deployment_authorized", "region",
    "image", "revision", "checks", "replicas", "limits", "teardown"})
ACCEPTANCE_IMAGE = re.compile(
    r"m10acr[a-z][a-z0-9]{5,11}\.azurecr\.io/module10-ai@sha256:[a-f0-9]{64}")
ACCEPTANCE_REVISION = re.compile(r"m10-api-[a-z][a-z0-9]{5,11}--[a-z0-9-]{1,64}")
ACCEPTANCE_FILE_BYTES = 32768
ACCEPTANCE_STALE_AFTER = timedelta(days=30)


class _Rejection(Exception):
    """Internal fixed-message rejection carrying one finite evidence status token."""

    def __init__(self, status: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def cloud_evidence_report(path_text: str) -> dict[str, object]:
    """Validate one operator-selected Azure acceptance artifact for presentation.

    Args:
        path_text: Exact file path explicitly supplied by the operator. Only that
            single file is opened, read-only and bounded; the path is never used
            to select commands, URLs, privileged operations or further filesystem
            access, and artifact content never selects any behavior.

    Returns:
        Detached presentation data: a ``verified`` status with the minimized
        allowlisted acceptance fields, or a fixed safe error with one finite
        status token (``missing``, ``malformed``, ``incomplete``, ``failed`` or
        ``incompatible``). Content outside the accepted schema is never reflected.

    Raises:
        Nothing: every failure, including unreadable files, is returned as data.
    """
    try:
        return _cloud_evidence_report(path_text)
    except _Rejection as rejection:
        return {"status": rejection.status, "error": rejection.message}
    except (OSError, ValueError, TypeError, RecursionError):
        # Presentation boundary: untrusted artifact content must not surface raw
        # diagnostics; this fail-closed fallback mirrors the accepted exercise style.
        return {"status": "malformed",
                "error": "The evidence artifact could not be accepted for display."}


def _cloud_evidence_report(path_text: str) -> dict[str, object]:
    """Apply the fail-closed acceptance-artifact schema; raise fixed rejections."""
    path = path_text.strip() if type(path_text) is str else ""
    if not path or len(path) > 1000 or "\x00" in path:
        raise _Rejection("missing", "Provide the exact file path of a verifier-written "
                         "Azure acceptance artifact.")
    try:
        with open(path, "rb") as stream:
            raw = stream.read(ACCEPTANCE_FILE_BYTES + 1)
    except OSError as exc:
        raise _Rejection("missing", "The evidence file could not be read at the exact "
                         "path provided.") from exc
    if len(raw) > ACCEPTANCE_FILE_BYTES:
        raise _Rejection("malformed", "The evidence file exceeds the accepted evidence "
                         "size bound.")
    try:
        evidence = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise _Rejection("malformed", "The evidence file is not a valid UTF-8 JSON "
                         "object.") from exc
    except RecursionError as exc:
        raise _Rejection("malformed", "The evidence file nests JSON too deeply to be "
                         "accepted.") from exc
    if type(evidence) is not dict:
        raise _Rejection("malformed", "The evidence file is not a valid UTF-8 JSON object.")
    if set(evidence) - ACCEPTANCE_FIELDS:
        raise _Rejection("malformed", "The evidence artifact contains fields outside the "
                         "accepted acceptance schema.")
    if ACCEPTANCE_FIELDS - set(evidence):
        raise _Rejection("incomplete", "The evidence artifact is missing required "
                         "acceptance fields.")
    if (type(evidence["schema_version"]) is not int
            or evidence["schema_version"] != ACCEPTANCE_SCHEMA_VERSION):
        raise _Rejection("incompatible", "The evidence artifact does not use the accepted "
                         "acceptance schema version.")
    if evidence["classification"] != ACCEPTANCE_CLASSIFICATION:
        raise _Rejection("incompatible", "The evidence artifact classification is not the "
                         "accepted Azure cloud acceptance classification.")
    if type(evidence["deployment_authorized"]) is not bool or evidence["deployment_authorized"]:
        raise _Rejection("incompatible", "Acceptance evidence never grants deployment "
                         "authority; the artifact's authority claim is incompatible.")
    verified_at = evidence["verified_at"]
    verified = _acceptance_timestamp(verified_at)
    now = datetime.now(UTC)
    if verified > now:
        raise _Rejection("malformed", "The acceptance timestamp is in the future.")
    if evidence["region"] != "southcentralus":
        raise _Rejection("malformed", "The evidence region differs from the approved "
                         "deployment region.")
    image, revision = evidence["image"], evidence["revision"]
    if (type(image) is not str or ACCEPTANCE_IMAGE.fullmatch(image) is None
            or type(revision) is not str or ACCEPTANCE_REVISION.fullmatch(revision) is None):
        raise _Rejection("malformed", "Deployment identity fields do not match the "
                         "accepted shapes.")
    replicas = evidence["replicas"]
    if (type(replicas) is not dict or set(replicas) != {"minimum", "maximum"}
            or type(replicas["minimum"]) is not int or replicas["minimum"] != 0
            or type(replicas["maximum"]) is not int or replicas["maximum"] != 2):
        raise _Rejection("malformed", "Replica bounds differ from the approved deployment "
                         "contract.")
    if evidence["teardown"] != ACCEPTANCE_TEARDOWN:
        raise _Rejection("malformed", "The teardown note differs from the accepted "
                         "evidence schema.")
    limits = evidence["limits"]
    if (type(limits) is not list or len(limits) > 16
            or any(type(item) is not str or not 1 <= len(item) <= 256 for item in limits)):
        raise _Rejection("malformed", "Evidence limitation entries are malformed or "
                         "oversized.")
    checks = evidence["checks"]
    if type(checks) is not dict:
        raise _Rejection("malformed", "Verifier gate results are malformed.")
    if set(checks) - set(ACCEPTANCE_CHECKS):
        raise _Rejection("malformed", "Verifier gate results contain unknown gate names.")
    if set(checks) != set(ACCEPTANCE_CHECKS):
        raise _Rejection("incomplete", "The evidence artifact is missing verifier gate "
                         "results.")
    failed = [name for name in ACCEPTANCE_CHECKS if checks[name] != "passed"]
    if failed:
        raise _Rejection("failed", "Verifier gate results did not pass: "
                         + ", ".join(failed) + ".")
    return {"status": "verified", "evidence": "azure-cloud-acceptance",
            "deployment_authorized": False, "verified_at": verified.isoformat(),
            "stale": now - verified > ACCEPTANCE_STALE_AFTER, "region": evidence["region"],
            "image": image, "revision": revision, "checks": list(ACCEPTANCE_CHECKS),
            "replicas": {"minimum": 0, "maximum": 2}, "limits": list(limits),
            "teardown": ACCEPTANCE_TEARDOWN}


def _acceptance_timestamp(verified_at: object) -> datetime:
    """Parse the bounded acceptance timestamp or reject it with a fixed message."""
    if type(verified_at) is not str:
        raise _Rejection("malformed", "The acceptance timestamp is malformed.")
    try:
        verified = datetime.fromisoformat(verified_at)
    except ValueError as exc:
        raise _Rejection("malformed", "The acceptance timestamp is malformed.") from exc
    if verified.tzinfo is None:
        raise _Rejection("malformed", "The acceptance timestamp lacks an explicit offset.")
    return verified


async def exercise(text: str, keyword_limit: int = 3,
                   service: InferenceService | None = None) -> dict[str, object]:
    """Run two sequential real jobs, then close all owned asynchronous resources.

    Args:
        text: Untrusted reviewer text validated by the accepted domain contract.
        keyword_limit: Accepted keyword bound, validated without coercion.
        service: Trusted injection for deterministic failure testing.

    Returns:
        Detached presentation evidence or a fixed safe error, never exception details.
    """
    records: deque[str] = deque(maxlen=32)
    observer = Telemetry(records.append)
    execution = LocalExecution(InferenceService() if service is None else service,
                               telemetry=observer)
    token = CORRELATION.set(correlation_id(uuid4().hex))
    report: dict[str, object] = {"evidence": "local-deterministic"}
    deadline = asyncio.timeout(12)
    try:
        request = InferenceRequest(text, keyword_limit)
        await execution.start()
        report["readiness_during_exercise"] = execution.accepting
        report["configuration"] = asdict(execution.config)
        runs = []
        async with deadline:
            for _ in range(2):
                job = execution.submit(request)
                admitted = job.state.value
                result = await job.result()
                runs.append({"admission": admitted, "outcome": job.state.value,
                             "result": asdict(result), "cache": asdict(execution.cache.stats())})
        report["runs"] = runs
    except ContractError:
        report["error"] = "Enter 1–4096 nonblank characters and a keyword limit from 1 to 10."
    except JobTimeout:
        report["error"] = "The bounded exercise timed out. Try again."
    except TimeoutError as exc:
        if deadline.expired():
            report["error"] = "The bounded exercise timed out. Try again."
        else:
            observer.event("application.failure", status="failure", category=failure_category(exc))
            report["error"] = "The local application could not complete this exercise."
    except QueueUnavailable:
        report["error"] = "Local execution capacity is unavailable. Try again."
    except Exception as exc:
        # Genuine presentation boundary: retain only an accepted diagnostic category.
        observer.event("application.failure", status="failure", category=failure_category(exc))
        report["error"] = "The local application could not complete this exercise."
    finally:
        await execution.close()
        report["accepting_after_cleanup"] = execution.accepting
        report["queue_after_cleanup"] = asdict(execution.stats())
        report["metrics"] = observer.snapshot()
        report["events"] = [json.loads(record) for record in records]
        CORRELATION.reset(token)
    return report
