"""Render data-only ARM contracts or explicitly collect bounded read-only cloud evidence."""

import argparse
import asyncio
import getpass
import json
import os
import re
import shutil
import subprocess
import time
import uuid
import warnings
from pathlib import Path

import httpx

from module10_ai.azure_contract import REGION, AzureConfig, arm_template
from module10_ai.azure_verification import (
    VerificationError,
    cloud_evidence,
    identifier,
    require,
    validate_state,
)
from module10_ai.http_schemas import ErrorOutput, InferenceOutput
from module10_ai.telemetry import correlation_id

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = ROOT.parent.parent / "EVIDENCE"
READ_COMMANDS = frozenset({
    ("group", "show"), ("resource", "list"), ("resource", "show"),
    ("acr", "config", "authentication-as-arm", "show"), ("acr", "manifest", "show-metadata"),
    ("role", "assignment", "list"), ("containerapp", "revision", "list"),
    ("monitor", "log-analytics", "query"),
})


def destination(path: Path) -> Path:
    """Require a new external evidence file in the repository's parent EVIDENCE folder."""
    resolved = path.resolve()
    if not resolved.is_relative_to(EVIDENCE_ROOT.resolve()) or resolved.exists():
        raise ValueError("Use a new file under parent TECHADEMY/EVIDENCE.")
    if not resolved.parent.is_dir():
        raise ValueError("Create the external evidence parent directory before this command.")
    return resolved


def az_read(command: tuple[str, ...], *args: str, subscription: str) -> object:
    """Run only fixed read-only CLI operations, with timeout and minimized failures.

    Args:
        command: One exact allowlisted read-only Azure command.
        args: Trusted collector arguments; never interpreted by a shell.
        subscription: Independent expected subscription; passed on every CLI read.

    Returns:
        Parsed observations in memory, never raw printed evidence.

    Raises:
        VerificationError: CLI, timeout, response size or JSON parsing fails.
    """
    if command not in READ_COMMANDS:
        raise VerificationError("Azure mutation/unknown CLI operation is forbidden.")
    subscription = identifier(subscription)
    require("--subscription" not in args and "-s" not in args,
            "Subscription override is forbidden.")
    require(not ("--scope" in args and "--all" in args),
            "Scope and all cannot be combined in an Azure read.")
    executable = shutil.which("az")
    if not executable:
        raise VerificationError("Azure CLI is unavailable; use the operator's authenticated shell.")
    prefix = [executable]
    if Path(executable).suffix.lower() in {".cmd", ".bat"}:
        # The official MSI wrapper invokes this interpreter. Avoid cmd.exe parsing entirely.
        runtime = Path(executable).resolve().parent.parent / "python.exe"
        if not runtime.is_file():
            raise VerificationError("Require Azure MSI Python runtime; batch execution forbidden.")
        prefix = [str(runtime), "-IBm", "azure.cli"]
    environment = dict(os.environ)
    environment.update(AZURE_CORE_COLLECT_TELEMETRY="no", AZURE_EXTENSION_USE_DYNAMIC_INSTALL="no",
                       AZURE_LOGGING_ENABLE_LOG_FILE="false")
    try:
        result = subprocess.run(
            [*prefix, *command, *args, "--subscription", subscription,
             "--only-show-errors", "--output", "json"],
            capture_output=True, text=True, check=False, timeout=90, env=environment,
        )
        if result.returncode or len(result.stdout.encode()) > 1_048_576:
            raise VerificationError(
                "Azure read failed; inspect access, extensions and resource state.")
        return json.loads(result.stdout)
    except (OSError, subprocess.TimeoutExpired, UnicodeError, json.JSONDecodeError) as exc:
        raise VerificationError("Azure read/JSON failed; no cloud acceptance recorded.") from exc


def collect(config: AzureConfig, digest: str, expected_subscription: str) -> dict:
    """Collect fresh resource and revision observations; never accept snapshot files."""
    n = config.names
    subscription = identifier(expected_subscription)

    def read(command: tuple[str, ...], *args: str) -> object:
        return az_read(command, *args, subscription=subscription)

    state = {"group": read(("group", "show"), "--name", n["group"]),
             "inventory": read(("resource", "list"), "--resource-group", n["group"])}
    kinds = {"registry": ("Microsoft.ContainerRegistry/registries", "2023-07-01"),
             "workspace": ("Microsoft.OperationalInsights/workspaces", "2023-09-01"),
             "environment": ("Microsoft.App/managedEnvironments", "2025-01-01"),
             "app": ("Microsoft.App/containerApps", "2025-01-01"),
             "identity": ("Microsoft.ManagedIdentity/userAssignedIdentities", "2023-01-31")}
    for key, (kind, version) in kinds.items():
        state[key] = read(("resource", "show"), "--resource-group", n["group"],
                             "--name", n[key], "--resource-type", kind, "--api-version", version)
    state["arm_auth"] = read(("acr", "config", "authentication-as-arm", "show"),
                                "--registry", n["registry"])
    state["manifest"] = read(("acr", "manifest", "show-metadata"), "--registry", n["registry"],
                                "--name", "module10-ai@" + digest)
    try:
        principal = identifier(state["identity"]["properties"]["principalId"])
        registry_id = state["registry"]["id"]
    except (KeyError, TypeError) as exc:
        raise VerificationError("Missing registry/identity observations.") from exc
    expected_registry = (f"/subscriptions/{subscription}/resourceGroups/{n['group']}/providers/"
                         f"Microsoft.ContainerRegistry/registries/{n['registry']}")
    require(type(registry_id) is str and registry_id.lower() == expected_registry.lower(),
            "Registry observation is outside the expected subscription/resource group.")
    role_args = ("--assignee-object-id", principal, "--include-groups",
                 "--fill-principal-name", "false",
                 "--fill-role-definition-name", "false")
    state["roles"] = read(("role", "assignment", "list"), *role_args, "--all")
    state["inherited_roles"] = read(("role", "assignment", "list"), *role_args,
                                    "--scope", expected_registry, "--include-inherited")
    state["revisions"] = read(("containerapp", "revision", "list"),
                                 "--resource-group", n["group"], "--name", n["app"])
    return state


def https_checks(fqdn: str, request_id: str) -> None:
    """Send exactly five bounded acceptance requests with TLS, no redirects or proxy secrets."""
    asyncio.run(_https_checks(fqdn, request_id))


async def _https_checks(fqdn: str, request_id: str) -> None:
    """Enforce a wall-clock deadline across headers and the entire response stream."""
    try:
        async with httpx.AsyncClient(
            base_url="https://" + fqdn, timeout=30, follow_redirects=False,
            trust_env=False, headers={"X-Request-ID": request_id}
        ) as client:
            async def call(path: str, payload: bytes | None = None) -> tuple[int, dict]:
                method = "GET" if payload is None else "POST"
                async with asyncio.timeout(30), client.stream(
                    method, path, content=payload, headers={"Content-Type": "application/json"}
                ) as response:
                    content = bytearray()
                    async for chunk in response.aiter_bytes(chunk_size=4096):
                        content.extend(chunk)
                        require(len(content) <= 65536, "HTTP response exceeded acceptance bound.")
                    return response.status_code, json.loads(content)

            require(await call("/health/live") == (
                        200, {"status": "alive", "mode": "deterministic"}),
                    "Cloud liveness failed; no acceptance recorded.")
            require(await call("/health/ready") == (
                        200, {"status": "ready", "mode": "deterministic"}),
                    "Cloud readiness failed; allow bounded cold-start recovery then rerun.")
            for _ in range(2):
                status, body = await call("/api/v1/inference",
                                          b'{"text":"Beta alpha beta gamma","keyword_limit":3}')
                result = InferenceOutput.model_validate(body)
                require(status == 200 and result.word_count == 4
                        and result.keywords == ["beta", "alpha", "gamma"]
                        and result.evidence == "deterministic" and result.request_id == request_id,
                        "Cloud deterministic inference differed.")
            status, body = await call("/api/v1/inference", b'{"text":"","keyword_limit":true}')
            result = ErrorOutput.model_validate(body)
            require(status == 422 and result.code == "invalid_request"
                    and result.message == "Request does not satisfy the input contract."
                    and result.request_id == request_id,
                    "Cloud bounded validation rejection differed.")
    except (httpx.HTTPError, ValueError, TimeoutError) as exc:
        if isinstance(exc, VerificationError):
            raise
        raise VerificationError(
            "HTTPS/schema acceptance failed; no cloud success recorded.") from exc


def monitor_query(app: str, revision: str, request_id: str) -> str:
    """Generate fixed KQL with validated scope and only aggregate results, never raw logs."""
    require(re.fullmatch(r"m10-api-[a-z][a-z0-9]{5,11}", app) is not None
            and re.fullmatch(re.escape(app) + r"--[a-z0-9-]{1,64}", revision) is not None
            and re.fullmatch(r"[a-f0-9]{32}", request_id) is not None,
            "Unsafe telemetry query scope rejected.")
    return (
        "ContainerAppConsoleLogs_CL | where TimeGenerated > ago(10m) "
        f"| where ContainerAppName_s == '{app}' and RevisionName_s == '{revision}' "
        "| extend record=parse_json(Log_s) "
        f"| where tostring(record.correlation_id) == '{correlation_id(request_id)}' "
        "and toint(record.schema_version) == 1 "
        "| summarize successes=countif(record.event == 'http.completed' "
        "and record.status == 'success'), failures=countif(record.event == 'http.completed' "
        "and record.status == 'failure') | project successes, failures"
    )


def verify(config: AzureConfig, digest: str, expected_subscription: str) -> dict:
    """Verify configuration, five HTTP calls and at most six telemetry queries before success.

    Args:
        config: Human-reviewed contract.
        digest: Human-reviewed manifest identity bound separately to the tested image.
        expected_subscription: Private independently selected subscription UUID.

    Returns:
        Minimized genuine cloud observations, not deployment or release authority.

    Raises:
        VerificationError: Any required gate or final drift check fails.
    """
    subscription = identifier(expected_subscription)
    state = collect(config, digest, subscription)
    fqdn = validate_state(config, digest, state, subscription)
    revision = state["app"]["properties"]["latestRevisionName"]
    request_id = uuid.uuid4().hex
    https_checks(fqdn, request_id)
    query = monitor_query(config.names["app"], revision, request_id)
    workspace = state["workspace"]["properties"]["customerId"]
    for attempt in range(6):
        rows = az_read(("monitor", "log-analytics", "query"), "--workspace", workspace,
                       "--analytics-query", query, "--timespan", "PT10M",
                       subscription=subscription)
        if (isinstance(rows, list) and len(rows) == 1 and isinstance(rows[0], dict)
                and type(rows[0].get("successes")) is int and rows[0]["successes"] >= 2
                and type(rows[0].get("failures")) is int and rows[0]["failures"] >= 1):
            break
        if attempt == 5:
            raise VerificationError("Azure Monitor receipt missing; wait for ingestion then rerun.")
        time.sleep(20)
    final = collect(config, digest, subscription)
    require(validate_state(config, digest, final, subscription) == fqdn
            and final["app"]["properties"]["latestRevisionName"] == revision,
            "Cloud configuration/revision changed during acceptance; rerun after stabilization.")
    return cloud_evidence(config, digest, revision)


def private_subscription() -> str:
    """Read an independent subscription without echo or insecure stdin fallback."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            return identifier(getpass.getpass("Expected subscription UUID (private): "))
    except (getpass.GetPassWarning, EOFError) as exc:
        raise VerificationError(
            "Verification requires a private interactive subscription prompt.") from exc


def main() -> None:
    """Keep rendering offline; require an explicit operator switch for bounded cloud traffic."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suffix", required=True)
    parser.add_argument("--reviewer-cidr", required=True)
    parser.add_argument("--digest")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--render", choices=("foundation", "app"))
    mode.add_argument("--verify-cloud", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        config = AzureConfig(args.suffix, args.reviewer_cidr)
        output = destination(args.output)
        if args.verify_cloud or args.render == "app":
            if not args.digest:
                raise ValueError("App/verification requires the reviewed manifest digest.")
            config.image(args.digest)
        elif args.digest:
            raise ValueError("Foundation rendering does not accept an image digest.")
        data = (verify(config, args.digest, private_subscription()) if args.verify_cloud
                else arm_template(config, args.digest))
        encoded = json.dumps(data, indent=2) + "\n"
        require(len(encoded.encode()) <= 32768, "Generated output exceeds metadata bound.")
        with output.open("x", encoding="utf-8") as stream:
            stream.write(encoded)
        print("Cloud verification passed." if args.verify_cloud else
              f"Offline ARM contract rendered for {REGION}; no deployment authorized.")
    except (ValueError, OSError) as exc:
        # Never print arbitrary OS/HTTP/Azure diagnostics or account identifiers.
        parser.exit(1, "Module 10 deployment command failed; check inputs/access/state. "
                    "No cloud acceptance was recorded.\n" if not isinstance(exc, VerificationError)
                    else str(exc) + "\n")


if __name__ == "__main__":
    main()
