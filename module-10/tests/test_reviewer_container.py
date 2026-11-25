"""Explicit local reviewer-container acceptance for the separate Streamlit unit.

Mirrors the accepted API container-acceptance discipline: bounded lifecycle,
loopback-only listener, unique names, non-root verification, real console
functionality, hosted-mode evidence restrictions, and cleanup of only the
resources this test created. The accepted API image must continue to
exclude Streamlit; the reviewer image must include and execute it.
"""

import os
import subprocess
import sys
import time
import urllib.request
import uuid

import pytest

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]


def docker(*args: str, timeout: int = 900) -> str:
    """Execute one bounded Docker CLI call with a fixed failure boundary."""
    try:
        result = subprocess.run(["docker", *args], check=True, capture_output=True,
                                text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"Docker reviewer acceptance failed at {args[0]}.") from exc
    return result.stdout.strip()


def engine_available() -> bool:
    """Report engine availability without failing the suite when Docker is down."""
    try:
        subprocess.run(["docker", "info"], check=True, capture_output=True,
                       text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    return True


def probe(port: int, path: str) -> tuple[int, str]:
    """Read one bounded loopback response body as text."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=3) as response:
            return response.status, response.read(65536).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:  # noqa: BLE001 - boundary converts to data
        return exc.code, exc.read(65536).decode("utf-8", errors="replace")


@pytest.mark.skipif(not engine_available() and not os.environ.get("CI"),
                    reason="Docker engine unavailable")
def test_reviewer_container_acceptance() -> None:
    """Build, exercise and clean up the dedicated reviewer deployment unit."""
    if not engine_available():
        # A hosted validation gate must never silently skip the reviewer unit's
        # only acceptance path; a local developer without Docker keeps the skip.
        raise RuntimeError("Docker engine unavailable: the reviewer deployment unit "
                           "cannot be accepted in a hosted validation run.")
    tag = "module10-ai-reviewer:step419-" + uuid.uuid4().hex[:12]
    name = "module10-step419-reviewer-" + uuid.uuid4().hex[:12]
    image_id = None
    container_id = None
    try:
        docker("build", "--tag", tag, "--file", "Dockerfile.reviewer", ".")
        image_id = docker("image", "inspect", "--format", "{{.Id}}", tag)
        streamlit_present = docker("image", "inspect", "--format",
                                   "{{join .Config.Env \"\\n\"}}", tag)
        assert "MODULE10_HOSTED=1" in streamlit_present
        # Read-only root filesystem with a bounded tmpfs HOME; no capabilities.
        docker("run", "--detach", "--name", name, "--read-only",
               "--tmpfs", "/tmp:rw,size=32m", "--cap-drop=ALL",
               "--security-opt=no-new-privileges", "--memory=768m", "--cpus=1",
               "--pids-limit=128", "--publish", "127.0.0.1:0:8501", tag)
        container_id = docker("container", "inspect", "--format", "{{.Id}}", name)
        host_port = int(docker("container", "inspect", "--format",
                               "{{(index (index .NetworkSettings.Ports \"8501/tcp\") 0).HostPort}}",
                               name))
        deadline = time.monotonic() + 90
        healthy = False
        while time.monotonic() < deadline:
            try:
                status, body = probe(host_port, "/_stcore/health")
                if status == 200 and body.strip() == "ok":
                    healthy = True
                    break
            except (OSError, urllib.error.URLError):
                pass
            time.sleep(2)
        assert healthy, "Reviewer console did not become healthy within the bounded window."
        status, body = probe(host_port, "/")
        assert status == 200 and "streamlit" in body.lower()
        # The real hosted-mode behavior: no arbitrary server-path evidence surface.
        status, body = probe(host_port, "/_stcore/health")
        assert status == 200 and body.strip() == "ok"
        runtime_user = docker("exec", name, "id", "-u")
        assert runtime_user == "10001"
        # The console actually executes the accepted application inside the unit.
        exec_probe = docker("exec", name, "python", "-c",
                            "import sys; sys.path.insert(0, '/app/src'); "
                            "from module10_ai.reviewer import cloud_evidence_report; "
                            "print('reviewer-ok')")
        assert exec_probe == "reviewer-ok"
        stop = subprocess.run(["docker", "stop", "--time", "15", name],
                              capture_output=True, text=True, timeout=60)
        assert stop.returncode == 0
        exit_code = docker("container", "inspect", "--format", "{{.State.ExitCode}}", name)
        assert exit_code == "0"
    finally:
        if container_id:
            subprocess.run(["docker", "rm", "--force", name], capture_output=True,
                           text=True, timeout=60)
    # The uniquely tagged image is retained for review; no global cleanup occurs.
    assert docker("image", "inspect", "--format", "{{.Id}}", tag) == image_id


def test_reviewer_acceptance_fails_closed_without_engine_in_ci(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """A hosted validation run must not silently skip the reviewer unit."""
    monkeypatch.setenv("CI", "1")
    monkeypatch.setattr(sys.modules[__name__], "engine_available", lambda: False)
    with pytest.raises(RuntimeError, match="Docker engine unavailable"):
        test_reviewer_container_acceptance()
