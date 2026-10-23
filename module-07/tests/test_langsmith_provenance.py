"""Story 6 durable Test 21 provenance cases: local mechanisms, no upgrade.

Cases (a) compatible local HTTP server with schema-complete matching
responses, (c) locally connected socket, and (e) local submit plus matching
readback. Every local mechanism exercises mocked/provider-contract behavior
only; none of them can mint ``live_vendor`` — the live lane refuses any
loopback endpoint before construction and its confirmation chain requires a
non-loopback HTTPS endpoint whose qualification and acceptance happens only
inside the owned branch. No external network is used.
"""

import asyncio
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import pytest
import test_langsmith_seam as seam_support
from pydantic import SecretStr

from reliability_safety_observability.config import RuntimeSettings
from reliability_safety_observability.domain import EvidenceClass, ExecutionMode
from reliability_safety_observability.errors import ConfigurationError
from reliability_safety_observability.langsmith_adapter import (
    LangSmithSdkTransport,
    close_bounded,
    run_live_langsmith_verification,
    submit_plan_bounded,
)
from reliability_safety_observability.langsmith_config import LangSmithSettings

_STAMP = "2026-01-01T00:00:00.000000"


class _LocalHandler(BaseHTTPRequestHandler):
    """Schema-complete canned LangSmith responses over one local origin."""

    server_version = "Module7Local/1"

    @property
    def records(self):
        return self.server.plan  # type: ignore[attr-defined]

    def _reply(self, payload: object) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _dataset(self):
        plan = self.server.plan  # type: ignore[attr-defined]
        return {
            "id": seam_support.DATASET_ID,
            "name": plan.dataset_name,
            "data_type": "kv",
            "created_at": _STAMP,
            "metadata": dict(plan.dataset_metadata),
        }

    def _project(self):
        plan = self.server.plan  # type: ignore[attr-defined]
        return {
            "id": seam_support.PROJECT_ID,
            "name": plan.project_name,
            "tenant_id": "eeeeeeee-eeee-5eee-8eee-eeeeeeeeeeee",
            "created_at": _STAMP,
            "reference_dataset_id": seam_support.DATASET_ID,
        }

    def do_GET(self) -> None:
        parts = urlsplit(self.path)
        path = parts.path
        plan = self.server.plan  # type: ignore[attr-defined]
        if path.startswith("/info"):
            self._reply({"version": "0.14.8", "instance_flags": {}})
        elif path.startswith("/sessions"):
            self._reply([])
        elif path.startswith("/datasets"):
            self._reply(self._dataset())
        elif path.startswith("/examples"):
            self._reply([
                {
                    "id": example.example_id,
                    "dataset_id": seam_support.DATASET_ID,
                    "inputs": dict(example.inputs),
                    "outputs": dict(example.outputs),
                    "metadata": dict(example.metadata),
                }
                for example in plan.examples
            ])
        elif path.startswith("/feedback"):
            trace_by_run = {
                fragment.run_id: fragment.trace_id for fragment in plan.runs
            }
            self._reply([
                {
                    "id": fragment.feedback_id,
                    "run_id": fragment.run_id,
                    "trace_id": trace_by_run[fragment.run_id],
                    "key": fragment.key,
                    "score": fragment.score,
                    "created_at": _STAMP,
                    "modified_at": _STAMP,
                    "feedback_source": {
                        "type": "model",
                        "metadata": dict(fragment.source_info),
                    },
                }
                for fragment in plan.feedback
            ])
        else:
            self._reply({})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except (ValueError, UnicodeError):
            body = {}
        plan = self.server.plan  # type: ignore[attr-defined]
        path = urlsplit(self.path).path
        if path.startswith("/examples/bulk") or path.startswith("/examples"):
            self._reply([{"id": example.example_id} for example in plan.examples])
        elif path.startswith("/feedback"):
            self._reply({
                "id": body.get("id"),
                "run_id": body.get("run_id"),
                "key": body.get("key"),
                "score": body.get("score"),
                "created_at": _STAMP,
                "modified_at": _STAMP,
            })
        elif path.startswith("/runs"):
            self._reply({
                "id": body.get("id") or "",
                "name": body.get("name") or "",
                "run_type": "chain",
                "created_at": _STAMP,
            })
        elif path.startswith("/sessions"):
            self._reply(self._project())
        else:
            self._reply({})

    def log_message(self, fmt: str, *args: object) -> None:
        return None  # Silent: provenance probes must not write vendor content.


def _local_server(plan):
    """Start one compatible local HTTP server for the plan."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _LocalHandler)
    server.plan = plan  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _runtime():
    return RuntimeSettings(
        mode=ExecutionMode.LIVE,
        live_integrations_enabled=True,
        provider_api_key=SecretStr("provider-key"),
    )


def _local_transport(port: int):
    return LangSmithSdkTransport(
        LangSmithSettings(
            enabled=True,
            api_key=SecretStr("lsv2_pt_local_provenance_key"),
            api_url=f"http://127.0.0.1:{port}",
            reservation_per_request_usd=0.001,
            run_cost_limit_usd=1.0,
        ),
        runtime=_runtime(),
        opt_in=True,
    )


def test_provenance_local_server_submit_readback_never_mints_live_vendor():
    """Cases (a)+(e): local HTTP server, schema-complete, matching readback.

    The transport submits the plan and reads back matching typed counts over
    a real local HTTP server; the evidence remains the mocked/provider-contract
    class and the live branch still refuses the same endpoint outright.
    """
    plan = seam_support.subset_plan(1)
    server, thread = _local_server(plan)
    try:
        transport = _local_transport(server.server_address[1])
        asyncio.run(submit_plan_bounded(transport, plan, 30))
        result, counts, _thread = asyncio.run(
            (__import__(
                "reliability_safety_observability.langsmith_adapter",
                fromlist=["read_back_bounded"],
            )).read_back_bounded(transport, plan, 30)
        )
        assert result == "ok"
        assert counts == {"examples": len(plan.examples), "feedback": len(plan.feedback)}
        # Provenance stays the mocked/provider-contract class, never live_vendor.
        assert transport.evidence_class is EvidenceClass.MOCKED_PROVIDER_CONTRACT
        close_outcome, state, _thread = asyncio.run(close_bounded(transport, 30))
        assert close_outcome == "ok" and state is True
        # Case (a): the live branch refuses the very local endpoint outright.
        with pytest.raises(ConfigurationError):
            run_live_langsmith_verification(
                _runtime(),
                LangSmithSettings(
                    enabled=True,
                    api_key=SecretStr("lsv2_pt_local_provenance_key"),
                    api_url=f"http://127.0.0.1:{server.server_address[1]}",
                    reservation_per_request_usd=0.001,
                    run_cost_limit_usd=1.0,
                ),
                opt_in=True,
            )
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_provenance_locally_connected_socket_is_local_only():
    """Case (c): a locally connected socket stays a local observed connection.

    A real client socket connects to the compatible local server, sends one
    INFO request at the TCP level and reads the schema-complete reply; the
    connection is loopback and the lane cannot mint ``live_vendor``.
    """
    plan = seam_support.subset_plan(1)
    server, thread = _local_server(plan)
    try:
        address = (server.server_address[0], server.server_address[1])
        with socket.create_connection(address, timeout=5) as client:
            request = f"GET /info HTTP/1.0\r\nHost: 127.0.0.1:{address[1]}\r\n\r\n"
            client.sendall(request.encode("ascii"))
            client.settimeout(5)
            client.shutdown(socket.SHUT_WR)  # Signal end of request side.
            received = b""
            while True:
                chunk = client.recv(65_536)
                if not chunk:
                    break
                received += chunk
        text = received.decode("utf-8", errors="replace")
        assert text.startswith("HTTP/1.") and " 200" in text.split("\r\n", 1)[0]
        assert '"version"' in text
        # Only a loopback address was contacted, and provenance is unchanged.
        assert address[0] in {"127.0.0.1", "::1"}
        transport = _local_transport(address[1])
        assert transport.evidence_class is EvidenceClass.MOCKED_PROVIDER_CONTRACT
        # Successful socket-level communication against this local origin
        # also cannot drive the live decision point to mint live_vendor.
        from reliability_safety_observability.langsmith_adapter import _execute_live
        result = _execute_live(
            transport, plan, _stub_benchmark(plan.run_id), "0" * 64, None,
            deadline=None,
        )
        assert result.outcome == "confirmed"  # Fully matching readback.
        assert result.evidence_class is EvidenceClass.MOCKED_PROVIDER_CONTRACT
        assert result.evidence_class is not EvidenceClass.LIVE_VENDOR
        assert transport.close() is True
        with pytest.raises(ConfigurationError):
            run_live_langsmith_verification(
                _runtime(),
                LangSmithSettings(
                    enabled=True,
                    api_key=SecretStr("lsv2_pt_local_provenance_key"),
                    api_url=f"http://127.0.0.1:{address[1]}",
                    reservation_per_request_usd=0.001,
                    run_cost_limit_usd=1.0,
                ),
                opt_in=True,
            )
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()



# ---------------------------------------------------------------------------
# Blocker: unqualified live_vendor mint at the live decision point.
# ---------------------------------------------------------------------------


def _stub_benchmark(run_id: str):
    import types

    return types.SimpleNamespace(
        run=types.SimpleNamespace(result=types.SimpleNamespace(run_id=run_id))
    )


def test_local_matching_server_cannot_mint_live_vendor():
    """Attack: local schema-complete HTTP server, submit+readback matches.

    ``_execute_live`` itself — the live decision point — drives the full
    successful chain against the local server and MUST cap the mint at the
    mocked/provider contract regardless of full matching counts.
    """
    from reliability_safety_observability.langsmith_adapter import _execute_live

    plan = seam_support.subset_plan(1)
    server, thread = _local_server(plan)
    try:
        transport = _local_transport(server.server_address[1])
        result = _execute_live(
            transport, plan, _stub_benchmark(plan.run_id), "0" * 64, None,
            deadline=None,
        )
        assert result.outcome == "confirmed"  # Fully matching readback.
        assert result.confirmed_examples == len(plan.examples)
        assert result.confirmed_feedback == len(plan.feedback)
        assert result.evidence_class is EvidenceClass.MOCKED_PROVIDER_CONTRACT
        assert result.evidence_class is not EvidenceClass.LIVE_VENDOR
        # Closing still lands cleanly; the mint cap is unchanged afterwards.
        from reliability_safety_observability.langsmith_adapter import _close_state
        close_label = asyncio.run(_close_state(transport, 30))
        assert close_label == "closed"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_in_process_seam_cannot_mint_live_vendor():
    """Attack: the in-process seam drives a fully matching execution."""
    from reliability_safety_observability.langsmith_adapter import _execute_live

    plan = seam_support.subset_plan(1)
    seam = seam_support.SeamDouble(plan)
    transport = seam_support.gated_transport(seam)
    result = _execute_live(
        transport, plan, _stub_benchmark(plan.run_id), "0" * 64, None,
        deadline=None,
    )
    assert result.outcome == "confirmed"
    assert result.evidence_class is EvidenceClass.MOCKED_PROVIDER_CONTRACT
    # Even with attacker-set qualification flags, the seam cannot upgrade.
    transport._live_qualified = True  # Attacker-supplied authority label.
    assert __import__(
        "reliability_safety_observability.langsmith_adapter",
        fromlist=["_qualified_live_provenance"],
    )._qualified_live_provenance(transport) is False
    assert transport.close() is True


def test_fake_transport_perfect_responses_cannot_mint_live_vendor(monkeypatch):
    """Attack: a fake transport returns perfect successful responses."""
    from reliability_safety_observability.langsmith_adapter import (
        FakeLangSmithSdkTransport,
        _execute_live,
        _qualified_live_provenance,
    )

    plan = seam_support.subset_plan(1)
    fake = FakeLangSmithSdkTransport()
    fake._settings = seam_support.settings_for()
    fake.live_qualified = True
    fake._live_qualified = True  # Caller-supplied upgrade claim.
    fake.evidence_class = EvidenceClass.LIVE_VENDOR  # Provider-style claim.
    fake.accounting = lambda: {"requests_sent": 0}
    result = _execute_live(
        fake, plan, _stub_benchmark(plan.run_id), "0" * 64, None, deadline=None
    )
    assert result.outcome == "confirmed"
    assert result.evidence_class is EvidenceClass.MOCKED_PROVIDER_CONTRACT
    assert result.evidence_class is not EvidenceClass.LIVE_VENDOR
    assert _qualified_live_provenance(fake) is False
    del monkeypatch


def test_caller_and_provider_claims_cannot_override_the_cap():
    """Attack: subclass/label/claim injection cannot upgrade the mint.

    Exact-type qualification means subclasses, injected flags, evidence
    labels, successful readbacks and matching identities can never mint
    ``live_vendor``; a qualified real transport requires its own owned
    construction path AND no seam.
    """
    from reliability_safety_observability.langsmith_adapter import (
        _execute_live,
        _qualified_live_provenance,
    )

    plan = seam_support.subset_plan(1)

    class Impostor(seam_support.LangSmithSdkTransport.__mro__[1]):  # LangSmithTransport
        _live_qualified = True

        def submit_plan(self, plan: object) -> None:
            self.submitted = getattr(self, "submitted", [])
            self.submitted.append(plan)

        def read_back(self, plan: object) -> dict[str, int]:
            return {"examples": len(plan.examples), "feedback": len(plan.feedback)}

        def close(self) -> bool:
            return True

    impostor = Impostor()
    impostor._settings = seam_support.settings_for()
    impostor.accounting = lambda: {"requests_sent": 0}
    result = _execute_live(
        impostor, plan, _stub_benchmark(plan.run_id), "0" * 64, None, deadline=None
    )
    assert result.outcome == "confirmed"
    assert result.evidence_class is EvidenceClass.MOCKED_PROVIDER_CONTRACT
    assert _qualified_live_provenance(impostor) is False

    # A real transport over the reserved seam origin cannot qualify either,
    # even if an attacker manually flips its internal flag.
    seam_transport = seam_support.gated_transport(seam_support.SeamDouble(plan))
    seam_transport._live_qualified = True
    assert _qualified_live_provenance(seam_transport) is False
    # Loopback HTTP real transport is not a remote HTTPS endpoint either.
    loopback = _local_transport(19876)
    loopback._live_qualified = True
    assert _qualified_live_provenance(loopback) is False
    loopback.close()


def test_structural_mint_authority_is_owned_only():
    """Structural proof (CI-safe): only the owned chain can mint live_vendor.

    Static source-level assertions on the deployed application code: the
    execution supervisor contains no live_vendor mint at all; the owned
    wrapper's mint exists exactly once and only behind the provenance
    qualification guard; the qualification flag is assigned only inside the
    owned transport's HTTPS qualification path; and qualification is
    anchored on exact type, no-seam and remote-HTTPS checks.
    """
    import inspect

    from reliability_safety_observability.langsmith_adapter import (
        LangSmithSdkTransport,
        _execute_live,
        _qualified_live_provenance,
        run_live_langsmith_verification,
    )

    supervisor_source = inspect.getsource(_execute_live)
    assert "EvidenceClass.LIVE_VENDOR" not in supervisor_source
    assert "EvidenceClass.MOCKED_PROVIDER_CONTRACT" in supervisor_source

    wrapper_source = inspect.getsource(run_live_langsmith_verification)
    assert wrapper_source.count("EvidenceClass.LIVE_VENDOR") == 1
    assert "_qualified_live_provenance" in wrapper_source

    initialize_source = inspect.getsource(LangSmithSdkTransport._initialize)
    assert initialize_source.count("_live_qualified") == 2  # default + qualify.
    assert "qualify_https_endpoint" in initialize_source

    qualification_source = inspect.getsource(_qualified_live_provenance)
    assert "type(transport) is not LangSmithSdkTransport" in qualification_source
    assert "_seam" in qualification_source
    assert "is_remote_https_endpoint" in qualification_source
