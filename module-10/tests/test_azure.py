"""Offline Azure contract, adversarial observations and bounded collector failure tests."""

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from module10_ai.azure_contract import (
    ACR_PULL,
    REGION,
    TAGS,
    AzureConfig,
    arm_template,
    container,
    footprint,
    ingress,
    publication,
    scale,
)
from module10_ai.azure_verification import VerificationError, subset, validate_state

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "azure_deployment", ROOT / "scripts/azure_deployment.py")
assert spec and spec.loader
deployment = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deployment)
CONFIG = AzureConfig("reviewa", "8.8.8.8/32")
DIGEST = "sha256:" + "a" * 64


def test_approved_identity_footprint() -> None:
    """The approved amendment adds only one pull identity and one registry-scoped assignment."""
    assert footprint() == {"resource_groups": 1, "registries": 1, "workspaces": 1,
                           "environments": 1, "container_apps": 1, "user_assigned_identities": 1,
                           "registry_scoped_acrpull_assignments": 1}
    resources = arm_template(CONFIG)["resources"]
    identities = [r for r in resources if r["type"] ==
                  "Microsoft.ManagedIdentity/userAssignedIdentities"]
    roles = [r for r in resources if r["type"] == "Microsoft.Authorization/roleAssignments"]
    assert len(identities) == len(roles) == 1
    assert roles[0]["scope"] == (
        f"[resourceId('Microsoft.ContainerRegistry/registries', '{CONFIG.names['registry']}')]")
    assert roles[0]["properties"]["roleDefinitionId"].endswith(f"'{ACR_PULL}')]")
    app = arm_template(CONFIG, DIGEST)["resources"][0]
    assert len(app["identity"]["userAssignedIdentities"]) == 1
    assert app["properties"]["configuration"]["identitySettings"][0]["lifecycle"] == "None"


@pytest.mark.parametrize("change", ["broader-role", "second-identity", "password-auth"])
def test_approved_identity_boundary_rejects_expansion(change: str) -> None:
    """Approval cannot be interpreted as permission for runtime privileges or registry passwords."""
    state = observed()
    if change == "broader-role":
        state["roles"][0]["roleDefinitionId"] = "/synthetic-role/Contributor"
    elif change == "second-identity":
        state["app"]["identity"]["userAssignedIdentities"]["/synthetic-extra-identity"] = {}
    else:
        registry = state["app"]["properties"]["configuration"]["registries"][0]
        registry.update(username="synthetic-user", passwordSecretRef="synthetic-reference")
    with pytest.raises(VerificationError):
        validate_state(CONFIG, DIGEST, state)


def observed() -> dict:
    """Build explicitly synthetic observations; never call Azure or emit cloud evidence."""
    names = CONFIG.names
    group_id = "/synthetic-account/resourceGroups/" + names["group"]
    state = {"group": {"name": names["group"], "id": group_id,
                       "tags": dict(TAGS), "location": REGION}, "inventory": []}
    kinds = {"registry": "Microsoft.ContainerRegistry/registries",
             "workspace": "Microsoft.OperationalInsights/workspaces",
             "environment": "Microsoft.App/managedEnvironments",
             "app": "Microsoft.App/containerApps",
             "identity": "Microsoft.ManagedIdentity/userAssignedIdentities"}
    for key, kind in kinds.items():
        state[key] = {"id": group_id + "/providers/" + kind + "/" + names[key],
                      "name": names[key], "location": REGION, "tags": dict(TAGS),
                      "properties": {"provisioningState": "Succeeded"}}
        state["inventory"].append({"name": names[key], "type": kind})
    registry = state["registry"]
    registry["sku"] = {"name": "Basic"}
    registry["properties"].update(adminUserEnabled=False, anonymousPullEnabled=False,
                                   loginServer=names["registry"] + ".azurecr.io")
    state["arm_auth"] = {"status": "enabled"}
    state["manifest"] = {"digest": DIGEST}
    workspace = state["workspace"]["properties"]
    workspace.update(sku={"name": "PerGB2018"}, retentionInDays=30,
                     workspaceCapping={"dailyQuotaGb": 0.1}, customerId="synthetic-workspace")
    state["environment"]["properties"].update(
        workloadProfiles=[{"name": "Consumption", "workloadProfileType": "Consumption"}],
        appLogsConfiguration={"destination": "log-analytics", "logAnalyticsConfiguration": {
            "customerId": "synthetic-workspace"}})
    identity = state["identity"]
    identity["properties"]["principalId"] = "synthetic-principal"
    state["roles"] = [{"principalId": "synthetic-principal", "scope": registry["id"],
                       "roleDefinitionId": "/synthetic-role/" + ACR_PULL}]
    app = state["app"]
    app["identity"] = {"type": "UserAssigned", "userAssignedIdentities": {identity["id"]: {}}}
    settings = {"activeRevisionsMode": "Single", "maxInactiveRevisions": 2,
                "ingress": ingress(CONFIG.reviewer_cidr),
                "registries": [{"server": names["registry"] + ".azurecr.io",
                                "identity": identity["id"]}],
                "identitySettings": [{"identity": identity["id"], "lifecycle": "None"}]}
    settings["ingress"]["fqdn"] = names["app"] + ".synthetic.southcentralus.azurecontainerapps.io"
    template = {"containers": [container(CONFIG.image(DIGEST))], "scale": scale(),
                "terminationGracePeriodSeconds": 15}
    revision = names["app"] + "--synthetic"
    app["properties"].update(environmentId=state["environment"]["id"],
                              workloadProfileName="Consumption", configuration=settings,
                              template=template, latestRevisionName=revision,
                              latestReadyRevisionName=revision)
    state["revisions"] = [{"name": revision, "properties": {
        "active": True, "healthState": "Healthy", "runningState": "Running",
        "provisioningState": "Provisioned", "trafficWeight": 100,
        "template": copy.deepcopy(template)}}]
    return state


@pytest.mark.parametrize("suffix", ["", "a1234", "a" * 13, "123456", "UPPER1",
                                    "evil;rm", "$(whoami)", "a-bbbb", None])
def test_names_reject_untrusted(suffix: str) -> None:
    """Names cannot carry account IDs, commands or unsupported resource syntax."""
    with pytest.raises(ValueError):
        AzureConfig(suffix, "8.8.8.8/32")


@pytest.mark.parametrize("cidr", ["0.0.0.0/0", "8.8.8.0/24", "127.0.0.1/32",
                                  "10.1.1.1/32", "::/0", "8.8.8.8", "8.8.8.8;pwd", None])
def test_ingress_requires_public_single_reviewer(cidr: str) -> None:
    """The unauthenticated accepted API must not receive unrestricted public ingress."""
    with pytest.raises(ValueError):
        AzureConfig("reviewa", cidr)


@pytest.mark.parametrize("digest", ["latest", "sha256:abc", "sha256:" + "A" * 64,
                                    "sha256:" + "a" * 64 + ";pwd", None])
def test_digest_required(digest: str) -> None:
    """Tags, malformed identities and injected command strings fail offline."""
    with pytest.raises(ValueError):
        CONFIG.image(digest)


def test_arm_minimal_security_and_source_contract() -> None:
    """The two phases retain approved service, compute, probe, cost and identity boundaries."""
    foundation = arm_template(CONFIG)
    assert len(foundation["resources"]) == 5 and foundation["outputs"] == {}
    by_type = {r["type"]: r for r in foundation["resources"]}
    assert by_type["Microsoft.ContainerRegistry/registries"]["sku"] == {"name": "Basic"}
    assert not by_type["Microsoft.ContainerRegistry/registries"]["properties"]["adminUserEnabled"]
    workspace = by_type["Microsoft.OperationalInsights/workspaces"]["properties"]
    assert workspace["retentionInDays"] == 30
    assert workspace["workspaceCapping"]["dailyQuotaGb"] == 0.1
    role = by_type["Microsoft.Authorization/roleAssignments"]
    assert "Microsoft.ContainerRegistry/registries" in role["scope"]
    assert ACR_PULL in role["properties"]["roleDefinitionId"]
    logs = by_type["Microsoft.App/managedEnvironments"]["properties"]["appLogsConfiguration"]
    assert logs["destination"] == "log-analytics"
    assert logs["logAnalyticsConfiguration"]["sharedKey"].startswith("[listKeys(")
    app = arm_template(CONFIG, DIGEST)
    assert len(app["resources"]) == 1 and app["outputs"] == {}
    props = app["resources"][0]["properties"]
    assert props["configuration"]["identitySettings"][0]["lifecycle"] == "None"
    assert props["template"]["scale"] == scale()
    service = props["template"]["containers"][0]
    assert service["resources"] == {"cpu": 0.25, "memory": "0.5Gi"}
    assert "command" not in service and "env" not in service
    assert [(p["type"], p["httpGet"]["path"]) for p in service["probes"]] == [
        ("Startup", "/health/ready"), ("Readiness", "/health/ready"), ("Liveness", "/health/live")]
    assert props["configuration"]["ingress"] == ingress(CONFIG.reviewer_cidr)
    serialized = json.dumps(app) + json.dumps(foundation)
    assert "/subscriptions/" not in serialized and "passwordSecretRef" not in serialized
    assert "Microsoft.Compute" not in serialized and "Microsoft.Network" not in serialized
    assert CONFIG.names == AzureConfig("reviewa", "1.1.1.1/32").names


def test_fixture_state_is_only_validation() -> None:
    """Synthetic state validation returns a hostname, never a genuine-cloud manifest."""
    result = validate_state(CONFIG, DIGEST, observed())
    assert isinstance(result, str) and result.endswith("azurecontainerapps.io")
    assert not subset(True, 1) and not subset([1, 2], [1])


@pytest.mark.parametrize("path,value", [
    (("group", "tags", "module"), "09"),
    (("registry", "sku", "name"), "Premium"),
    (("registry", "properties", "adminUserEnabled"), True),
    (("manifest", "digest"), "sha256:" + "b" * 64),
    (("arm_auth", "status"), "disabled"),
    (("workspace", "properties", "retentionInDays"), 365),
    (("workspace", "properties", "workspaceCapping", "dailyQuotaGb"), -1),
    (("environment", "properties", "appLogsConfiguration", "destination"), "none"),
    (("environment", "properties", "zoneRedundant"), True),
    (("roles", 0, "scope"), "/synthetic-account"),
    (("roles", 0, "roleDefinitionId"), "/Owner"),
    (("app", "properties", "configuration", "ingress", "allowInsecure"), True),
    (("app", "properties", "configuration", "ingress", "fqdn"), "localhost"),
    (("app", "properties", "configuration", "secrets"), [{"value": "sensitive"}]),
    (("app", "properties", "configuration", "identitySettings", 0, "lifecycle"), "All"),
    (("app", "properties", "template", "scale", "minReplicas"), 1),
    (("app", "properties", "template", "scale", "maxReplicas"), 3),
    (("app", "properties", "template", "containers", 0, "image"), "public:latest"),
    (("app", "properties", "template", "containers", 0, "env"), [{"name": "API_KEY"}]),
    (("app", "properties", "template", "containers", 0, "command"), ["bash"]),
    (("app", "properties", "template", "containers", 0, "resources", "cpu"), 1),
    (("app", "properties", "template", "containers", 0, "probes", 0, "httpGet", "path"), "/"),
    (("revisions", 0, "properties", "healthState"), "Unhealthy"),
    (("revisions", 0, "properties", "active"), False),
    (("app", "properties", "latestReadyRevisionName"), "other"),
])
def test_observation_drift_fails_closed(path: tuple, value: object) -> None:
    """Resource, cost, identity, ingress, image, runtime and revision deviations cannot pass."""
    state = observed()
    target = state
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(VerificationError) as error:
        validate_state(CONFIG, DIGEST, state)
    assert "sensitive" not in str(error.value)


@pytest.mark.parametrize("missing", ["app", "registry", "workspace", "roles", "inventory"])
def test_missing_observation(missing: str) -> None:
    """Incomplete or incompatible Azure responses retain an actionable causal failure."""
    state = observed()
    del state[missing]
    with pytest.raises(VerificationError):
        validate_state(CONFIG, DIGEST, state)


def test_extra_resources_and_authority_fail() -> None:
    """Foreign resources and extra inherited privileges prevent group acceptance."""
    state = observed()
    state["inventory"].append({"name": "foreign", "type": "Microsoft.Compute/virtualMachines"})
    with pytest.raises(VerificationError):
        validate_state(CONFIG, DIGEST, state)
    state = observed()
    state["roles"].append(copy.deepcopy(state["roles"][0]))
    with pytest.raises(VerificationError):
        validate_state(CONFIG, DIGEST, state)


@pytest.mark.parametrize("command", [("group", "delete"), ("deployment", "group", "create"),
                                     ("acr", "login"), ("provider", "register")])
def test_collector_cannot_mutate(command: tuple[str, ...], monkeypatch: pytest.MonkeyPatch) -> None:
    """Unknown and privileged commands fail before process execution or credential inspection."""
    monkeypatch.setattr(deployment.subprocess, "run", lambda *a, **kw: pytest.fail("CLI reached"))
    with pytest.raises(VerificationError, match="forbidden"):
        deployment.az_read(command)


@pytest.mark.parametrize("result", [subprocess.CompletedProcess([], 1, "sensitive", "sensitive"),
                                    subprocess.CompletedProcess([], 0, "not-json", ""),
                                    subprocess.CompletedProcess([], 0, "x" * 1_048_577, "")])
def test_cli_boundary_minimizes_errors(result: subprocess.CompletedProcess,
                                      monkeypatch: pytest.MonkeyPatch) -> None:
    """Failed, incompatible or oversized CLI observations do not leak raw diagnostics."""
    monkeypatch.setattr(deployment.shutil, "which", lambda name: "az")
    monkeypatch.setattr(deployment.subprocess, "run", lambda *a, **kw: result)
    with pytest.raises(VerificationError) as error:
        deployment.az_read(("group", "show"), "--name", CONFIG.names["group"])
    assert "sensitive" not in str(error.value)


def test_cli_timeout_and_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    """Timeouts are causal and fixed commands disable automatic extension installs."""
    monkeypatch.setattr(deployment.shutil, "which", lambda name: "az")

    def run(command: list[str], **kwargs: object) -> None:
        assert kwargs["timeout"] == 90 and kwargs["capture_output"] is True
        assert kwargs["env"]["AZURE_EXTENSION_USE_DYNAMIC_INSTALL"] == "no"
        raise subprocess.TimeoutExpired(command, 90, output="sensitive")

    monkeypatch.setattr(deployment.subprocess, "run", run)
    with pytest.raises(VerificationError) as error:
        deployment.az_read(("group", "show"))
    assert isinstance(error.value.__cause__, subprocess.TimeoutExpired)


def test_monitor_query_is_correlated_and_minimized() -> None:
    """KQL scopes fresh traffic to app/revision and returns fixed aggregates only."""
    request_id = "b" * 32
    query = deployment.monitor_query(CONFIG.names["app"], CONFIG.names["app"] + "--synthetic",
                                     request_id)
    assert request_id not in query and "ago(10m)" in query
    assert "project successes, failures" in query and "project Log_s" not in query
    with pytest.raises(VerificationError):
        deployment.monitor_query(CONFIG.names["app"], "evil' | take 10", request_id)


@pytest.mark.parametrize("failure", ["state", "http", "monitor", "drift"])
def test_verifier_no_success_on_required_failure(failure: str,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    """Every stage failure prevents construction of genuine-cloud success metadata."""
    calls = []

    def collect(*args: object) -> dict:
        state = observed()
        calls.append("collect")
        if failure == "state" or (failure == "drift" and len(calls) > 1):
            state["app"]["properties"]["template"]["scale"]["maxReplicas"] = 3
        return state

    def http(*args: object) -> None:
        if failure == "http":
            raise VerificationError("HTTP failed")

    monkeypatch.setattr(deployment, "collect", collect)
    monkeypatch.setattr(deployment, "https_checks", http)
    monkeypatch.setattr(deployment, "az_read", lambda *args:
                        [] if failure == "monitor" else [{"successes": 2, "failures": 1}])
    monkeypatch.setattr(deployment.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(deployment, "cloud_evidence", lambda *args: pytest.fail("false success"))
    with pytest.raises(VerificationError):
        deployment.verify(CONFIG, DIGEST)


def test_monitor_retry_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bound ingestion lag to six queries and five sleeps without repeating HTTP traffic."""
    queries, sleeps, http_calls = [], [], []
    monkeypatch.setattr(deployment, "collect", lambda *args: observed())
    monkeypatch.setattr(deployment, "https_checks", lambda *args: http_calls.append(args))
    monkeypatch.setattr(deployment, "az_read", lambda *args: queries.append(args) or [])
    monkeypatch.setattr(deployment.time, "sleep", lambda seconds: sleeps.append(seconds))
    with pytest.raises(VerificationError, match="receipt missing"):
        deployment.verify(CONFIG, DIGEST)
    assert len(queries) == 6 and sleeps == [20] * 5 and len(http_calls) == 1


@pytest.mark.parametrize("bad", ["redirect", "schema", "determinism", "rejection", "large"])
def test_https_failures(bad: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirects, altered output, unsafe rejection and response growth fail acceptance."""
    original = httpx.AsyncClient
    request_id = "b" * 32

    def respond(request: httpx.Request) -> httpx.Response:
        if bad == "redirect":
            return httpx.Response(302, headers={"Location": "http://localhost"}, json={})
        if bad == "large":
            return httpx.Response(200, content=b"x" * 65537)
        if request.url.path == "/health/live":
            return httpx.Response(200, json={"status": "alive", "mode": "deterministic"})
        if request.url.path == "/health/ready":
            return httpx.Response(200, json={"status": "ready", "mode": "deterministic"})
        if json.loads(request.content)["text"] == "":
            return httpx.Response(422, json={"code": "invalid_request", "request_id": request_id,
                "message": "sensitive" if bad == "rejection" else
                           "Request does not satisfy the input contract."})
        result = {"word_count": 4, "keywords": ["beta", "alpha", "gamma"],
                  "evidence": "deterministic", "request_id": request_id}
        if bad == "schema":
            result["secret"] = "sensitive"
        if bad == "determinism":
            result["word_count"] = 5
        return httpx.Response(200, json=result)

    monkeypatch.setattr(deployment.httpx, "AsyncClient", lambda **kw:
                        original(**kw, transport=httpx.MockTransport(respond)))
    with pytest.raises(VerificationError) as error:
        deployment.https_checks("synthetic.azurecontainerapps.io", request_id)
    assert "sensitive" not in str(error.value)


def test_render_is_offline_and_no_cloud_claim(monkeypatch: pytest.MonkeyPatch,
                                            tmp_path: Path) -> None:
    """Rendering has no Azure/Docker/HTTP calls and never emits deployed status."""
    monkeypatch.setattr(deployment, "EVIDENCE_ROOT", tmp_path)
    monkeypatch.setattr(deployment, "verify", lambda *args: pytest.fail("cloud reached"))
    monkeypatch.setattr(sys, "argv", ["azure_deployment", "--suffix", "reviewa",
                        "--reviewer-cidr", "8.8.8.8/32", "--render", "foundation",
                        "--output", str(tmp_path / "foundation.json")])
    deployment.main()
    assert json.loads((tmp_path / "foundation.json").read_text()) == arm_template(CONFIG)
    with pytest.raises(ValueError):
        deployment.destination(tmp_path / "foundation.json")
    with pytest.raises(ValueError):
        deployment.destination(ROOT / "evidence.json")


def candidate() -> dict:
    """Construct synthetic local validation data, never operator approval."""
    return {"classification": "LOCAL CI/CD CONTRACT", "source_clean": True,
            "deployment_authorized": False, "source_commit": "a" * 40,
            "image_id": "sha256:" + "b" * 64, "build": "passed",
            "container_acceptance": "passed", "gates": {"ruff": "passed", "pytest": "passed",
                "compileall": "passed",
                "security_contract": "passed/targeted-not-vulnerability-audit"}}


def manifest() -> bytes:
    """Return synthetic single-platform registry bytes bound to the fixture Docker content ID."""
    return json.dumps({"schemaVersion": 2,
                       "mediaType": "application/vnd.docker.distribution.manifest.v2+json",
                       "config": {"digest": "sha256:" + "b" * 64},
                       "layers": [{"digest": "sha256:" + "c" * 64}]}).encode()


@pytest.mark.parametrize("key,value", [("source_clean", False), ("source_clean", 1),
                                      ("deployment_authorized", True), ("source_commit", "latest"),
                                      ("image_id", "latest"), ("build", "failed"),
                                      ("container_acceptance", "failed"), ("gates", {}),
                                      ("classification", "AZURE CLOUD")])
def test_publication_rejects_failed_or_forged_candidate(key: str, value: object) -> None:
    """No clean-source or quality-stage requirement can be bypassed by candidate JSON."""
    data = candidate()
    data[key] = value
    with pytest.raises(ValueError):
        publication(data, manifest())


@pytest.mark.parametrize("raw", [b"{", b"x" * 65537, b"{}", b'{"schemaVersion":1}',
                                b'{"schemaVersion":2,"mediaType":"index"}'],
                         ids=["malformed", "oversized", "empty", "schema", "index"])
def test_publication_rejects_bad_manifest(raw: bytes) -> None:
    """Malformed, oversized and multi-platform manifest identities cannot bind accepted content."""
    with pytest.raises(ValueError):
        publication(candidate(), raw)


def test_publication_binds_content_but_never_authorizes() -> None:
    """Registry manifest identity differs from Docker content ID and still grants no authority."""
    result = publication(candidate(), manifest())
    assert result["deployment_authorized"] is False
    assert result["registry_manifest_digest"] != result["image_id"]
    assert "OPERATOR REVIEW REQUIRED" in result["classification"]
    data = json.loads(manifest())
    data["config"]["digest"] = "sha256:" + "d" * 64
    with pytest.raises(ValueError):
        publication(candidate(), json.dumps(data).encode())


def test_https_success_is_five_bounded_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """The transport fixture exercises the happy path without live network or evidence output."""
    original = httpx.AsyncClient
    request_id = "b" * 32
    calls = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.url.scheme == "https" and request.headers["X-Request-ID"] == request_id
        if request.url.path.startswith("/health/"):
            return httpx.Response(200, json={"status": "alive" if
                request.url.path.endswith("live") else "ready", "mode": "deterministic"})
        if json.loads(request.content)["text"] == "":
            return httpx.Response(422, json={
                "code": "invalid_request", "request_id": request_id,
                "message": "Request does not satisfy the input contract."})
        return httpx.Response(200, json={"word_count": 4, "keywords": ["beta", "alpha", "gamma"],
                                        "evidence": "deterministic", "request_id": request_id})

    def client(**kwargs: object) -> httpx.AsyncClient:
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        assert kwargs["timeout"] == 30
        return original(**kwargs, transport=httpx.MockTransport(respond))

    monkeypatch.setattr(deployment.httpx, "AsyncClient", client)
    deployment.https_checks("synthetic.azurecontainerapps.io", request_id)
    assert len(calls) == 5


def test_windows_cli_avoids_batch_shell(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """MSI command wrappers are resolved to direct Python execution instead of cmd.exe."""
    wrapper = tmp_path / "wbin" / "az.cmd"
    wrapper.parent.mkdir()
    wrapper.write_text("synthetic wrapper")
    runtime = tmp_path / "python.exe"
    runtime.write_text("synthetic runtime")
    monkeypatch.setattr(deployment.shutil, "which", lambda name: str(wrapper))

    def execute(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        assert command[:3] == [str(runtime), "-IBm", "azure.cli"]
        assert kwargs["env"]["AZURE_LOGGING_ENABLE_LOG_FILE"] == "false"
        return subprocess.CompletedProcess(command, 0, "{}", "")

    monkeypatch.setattr(deployment.subprocess, "run", execute)
    assert deployment.az_read(("group", "show")) == {}
    runtime.unlink()
    with pytest.raises(VerificationError, match="batch execution forbidden"):
        deployment.az_read(("group", "show"))
