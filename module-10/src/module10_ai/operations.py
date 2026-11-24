"""Deterministic, data-only operational-readiness validation for Module 10.

Every validator consumes explicitly supplied minimized evidence as untrusted
data, validates it fail-closed against the accepted contracts, and returns a
detached machine-readable report. No function in this module performs network,
subprocess, cloud, or privileged operations, and no validation result
constitutes authorization of any kind.

Validated rollback plan is NOT authorized execution: plan validation checks
data conformance against the accepted promotion contract only.
"""

import json
import re
from datetime import datetime

CHECKLIST_SCHEMA_VERSION = 1
CHECKLIST_CLASSIFICATION = "MODULE 10 OPERATIONAL READINESS / OFFLINE DETERMINISTIC"
CHECKLIST_GATE_ITEMS = ("inventory", "configuration", "registry_digest",
                        "revision_health", "https_health",
                        "deterministic_inference", "bounded_rejection",
                        "azure_monitor_receipt")
CHECKLIST_OPEN_ITEMS = ("tested_source_provenance", "rollback_execution",
                        "live_slo_attainment")
CHECKLIST_FIELDS = frozenset({"schema_version", "classification",
                              "generated_at", "items"})
CHECKLIST_NOTE = ("Checklist consistency reflects accepted point-in-time "
                  "evidence only; it is not deployment authority.")

INCIDENT_SCHEMA_VERSION = 1
INCIDENT_CLASSIFICATION = "MODULE 10 INCIDENT DIAGNOSTIC / OFFLINE DETERMINISTIC"
INCIDENT_FIELDS = frozenset({"schema_version", "classification", "observed_at",
                             "scenario", "observations"})
INCIDENT_WINDOW_MAX = 1440
INCIDENT_COUNT_MAX = 2 ** 20
INCIDENT_STATUS_VALUES = frozenset({"success", "failure"})
REVISION_PATTERN = re.compile(r"m10-api-[a-z][a-z0-9]{5,11}--[a-z0-9-]{1,64}")
IMAGE_PATTERN = re.compile(
    r"m10acr[a-z][a-z0-9]{5,11}\.azurecr\.io/module10-ai@sha256:[a-f0-9]{64}")

ROLLBACK_SCHEMA_VERSION = 1
ROLLBACK_CLASSIFICATION = "MODULE 10 ROLLBACK PLAN / DATA ONLY"
ROLLBACK_FIELDS = frozenset({"schema_version", "classification",
                             "target_revision", "target_image", "trigger",
                             "post_rollback_checks", "execution_authority",
                             "deployment_authorized",
                             "provenance_precondition", "prepared_at"})
ROLLBACK_TRIGGERS = ("failed_health_verification", "failed_inference",
                     "operational_regression")
ROLLBACK_POST_CHECKS = ("liveness", "readiness", "deterministic_inference",
                        "azure_monitor_receipt", "revision_traffic")
ROLLBACK_AUTHORITY = "operator-approved protected GitHub Environment"
ROLLBACK_PROVENANCE_PRECONDITION = "unresolved"
ROLLBACK_NOTE = ("A validated rollback plan is not authorized, performed, or "
                 "successful rollback; execution remains operator-gated.")

SLO_SCHEMA_VERSION = 1
SLO_CLASSIFICATION = "MODULE 10 SLO REGISTER / EVIDENCE-GROUNDED"
SLO_FIELDS = frozenset({"schema_version", "classification", "objectives"})
SLO_OBJECTIVES = ("readiness_availability", "liveness", "inference_latency",
                  "queue_saturation_rate", "monitor_receipt_presence")
SLO_LABELS = ("measured", "proposed", "illustrative")
SLO_SOURCES = ("local-telemetry", "azure-monitor-receipt", "verifier-gates",
               "none")
SLO_ENTRY_FIELDS = frozenset({"name", "label", "objective",
                              "measurement_source", "measurement"})
SLO_MEASUREMENT_MAX = 10 ** 6

COST_SCHEMA_VERSION = 1
COST_CLASSIFICATION = "MODULE 10 COST REGISTER / CONFIGURATION-BOUNDED"
COST_FIELDS = frozenset({"schema_version", "classification", "entries",
                         "budget_threshold"})
COST_ITEMS = ("registry", "log-analytics", "container-app", "identity",
              "teardown")
COST_KINDS = ("verified", "assumption")
COST_BASES = ("observed-configuration", "operator-judgment")
COST_ENTRY_FIELDS = frozenset({"item", "kind", "basis"})
COST_TEXT_MAX = 200

FILE_BYTES = 32768


class _Rejection(Exception):
    """Internal fixed-message rejection carrying one finite evidence status token."""

    def __init__(self, status: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class EvidenceError(ValueError):
    """Fixed-message evidence load failure carrying one finite status token."""

    def __init__(self, status: str, message: str) -> None:
        """Record the finite status token and the fixed sanitized message.

        Args:
            status: One finite status token distinguishing missing evidence
                from malformed evidence.
            message: Fixed sanitized message that never reflects file content
                or the supplied path.
        """
        super().__init__(message)
        self.status = status
        self.message = message


def _validated_timestamp(value: object, label: str) -> datetime:
    """Parse one tz-aware ISO timestamp or reject with a fixed message."""
    if type(value) is not str:
        raise _Rejection("malformed", f"The {label} timestamp is malformed.")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise _Rejection("malformed", f"The {label} timestamp is malformed.") from exc
    if parsed.tzinfo is None:
        raise _Rejection("malformed", f"The {label} timestamp lacks an offset.")
    return parsed

def _document_shape(document: object, fields: frozenset,
                    schema_version: int, classification: str,
                    schema_label: str,
                    optional_fields: frozenset = frozenset()) -> dict:
    """Apply the shared fail-closed document envelope for one register kind."""
    if type(document) is not dict:
        raise _Rejection("malformed", f"The {schema_label} evidence is not a "
                         "JSON object.")
    if set(document) - fields:
        raise _Rejection("malformed", f"The {schema_label} evidence contains "
                         "fields outside the accepted schema.")
    if fields - optional_fields - set(document):
        raise _Rejection("incomplete", f"The {schema_label} evidence is "
                         "missing required fields.")
    if (type(document["schema_version"]) is not int
            or document["schema_version"] != schema_version):
        raise _Rejection("incompatible", f"The {schema_label} evidence does "
                         "not use the accepted schema version.")
    if document["classification"] != classification:
        raise _Rejection("incompatible", f"The {schema_label} evidence "
                         "classification differs from the accepted "
                         "classification.")
    return document


def _bounded_text(value: object, label: str) -> str:
    """Require bounded nonblank text and return it unchanged."""
    if type(value) is not str or not 1 <= len(value) <= COST_TEXT_MAX:
        raise _Rejection("malformed", f"The {label} entry text is malformed "
                         "or oversized.")
    return value


def checklist_report(document: object) -> dict[str, object]:
    """Validate one deployment-readiness checklist for presentation.

    Args:
        document: Untrusted parsed JSON evidence; never executed or trusted.

    Returns:
        A detached report: ``ready`` when every accepted M2 gate item reads
        ``passed`` and every carried-open item reads ``open``, ``not_ready``
        for honest failures, ``contradictory`` for unsupported claims, and a
        fixed error with one finite status token otherwise. Consistency is
        not deployment authority.

    Raises:
        Nothing: every failure is returned as data.
    """
    try:
        return _checklist_report(document)
    except _Rejection as rejection:
        return {"status": rejection.status, "error": rejection.message}


def _checklist_report(document: object) -> dict[str, object]:
    """Apply the fail-closed checklist schema; raise fixed rejections."""
    document = _document_shape(document, CHECKLIST_FIELDS,
                               CHECKLIST_SCHEMA_VERSION,
                               CHECKLIST_CLASSIFICATION, "checklist")
    generated = _validated_timestamp(document["generated_at"], "checklist")
    items = document["items"]
    if type(items) is not list or not items or len(items) > 32:
        raise _Rejection("malformed", "The checklist items are malformed.")
    seen: dict[str, str] = {}
    for item in items:
        if type(item) is not dict or set(item) != {"name", "status"}:
            raise _Rejection("malformed", "A checklist item contains fields "
                             "outside the accepted item schema.")
        name, status = item["name"], item["status"]
        if type(name) is not str or type(status) is not str:
            raise _Rejection("malformed", "A checklist item is malformed.")
        if name not in CHECKLIST_GATE_ITEMS + CHECKLIST_OPEN_ITEMS:
            raise _Rejection("malformed", "The checklist contains an item "
                             "outside the accepted vocabulary.")
        if status not in ("passed", "failed", "open"):
            raise _Rejection("malformed", "A checklist item status is "
                             "outside the accepted vocabulary.")
        if name in seen:
            raise _Rejection("malformed", "The checklist repeats an item.")
        seen[name] = status
    for name in CHECKLIST_GATE_ITEMS + CHECKLIST_OPEN_ITEMS:
        if name not in seen:
            raise _Rejection("incomplete", "The checklist is missing a "
                             "required item.")
    gates_failed = [name for name in CHECKLIST_GATE_ITEMS
                    if seen[name] != "passed"]
    unsupported = [name for name in CHECKLIST_OPEN_ITEMS
                   if seen[name] != "open"]
    if unsupported:
        raise _Rejection("contradictory", "Carried-open checklist items must "
                         "read open: " + ", ".join(unsupported) + ".")
    report: dict[str, object] = {
        "status": "not_ready" if gates_failed else "ready",
        "checklist_version": CHECKLIST_SCHEMA_VERSION,
        "gates_passed": [name for name in CHECKLIST_GATE_ITEMS
                         if seen[name] == "passed"],
        "gates_not_passed": gates_failed,
        "open_items": [name for name in CHECKLIST_OPEN_ITEMS
                       if seen[name] == "open"],
        "generated_at": generated.isoformat(),
        "authority_note": CHECKLIST_NOTE}
    return report


def incident_report(document: object) -> dict[str, object]:
    """Validate and classify one evidence-based incident diagnostic.

    Args:
        document: Untrusted parsed JSON evidence; never executed or trusted.

    Returns:
        A detached report: ``classified`` with the fixed scenario guidance,
        ``unsupported`` for an unknown scenario, or a fixed error with one
        finite status token otherwise. Diagnostics are read-only analysis.

    Raises:
        Nothing: every failure is returned as data.
    """
    try:
        return _incident_report(document)
    except _Rejection as rejection:
        return {"status": rejection.status, "error": rejection.message}


def _bounded_window(value: object) -> int:
    """Validate one bounded incident window in minutes."""
    if type(value) is not int or not 1 <= value <= INCIDENT_WINDOW_MAX:
        raise _Rejection("malformed", "The incident window is malformed.")
    return value


def _incident_report(document: object) -> dict[str, object]:
    """Apply the fail-closed incident schema; raise fixed rejections."""
    document = _document_shape(document, INCIDENT_FIELDS,
                               INCIDENT_SCHEMA_VERSION,
                               INCIDENT_CLASSIFICATION, "incident")
    observed = _validated_timestamp(document["observed_at"], "incident")
    scenario = document["scenario"]
    if type(scenario) is not str or scenario not in ("health-flap",
                                                     "queue-saturation",
                                                     "inference-deadline",
                                                     "telemetry-gap",
                                                     "revision-drift"):
        raise _Rejection("unsupported", "The incident scenario is outside "
                         "the accepted diagnostic vocabulary.")
    observations = document["observations"]
    if type(observations) is not dict:
        raise _Rejection("malformed", "The incident observations are "
                         "malformed.")
    if scenario == "health-flap":
        if set(observations) != {"readiness_outcomes", "window_minutes"}:
            raise _Rejection("malformed", "The health-flap observations "
                             "contain fields outside the accepted schema.")
        outcomes = observations["readiness_outcomes"]
        if (type(outcomes) is not list or not 1 <= len(outcomes) <= 64
                or any(outcome not in INCIDENT_STATUS_VALUES
                       or type(outcome) is not str for outcome in outcomes)):
            raise _Rejection("malformed", "The readiness outcomes are "
                             "malformed.")
        summary: dict[str, object] = {
            "readiness_failures": outcomes.count("failure"),
            "window_minutes": _bounded_window(observations["window_minutes"])}
        diagnostic = ("Inspect worker readiness per the operations runbook; "
                      "readiness failure while liveness holds indicates "
                      "worker/lifecycle degradation, not process death.")
    elif scenario == "queue-saturation":
        if set(observations) != {"queue_rejected", "window_minutes"}:
            raise _Rejection("malformed", "The queue-saturation observations "
                             "contain fields outside the accepted schema.")
        rejected = observations["queue_rejected"]
        if type(rejected) is not int or not 0 <= rejected <= INCIDENT_COUNT_MAX:
            raise _Rejection("malformed", "The rejected-event count is "
                             "malformed.")
        summary = {"queue_rejected": rejected,
                   "window_minutes": _bounded_window(
                       observations["window_minutes"])}
        diagnostic = ("Bounded admission rejected work; confirm the "
                      "documented backpressure expectation and reviewer "
                      "load shape; no retry mechanism exists by contract.")
    elif scenario == "inference-deadline":
        if set(observations) != {"inference_timeouts", "window_minutes"}:
            raise _Rejection("malformed", "The inference-deadline "
                             "observations contain fields outside the "
                             "accepted schema.")
        timeouts = observations["inference_timeouts"]
        if type(timeouts) is not int or not 0 <= timeouts <= INCIDENT_COUNT_MAX:
            raise _Rejection("malformed", "The timeout count is malformed.")
        summary = {"inference_timeouts": timeouts,
                   "window_minutes": _bounded_window(
                       observations["window_minutes"])}
        diagnostic = ("Cooperative deadlines expired; check queue depth and "
                      "worker readiness before any traffic or scale action; "
                      "scaling remains a human-operated decision.")
    elif scenario == "telemetry-gap":
        if set(observations) != {"monitor_receipt_rows"}:
            raise _Rejection("malformed", "The telemetry-gap observations "
                             "contain fields outside the accepted schema.")
        rows = observations["monitor_receipt_rows"]
        if type(rows) is not int or not 0 <= rows <= 100:
            raise _Rejection("malformed", "The receipt-row count is "
                             "malformed.")
        summary = {"monitor_receipt_rows": rows}
        diagnostic = ("No correlated Monitor receipt was observed; allow the "
                      "documented ingestion window, then rerun the accepted "
                      "bounded aggregate query before escalation.")
    else:
        expected, observed_revision = (observations.get("expected_revision"),
                                       observations.get("observed_revision"))
        if set(observations) != {"expected_revision", "observed_revision"}:
            raise _Rejection("malformed", "The revision-drift observations "
                             "contain fields outside the accepted schema.")
        if (type(expected) is not str or type(observed_revision) is not str
                or REVISION_PATTERN.fullmatch(expected) is None
                or REVISION_PATTERN.fullmatch(observed_revision) is None):
            raise _Rejection("malformed", "The revision observations do not "
                             "match the accepted revision shape.")
        summary = {"expected_revision": expected,
                   "observed_revision": observed_revision}
        diagnostic = ("Active revision differs from the expected revision; "
                      "compare against the recorded accepted revision and "
                      "consult the rollback plan boundary before any action.")
    return {"status": "classified", "scenario": scenario,
            "observed_at": observed.isoformat(), "summary": summary,
            "diagnostic": diagnostic,
            "boundary_note": "Diagnostics are read-only analysis; no "
                             "incident response action is authorized by "
                             "this report."}


def rollback_plan_report(document: object) -> dict[str, object]:
    """Validate one data-only rollback plan against the promotion contract.

    Args:
        document: Untrusted parsed JSON evidence; never executed or trusted.

    Returns:
        A detached report: ``validated`` with the explicit authority note
        when the plan conforms to the accepted promotion contract, or a fixed
        error with one finite status token otherwise. Validation never
        executes, authorizes, or proves a rollback.

    Raises:
        Nothing: every failure is returned as data.
    """
    try:
        return _rollback_plan_report(document)
    except _Rejection as rejection:
        return {"status": rejection.status, "error": rejection.message}


def _rollback_plan_report(document: object) -> dict[str, object]:
    """Apply the fail-closed rollback-plan schema; raise fixed rejections."""
    document = _document_shape(document, ROLLBACK_FIELDS,
                               ROLLBACK_SCHEMA_VERSION,
                               ROLLBACK_CLASSIFICATION, "rollback plan")
    prepared = _validated_timestamp(document["prepared_at"], "rollback plan")
    target_image, target_revision = (document["target_image"],
                                     document["target_revision"])
    if (type(target_image) is not str or IMAGE_PATTERN.fullmatch(target_image)
            is None or type(target_revision) is not str
            or REVISION_PATTERN.fullmatch(target_revision) is None):
        raise _Rejection("malformed", "Rollback target identity does not "
                         "match the accepted shapes.")
    trigger = document["trigger"]
    if type(trigger) is not str or trigger not in ROLLBACK_TRIGGERS:
        raise _Rejection("malformed", "The rollback trigger is outside the "
                         "accepted promotion-contract vocabulary.")
    checks = document["post_rollback_checks"]
    if (type(checks) is not list or len(checks) != len(ROLLBACK_POST_CHECKS)
            or any(check != expected for check, expected in
                   zip(checks, ROLLBACK_POST_CHECKS, strict=True))):
        raise _Rejection("incomplete", "Post-rollback checks must be exactly "
                         "the accepted promotion-contract sequence.")
    if document["execution_authority"] != ROLLBACK_AUTHORITY:
        raise _Rejection("incompatible", "The rollback execution authority "
                         "differs from the accepted promotion contract.")
    if (type(document["deployment_authorized"]) is not bool
            or document["deployment_authorized"]):
        raise _Rejection("incompatible", "A rollback plan never carries "
                         "deployment authority.")
    if document["provenance_precondition"] != ROLLBACK_PROVENANCE_PRECONDITION:
        raise _Rejection("contradictory", "The tested-source provenance "
                         "precondition is unresolved; a plan cannot claim it "
                         "resolved without accepted evidence.")
    return {"status": "validated", "target_revision": target_revision,
            "target_image": target_image, "trigger": trigger,
            "post_rollback_checks": list(ROLLBACK_POST_CHECKS),
            "execution_authority": ROLLBACK_AUTHORITY,
            "deployment_authorized": False,
            "provenance_precondition": ROLLBACK_PROVENANCE_PRECONDITION,
            "prepared_at": prepared.isoformat(), "authority_note":
            ROLLBACK_NOTE}


def slo_report(document: object) -> dict[str, object]:
    """Validate one evidence-grounded SLO register with label discipline.

    Args:
        document: Untrusted parsed JSON evidence; never executed or trusted.

    Returns:
        A detached report: ``consistent`` when every objective uses the
        measured/proposed/illustrative label discipline correctly, or a fixed
        error with one finite status token otherwise.

    Raises:
        Nothing: every failure is returned as data.
    """
    try:
        return _slo_report(document)
    except _Rejection as rejection:
        return {"status": rejection.status, "error": rejection.message}


def _slo_report(document: object) -> dict[str, object]:
    """Apply the fail-closed SLO-register schema; raise fixed rejections."""
    document = _document_shape(document, SLO_FIELDS, SLO_SCHEMA_VERSION,
                               SLO_CLASSIFICATION, "SLO register")
    objectives = document["objectives"]
    if type(objectives) is not list or not objectives or len(objectives) > 16:
        raise _Rejection("malformed", "The SLO objectives are malformed.")
    seen: set[str] = set()
    validated: list[dict[str, object]] = []
    for entry in objectives:
        if type(entry) is not dict:
            raise _Rejection("malformed", "An SLO objective is malformed.")
        if set(entry) - SLO_ENTRY_FIELDS:
            raise _Rejection("malformed", "An SLO objective contains fields "
                             "outside the accepted schema.")
        required = {"name", "label", "objective", "measurement_source"}
        if required - set(entry):
            raise _Rejection("incomplete", "An SLO objective is missing "
                             "required fields.")
        name = entry["name"]
        if type(name) is not str or name not in SLO_OBJECTIVES:
            raise _Rejection("malformed", "An SLO objective name is outside "
                             "the accepted vocabulary.")
        if name in seen:
            raise _Rejection("malformed", "The SLO register repeats an "
                             "objective.")
        seen.add(name)
        label, source = entry["label"], entry["measurement_source"]
        if type(label) is not str or label not in SLO_LABELS:
            raise _Rejection("malformed", "An SLO label is outside the "
                             "accepted measured/proposed/illustrative "
                             "vocabulary.")
        if type(source) is not str or source not in SLO_SOURCES:
            raise _Rejection("malformed", "An SLO measurement source is "
                             "outside the accepted vocabulary.")
        _bounded_text(entry["objective"], "SLO")
        measurement = entry.get("measurement")
        if label == "measured":
            if (type(measurement) not in (int, float)
                    or not 0 <= measurement <= SLO_MEASUREMENT_MAX):
                raise _Rejection("contradictory", "A measured SLO requires a "
                                 "bounded measurement value.")
            if source == "none":
                raise _Rejection("contradictory", "A measured SLO requires "
                                 "an accepted measurement source.")
        elif measurement is not None:
            raise _Rejection("contradictory", "A proposed or illustrative "
                             "SLO must not carry a measurement value.")
        projected: dict[str, object] = {"name": name, "label": label,
                                        "objective": entry["objective"],
                                        "measurement_source": source}
        if measurement is not None:
            projected["measurement"] = measurement
        validated.append(projected)
    return {"status": "consistent", "objectives": validated,
            "label_note": "Labels follow the accepted measured/proposed/"
                          "illustrative discipline; labels are reasoning, "
                          "not SLA claims."}


def cost_report(document: object) -> dict[str, object]:
    """Validate one configuration-bounded cost register.

    Args:
        document: Untrusted parsed JSON evidence; never executed or trusted.

    Returns:
        A detached report: ``consistent`` when every entry separates verified
        configuration facts from operator assumptions and no monetary amount
        is claimed, or a fixed error with one finite status token otherwise.

    Raises:
        Nothing: every failure is returned as data.
    """
    try:
        return _cost_report(document)
    except _Rejection as rejection:
        return {"status": rejection.status, "error": rejection.message}


def _cost_report(document: object) -> dict[str, object]:
    """Apply the fail-closed cost-register schema; raise fixed rejections."""
    document = _document_shape(document, COST_FIELDS, COST_SCHEMA_VERSION,
                               COST_CLASSIFICATION, "cost register",
                               optional_fields=frozenset({"budget_threshold"}))
    entries = document["entries"]
    if type(entries) is not list or not entries or len(entries) > 16:
        raise _Rejection("malformed", "The cost register entries are "
                         "malformed.")
    seen: set[str] = set()
    validated: list[dict[str, object]] = []
    for entry in entries:
        if type(entry) is not dict or set(entry) != COST_ENTRY_FIELDS:
            raise _Rejection("malformed", "A cost entry contains fields "
                             "outside the accepted schema; monetary amounts "
                             "are not an accepted cost-register field.")
        item, kind, basis = entry["item"], entry["kind"], entry["basis"]
        if type(item) is not str or item not in COST_ITEMS:
            raise _Rejection("malformed", "A cost item is outside the "
                             "accepted vocabulary.")
        if item in seen:
            raise _Rejection("malformed", "The cost register repeats an "
                             "item.")
        seen.add(item)
        if type(kind) is not str or kind not in COST_KINDS:
            raise _Rejection("malformed", "A cost entry kind is outside the "
                             "accepted vocabulary.")
        if type(basis) is not str or basis not in COST_BASES:
            raise _Rejection("malformed", "A cost basis is outside the "
                             "accepted vocabulary.")
        if (kind, basis) not in (("verified", "observed-configuration"),
                                 ("assumption", "operator-judgment")):
            raise _Rejection("contradictory", "A verified cost entry must "
                             "rest on observed configuration; an assumption "
                             "must rest on operator judgment.")
        validated.append({"item": item, "kind": kind, "basis": basis})
    threshold = document.get("budget_threshold")
    if threshold is not None:
        _bounded_text(threshold, "budget threshold")
    report: dict[str, object] = {"status": "consistent",
                                 "entries": validated,
                                 "amount_note": "The register records "
                                 "configuration-bounded cost levers; it "
                                 "asserts no dollar amount and is not a "
                                 "billing record."}
    if threshold is not None:
        report["budget_threshold"] = threshold
    return report


def load_evidence(path_text: object) -> object:
    """Read one operator-supplied bounded evidence file and parse its JSON.

    Args:
        path_text: Exact file path supplied by the operator; only that single
            file is opened, read-only and bounded.

    Returns:
        The parsed JSON value; the caller owns further validation.

    Raises:
        EvidenceError: The path is invalid, the file is unreadable, oversized,
            or not a valid UTF-8 JSON document. Messages are fixed and never
            reflect file content or paths; the status token distinguishes
            missing evidence from malformed evidence.
    """
    path = path_text.strip() if type(path_text) is str else ""
    if not path or len(path) > 1000 or "\x00" in path:
        raise EvidenceError("missing", "Provide the exact file path of an "
                            "operations evidence artifact.")
    try:
        with open(path, "rb") as stream:
            raw = stream.read(FILE_BYTES + 1)
    except OSError as exc:
        raise EvidenceError("missing", "The evidence file could not be read "
                            "at the exact path provided.") from exc
    if len(raw) > FILE_BYTES:
        raise EvidenceError("malformed", "The evidence file exceeds the "
                            "accepted evidence size bound.")
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise EvidenceError("malformed", "The evidence file is not a valid "
                            "UTF-8 JSON document.") from exc
    except RecursionError as exc:
        raise EvidenceError("malformed", "The evidence file nests JSON too "
                            "deeply to be accepted.") from exc
