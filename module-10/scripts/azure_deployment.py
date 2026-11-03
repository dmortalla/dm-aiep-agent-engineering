"""Render data-only ARM contracts or explicitly collect bounded read-only cloud evidence."""

import argparse
import asyncio
import getpass
import json
import os
import re
import shutil
import subprocess
import sys
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
READ_COMMANDS = frozenset({
    ("group", "show"), ("resource", "list"), ("resource", "show"),
    ("acr", "config", "authentication-as-arm", "show"), ("acr", "manifest", "show-metadata"),
    ("role", "assignment", "list"), ("containerapp", "revision", "list"),
    ("monitor", "log-analytics", "query"),
})
READ_LABELS = ("group-observation", "resource-inventory", "registry-resource",
               "workspace-resource", "environment-resource", "app-resource",
               "identity-resource", "acr-arm-auth", "acr-manifest-metadata",
               "role-assignments-all", "role-assignments-inherited",
               "containerapp-revisions", "monitor-log-analytics")
READ_PHASES = ("", "initial-collection", "monitor-receipt", "final-drift-check")
HTTPS_OPERATIONS = ("cloud-liveness", "cloud-readiness", "deterministic-inference-1",
                    "deterministic-inference-2", "bounded-validation-rejection")


def _https_identity(label: str) -> None:
    """Validate the finite HTTPS acceptance identity before any network activity."""
    require(label in HTTPS_OPERATIONS, "HTTPS label is not an approved acceptance identity.")


def _git_lines(cwd: Path, *args: str) -> list[str]:
    """Run a bounded read-only Git query with environment overrides stripped."""
    environment = {key: value for key, value in os.environ.items()
                   if not key.upper().startswith("GIT_")}
    result = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True,
                            text=True, check=True, timeout=5, env=environment)
    if len(result.stdout.encode()) > 8192:
        raise ValueError("Git reported an oversized response.")
    return result.stdout.splitlines()


def _authenticated_worktree(repository: Path, common: Path) -> None:
    """Authenticate a linked-worktree checkout against Git's own registration files.

    Args:
        repository: The running linked-worktree checkout with a ``.git`` pointer file.
        common: Git's reported common directory; must own the worktree registration.

    Raises:
        ValueError: The pointer, registration reciprocity or commondir binding is
            not exactly the relationship Git creates between a real checkout and
            its owning repository.
    """
    pointer = (repository / ".git").read_text(encoding="utf-8").strip()
    if not pointer.startswith("gitdir: "):
        raise ValueError("Checkout lacks an authoritative Git worktree pointer.")
    gitdir = Path(pointer[len("gitdir: "):])
    if not gitdir.is_absolute():
        gitdir = repository / gitdir
    gitdir = gitdir.resolve(strict=True)
    if gitdir.parent.name != "worktrees" \
            or os.path.normcase(str(gitdir.parent.parent)) != os.path.normcase(str(common)):
        raise ValueError("Worktree metadata is not registered inside the common directory.")
    common_binding = gitdir / "commondir"
    if not common_binding.is_file() \
            or os.path.normcase(str((gitdir / common_binding.read_text(encoding="utf-8").strip())
                                    .resolve(strict=True))) != os.path.normcase(str(common)):
        raise ValueError("Worktree common-directory binding differs from common metadata.")
    reciprocal = gitdir / "gitdir"
    if not reciprocal.is_file() \
            or os.path.normcase(str(Path(reciprocal.read_text(encoding="utf-8").strip())
                                    .resolve(strict=True))) \
            != os.path.normcase(str((repository / ".git").resolve())):
        raise ValueError("Worktree registration does not point back to this checkout.")


def trusted_evidence(checkout: Path, module: Path) -> Path:
    """Authenticate the checkout/metadata/common/primary relationship and approve EVIDENCE.

    Args:
        checkout: The running repository or linked-worktree checkout root.
        module: The executing module file that the authenticated repository must track.

    Returns:
        The canonical external evidence directory sibling to the authenticated
        primary checkout's parent.

    Raises:
        ValueError: Git metadata is redirected, tampered, foreign to the running
            module's repository or otherwise ambiguous. The relationship must
            agree from the running checkout and from the presumed primary
            checkout, and the running module must be tracked there.
    """
    message = "Cannot establish the trusted project evidence boundary; inspect Git checkout setup."
    try:
        repository = checkout.resolve()
        lines = _git_lines(repository, "rev-parse", "--path-format=absolute",
                           "--show-toplevel", "--git-common-dir")
        if len(lines) != 2 or Path(lines[0]).resolve(strict=True) != repository \
                or not Path(lines[1]).is_absolute() or Path(lines[1]).name != ".git" \
                or not Path(lines[1]).resolve(strict=True).is_dir():
            raise ValueError("Git metadata does not identify the running checkout.")
        common = Path(lines[1]).resolve(strict=True)
        if (repository / ".git").is_dir():
            if os.path.normcase(str(common)) != os.path.normcase(str((repository / ".git")
                                                                     .resolve())):
                raise ValueError("Common metadata does not belong to the primary checkout.")
        else:
            _authenticated_worktree(repository, common)
        primary = common.parent
        primary_lines = _git_lines(primary, "rev-parse", "--path-format=absolute",
                                   "--show-toplevel", "--git-common-dir")
        if len(primary_lines) != 2 \
                or Path(primary_lines[0]).resolve(strict=True) != primary \
                or os.path.normcase(str(Path(primary_lines[1]).resolve(strict=True))) \
                != os.path.normcase(str(common)):
            raise ValueError("The primary checkout does not authenticate the common directory.")
        tracked = module.relative_to(repository).as_posix()
        lines = _git_lines(primary, "ls-files", "--error-unmatch", "--", tracked)
        if len(lines) != 1 or os.path.normcase(lines[0]) != os.path.normcase(tracked):
            raise ValueError("Running module is not tracked by the authenticated repository.")
        approved = primary.parent / "EVIDENCE"
        if approved.resolve() != approved:
            raise ValueError("Evidence boundary could not be normalized.")
        return approved
    except (OSError, UnicodeError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        raise ValueError(message) from exc


def evidence_root() -> Path:
    """Derive the approved evidence sibling for the running module checkout."""
    return trusted_evidence(ROOT.parent, Path(__file__).resolve())


def destination(path: Path) -> Path:
    """Require a new file within the canonical external project evidence directory."""
    approved = evidence_root()
    try:
        resolved = path.resolve()
    except RuntimeError as exc:
        raise ValueError("Evidence destination could not be resolved safely.") from exc
    if (not resolved.is_relative_to(approved) or resolved.is_relative_to(ROOT.parent.resolve())
            or resolved.exists() or path.is_symlink()):
        raise ValueError("Use a new file under parent TECHADEMY/EVIDENCE.")
    if not resolved.parent.is_dir():
        raise ValueError("Create the external evidence parent directory before this command.")
    return resolved


GROUP_STATE_FAILURES = ("group or scope are not required when --all is used",
                        "usage error: --resource-group can't be an empty string")
GROUP_STATE_REDUNDANT = re.compile(
    r'Resource group "[^"]*" is redundant because scope is supplied')


def group_state_interference(stderr: str) -> bool:
    """Classify known operator-local CLI default/persistence contract failures.

    Args:
        stderr: Captured Azure CLI diagnostic, never echoed or written anywhere.

    Returns:
        True only for the three fixed resource-group injection failure messages.
    """
    return GROUP_STATE_REDUNDANT.search(stderr) is not None or any(
        message in stderr for message in GROUP_STATE_FAILURES)


def child_environment() -> dict[str, str]:
    """Build Azure CLI child state with application-owned default neutralization.

    The parent environment is preserved; only this child copy neutralizes the
    operator-local resource-group default (``defaults.group``) and disables the
    CLI local context for the resolved username so persisted
    ``resource_group_name`` state cannot be injected. Other CLI configuration,
    authentication and token locations stay untouched.
    """
    environment = dict(os.environ)
    environment.update(AZURE_CORE_COLLECT_TELEMETRY="no", AZURE_EXTENSION_USE_DYNAMIC_INSTALL="no",
                       AZURE_LOGGING_ENABLE_LOG_FILE="false", AZURE_DEFAULTS_GROUP="")
    try:
        context_user = getpass.getuser().upper()
    except (OSError, KeyError):
        # Preserve the CLI's own fail-safe behavior; never fabricate a username
        # variable from a failed lookup.
        context_user = ""
    if context_user:
        environment["AZURE_LOCAL_CONTEXT_" + context_user] = "off"
    return environment


def az_read(command: tuple[str, ...], *args: str, subscription: str, label: str,
            phase: str = "") -> object:
    """Run only fixed read-only CLI operations, with timeout and attributed failures.

    Args:
        command: One exact allowlisted read-only Azure command.
        args: Trusted collector arguments; never interpreted by a shell.
        subscription: Independent expected subscription; passed on every CLI read.
        label: One fixed source-controlled operation identity from ``READ_LABELS``.
        phase: Optional fixed verification phase from ``READ_PHASES``.

    Returns:
        Parsed observations in memory, never raw printed evidence.

    Raises:
        VerificationError: CLI, timeout, response size, JSON parsing or the
            known operator-local resource-group default/persistence contract
            failures. The state-interference class is sanitized and actionable;
            unrelated failures keep the generic non-echoing message and every
            diagnostic carries only the fixed operation/phase identity.
    """
    require(label in READ_LABELS, "Azure read label is not an approved operation identity.")
    require(phase in READ_PHASES, "Azure read phase is not an approved verification phase.")
    scope = f" ({label}" + (f" during {phase})" if phase else ")")
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
    environment = child_environment()
    try:
        result = subprocess.run(
            [*prefix, *command, *args, "--subscription", subscription,
             "--only-show-errors", "--output", "json"],
            capture_output=True, text=True, check=False, timeout=90, env=environment,
        )
        if result.returncode:
            if group_state_interference(result.stderr):
                raise VerificationError(
                    "Azure CLI resource-group defaults or parameter persistence interfered "
                    "with deterministic verifier reads; clear the operator-local az "
                    "defaults or persisted group state and rerun. No acceptance evidence "
                    "was recorded.")
            raise VerificationError(f"Azure read{scope} failed; inspect access, "
                                    "extensions and resource state.")
        if len(result.stdout.encode()) > 1_048_576:
            raise VerificationError(f"Azure read{scope} exceeded the response size bound; "
                                    "no acceptance recorded.")
        return json.loads(result.stdout)
    except (OSError, subprocess.TimeoutExpired, UnicodeError, json.JSONDecodeError) as exc:
        raise VerificationError(f"Azure read{scope} failed at the process/JSON stage; "
                                "no cloud acceptance recorded.") from exc


def collect(config: AzureConfig, digest: str, expected_subscription: str,
            phase: str = "initial-collection") -> dict:
    """Collect fresh resource and revision observations; never accept snapshot files."""
    require(phase in ("initial-collection", "final-drift-check"),
            "Disallowed verification phase for collection.")
    n = config.names
    subscription = identifier(expected_subscription)

    def read(label: str, command: tuple[str, ...], *args: str) -> object:
        return az_read(command, *args, subscription=subscription, label=label, phase=phase)

    state = {"group": read("group-observation", ("group", "show"), "--name", n["group"]),
             "inventory": read("resource-inventory", ("resource", "list"),
                               "--resource-group", n["group"])}
    kinds = {"registry": ("Microsoft.ContainerRegistry/registries", "2023-07-01",
                          "registry-resource"),
             "workspace": ("Microsoft.OperationalInsights/workspaces", "2023-09-01",
                           "workspace-resource"),
             "environment": ("Microsoft.App/managedEnvironments", "2025-01-01",
                             "environment-resource"),
             "app": ("Microsoft.App/containerApps", "2025-01-01", "app-resource"),
             "identity": ("Microsoft.ManagedIdentity/userAssignedIdentities", "2023-01-31",
                          "identity-resource")}
    for key, (kind, version, label) in kinds.items():
        state[key] = read(label, ("resource", "show"), "--resource-group", n["group"],
                          "--name", n[key], "--resource-type", kind, "--api-version", version)
    state["arm_auth"] = read("acr-arm-auth", ("acr", "config", "authentication-as-arm", "show"),
                             "--registry", n["registry"])
    state["manifest"] = read("acr-manifest-metadata", ("acr", "manifest", "show-metadata"),
                             "--registry", n["registry"], "--name", "module10-ai@" + digest)
    try:
        principal = identifier(state["identity"]["properties"]["principalId"])
        registry_id = state["registry"]["id"]
    except (KeyError, TypeError) as exc:
        raise VerificationError("Missing registry/identity observations.") from exc
    expected_registry = (f"/subscriptions/{subscription}/resourceGroups/{n['group']}/providers/"
                         f"Microsoft.ContainerRegistry/registries/{n['registry']}")
    require(type(registry_id) is str and registry_id.lower() == expected_registry.lower(),
            "Registry observation is outside the expected subscription/resource group.")
    # An explicit group is not contract-valid on either read: an empty argv value
    # is rejected by the CLI as a usage error, a non-empty value conflicts with
    # the --all read ("group or scope are not required when --all is used") and
    # is redundant with --scope on the scoped read. The flag stays omitted and
    # the child environment neutralizes defaults.group/local-context state so
    # no operator-local CLI value can be injected, as with the explicit
    # --subscription binding for account-default isolation.
    role_args = ("--assignee-object-id", principal, "--include-groups",
                 "--fill-principal-name", "false",
                 "--fill-role-definition-name", "false")
    state["roles"] = read("role-assignments-all", ("role", "assignment", "list"),
                          *role_args, "--all")
    state["inherited_roles"] = read("role-assignments-inherited", ("role", "assignment", "list"),
                                    *role_args, "--scope", expected_registry,
                                    "--include-inherited")
    state["revisions"] = read("containerapp-revisions", ("containerapp", "revision", "list"),
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
            async def call(label: str, path: str, payload: bytes | None = None) -> tuple:
                _https_identity(label)
                method = "GET" if payload is None else "POST"
                try:
                    async with asyncio.timeout(30), client.stream(
                        method, path, content=payload, headers={"Content-Type": "application/json"}
                    ) as response:
                        content = bytearray()
                        async for chunk in response.aiter_bytes(chunk_size=4096):
                            content.extend(chunk)
                            require(len(content) <= 65536,
                                    f"HTTP response exceeded acceptance bound for ({label}).")
                        return response.status_code, json.loads(content)
                except VerificationError:
                    raise
                except (httpx.HTTPError, TimeoutError) as exc:
                    raise VerificationError(
                        f"HTTPS acceptance ({label}) failed at the transport stage; "
                        "no cloud success recorded.") from exc
                except (ValueError, UnicodeError) as exc:
                    raise VerificationError(
                        f"HTTPS acceptance ({label}) failed at receiving/JSON parsing; "
                        "no cloud success recorded.") from exc

            def validated(label: str, model, body: object) -> object:
                try:
                    return model.model_validate(body)
                except ValueError as exc:
                    raise VerificationError(
                        f"HTTPS acceptance ({label}) failed schema validation; "
                        "no cloud success recorded.") from exc

            require(await call("cloud-liveness", "/health/live") == (
                        200, {"status": "alive", "mode": "deterministic"}),
                    "Cloud liveness failed; no acceptance recorded.")
            require(await call("cloud-readiness", "/health/ready") == (
                        200, {"status": "ready", "mode": "deterministic"}),
                    "Cloud readiness failed; allow bounded cold-start recovery then rerun.")
            for attempt in range(2):
                label = f"deterministic-inference-{attempt + 1}"
                status, body = await call(label, "/api/v1/inference",
                                          b'{"text":"Beta alpha beta gamma","keyword_limit":3}')
                result = validated(label, InferenceOutput, body)
                require(status == 200 and result.word_count == 4
                        and result.keywords == ["beta", "alpha", "gamma"]
                        and result.evidence == "deterministic" and result.request_id == request_id,
                        "Cloud deterministic inference differed.")
            status, body = await call("bounded-validation-rejection", "/api/v1/inference",
                                      b'{"text":"","keyword_limit":true}')
            result = validated("bounded-validation-rejection", ErrorOutput, body)
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
                       subscription=subscription, label="monitor-log-analytics",
                       phase="monitor-receipt")
        if (isinstance(rows, list) and len(rows) == 1 and isinstance(rows[0], dict)
                and type(rows[0].get("successes")) is int and rows[0]["successes"] >= 2
                and type(rows[0].get("failures")) is int and rows[0]["failures"] >= 1):
            break
        if attempt == 5:
            raise VerificationError("Azure Monitor receipt missing; wait for ingestion then rerun.")
        time.sleep(20)
    final = collect(config, digest, subscription, phase="final-drift-check")
    require(validate_state(config, digest, final, subscription) == fqdn
            and final["app"]["properties"]["latestRevisionName"] == revision,
            "Cloud configuration/revision changed during acceptance; rerun after stabilization.")
    return cloud_evidence(config, digest, revision)


def private_subscription(*, from_stdin: bool = False) -> str:
    """Read only the explicitly selected private operator channel; never fall back.

    Stdin requires an operator-owned redirected pipe closed after one UUID line.
    The switch selects a transport, not proof of human provenance. Never connect
    model output, files or Azure observations to this authority-bearing channel.
    """
    if from_stdin:
        try:
            require(not sys.stdin.isatty(), "Private stdin requires a redirected operator pipe.")
            # Read raw bounded bytes, bypassing text-mode newline translation so a
            # lone CR is never silently rewritten into a strippable LF and acceptance
            # cannot flip on a chunk-split CRLF or the wrapper's translation mode.
            value = sys.stdin.buffer.read(39).decode("ascii")
        except (OSError, UnicodeError) as exc:
            raise VerificationError("Private subscription pipe could not be read.") from exc
        # Accept only an exact UUID, optionally followed by one transport newline.
        if value.endswith("\r\n"):
            value = value[:-2]
        elif value.endswith("\n"):
            value = value[:-1]
        return identifier(value)
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
    parser.add_argument("--subscription-stdin", action="store_true",
                        help="Read private UUID only from an operator-owned pipe; no fallback.")
    args = parser.parse_args()
    try:
        try:
            require(not args.subscription_stdin or args.verify_cloud,
                    "Private subscription stdin is only valid with --verify-cloud.")
            config = AzureConfig(args.suffix, args.reviewer_cidr)
            output = destination(args.output)
            if args.verify_cloud or args.render == "app":
                if not args.digest:
                    raise ValueError("App/verification requires the reviewed manifest digest.")
                config.image(args.digest)
            elif args.digest:
                raise ValueError("Foundation rendering does not accept an image digest.")
        except VerificationError:
            raise
        except (ValueError, OSError) as exc:
            raise VerificationError(
                "Pre-verification input/configuration validation failed; correct the "
                "operator inputs and rerun. No cloud acceptance was recorded.") from exc
        data = (verify(config, args.digest,
                       private_subscription(from_stdin=args.subscription_stdin))
                if args.verify_cloud
                else arm_template(config, args.digest))
        encoded = json.dumps(data, indent=2) + "\n"
        require(len(encoded.encode()) <= 32768, "Generated output exceeds metadata bound.")
        try:
            with output.open("x", encoding="utf-8") as stream:
                stream.write(encoded)
        except (ValueError, OSError) as exc:
            raise VerificationError(
                "Success evidence could not be persisted; no cloud acceptance was "
                "recorded.") from exc
        print("Cloud verification passed." if args.verify_cloud else
              f"Offline ARM contract rendered for {REGION}; no deployment authorized.")
    except VerificationError as exc:
        # Keep application-controlled sanitized diagnostics; never print arbitrary
        # OS/HTTP/Azure diagnostics or account identifiers.
        parser.exit(1, str(exc) + "\n")
    except (ValueError, OSError):
        # Unexpected internal failure at an unclassified boundary: fail closed on
        # the fixed generic message; arbitrary exception text stays unprinted.
        parser.exit(1, "Module 10 deployment command failed; check inputs/access/state. "
                    "No cloud acceptance was recorded.\n")


if __name__ == "__main__":
    main()
