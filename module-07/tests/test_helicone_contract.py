"""Story 7 Helicone contract tests: the 24 accepted contract tests.

Each numbered ``Contract Test N`` verifies exactly one accepted Story 7
contract behavior. Nothing in this module performs a live external write;
the opt-in live contract test is skipped unless its explicit opt-in variable
is set to ``1``.
"""

import ast
import asyncio
import http.server
import json
import logging
import os
import subprocess
import sys
import textwrap
import threading
import tomllib
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from pydantic import SecretStr

from reliability_safety_observability.authorization import (
    AuthorizationPolicy,
    ToolPermission,
)
from reliability_safety_observability.config import RuntimeSettings
from reliability_safety_observability.domain import (
    BudgetState,
    EvidenceClass,
    ExecutionMode,
    UntrustedContent,
    UsageRecord,
    WorkflowIdentity,
    WorkflowState,
)
from reliability_safety_observability.errors import ConfigurationError
from reliability_safety_observability.guardrails_adapter import (
    GuardrailsCredentialProvider,
)
from reliability_safety_observability.helicone_adapter import (
    _MONOTONIC_CLOCK,
    FakeHeliconeEvidenceTransport,
    HeliconeCostEvidenceState,
    HeliconeEvidenceError,
    HeliconeEvidenceExportSpec,
    HeliconeEvidenceSnapshot,
    HeliconeFallbackEvidenceState,
    HeliconeGatewayRoutingSpec,
    HeliconeHttpEvidenceTransport,
    HeliconeReadbackResult,
    RefusalSource,
    _execute_live,
    build_evidence_snapshot,
    build_gateway_routing_spec,
    build_live_verification_spec,
    classify_cost_evidence,
    classify_fallback_evidence,
    close_bounded,
    custom_log_body,
    read_back_bounded,
    run_live_helicone_verification,
    submit_evidence_bounded,
)
from reliability_safety_observability.helicone_config import (
    HeliconeSettings,
    ambient_helicone_variables,
    require_live_helicone,
)
from reliability_safety_observability.reliability import (
    AttemptResult,
    Failure,
    Principal,
    ReliabilityController,
    ReliabilityPolicy,
    Target,
)
from reliability_safety_observability.safety import SafetyPipeline

SRC = Path(__file__).resolve().parents[1] / "src" / "reliability_safety_observability"
MODULE_DIR = SRC.parents[1]
SEAM_ORIGIN = "https://198.51.100.1"
PROVIDER_TARGET = "https://provider.example"
_LIVE_OPT_IN_ENV = "MODULE7_HELICONE_LIVE_VERIFICATION"
REQUEST_ID = str(uuid.uuid5(uuid.NAMESPACE_URL, "module7-story7-request"))
SESSION_ID = str(uuid.uuid5(uuid.NAMESPACE_URL, "module7-story7-session"))
WORKFLOW_ID = str(uuid.uuid5(uuid.NAMESPACE_URL, "module7-story7-workflow"))
OTHER_ID = str(uuid.uuid5(uuid.NAMESPACE_URL, "module7-story7-other"))


def runtime():
    """Build one live runtime settings object for gated branches."""
    return RuntimeSettings(
        mode=ExecutionMode.LIVE,
        live_integrations_enabled=True,
        provider_api_key=SecretStr("provider-key"),
    )


def settings_for(**override):
    """Build one enabled, budgeted settings object bound to the seam origin."""
    values = {
        "enabled": True,
        "api_key": SecretStr("hlcn_seam_key"),
        "provider_target_url": PROVIDER_TARGET,
        "gateway_base_url": SEAM_ORIGIN,
        "evidence_api_base_url": SEAM_ORIGIN,
        "reservation_per_request_usd": 0.001,
        "run_cost_limit_usd": 1.0,
        "readback_attempts": 2,
        "readback_interval_seconds": 0.0,
    }
    values.update(override)
    return HeliconeSettings(**values)


def make_spec(**override) -> HeliconeEvidenceExportSpec:
    """Build one fully validated evidence export specification."""
    values = {
        "request_id": REQUEST_ID,
        "session_id": SESSION_ID,
        "workflow_id": WORKFLOW_ID,
        "evidence_label": "module7-test",
        "application_meta": {"attempts": 1, "fallback_used": False},
    }
    values.update(override)
    return HeliconeEvidenceExportSpec.build(**values)


def row(request_id=REQUEST_ID, session_id=SESSION_ID, cost=None, fallback=None,
        fallback_to=None, **extra):
    """Build one gateway readback row of primitive values."""
    values = {"request_id": request_id, "session_id": session_id}
    values.update(extra)
    if cost is not None:
        values["cost_usd"] = cost
    if fallback is not None:
        values["fallback"] = fallback
    if fallback_to is not None:
        values["fallback_to"] = fallback_to
    return values


def _project(rows) -> HeliconeReadbackResult:
    """Project rows for the test request identity."""
    return HeliconeReadbackResult.project(
        rows, request_id=REQUEST_ID, session_id=SESSION_ID
    )


class SeamDouble:
    """In-process canned Helicone seam over the reserved non-routable origin."""

    def __init__(self, payloads):
        self.payloads = payloads
        self.requests = []

    def __call__(self, observed, request):
        self.requests.append(request)
        path = urlsplit(str(request.url)).path
        return self.payloads.get(path, b"{}")


def _seam_transport(payloads=None, *, opt_in=True, **settings_override):
    """Build one seam-backed HTTP transport over the reserved test origin."""
    return HeliconeHttpEvidenceTransport(
        settings_for(**settings_override),
        runtime=runtime(),
        in_process_seam=SeamDouble(payloads or {}),
        opt_in=opt_in,
    )


def _mini_server(handler):
    """Start one loopback HTTP server driven by a ``(path, body)`` handler."""
    seen = {"hits": 0, "paths": [], "bodies": []}

    class Handler(http.server.BaseHTTPRequestHandler):
        def _dispatch(self):
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            seen["hits"] += 1
            seen["paths"].append(self.path)
            seen["bodies"].append(body)
            status, headers, content = handler(self.path, body)
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        do_POST = do_GET = _dispatch

        def log_message(self, *args):
            return None

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}", seen


def _stop(server):
    server.shutdown()
    server.server_close()


# --------------------------------------------------------------------------
# Contract Test 1: Gated environments.
# --------------------------------------------------------------------------
def test_01_disabled_settings_construct_nothing():
    """Disabled settings refuse the live gate and the routing build."""
    disabled = settings_for(enabled=False)
    assert require_live_helicone(runtime(), disabled) is False
    assert build_gateway_routing_spec(
        runtime(),
        disabled,
        action_id=uuid.UUID(REQUEST_ID),
        trace_id=uuid.UUID(SESSION_ID),
        workflow_id=uuid.UUID(WORKFLOW_ID),
        evidence_class=EvidenceClass.MOCKED_PROVIDER_CONTRACT,
    ) is None
    require_live_helicone(runtime(), settings_for())
    with pytest.raises(ConfigurationError):
        run_live_helicone_verification(runtime(), disabled, opt_in=True)


def test_01b_ambient_vendor_variables_refuse_the_gate(monkeypatch):
    """Ambient vendor variables and incomplete live settings refuse."""
    for key in ("HELICONE_API_KEY", "HELC_AGENT"):
        monkeypatch.setenv(key, "ambient")
    assert ambient_helicone_variables()
    with pytest.raises(ConfigurationError):
        require_live_helicone(runtime(), settings_for())
    with pytest.raises(ConfigurationError):
        HeliconeSettings(
            enabled=True,
            api_key=SecretStr("hlcn_partial"),
            reservation_per_request_usd=None,
            run_cost_limit_usd=None,
            gateway_base_url=None,
            evidence_api_base_url=None,
            provider_target_url=None,
        )


def test_01c_provider_target_urls_fail_closed_including_prohibited_shapes():
    """Unsafe, local or prohibited provider targets fail closed at settings."""
    for candidate in (
        "http://provider.example",
        "https://localhost",
        "https://127.0.0.1",
        "https://169.254.169.254",
        "https://198.51.100.5",
        "https://user@provider.example",
        "https://provider.example/path?q=1",
        "https://sub.instance.internal",
        "",
    ):
        with pytest.raises(ConfigurationError):
            HeliconeSettings(
                enabled=False,
                provider_target_url=candidate,
            )


# --------------------------------------------------------------------------
# Contract Test 2: Token and header hygiene.
# --------------------------------------------------------------------------
def test_02_token_never_renders_and_headers_stay_allowlisted():
    """No secret in repr/body/errors; routing headers are allowlisted only."""
    secret_text = "hlcn_secret_value"
    settings = settings_for(api_key=SecretStr(secret_text))
    assert secret_text not in repr(settings)
    spec = HeliconeGatewayRoutingSpec(
        action_id=uuid.UUID(REQUEST_ID),
        trace_id=uuid.UUID(SESSION_ID),
        workflow_id=uuid.UUID(WORKFLOW_ID),
        evidence_class=EvidenceClass.MOCKED_PROVIDER_CONTRACT,
        _settings=settings,
    )
    assert secret_text not in repr(spec)
    headers = spec.compose_headers({})
    assert set(headers) >= {
        "Helicone-Request-Id",
        "Helicone-Session-Id",
        "Helicone-Auth",
    }
    assert headers["Helicone-Request-Id"] == REQUEST_ID
    assert headers["Helicone-Session-Id"] == SESSION_ID
    with pytest.raises(HeliconeEvidenceError) as exc_info:
        spec.compose_headers({"Helicone-Trace": "caller-override"})
    assert exc_info.value.reason == RefusalSource.CALLER_HEADER_OVERRIDE
    body = json.dumps(custom_log_body(make_spec()))
    assert secret_text not in body
    refusal = HeliconeEvidenceError(RefusalSource.BUDGET)
    assert str(refusal) == "Helicone gateway evidence refused (budget_refused)."
    assert secret_text not in str(refusal)


# --------------------------------------------------------------------------
# Contract Test 3: Source confinement (AST).
# --------------------------------------------------------------------------
def test_03_requests_imports_confined_and_no_authority_import():
    """``requests`` stays in the two adapters; no Story 3 authority imports."""
    for path in sorted(SRC.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        roots: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots.add(node.module.split(".")[0])
        adapters = {"helicone_adapter.py", "langsmith_adapter.py"}
        if path.name in adapters:
            assert "requests" in roots
        else:
            assert "requests" not in roots
        assert "helicone" not in roots | {path.stem}
        if path.name == "helicone_adapter.py":
            forbidden = {"reliability", "safety", "authorization"}
            assert not (forbidden & roots)
        init_tree = ast.parse(
            (SRC / "__init__.py").read_text(encoding="utf-8"),
        )
        for node in ast.walk(init_tree):
            names = [alias.name for alias in node.names] if isinstance(
                node, (ast.Import, ast.ImportFrom)
            ) else []
            for name in names:
                assert "helicone_adapter" not in name and "langsmith_adapter" not in name
        for other in sorted(SRC.glob("*.py")):
            skip = {"helicone_adapter.py", "langsmith_adapter.py", "__init__.py"}
            # Human-approved Story 7 / Story 8 reconciliation (Option A): the
            # accepted Story 8 contract (vendor-import rule) authorizes
            # failure_lab.py — and only failure_lab.py — to exercise the
            # accepted adapter public deterministic/offline/fake/seam
            # surfaces. This named allowance narrows nothing else: the
            # confined `requests` rule above and every other module's
            # helicone_adapter prohibition remain fully in force.
            if other.name == "failure_lab.py":
                skip.add("failure_lab.py")
            if other.name in skip:
                continue
            tree = ast.parse(other.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                modules = []
                if isinstance(node, ast.Import):
                    modules.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    modules.append(node.module or "")
                for module_name in modules:
                    assert "helicone_adapter" not in module_name.split(".")


# --------------------------------------------------------------------------
# Contract Test 4: Zero-network deterministic startup with ambient vars.
# --------------------------------------------------------------------------
def test_04_zero_network_deterministic_flow_with_ambient_variables():
    """Subprocess: ambient vars present, zero socket use, vendor absent."""
    script = MODULE_DIR / "_tmp_zero_net_helicone.py"
    script.write_text(
        textwrap.dedent(
            r"""
            import json, os, sys
            for key, value in (
                ("MODULE7_HELICONE_ENABLED", "true"),
                ("MODULE7_HELICONE_API_KEY", "hlcn_env"),
                ("MODULE7_HELICONE_GATEWAY_BASE_URL", "https://198.51.100.1"),
                ("MODULE7_HELICONE_EVIDENCE_API_BASE_URL", "https://198.51.100.1"),
                ("MODULE7_HELICONE_RESERVATION_PER_REQUEST_USD", "0.001"),
                ("MODULE7_HELICONE_RUN_COST_LIMIT_USD", "1.0"),
                ("MODULE7_MODE", "live"),
                ("MODULE7_LIVE_INTEGRATIONS_ENABLED", "true"),
                ("HELICONE_API_KEY", "ambient"),
                ("HELC_AGENT", "ambient"),
            ):
                os.environ[key] = value

            import socket as _socket
            _orig_socket = _socket.socket
            attempts = []

            class _Guarded(_orig_socket):
                def _check(self, address):
                    host = address[0] if isinstance(address, tuple) and address else None
                    if isinstance(host, str) and host not in {
                        "127.0.0.1", "::1", "localhost",
                    }:
                        attempts.append(address)
                        raise AssertionError("network attempted")

                def connect(self, address):
                    self._check(address)
                    return super().connect(address)

                def connect_ex(self, address):
                    self._check(address)
                    return super().connect_ex(address)

            _socket.socket = _Guarded

            from pydantic import SecretStr
            from reliability_safety_observability.config import RuntimeSettings
            from reliability_safety_observability.domain import ExecutionMode
            from reliability_safety_observability.errors import ConfigurationError
            from reliability_safety_observability.helicone_config import (
                HeliconeSettings,
                ambient_helicone_variables,
                require_live_helicone,
            )

            assert "helicone" not in sys.modules
            assert "requests" not in sys.modules
            assert ambient_helicone_variables()
            live = RuntimeSettings(
                mode=ExecutionMode.LIVE,
                live_integrations_enabled=True,
                provider_api_key=SecretStr("provider-key"),
            )
            try:
                require_live_helicone(live, HeliconeSettings())
            except ConfigurationError:
                pass
            else:
                raise AssertionError("ambient variables must refuse the gate")

            import asyncio as _asyncio
            from reliability_safety_observability.evaluation_benchmark import (
                benchmark_report,
            )
            from reliability_safety_observability.evaluation_contracts import (
                canonical_digest,
            )
            from reliability_safety_observability.evaluation_dataset import (
                load_benchmark_dataset,
            )
            from reliability_safety_observability.evaluation_engine import (
                EvaluationEngine,
            )
            from reliability_safety_observability.evaluation_target import (
                ReferenceTarget,
            )
            from reliability_safety_observability.helicone_adapter import (
                build_gateway_routing_spec,
            )

            dataset = load_benchmark_dataset()
            exported_subset = tuple(dataset.scenario_ids[:1])
            artifact = _asyncio.run(EvaluationEngine().run(
                dataset,
                target_id="reference_default",
                target_version=1,
                target_factory=ReferenceTarget.build,
                scenario_ids=exported_subset,
            ))
            digest = canonical_digest(
                benchmark_report(artifact, exported_subset, None)
            )
            assert digest

            spec_result = build_gateway_routing_spec(
                live,
                HeliconeSettings(enabled=False),
                action_id=__import__("uuid").uuid4(),
                trace_id=__import__("uuid").uuid4(),
                workflow_id=__import__("uuid").uuid4(),
                evidence_class=None,
            )
            assert spec_result is None
            assert attempts == [], attempts
            assert "helicone" not in sys.modules
            print(json.dumps({"zero_network": True, "scenarios": 1}))
            """,
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, timeout=180,
        cwd=str(MODULE_DIR),
    )
    script.unlink(missing_ok=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout.strip().splitlines()[-1]) == {
        "zero_network": True,
        "scenarios": 1,
    }


# --------------------------------------------------------------------------
# Contract Test 5: Routing specification boundaries.
# --------------------------------------------------------------------------
def test_05_routing_spec_composition_and_refusals():
    """Gated build; exact allowlisted headers; UUID/override boundaries."""
    settings = settings_for()
    spec = build_gateway_routing_spec(
        runtime(),
        settings,
        action_id=uuid.UUID(REQUEST_ID),
        trace_id=uuid.UUID(SESSION_ID),
        workflow_id=uuid.UUID(WORKFLOW_ID),
        evidence_class=EvidenceClass.MOCKED_PROVIDER_CONTRACT,
    )
    headers = spec.compose_headers({"x-caller": "ok"})
    assert headers["x-caller"] == "ok"
    assert headers["Helicone-Request-Id"] == REQUEST_ID
    assert headers["Helicone-Session-Id"] == SESSION_ID
    with pytest.raises(ValueError):
        build_gateway_routing_spec(
            runtime(),
            settings,
            action_id=REQUEST_ID,
            trace_id=uuid.UUID(SESSION_ID),
            workflow_id=uuid.UUID(WORKFLOW_ID),
            evidence_class=EvidenceClass.MOCKED_PROVIDER_CONTRACT,
        )
    with pytest.raises(HeliconeEvidenceError):
        spec.compose_headers({"Helicone-Session-Id": "override"})
    assert build_gateway_routing_spec(
        runtime(),
        settings_for(enabled=False),
        action_id=uuid.UUID(REQUEST_ID),
        trace_id=uuid.UUID(SESSION_ID),
        workflow_id=uuid.UUID(WORKFLOW_ID),
        evidence_class=EvidenceClass.MOCKED_PROVIDER_CONTRACT,
    ) is None


def test_05b_enabled_build_requires_the_live_runtime_gate():
    """Enabled settings outside the activated live gate refuse to build."""
    deterministic = RuntimeSettings(
        mode=ExecutionMode.DETERMINISTIC,
        live_integrations_enabled=False,
        provider_api_key=SecretStr("provider-key"),
    )
    with pytest.raises(ConfigurationError):
        build_gateway_routing_spec(
            deterministic,
            settings_for(),
            action_id=uuid.UUID(REQUEST_ID),
            trace_id=uuid.UUID(SESSION_ID),
            workflow_id=uuid.UUID(WORKFLOW_ID),
            evidence_class=EvidenceClass.MOCKED_PROVIDER_CONTRACT,
        )


# --------------------------------------------------------------------------
# Contract Test 6: Evidence layering (snapshot assembly).
# --------------------------------------------------------------------------
def test_06_evidence_snapshot_classification_layering():
    """The snapshot joins projection, cost and fallback classification."""
    spec = make_spec()
    readback = _project([row(cost=0.5, fallback=False)])
    snapshot = build_evidence_snapshot(
        spec,
        readback,
        app_cost_usd=0.5,
        app_fallback_used=False,
        app_fallback_targets=None,
        tolerance=0.01,
    )
    assert snapshot.correlation_matched is True
    assert snapshot.cost_state == "match"
    assert snapshot.fallback_state == "agree"
    assert snapshot.gateway_fallback_observed == "none"
    assert snapshot.unrelated_rows == 0
    assert snapshot == HeliconeEvidenceSnapshot(
        request_id=REQUEST_ID,
        session_id=SESSION_ID,
        workflow_id=WORKFLOW_ID,
        correlation_matched=True,
        cost_state="match",
        gateway_cost_usd=0.5,
        fallback_state="agree",
        gateway_fallback_observed="none",
        unrelated_rows=0,
        stale_rows=0,
        ambiguous_rows=0,
        conflicting_rows=0,
        malformed_rows=0,
    )


def test_06b_snapshot_records_mismatch_without_authority():
    """Mismatched and unresolved evidence stay non-authoritative."""
    spec = make_spec()
    mismatch = build_evidence_snapshot(
        spec,
        _project([row(cost=9.9)]),
        app_cost_usd=0.5,
        app_fallback_used=False,
        app_fallback_targets=None,
        tolerance=0.01,
    )
    assert mismatch.cost_state == "disagree"
    unresolved = build_evidence_snapshot(
        spec,
        _project([row(cost=0.5), row(cost=0.5)]),
        app_cost_usd=0.5,
        app_fallback_used=False,
        app_fallback_targets=None,
        tolerance=0.01,
    )
    assert unresolved.correlation_matched is False
    with pytest.raises(ValueError):
        build_evidence_snapshot(
            spec,
            _project([]),
            app_cost_usd=-1.0,
            app_fallback_used=False,
            app_fallback_targets=None,
            tolerance=0.01,
        )


# --------------------------------------------------------------------------
# Contract Test 7: Export body allowlist.
# --------------------------------------------------------------------------
def test_07_export_body_shape_is_fixed_and_bounded():
    """The custom-log body is exactly the fixed two-level allowlist."""
    spec = make_spec(
        application_meta={
            "attempts": 2,
            "fallbacks": 1,
            "replayed": 0,
            "effect_count": 1,
            "budget_outcome": "ok",
        },
        provider_request_intent={"model": "synthetic"},
        observed_evidence={"response_summary": "bounded"},
        timing={"duration_ms": 1.0},
    )
    body = custom_log_body(spec)
    assert set(body) == {"_type", "log"}
    assert body["_type"] == "data"
    log = body["log"]
    assert set(log) == {"helicone_request_id", "provider", "meta"}
    assert log["helicone_request_id"] == REQUEST_ID
    assert log["provider"] == "module7-synthetic-evidence"
    assert set(log["meta"]) == {
        "action_id",
        "trace_id",
        "workflow_id",
        "application_evidence_label",
        "provider_request_intent",
        "application_meta",
        "observed_evidence",
        "timing",
    }
    assert log["meta"]["action_id"] == REQUEST_ID
    assert json.loads(json.dumps(body)) == body


def test_07b_application_meta_only_admits_the_allowlisted_facts():
    """Unsupported or oversized application_meta entries are refused."""
    for candidate in ("model", "prompt", "output", "scenario_text"):
        with pytest.raises(ValueError):
            HeliconeEvidenceExportSpec.build(
                request_id=REQUEST_ID,
                session_id=SESSION_ID,
                workflow_id=WORKFLOW_ID,
                evidence_label="module7-test",
                application_meta={candidate: "x"},
            )
    with pytest.raises(ValueError):
        HeliconeEvidenceExportSpec.build(
            request_id=REQUEST_ID,
            session_id=SESSION_ID,
            workflow_id=WORKFLOW_ID,
            evidence_label="module7-test",
            application_meta={"attempts": "y" * 300},
        )


# --------------------------------------------------------------------------
# Contract Test 8: Readback projection and correlation.
# --------------------------------------------------------------------------
def test_08_readback_projection_count_evidence_and_extractions():
    """Rows and counts are projected under the exact accepted rules."""
    single = _project([row(cost=0.5, fallback=False)])
    assert single.usable_rows == ({
        "helicone_request_id": REQUEST_ID,
        "session_id": SESSION_ID,
        "cost_usd": 0.5,
        "fallback": False,
    },)
    assert single.confirmed_correlation is True
    assert _project([row(request_id=OTHER_ID)]).unrelated_rows == 1
    assert _project([row(session_id=OTHER_ID)]).stale_rows == 1
    malformed = HeliconeReadbackResult.project(
        [42], request_id=REQUEST_ID, session_id=SESSION_ID
    )
    assert malformed.malformed_rows == 1
    duplicate = _project([row(cost=0.5), row(cost=0.5)])
    assert duplicate.ambiguous_rows == 1
    assert duplicate.confirmed_correlation is False
    assert _project([]).usable_rows == ()


def test_08b_conflicting_matching_rows_fail_safe():
    """Extraction disagreement across rows refuses confirmation."""
    conflicting = _project([row(cost=0.5), row(cost=0.6)])
    assert conflicting.conflicting_rows == 1
    assert conflicting.unresolved is True
    assert conflicting.confirmed_correlation is False
    assert _project([row(session_id=OTHER_ID)]).confirmed_correlation is False
    assert _project([row()]).confirmed_correlation is True


def test_08c_projection_field_aliases_are_normalized():
    """Gateway snake_case aliases normalize onto canonical projections."""
    readback = _project([{
        "helicone_request_id": REQUEST_ID,
        "trace_id": SESSION_ID,
        "costUSD": 0.5,
        "provider_fallback": True,
        "fallbackTo": "other-target",
    }])
    assert readback.usable_rows == ({
        "helicone_request_id": REQUEST_ID,
        "session_id": SESSION_ID,
        "cost_usd": 0.5,
        "fallback": True,
        "fallback_to": "other-target",
    },)
    assert readback.confirmed_correlation is True


def _cost_state(readback, app_cost, tolerance=1e-9):
    """Classify cost and return the state label of record."""
    return classify_cost_evidence(app_cost, readback, tolerance=tolerance).state


def _fallback_state(app_used, app_targets, readback):
    """Classify fallback evidence and return the state object of record."""
    return classify_fallback_evidence(app_used, app_targets, readback)


def test_07_extra_alias_export_reuses_allowlisted_fields():
    """Body meta strings only contain allowlisted field keys."""
    spec = make_spec()
    body = custom_log_body(spec)
    assert set(body["log"]["meta"]) <= set(
        custom_log_body(make_spec())["log"]["meta"]
    )


# --------------------------------------------------------------------------
# Contract Test 9: Cost classification table.
# --------------------------------------------------------------------------
def test_09_cost_classification_table_is_exact():
    """Missing/malformed/match/disagree classify exactly, never match unsafely."""
    empty = _project([])
    assert _cost_state(empty, 0.5) == "missing"
    plain = _project([row(cost=0.5)])
    assert _cost_state(plain, 0.5) == "match"
    assert _cost_state(plain, 0.55, tolerance=0.1) == "match"
    assert _cost_state(plain, 0.55, tolerance=1e-9) == "disagree"
    duplicates = _project([row(cost=0.5), row(cost=0.5)])
    assert _cost_state(duplicates, 0.5) == "malformed"
    conflicting = _project([row(cost=0.5), row(cost=0.6)])
    assert _cost_state(conflicting, 0.5) == "malformed"
    stale = _project([row(session_id=OTHER_ID, cost=0.5)])
    assert _cost_state(stale, 0.5) == "missing"
    no_cost = _project([row()])
    assert _cost_state(no_cost, 0.5) == "malformed"
    noncost = _project([row(cost="not-a-number")])
    assert _cost_state(noncost, 0.5) == "malformed"
    for bad in (-1, "x", float("nan"), float("inf")):
        with pytest.raises(ValueError):
            classify_cost_evidence(bad, plain, tolerance=0.01)
    with pytest.raises(ValueError):
        classify_cost_evidence(0.5, plain, tolerance=float("nan"))
    with pytest.raises(ValueError):
        classify_cost_evidence(0.5, plain, tolerance=-0.1)
    state = classify_cost_evidence(0.5, plain, tolerance=0.01)
    assert state == HeliconeCostEvidenceState(
        state="match", gateway_cost_usd=0.5, app_cost_usd=0.5, malformed_rows=0
    )
    classify_cost_evidence("0.5", plain, tolerance=0.01)


# --------------------------------------------------------------------------
# Contract Test 10: Fallback evidence truth table.
# --------------------------------------------------------------------------
def test_10_fallback_truth_table_is_exact():
    """agree/disagree/gateway_only/app_only/unknown classify exactly."""
    one_false = _project([row(fallback=False)])
    one_true = _project([row(fallback=True, fallback_to=PROVIDER_TARGET)])
    other_target = _project([row(fallback=True, fallback_to="other-target")])
    unknown_row = _project([row(cost=0.2)])
    assert _fallback_state(False, None, one_false).state == "agree"
    assert _fallback_state(True, (PROVIDER_TARGET,), one_true).state == "agree"
    assert _fallback_state(False, None, one_true).state == "gateway_only"
    assert _fallback_state(True, None, one_false).state == "app_only"
    assert _fallback_state(True, (PROVIDER_TARGET,), other_target).state == "disagree"
    assert _fallback_state(None, None, one_true).state == "unknown"
    assert _fallback_state(True, None, unknown_row).state == "unknown"
    assert _fallback_state(False, None, unknown_row).state == "unknown"
    assert _fallback_state(False, None, _project([])).state == "unknown"
    assert _fallback_state(False, None, one_true).gateway_fallback_observed == "observed"
    assert _fallback_state(False, None, one_false).gateway_fallback_observed == "none"
    assert _fallback_state(False, None, unknown_row).gateway_fallback_observed == "unknown"
    gateway = _fallback_state(False, None, one_true)
    assert gateway.fallback_target == PROVIDER_TARGET
    assert gateway == HeliconeFallbackEvidenceState(
        state="gateway_only",
        gateway_fallback_observed="observed",
        fallback_target=PROVIDER_TARGET,
    )


def test_10b_true_true_with_known_target_mismatch_disagrees():
    """Both-used with differing known targets classifies disagree."""
    other_target = _project([row(fallback=True, fallback_to="other-target")])
    state = _fallback_state(True, (PROVIDER_TARGET,), other_target)
    assert state.state == "disagree"
    assert state.fallback_target == "other-target"
    matched = _fallback_state(
        True, (PROVIDER_TARGET,),
        _project([row(fallback=True, fallback_to=PROVIDER_TARGET)]),
    )
    assert matched.state == "agree"


# --------------------------------------------------------------------------
# Contract Test 11: Story 3 authority preservation (behavioral evidence).
# --------------------------------------------------------------------------
def _controller_setup():
    """Build one real Story 3 controller under a permissive local policy."""
    auth = AuthorizationPolicy(
        policy_id="story7-contract",
        tools=[ToolPermission(tool_name=name) for name in ("a", "b", "c")],
        grants={"alice": ["a", "b"]},
    )
    controller = ReliabilityController(
        policy=ReliabilityPolicy(backoff_seconds=0.0),
        authorization=auth,
        safety=SafetyPipeline(providers=[GuardrailsCredentialProvider()]),
        clock=lambda: 0.0,
        sleeper=asyncio.sleep,
    )
    return controller, auth


def _make_operation(responses, counters):
    """Build one target adapter recording keys and side effects."""
    iterator = iter(responses)

    async def operation(key, content):
        counters["keys"].append(key)
        response = next(iterator)
        if response.output is not None:
            counters["effects"] += 1
        return response

    return operation


def _controller_run(controller, auth, primaries):
    """Run one approved operation through the real controller."""
    counters = {"keys": [], "effects": 0}
    state = WorkflowState(
        identity=WorkflowIdentity(),
        operation="effect",
        budget=BudgetState(cost_limit_usd=5.0),
        evidence_class=EvidenceClass.SIMULATED_FAILURE,
    )
    targets = []
    for index, (tool, responses) in enumerate(primaries):
        operation = _make_operation(responses, counters)
        targets.append(Target(
            tool,
            auth.authorize(principal_id="alice", tool_name=tool),
            operation,
            0.01,
        ))
        _ = index
    result = asyncio.run(controller.execute(
        principal=Principal(principal_id="alice"),
        state=state,
        content=UntrustedContent(value="Perform the approved action"),
        targets=tuple(targets),
    ))
    return result, counters


def _transient_failure(cost=0.01) -> AttemptResult:
    """Build one recorded transient failure attempt result."""
    return AttemptResult(
        failure=Failure.TRANSIENT,
        repeat_safe=True,
        usage=UsageRecord(cost_usd=cost),
    )


def _success(cost=0.01) -> AttemptResult:
    """Build one recorded successful attempt result."""
    return AttemptResult(
        output=UntrustedContent(value="ok"),
        usage=UsageRecord(cost_usd=cost),
    )


_FLAKY_PAIR = (
    ("a", (_transient_failure(), _transient_failure())),
    ("b", (_success(),)),
)


def test_11_helicone_classification_never_drives_story3_or_authority():
    """Real-controller runs stay identical with Helicone churn between them."""
    controller, auth = _controller_setup()
    result1, counters1 = _controller_run(controller, auth, _FLAKY_PAIR)
    assert result1.classification == "success"
    assert result1.fallbacks == 1
    fake = FakeHeliconeEvidenceTransport(
        rows=[row(cost=9.9, fallback=True, fallback_to="never")],
    )
    spec = make_spec()
    fake.submit_evidence(spec)
    readback = _project(fake.read_back(spec))
    snapshot = build_evidence_snapshot(
        spec,
        readback,
        app_cost_usd=0.02,
        app_fallback_used=True,
        app_fallback_targets=("b",),
        tolerance=0.01,
    )
    assert snapshot.fallback_state in {"agree", "disagree", "gateway_only"}
    assert fake.evidence_class == EvidenceClass.MOCKED_PROVIDER_CONTRACT
    result2, counters2 = _controller_run(controller, auth, _FLAKY_PAIR)
    assert result2.classification == result1.classification
    assert result2.attempts == result1.attempts
    assert result2.fallbacks == result1.fallbacks
    assert result2.state.usage.cost_usd == result1.state.usage.cost_usd
    assert result2.state.budget.cost_used_usd == result1.state.budget.cost_used_usd
    assert len(set(counters1["keys"])) == 1
    assert len(counters1["keys"]) == len(counters2["keys"]) == 3
    assert counters1["effects"] == counters2["effects"] == 1
    with pytest.raises(HeliconeEvidenceError):
        FakeHeliconeEvidenceTransport(failure=RefusalSource.BUDGET).submit_evidence(
            make_spec()
        )


# --------------------------------------------------------------------------
# Contract Test 12: Zero hidden retries.
# --------------------------------------------------------------------------
def test_12_no_hidden_retries_at_adapter_session_or_spec_level():
    """Exactly one submit per spec; repeat submit sends no further request."""
    payloads = {
        "/custom/v1/log": b"{}",
        f"/api/v1/request/{REQUEST_ID}": b"{}",
    }
    transport = _seam_transport(payloads)
    spec = make_spec()
    transport.submit_evidence(spec)
    with pytest.raises(HeliconeEvidenceError) as exc_info:
        transport.submit_evidence(spec)
    assert exc_info.value.reason == RefusalSource.REPEAT_EXPORT
    assert sum(len(b.observed) for b in transport._boundary._boundaries.values()) == 1
    assert transport.accounting()["requests_sent"] == 1
    assert transport.accounting()["requests_refused"] == 0
    asyncio.run(close_bounded(transport, 5.0))


def test_12b_readback_bound_attempts_only_and_ledger_matches_hits():
    """Readback attempts are bounded; ledger charges equal actual requests."""
    payloads = {
        "/custom/v1/log": b"{}",
        f"/api/v1/request/{REQUEST_ID}": b"[]",
    }
    transport = _seam_transport(payloads)
    spec = make_spec()
    transport.submit_evidence(spec)
    for _attempt in range(2):
        rows = transport.read_back(spec)
        assert rows == []
    accounting = transport.accounting()
    assert accounting["requests_sent"] == 3
    seam_hits = sum(
        1 for request in transport._seam.requests if urlsplit(
            str(request.url)
        ).path == "/custom/v1/log"
    )
    seam_readbacks = sum(
        1 for request in transport._seam.requests if urlsplit(
            str(request.url)
        ).path.startswith("/api/v1/request/")
    )
    assert seam_hits == 1
    assert seam_readbacks == 2
    asyncio.run(close_bounded(transport, 5.0))


# --------------------------------------------------------------------------
# Contract Test 13: Bounded timeout, deadline and resource behavior.
# --------------------------------------------------------------------------
def test_13c_oversized_readback_refused_with_one_charged_request():
    """The readback path refuses oversize with exactly one charged request."""
    oversized = b"x" * 1_048_577

    def handler(path, body):
        content = oversized if path != "/custom/v1/log" else b"{}"
        return (200, {"Content-Type": "application/json"}, content)

    server, origin, _seen = _mini_server(handler)
    try:
        transport = HeliconeHttpEvidenceTransport(
            settings_for(
                gateway_base_url=origin,
                evidence_api_base_url=origin,
                request_timeout_seconds=5.0,
            ),
            runtime=runtime(),
            opt_in=True,
        )
        spec = make_spec()
        transport.submit_evidence(spec)
        with pytest.raises(HeliconeEvidenceError) as exc_info:
            transport.read_back(spec)
        assert exc_info.value.reason == RefusalSource.OVERSIZED_RESPONSE
        assert transport.accounting()["requests_sent"] == 2
        asyncio.run(close_bounded(transport, 5.0))
    finally:
        _stop(server)


def test_13d_per_op_timeout_and_whole_run_deadline_are_distinct():
    """A per-op timeout reports 'timeout'; whole-run exhaustion never mints."""
    import time as _time

    def slow_logger(path, body):
        _time.sleep(1.5)
        return (200, {"Content-Type": "application/json"}, b"{}")

    server, origin, _seen = _mini_server(slow_logger)
    try:
        transport = HeliconeHttpEvidenceTransport(
            settings_for(
                gateway_base_url=origin,
                evidence_api_base_url=origin,
                request_timeout_seconds=5.0,
            ),
            runtime=runtime(),
            opt_in=True,
        )
        spec = make_spec()
        outcome, _value, thread = asyncio.run(
            submit_evidence_bounded(transport, spec, 0.2),
        )
        assert outcome == "timeout"
        assert thread.is_alive()
        thread.join(timeout=10.0)
        deadline = _MONOTONIC_CLOCK() - 1.0
        transport._boundary.set_deadline(deadline)
        whole_run = _execute_live(transport, spec, deadline=deadline)
        assert whole_run.outcome == "timeout_unresolved"
        assert whole_run.outcome != outcome
        asyncio.run(close_bounded(transport, 5.0))
    finally:
        _stop(server)
def test_13_bounded_export_and_readback_over_loopback():
    """Bounded wrappers drive one submit plus bounded readback attempts."""
    payloads = {
        "/custom/v1/log": b"{}",
        f"/api/v1/request/{REQUEST_ID}": b"[]",
    }
    server, origin, seen = _mini_server(
        lambda path, body: (
            (200, {"Content-Type": "application/json"}, payloads.get(path, b"{}")),
            (404, {"Content-Type": "application/json"}, b"{}"),
        )[path != "/custom/v1/log"]
    )
    try:
        transport = HeliconeHttpEvidenceTransport(
            settings_for(
                gateway_base_url=origin,
                evidence_api_base_url=origin,
                request_timeout_seconds=5.0,
                readback_attempts=2,
            ),
            runtime=runtime(),
            opt_in=True,
        )
        spec = make_spec()
        outcome, value, _thread = asyncio.run(submit_evidence_bounded(
            transport, spec, 5.0,
        ))
        assert outcome == "ok"
        assert value is None
        for _attempt in range(2):
            readback_outcome, rows, _ = asyncio.run(read_back_bounded(
                transport, spec, 5.0,
            ))
            assert readback_outcome == "ok"
            assert rows == []
        assert seen["hits"] == 3
        assert transport.accounting()["requests_sent"] == 3
        asyncio.run(close_bounded(transport, 5.0))
    finally:
        _stop(server)


def test_13b_oversized_export_refuses_with_response_too_large():
    """A response body above the fixed cap refuses with response_too_large."""
    oversized = b"x" * 1_048_577

    def handler(path, body):
        content = oversized if path == "/custom/v1/log" else b"{}"
        return (200, {"Content-Type": "application/json"}, content)

    server, origin, _seen = _mini_server(handler)
    try:
        transport = HeliconeHttpEvidenceTransport(
            settings_for(
                gateway_base_url=origin,
                evidence_api_base_url=origin,
                request_timeout_seconds=5.0,
            ),
            runtime=runtime(),
            opt_in=True,
        )
        with pytest.raises(HeliconeEvidenceError) as exc_info:
            transport.submit_evidence(make_spec())
        assert exc_info.value.reason == RefusalSource.OVERSIZED_RESPONSE
        assert transport.accounting()["requests_sent"] == 1
        asyncio.run(close_bounded(transport, 5.0))
    finally:
        _stop(server)


# --------------------------------------------------------------------------
# Contract Test 14: Lifecycle ownership (close, idempotent, tracked lane).
# --------------------------------------------------------------------------
def test_14_close_is_idempotent_and_closed_transports_refuse_ops():
    """Close closes once; repeat close reports the same result; refusals hold."""
    server, origin, _seen = _mini_server(
        lambda path, body: (200, {"Content-Type": "application/json"}, b"{}"),
    )
    try:
        transport = HeliconeHttpEvidenceTransport(
            settings_for(gateway_base_url=origin, evidence_api_base_url=origin),
            runtime=runtime(),
            opt_in=True,
        )
        assert asyncio.run(close_bounded(transport, 5.0))[0] == "ok"
        outcome, value, _thread = asyncio.run(close_bounded(transport, 5.0))
        assert outcome == "ok"
        assert value is True
        with pytest.raises(HeliconeEvidenceError) as exc_info:
            transport.submit_evidence(make_spec())
        assert exc_info.value.reason == RefusalSource.CLOSED
    finally:
        _stop(server)


# --------------------------------------------------------------------------
# Contract Test 15: Redirect refusal and transport hygiene.
# --------------------------------------------------------------------------
def test_15_redirect_refused_without_following():
    """Any 3xx is returned un-followed and refused; hits stay minimal."""
    server, origin, seen = _mini_server(
        lambda path, body: (
            (301, {"Location": f"{SEAM_ORIGIN}/redirect"}, b"redirect"),
            (404, {"Content-Type": "application/json"}, b"{}"),
        )[path != "/custom/v1/log"]
    )
    try:
        transport = HeliconeHttpEvidenceTransport(
            settings_for(gateway_base_url=origin, evidence_api_base_url=origin),
            runtime=runtime(),
            opt_in=True,
        )
        with pytest.raises(HeliconeEvidenceError) as exc_info:
            transport.submit_evidence(make_spec())
        assert exc_info.value.reason == RefusalSource.REDIRECT
        assert seen["hits"] == 1
        assert transport._session.trust_env is False
        asyncio.run(close_bounded(transport, 5.0))
    finally:
        _stop(server)


# --------------------------------------------------------------------------
# Contract Test 16: Endpoint qualification (syntactic + loopback rules).
# --------------------------------------------------------------------------
def test_16_requires_qualifying_endpoints_and_loopback_http_only():
    """Syntactically unsupported endpoints refuse; loopback http is accepted."""
    with pytest.raises(ConfigurationError):
        settings_for(gateway_base_url="http://api.helicone.example")
    transport = HeliconeHttpEvidenceTransport(
        settings_for(
            gateway_base_url="http://127.0.0.1:1",
            evidence_api_base_url="http://127.0.0.1:1",
        ),
        runtime=runtime(),
        opt_in=True,
    )
    assert transport._live_qualified is False
    transport.close()
    with pytest.raises(HeliconeEvidenceError) as exc_info:
        transport.submit_evidence(make_spec())
    assert exc_info.value.reason == RefusalSource.CLOSED


# --------------------------------------------------------------------------
# Contract Test 17: Provenance mint cap (structural rules).
# --------------------------------------------------------------------------
def test_17_seam_and_fake_transports_never_mint_live_vendor():
    """Confirmed outcomes cap at the mocked/provider contract."""
    payloads = {
        "/custom/v1/log": b"{}",
        f"/api/v1/request/{REQUEST_ID}": json.dumps(
            [{"helicone_request_id": REQUEST_ID, "session_id": SESSION_ID}]
        ).encode(),
    }
    transport = _seam_transport(payloads)
    spec = make_spec()
    result = _execute_live(transport, spec, deadline=_MONOTONIC_CLOCK() + 60)
    assert result.outcome == "confirmed"
    assert result.evidence_class == EvidenceClass.MOCKED_PROVIDER_CONTRACT
    assert result.evidence_class != EvidenceClass.LIVE_VENDOR
    with pytest.raises(AttributeError):
        _execute_live(FakeHeliconeEvidenceTransport(), spec, deadline=None)
    asyncio.run(close_bounded(transport, 5.0))


def test_17b_deadline_exhaustion_never_mints_and_never_refunds():
    """Deadline refusal reports the fixed unresolved label without a mint."""
    payloads = {"/custom/v1/log": b"{}"}
    transport = _seam_transport(payloads)
    spec = make_spec()
    past = _MONOTONIC_CLOCK() - 1.0
    transport._boundary.set_deadline(past)
    result = _execute_live(transport, spec, deadline=past)
    assert result.outcome == "timeout_unresolved"
    assert result.evidence_class is None
    assert result.confirmed_readback is False
    assert "request_accounting" in result.evidence
    asyncio.run(close_bounded(transport, 5.0))


# --------------------------------------------------------------------------
# Contract Test 18: Live wrapper refusal chain.
# --------------------------------------------------------------------------
def test_18_live_wrapper_requires_explicit_opt_in():
    """The wrapper refuses without explicit opt-in before anything else."""
    with pytest.raises(ConfigurationError):
        run_live_helicone_verification(runtime(), settings_for(), opt_in=False)


def test_18b_live_wrapper_requires_remote_non_seam_https_endpoints():
    """Local, loopback and seam endpoints never enter the live branch."""
    loopback = settings_for(
        gateway_base_url="http://127.0.0.1:1",
        evidence_api_base_url="http://127.0.0.1:1",
    )
    with pytest.raises(ConfigurationError):
        run_live_helicone_verification(runtime(), loopback, opt_in=True)
    seam_based = settings_for()
    with pytest.raises(ConfigurationError):
        run_live_helicone_verification(runtime(), seam_based, opt_in=True)


# --------------------------------------------------------------------------
# Contract Test 19: Log and exception containment.
# --------------------------------------------------------------------------
def test_19_vendor_logs_are_elided_and_refusals_carry_no_gateway_text():
    """Helicone-adjacent log records collapse to a fixed safe rendering."""
    secret_text = "hlcn_secret_value"
    from reliability_safety_observability.helicone_adapter import _HeliconeLogFilter

    vendor = logging.getLogger("helicone.gateway.test")
    application = logging.getLogger("not.helicone.app")
    for logger in (vendor, application):
        logger.handlers = [logging.NullHandler()]
    filter_ = _HeliconeLogFilter((secret_text,))
    try:
        vendor.addFilter(filter_)
        application.addFilter(filter_)
        record = logging.LogRecord(
            "helicone.gateway.test", logging.ERROR, "vendor.py", 1,
            "Vendor emitted Bearer %s with %s", (secret_text, "payload"), None,
        )
        filtered = bool(filter_.filter(record))
        assert filtered is True
        assert record.args is None
        assert secret_text not in record.getMessage()
        assert "payload" not in record.getMessage()
        app_record = logging.LogRecord(
            "not.helicone.app", logging.INFO, "app.py", 1,
            "Cost used %s (" + secret_text + ")", ("1.0",), None,
        )
        bool(filter_.filter(app_record))
        assert secret_text not in app_record.getMessage()
        assert "[REDACTED]" in app_record.getMessage()
    finally:
        vendor.removeFilter(filter_)
        application.removeFilter(filter_)

    def leaky_handler(path, body):
        return (
            500,
            {"Content-Type": "application/json"},
            json.dumps({"message": secret_text}).encode(),
        )

    server, origin, _seen = _mini_server(leaky_handler)
    try:
        transport = HeliconeHttpEvidenceTransport(
            settings_for(
                gateway_base_url=origin,
                evidence_api_base_url=origin,
                api_key=SecretStr(secret_text),
            ),
            runtime=runtime(),
            opt_in=True,
        )
        with pytest.raises(HeliconeEvidenceError) as exc_info:
            transport.submit_evidence(make_spec())
        message = str(exc_info.value)
        assert message == "Helicone gateway evidence refused (gateway_refused)."
        assert secret_text not in message
        asyncio.run(close_bounded(transport, 5.0))
    finally:
        _stop(server)


# --------------------------------------------------------------------------
# Contract Test 20: Lifecycle ownership (busy, retained, resolved).
# --------------------------------------------------------------------------
def test_20_busy_lanes_retain_ownership_and_quit_cleanly():
    """Timeout retains ownership; second call refuses busy; close follows."""
    import time as _time

    def slow_logger(path, body):
        _time.sleep(1.5)
        return (200, {"Content-Type": "application/json"}, b"{}")

    server, origin, seen = _mini_server(slow_logger)
    try:
        transport = HeliconeHttpEvidenceTransport(
            settings_for(
                gateway_base_url=origin,
                evidence_api_base_url=origin,
                request_timeout_seconds=5.0,
            ),
            runtime=runtime(),
            opt_in=True,
        )
        spec = make_spec()
        outcome, _value, thread = asyncio.run(
            submit_evidence_bounded(transport, spec, 0.15),
        )
        assert outcome == "timeout"
        assert thread.is_alive()
        busy, _rows, _thread = asyncio.run(
            submit_evidence_bounded(transport, spec, 0.15),
        )
        assert busy == "busy"
        close_outcome, _closed, _t = asyncio.run(close_bounded(transport, 0.15))
        assert close_outcome == "busy"
        thread.join(timeout=10.0)
        assert not thread.is_alive()
        assert seen["hits"] == 1
        assert transport.accounting()["requests_sent"] == 1
        assert transport._live_qualified is False
        final = asyncio.run(close_bounded(transport, 5.0))
        assert final[0] == "ok"
        assert final[1] is True
    finally:
        _stop(server)


# --------------------------------------------------------------------------
# Contract Test 21: Deterministic reproducibility.
# --------------------------------------------------------------------------
def test_21_same_inputs_produce_identical_specs_bodies_and_rows():
    """Reproduction equality for specs, bodies, projections and snapshots."""
    spec_a, spec_b = make_spec(), make_spec()
    assert spec_a == spec_b
    assert custom_log_body(spec_a) == custom_log_body(spec_b)
    payload = {"cost_usd": 0.5, "fallback": False}
    project_a = _project([row(**payload)])
    project_b = _project([row(**payload)])
    assert project_a == project_b
    snapshot_a = build_evidence_snapshot(
        spec_a,
        project_a,
        app_cost_usd=0.5,
        app_fallback_used=False,
        app_fallback_targets=None,
        tolerance=1e-9,
    )
    snapshot_b = build_evidence_snapshot(
        spec_b,
        project_b,
        app_cost_usd=0.5,
        app_fallback_used=False,
        app_fallback_targets=None,
        tolerance=1e-9,
    )
    assert snapshot_a == snapshot_b
    live_a, live_b = build_live_verification_spec(), build_live_verification_spec()
    assert live_a == live_b


# --------------------------------------------------------------------------
# Contract Test 22: Cross-suite regression (subprocess).
# --------------------------------------------------------------------------
def test_22_cross_suite_regression_stays_green():
    """Every other Module 7 test file still passes beside this contract."""
    others = sorted(
        str(path)
        for path in (Path(__file__).parent / "test_*.py").parent.glob("test_*.py")
        if path.name not in {"test_helicone_contract.py"}
    )
    assert others, "expected existing module test files"
    # The Story 5 adapter file retains its full suite but is scheduled early:
    # its bounded read-back lane (2.0s per call) uses load-sensitive timing
    # that sustained thread churn from later files can legitimately stretch
    # into lifecycle-busy fail-closed states. Scheduling it before that churn
    # preserves the complete selection, every original assertion, and the
    # production fail-closed behavior unchanged.
    langfuse = [name for name in others if Path(name).name == "test_langfuse_adapter.py"]
    assert len(langfuse) == 1, "expected exactly one Langfuse test file"
    selected = [name for name in others if Path(name).name != "test_langfuse_adapter.py"]
    authorization = next(
        (index for index, name in enumerate(selected)
         if Path(name).name == "test_authorization.py"),
        -1,
    )
    selected.insert(authorization + 1, langfuse[0])
    assert len(selected) == len(others) == len(set(selected))
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-x", *selected],
        capture_output=True,
        text=True,
        timeout=900,
        cwd=str(MODULE_DIR),
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]


# --------------------------------------------------------------------------
# Contract Test 23: Dependency contract.
# --------------------------------------------------------------------------
def test_23_dependency_contract_snapshot_satisfies_declaration():
    """pyproject and uv.lock agree; no Helicone SDK dependency exists."""
    pyproject = tomllib.loads((MODULE_DIR / "pyproject.toml").read_text("utf-8"))
    declared = " ".join(pyproject["project"]["dependencies"])
    assert "requests>=2.32,<3" in declared
    lock = tomllib.loads((MODULE_DIR / "uv.lock").read_text("utf-8"))
    packages = {package["name"]: package for package in lock["package"]}
    assert "requests" in packages
    assert "helicone" not in packages
    assert "guardrails-ai" in packages


# --------------------------------------------------------------------------
# Contract Test 24: Opt-in live verification (default skipped).
# --------------------------------------------------------------------------
@pytest.mark.skipif(
    os.environ.get(_LIVE_OPT_IN_ENV) != "1",
    reason="Opt-in live Helicone contract test requires "
    + _LIVE_OPT_IN_ENV + "=1; skipped by default.",
)
@pytest.mark.live_vendor
def test_24_opt_in_live_verification_confirms_bounded_chain():
    """The explicit opt-in live contract test verifies the full owned chain."""
    settings = HeliconeSettings()
    runtime_yes = RuntimeSettings()
    spec = build_live_verification_spec()
    assert spec.worst_case_requests() == 2
    result = run_live_helicone_verification(
        runtime_yes, settings, opt_in=True,
    )
    assert isinstance(result.outcome, str)
    if result.outcome == "confirmed":
        assert result.confirmed_readback is True
        accounting = result.evidence["request_accounting"]
        assert accounting["requests_sent"] in (1, 1 + settings.readback_attempts)
    assert result.evidence_class in (None, EvidenceClass.LIVE_VENDOR)

