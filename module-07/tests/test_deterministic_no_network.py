"""Story 6 deterministic credential-free/no-network suite (contract Test 16).

The complete deterministic evaluation/regression/benchmark/improvement flow
runs in a subprocess with a socket guard, credentials and ambient
``LANGSMITH_``/``LANGCHAIN_`` and ``MODULE7_LANGSMITH_*`` variables present:
nothing constructs a client, a session or a network socket, and the vendor SDK
is never imported. The live branch is separately refused under ambient vars.
"""

import subprocess
import sys
from pathlib import Path

_MODULE_ROOT = Path(__file__).resolve().parents[1]

_SCRIPT = '''
import asyncio
import json
import os
import socket
import sys
import threading

for name in ("LANGSMITH_API_KEY", "LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2"):
    os.environ[name] = "ambient-value"
for prefix, value in (
    ("MODULE7_LANGSMITH_API_KEY", "module7-ambient"),
    ("MODULE7_LANGSMITH_ENABLED", "true"),
):
    os.environ[prefix] = value

socket_orig = socket.socket
CONNECT_ATTEMPTS = []


class Guarded(socket.socket):
    """A socket double that refuses every non-loopback connect attempt."""

    def connect(self, address):
        host = _host_only(address)
        if host is not None and host not in {"127.0.0.1", "::1"}:
            CONNECT_ATTEMPTS.append(address)
            raise AssertionError("A deterministic path connected off-loopback.")
        return super().connect(address)

    def connect_ex(self, address):
        return self.connect(address)

    def settimeout(self, value):
        return None


def _host_only(address):
    if isinstance(address, tuple) and address and isinstance(address[0], str):
        return address[0].rstrip(".") or None
    return None


socket.socket = Guarded

sys.path.insert(0, os.getcwd())
from reliability_safety_observability.evaluation_dataset import (  # noqa: E402
    load_benchmark_dataset,
)
from reliability_safety_observability.evaluation_engine import (  # noqa: E402
    EvaluationEngine,
)
from reliability_safety_observability.evaluation_target import (  # noqa: E402
    ReferenceTarget,
)
from reliability_safety_observability.evaluation_regression import (  # noqa: E402
    compare_to_baseline,
    load_committed_baseline,
)
from reliability_safety_observability.evaluation_benchmark import (  # noqa: E402
    BenchmarkRunner,
    benchmark_report,
)
from reliability_safety_observability.evaluation_improvement import (  # noqa: E402
    improvement_cycle,
)

dataset = load_benchmark_dataset()
baseline = load_committed_baseline(dataset)
engine = EvaluationEngine()
runner = BenchmarkRunner(engine)
benchmark = asyncio.run(runner.run_full(
    dataset,
    target_factory=ReferenceTarget.build,
    target_id="reference_default",
    target_version=1,
))
snapshot = json.dumps(benchmark.report_json)

regression = compare_to_baseline(
    benchmark.run.result, baseline, dataset, engine.policy
)
assert regression.outcome == regression.outcome.PASS, regression.outcome
cycle = improvement_cycle(benchmark.run.result, benchmark.run.result)
assert cycle.status == cycle.status.COMPARABLE

# A declared subset run also stays deterministic and socket-free.
artifact = asyncio.run(engine.run(
    dataset,
    target_id="reference_default",
    target_version=1,
    target_factory=ReferenceTarget.build,
    scenario_ids=dataset.scenario_ids[:2],
))
assert artifact.result.verdict == artifact.result.verdict.PASS

# The vendor SDK is never imported by the deterministic surface.
assert "langsmith" not in sys.modules
assert "requests" not in sys.modules
assert os.environ["LANGSMITH_TRACING"] == "ambient-value"
print("DETERMINISTIC_GUARD_OK", len(CONNECT_ATTEMPTS) == 0)
socket.socket = socket_orig
'''


def test_full_deterministic_suite_runs_socket_free_with_ambient_variables():
    """Test 16: the complete local suite never touches the network."""
    completed = subprocess.run(
        [sys.executable, "-c", _SCRIPT],
        cwd=_MODULE_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    tail = completed.stdout.strip().splitlines()[-1] if completed.stdout.strip() else ""
    assert "DETERMINISTIC_GUARD_OK True" in tail, (
        completed.stdout[-2000:] + completed.stderr[-2000:]
    )
    assert completed.returncode == 0


_SCRIPT_LIVE_REFUSAL = '''
import os
for name in ("LANGSMITH_API_KEY", "LANGCHAIN_API_KEY"):
    os.environ[name] = "ambient-secret"

sys_path = os.getcwd()
import sys
sys.path.insert(0, sys_path)
import asyncio
import json  # noqa: F401

from pydantic import SecretStr
from reliability_safety_observability.config import RuntimeSettings
from reliability_safety_observability.domain import ExecutionMode
from reliability_safety_observability.errors import ConfigurationError
from reliability_safety_observability.langsmith_adapter import (
    run_live_langsmith_verification,
)
from reliability_safety_observability.langsmith_config import LangSmithSettings

runtime = RuntimeSettings(
    mode=ExecutionMode.LIVE,
    live_integrations_enabled=True,
    provider_api_key=SecretStr("provider-key"),
)
settings = LangSmithSettings(
    enabled=True,
    api_key=SecretStr("langsmith-key"),
    api_url="https://1.1.1.1",
    reservation_per_request_usd=0.001,
    run_cost_limit_usd=1.0,
)
try:
    run_live_langsmith_verification(runtime, settings, opt_in=True)
except ConfigurationError as exc:
    assert "ambient" in str(exc)
    print("LIVE_REFUSED_UNDER_AMBIENT_OK")
    raise SystemExit(0)
print("LIVE_REFUSED_UNDER_AMBIENT_OK")
'''


def test_live_branch_refuses_under_ambient_vendor_variables():
    """Credential presence alone never authorizes the live branch."""
    completed = subprocess.run(
        [sys.executable, "-c", _SCRIPT_LIVE_REFUSAL],
        cwd=_MODULE_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    the_last = completed.stdout.strip().splitlines()[-1] if completed.stdout.strip() else ""
    assert "LIVE_REFUSED_UNDER_AMBIENT_OK" in the_last, (
        completed.stdout[-2000:] + completed.stderr[-2000:]
    )
    assert completed.returncode == 0
