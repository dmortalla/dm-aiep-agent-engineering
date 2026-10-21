"""Offline Azure contract, adversarial observations and bounded collector failure tests."""

import copy
import importlib.util
import io
import json
import subprocess
import sys
from itertools import permutations
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

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
SUBSCRIPTION = str(uuid5(NAMESPACE_URL, "module10.synthetic.subscription"))
PRINCIPAL = str(uuid5(NAMESPACE_URL, "module10.synthetic.principal"))


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
        validate_state(CONFIG, DIGEST, state, SUBSCRIPTION)


def observed() -> dict:
    """Build explicitly synthetic observations; never call Azure or emit cloud evidence."""
    names = CONFIG.names
    group_id = f"/subscriptions/{SUBSCRIPTION}/resourceGroups/" + names["group"]
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
    identity["properties"]["principalId"] = PRINCIPAL
    assignment = str(uuid5(NAMESPACE_URL, "module10.synthetic.assignment"))
    state["roles"] = [{"principalId": PRINCIPAL, "scope": registry["id"],
                       "principalType": "ServicePrincipal",
                       "id": registry["id"] + "/providers/Microsoft.Authorization/"
                             "roleAssignments/" + assignment,
                       "roleDefinitionId": f"/subscriptions/{SUBSCRIPTION}/providers/"
                                           "Microsoft.Authorization/roleDefinitions/" + ACR_PULL}]
    state["inherited_roles"] = copy.deepcopy(state["roles"])
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
    result = validate_state(CONFIG, DIGEST, observed(), SUBSCRIPTION)
    assert isinstance(result, str) and result.endswith("azurecontainerapps.io")
    assert not subset(True, 1) and not subset([1, 2], [1])



@pytest.mark.parametrize("transport", ["http", "Http"])
def test_approved_transport_representations(transport: str) -> None:
    """Only observation interpretation changes; contract and raw state stay intact."""
    state = observed()
    state["app"]["properties"]["configuration"]["ingress"]["transport"] = transport
    original = copy.deepcopy(state)
    assert validate_state(CONFIG, DIGEST, state, SUBSCRIPTION).endswith("azurecontainerapps.io")
    assert state == original
    assert ingress(CONFIG.reviewer_cidr)["transport"] == "http"
    assert not subset({"transport": "Http"}, {"transport": "http"})


@pytest.mark.parametrize("transport", [
    "HTTP", "hTtp", "httP", " http", "http ", "Http\n", "http\t", "http\x00",
    "https", "tcp", "auto", "http2", "unknown", "", None, True, 1, [], {}, ["Http"],
])
def test_transport_observations_fail_closed(transport: object) -> None:
    """Exact allowlisting rejects near matches, other modes and malformed types."""
    state = observed()
    state["app"]["properties"]["configuration"]["ingress"]["transport"] = transport
    with pytest.raises(VerificationError, match="approved HTTP transport"):
        validate_state(CONFIG, DIGEST, state, SUBSCRIPTION)


@pytest.mark.parametrize("field", list(ingress(CONFIG.reviewer_cidr)))
def test_transport_alias_requires_complete_ingress(field: str) -> None:
    """The approved spelling cannot compensate for any missing contract field."""
    state = observed()
    target = state["app"]["properties"]["configuration"]["ingress"]
    target["transport"] = "Http"
    del target[field]
    with pytest.raises(VerificationError):
        validate_state(CONFIG, DIGEST, state, SUBSCRIPTION)


@pytest.mark.parametrize("value", [None, [], ["malformed"], "Http", True, 8000])
def test_malformed_ingress_fails_closed(value: object) -> None:
    """An ingress observation must be a mapping before transport interpretation."""
    state = observed()
    state["app"]["properties"]["configuration"]["ingress"] = value
    with pytest.raises(VerificationError):
        validate_state(CONFIG, DIGEST, state, SUBSCRIPTION)


@pytest.mark.parametrize("field,value", [
    ("external", False), ("targetPort", 80), ("targetPort", "8000"),
    ("allowInsecure", True), ("allowInsecure", 0),
    ("traffic", []), ("traffic", [{"latestRevision": True, "weight": 99}]),
    ("ipSecurityRestrictions", []),
    ("ipSecurityRestrictions", [{"name": "reviewer", "action": "Allow",
                                 "ipAddressRange": "0.0.0.0/0"}]),
    ("ipSecurityRestrictions", [{"name": "reviewer", "action": "Deny",
                                 "ipAddressRange": CONFIG.reviewer_cidr}]),
    ("ipSecurityRestrictions", ingress(CONFIG.reviewer_cidr)["ipSecurityRestrictions"] * 2),
    ("additionalPortMappings", [{"external": True, "targetPort": 9000}]),
    ("customDomains", [{"name": "synthetic.invalid"}]),
])
def test_transport_alias_preserves_ingress_security(field: str, value: object) -> None:
    """HTTP representation equivalence grants no additional ingress exposure."""
    state = observed()
    target = state["app"]["properties"]["configuration"]["ingress"]
    target.update(transport="Http")
    target[field] = value
    with pytest.raises(VerificationError):
        validate_state(CONFIG, DIGEST, state, SUBSCRIPTION)


RESOURCE_KEYS = ("registry", "workspace", "environment", "app", "identity")


@pytest.mark.parametrize("resource", ("group", *RESOURCE_KEYS))
@pytest.mark.parametrize("location", [REGION, "South Central US"])
def test_approved_region_representations(resource: str, location: str) -> None:
    """Every Azure resource observation accepts exactly the approved region aliases."""
    state = observed()
    state[resource]["location"] = location
    original = copy.deepcopy(state)
    assert validate_state(CONFIG, DIGEST, state, SUBSCRIPTION).endswith("azurecontainerapps.io")
    assert state == original  # Canonicalization must not rewrite raw observations.


@pytest.mark.parametrize("resource", ("group", *RESOURCE_KEYS))
@pytest.mark.parametrize("location", [
    "eastus", "East US", "southcentralus2", "South Central US EUAP",
    "prefixsouthcentralus", "southcentralus/", "SOUTHCENTRALUS", "south central us",
    " South Central US", "South Central US ", "South  Central US", "South\tCentral US",
    "South\u00a0Central US", "southcentralus\n", "South Central US\x00", "", "unknown",
    None, True, 1, [], {}, [REGION],
])
def test_region_observations_fail_closed(resource: str, location: object) -> None:
    """Other regions, near matches, Unicode, whitespace and malformed types fail closed."""
    state = observed()
    state[resource]["location"] = location
    with pytest.raises(VerificationError, match="approved South Central US region"):
        validate_state(CONFIG, DIGEST, state, SUBSCRIPTION)


@pytest.mark.parametrize("resource", RESOURCE_KEYS)
@pytest.mark.parametrize("field", ["id", "name", *TAGS])
@pytest.mark.parametrize("damage", ["wrong", "missing"])
def test_region_alias_preserves_resource_ownership(resource: str, field: str, damage: str) -> None:
    """Display-name locations cannot bypass any resource ID, name or required tag gate."""
    state = observed()
    for key in RESOURCE_KEYS:
        state[key]["location"] = "South Central US"
    target = state[resource]["tags"] if field in TAGS else state[resource]
    if damage == "missing":
        del target[field]
    elif field == "id":
        target[field] = target[field].replace(SUBSCRIPTION, PRINCIPAL)
    else:
        target[field] = "synthetic-foreign"
    with pytest.raises(VerificationError):
        validate_state(CONFIG, DIGEST, state, SUBSCRIPTION)


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
@pytest.mark.parametrize("transport", ["http", "Http"])
def test_observation_drift_fails_closed(path: tuple, value: object, transport: str) -> None:
    """Resource, cost, identity, ingress, image, runtime and revision deviations cannot pass."""
    state = observed()
    state["app"]["properties"]["configuration"]["ingress"]["transport"] = transport
    target = state
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(VerificationError) as error:
        validate_state(CONFIG, DIGEST, state, SUBSCRIPTION)
    assert "sensitive" not in str(error.value)


@pytest.mark.parametrize("missing", ["app", "registry", "workspace", "roles", "inventory"])
def test_missing_observation(missing: str) -> None:
    """Incomplete or incompatible Azure responses retain an actionable causal failure."""
    state = observed()
    del state[missing]
    with pytest.raises(VerificationError):
        validate_state(CONFIG, DIGEST, state, SUBSCRIPTION)


def test_extra_resources_and_authority_fail() -> None:
    """Foreign resources and extra inherited privileges prevent group acceptance."""
    state = observed()
    state["inventory"].append({"name": "foreign", "type": "Microsoft.Compute/virtualMachines"})
    with pytest.raises(VerificationError):
        validate_state(CONFIG, DIGEST, state, SUBSCRIPTION)
    state = observed()
    state["roles"].append(copy.deepcopy(state["roles"][0]))
    with pytest.raises(VerificationError):
        validate_state(CONFIG, DIGEST, state, SUBSCRIPTION)


@pytest.mark.parametrize("command", [("group", "delete"), ("deployment", "group", "create"),
                                     ("acr", "login"), ("provider", "register")])
def test_collector_cannot_mutate(command: tuple[str, ...], monkeypatch: pytest.MonkeyPatch) -> None:
    """Unknown and privileged commands fail before process execution or credential inspection."""
    monkeypatch.setattr(deployment.subprocess, "run", lambda *a, **kw: pytest.fail("CLI reached"))
    with pytest.raises(VerificationError, match="forbidden"):
        deployment.az_read(command, subscription=SUBSCRIPTION)


@pytest.mark.parametrize("result", [subprocess.CompletedProcess([], 1, "sensitive", "sensitive"),
                                    subprocess.CompletedProcess([], 0, "not-json", ""),
                                    subprocess.CompletedProcess([], 0, "x" * 1_048_577, "")])
def test_cli_boundary_minimizes_errors(result: subprocess.CompletedProcess,
                                      monkeypatch: pytest.MonkeyPatch) -> None:
    """Failed, incompatible or oversized CLI observations do not leak raw diagnostics."""
    monkeypatch.setattr(deployment.shutil, "which", lambda name: "az")
    monkeypatch.setattr(deployment.subprocess, "run", lambda *a, **kw: result)
    with pytest.raises(VerificationError) as error:
        deployment.az_read(("group", "show"), "--name", CONFIG.names["group"],
                           subscription=SUBSCRIPTION)
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
        deployment.az_read(("group", "show"), subscription=SUBSCRIPTION)
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
    monkeypatch.setattr(deployment, "az_read", lambda *args, **kwargs:
                        [] if failure == "monitor" else [{"successes": 2, "failures": 1}])
    monkeypatch.setattr(deployment.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(deployment, "cloud_evidence", lambda *args: pytest.fail("false success"))
    with pytest.raises(VerificationError):
        deployment.verify(CONFIG, DIGEST, SUBSCRIPTION)


def test_monitor_retry_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bound ingestion lag to six queries and five sleeps without repeating HTTP traffic."""
    queries, sleeps, http_calls = [], [], []
    monkeypatch.setattr(deployment, "collect", lambda *args: observed())
    monkeypatch.setattr(deployment, "https_checks", lambda *args: http_calls.append(args))
    monkeypatch.setattr(deployment, "az_read", lambda *args, **kwargs: queries.append(args) or [])
    monkeypatch.setattr(deployment.time, "sleep", lambda seconds: sleeps.append(seconds))
    with pytest.raises(VerificationError, match="receipt missing"):
        deployment.verify(CONFIG, DIGEST, SUBSCRIPTION)
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
    assert deployment.az_read(("group", "show"), subscription=SUBSCRIPTION) == {}
    runtime.unlink()
    with pytest.raises(VerificationError, match="batch execution forbidden"):
        deployment.az_read(("group", "show"), subscription=SUBSCRIPTION)


def collector_double(state: dict, calls: list) -> object:
    """Adapt synthetic observations to real collector commands without calling Azure."""
    def read(command: tuple[str, ...], *args: str, subscription: str) -> object:
        calls.append((command, args, subscription))
        assert subscription == SUBSCRIPTION
        assert not ("--scope" in args and "--all" in args)
        if command == ("group", "show"):
            return copy.deepcopy(state["group"])
        if command == ("resource", "list"):
            return copy.deepcopy(state["inventory"])
        if command == ("resource", "show"):
            name = args[args.index("--name") + 1]
            return copy.deepcopy(state[next(k for k, v in CONFIG.names.items() if v == name)])
        if command == ("role", "assignment", "list"):
            assert "--assignee-object-id" in args and "--include-groups" in args
            assert args[args.index("--assignee-object-id") + 1] == PRINCIPAL
            if "--all" in args:
                return copy.deepcopy(state["roles"])
            assert "--include-inherited" in args
            return copy.deepcopy(state["inherited_roles"])
        if command == ("containerapp", "revision", "list"):
            return copy.deepcopy(state["revisions"])
        if command == ("acr", "manifest", "show-metadata"):
            return copy.deepcopy(state["manifest"])
        if command == ("acr", "config", "authentication-as-arm", "show"):
            return copy.deepcopy(state["arm_auth"])
        if command == ("monitor", "log-analytics", "query"):
            return [{"successes": 2, "failures": 1}]
        pytest.fail("Unexpected collector command")
    return read


def test_real_collector_and_verifier_bind_every_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """Both snapshots, RBAC views and monitor query use the independent subscription."""
    calls = []
    monkeypatch.setattr(deployment, "az_read", collector_double(observed(), calls))
    monkeypatch.setattr(deployment, "https_checks", lambda *args: None)
    evidence = deployment.verify(CONFIG, DIGEST, SUBSCRIPTION)
    assert evidence["classification"] == "AZURE CLOUD / DETERMINISTIC INFERENCE"
    assert SUBSCRIPTION not in json.dumps(evidence) and PRINCIPAL not in json.dumps(evidence)
    roles = [args for command, args, _ in calls if command == ("role", "assignment", "list")]
    assert len(roles) == 4
    assert sum("--all" in args for args in roles) == 2
    assert sum("--scope" in args and "--include-inherited" in args for args in roles) == 2
    assert len(calls) == 25  # Two twelve-read snapshots and one telemetry query.


@pytest.mark.parametrize("view", ["roles", "inherited_roles"])
@pytest.mark.parametrize("scope", ["subscription", "group", "sibling", "other-group", "parent"])
def test_collector_rejects_authority_outside_registry(view: str, scope: str,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    """Full subscription and ancestor lists expose forbidden assignments before HTTP."""
    state = observed()
    extra = copy.deepcopy(state[view][0])
    root = f"/subscriptions/{SUBSCRIPTION}"
    scopes = {"subscription": root, "group": root + "/resourceGroups/" + CONFIG.names["group"],
              "sibling": state["workspace"]["id"],
              "other-group": root + "/resourceGroups/synthetic-other",
              "parent": "/providers/Microsoft.Management/managementGroups/synthetic-parent"}
    extra["scope"] = scopes[scope]
    state[view].append(extra)
    monkeypatch.setattr(deployment, "az_read", collector_double(state, []))
    monkeypatch.setattr(deployment, "https_checks", lambda *a: pytest.fail("HTTP reached"))
    with pytest.raises(VerificationError):
        deployment.verify(CONFIG, DIGEST, SUBSCRIPTION)


@pytest.mark.parametrize("view", ["roles", "inherited_roles"])
@pytest.mark.parametrize("bad", [None, [], {}, {"value": [], "nextLink": "untrusted"},
                                 [None], [True], ["partial"]])
def test_rbac_partial_or_malformed_lists_fail(view: str, bad: object) -> None:
    """Missing pages, envelopes, wrong types and absent expected assignments cannot pass."""
    state = observed()
    state[view] = bad
    with pytest.raises(VerificationError):
        validate_state(CONFIG, DIGEST, state, SUBSCRIPTION)


@pytest.mark.parametrize("view", ["roles", "inherited_roles"])
@pytest.mark.parametrize("field", ["id", "scope", "principalId", "principalType",
                                  "roleDefinitionId"])
def test_rbac_missing_required_fields_fail(view: str, field: str) -> None:
    """Successful CLI status cannot substitute for a complete assignment identity."""
    state = observed()
    del state[view][0][field]
    with pytest.raises(VerificationError):
        validate_state(CONFIG, DIGEST, state, SUBSCRIPTION)


def test_missing_inherited_collection_fails() -> None:
    """A subscription-only result cannot stand in for the required inherited read."""
    state = observed()
    del state["inherited_roles"]
    with pytest.raises(VerificationError):
        validate_state(CONFIG, DIGEST, state, SUBSCRIPTION)


@pytest.mark.parametrize("change", ["push", "owner", "group", "assignment", "definition"])
def test_rbac_exact_identity_and_authority(change: str) -> None:
    """Broader roles, group authority, conflicting observations and forged role paths fail."""
    state = observed()
    role = state["inherited_roles"][0]
    if change in ("push", "owner"):
        role["roleDefinitionId"] = "/synthetic/" + change
    elif change == "group":
        role["principalType"] = "Group"
    elif change == "assignment":
        role["id"] = role["id"].rsplit("/", 1)[0] + "/" + str(uuid5(NAMESPACE_URL, "other"))
    else:
        role["roleDefinitionId"] = "/untrusted/" + ACR_PULL
    with pytest.raises(VerificationError):
        validate_state(CONFIG, DIGEST, state, SUBSCRIPTION)


@pytest.mark.parametrize("bad", [None, "", True, 42, "not-an-id", "0" * 32])
def test_null_or_malformed_principals_fail(bad: object,
                                         monkeypatch: pytest.MonkeyPatch) -> None:
    """Matching malformed identifiers cannot grant acceptance or reach a role query."""
    state = observed()
    state["identity"]["properties"]["principalId"] = bad
    state["roles"][0]["principalId"] = bad
    state["inherited_roles"][0]["principalId"] = bad
    with pytest.raises(VerificationError):
        validate_state(CONFIG, DIGEST, state, SUBSCRIPTION)
    calls = []
    monkeypatch.setattr(deployment, "az_read", collector_double(state, calls))
    with pytest.raises(VerificationError):
        deployment.collect(CONFIG, DIGEST, SUBSCRIPTION)
    assert not any(command == ("role", "assignment", "list") for command, _, _ in calls)


@pytest.mark.parametrize("target", ["app", "revision", "both"])
@pytest.mark.parametrize("probe_index", [0, 1, 2])
@pytest.mark.parametrize("field,value", [
    ("host", "external.example"),
    ("httpHeaders", [{"name": "Authorization", "value": "synthetic-sensitive"}]),
    ("httpHeaders", [{"name": "X-Custom", "value": "synthetic"}]),
    ("unknown", "unapproved"),
])
def test_probe_extra_fields_fail_closed(target: str, probe_index: int,
                                        field: str, value: object) -> None:
    """Review exploits fail even when app and active revision agree on the extra fields."""
    state = observed()
    templates = []
    if target in ("app", "both"):
        templates.append(state["app"]["properties"]["template"])
    if target in ("revision", "both"):
        templates.append(state["revisions"][0]["properties"]["template"])
    for template in templates:
        template["containers"][0]["probes"][probe_index]["httpGet"][field] = value
    with pytest.raises(VerificationError) as error:
        validate_state(CONFIG, DIGEST, state, SUBSCRIPTION)
    assert "synthetic-sensitive" not in str(error.value)


def test_consistently_wrong_subscription_fails() -> None:
    """An internally coherent deployment in another subscription is still rejected."""
    state = observed()
    other = str(uuid5(NAMESPACE_URL, "module10.synthetic.other-subscription"))
    state = json.loads(json.dumps(state).replace(SUBSCRIPTION, other))
    with pytest.raises(VerificationError, match="expected subscription") as error:
        validate_state(CONFIG, DIGEST, state, SUBSCRIPTION)
    assert SUBSCRIPTION not in str(error.value) and other not in str(error.value)


@pytest.mark.parametrize("bad", [None, "", True, "default", "0" * 32])
def test_invalid_subscription_never_reaches_cli(bad: object,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing independent binding cannot fall back to the CLI account default."""
    monkeypatch.setattr(deployment.shutil, "which", lambda *a: pytest.fail("CLI reached"))
    with pytest.raises(VerificationError):
        deployment.az_read(("group", "show"), subscription=bad)


@pytest.mark.parametrize("args", [("--scope", "synthetic", "--all"),
                                  ("--subscription", "default"), ("-s", "default")])
def test_cli_forbids_invalid_scope_and_subscription_override(
        args: tuple, monkeypatch: pytest.MonkeyPatch) -> None:
    """Reject invalid role flags and subscription substitution before process execution."""
    monkeypatch.setattr(deployment.shutil, "which", lambda *a: pytest.fail("CLI reached"))
    with pytest.raises(VerificationError):
        deployment.az_read(("role", "assignment", "list"), *args, subscription=SUBSCRIPTION)


def test_cli_explicit_subscription_ignores_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """The process command binds reads without relying on mutable account defaults."""
    monkeypatch.setattr(deployment.shutil, "which", lambda *a: "az")
    monkeypatch.setenv("AZURE_SUBSCRIPTION_ID", "synthetic-other-default")

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        assert command[command.index("--subscription") + 1] == SUBSCRIPTION
        return subprocess.CompletedProcess(command, 0, "{}", "")

    monkeypatch.setattr(deployment.subprocess, "run", run)
    assert deployment.az_read(("group", "show"), subscription=SUBSCRIPTION) == {}


@pytest.mark.parametrize("view", ["roles", "inherited_roles"])
def test_failed_rbac_read_prevents_evidence(view: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Either failed authority read prevents HTTP and success evidence construction."""
    read = collector_double(observed(), [])

    def failing(command: tuple[str, ...], *args: str, subscription: str) -> object:
        if command == ("role", "assignment", "list") and (
                (view == "roles" and "--all" in args)
                or (view == "inherited_roles" and "--scope" in args)):
            raise VerificationError("Synthetic RBAC collection failure.")
        return read(command, *args, subscription=subscription)

    monkeypatch.setattr(deployment, "az_read", failing)
    monkeypatch.setattr(deployment, "https_checks", lambda *a: pytest.fail("HTTP reached"))
    with pytest.raises(VerificationError):
        deployment.verify(CONFIG, DIGEST, SUBSCRIPTION)


def test_acr_uses_documented_default_and_retains_receipt_gate() -> None:
    """No unsupported ARM authentication policy is emitted; its required state is verified."""
    registry = arm_template(CONFIG)["resources"][0]
    assert "azureADAuthenticationAsArmPolicy" not in json.dumps(registry)
    state = observed()
    state["arm_auth"] = {"status": "disabled"}
    with pytest.raises(VerificationError):
        validate_state(CONFIG, DIGEST, state, SUBSCRIPTION)


def test_private_subscription_refuses_echo_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """A noninteractive environment cannot silently echo the expected subscription."""
    def fallback(prompt: str) -> str:
        raise deployment.getpass.GetPassWarning("synthetic fallback")

    monkeypatch.setattr(deployment.getpass, "getpass", fallback)
    with pytest.raises(VerificationError, match="private interactive"):
        deployment.private_subscription()


@pytest.mark.parametrize("failure", ["roles", "inherited_roles", "subscription", "probe"])
def test_cli_acceptance_never_writes_failed_evidence(failure: str,
                                                   monkeypatch: pytest.MonkeyPatch,
                                                   tmp_path: Path,
                                                   capsys: pytest.CaptureFixture) -> None:
    """Exploit and partial-response regressions fail through the real command entry point."""
    state = observed()
    if failure in ("roles", "inherited_roles"):
        state[failure] = {"value": state[failure], "nextLink": "synthetic-partial"}
    elif failure == "subscription":
        other = str(uuid5(NAMESPACE_URL, "module10.synthetic.wrong-entrypoint-subscription"))
        state = json.loads(json.dumps(state).replace(SUBSCRIPTION, other))
    else:
        state["app"]["properties"]["template"]["containers"][0]["probes"][0]["httpGet"][
            "host"] = "external.example"
    output = tmp_path / "no-acceptance.json"
    monkeypatch.setattr(deployment, "EVIDENCE_ROOT", tmp_path)
    monkeypatch.setattr(deployment, "az_read", collector_double(state, []))
    monkeypatch.setattr(deployment.getpass, "getpass", lambda prompt: SUBSCRIPTION)
    monkeypatch.setattr(deployment, "https_checks", lambda *a: pytest.fail("HTTP reached"))
    monkeypatch.setattr(sys, "argv", ["azure_deployment", "--suffix", CONFIG.suffix,
                        "--reviewer-cidr", CONFIG.reviewer_cidr, "--digest", DIGEST,
                        "--verify-cloud", "--output", str(output)])
    with pytest.raises(SystemExit) as error:
        deployment.main()
    assert error.value.code == 1 and not output.exists()
    captured = capsys.readouterr()
    assert "Cloud verification passed" not in captured.out
    assert SUBSCRIPTION not in captured.out + captured.err


@pytest.mark.parametrize("payload", ["valid", "lf", "crlf", "missing", "empty", "bad",
                                     "zero", "compact", "braces", "extra", "oversize"])
def test_private_pipe_entrypoint(payload: str, monkeypatch: pytest.MonkeyPatch,
                                tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """Exercise actual input, collector and evidence path without cloud operations."""
    values = {"valid": SUBSCRIPTION, "lf": SUBSCRIPTION + "\n",
              "crlf": SUBSCRIPTION + "\r\n", "missing": "", "empty": "\n",
              "bad": "synthetic-malformed-private", "zero": str(UUID(int=0)),
              "compact": SUBSCRIPTION.replace("-", ""), "braces": "{" + SUBSCRIPTION + "}",
              "extra": SUBSCRIPTION + "\nX", "oversize": SUBSCRIPTION + "x" * 100}
    value = values[payload]
    calls = []
    output = tmp_path / "acceptance.json"
    monkeypatch.setattr(sys, "stdin", io.StringIO(value))
    monkeypatch.setattr(deployment.getpass, "getpass", lambda *a: pytest.fail("fallback"))
    monkeypatch.setattr(deployment, "EVIDENCE_ROOT", tmp_path)
    monkeypatch.setattr(deployment, "az_read", collector_double(observed(), calls))
    monkeypatch.setattr(deployment, "https_checks", lambda *a: None)
    monkeypatch.setattr(sys, "argv", ["azure_deployment", "--suffix", CONFIG.suffix,
                        "--reviewer-cidr", CONFIG.reviewer_cidr, "--digest", DIGEST,
                        "--verify-cloud", "--subscription-stdin", "--output", str(output)])
    if payload in {"valid", "lf", "crlf"}:
        deployment.main()
        assert calls and SUBSCRIPTION not in output.read_text()
    else:
        with pytest.raises(SystemExit) as error:
            deployment.main()
        assert error.value.code == 1
        assert not calls and not output.exists()
    captured = capsys.readouterr()
    assert SUBSCRIPTION not in captured.out + captured.err
    if value.strip():
        assert value.strip() not in captured.out + captured.err


def test_private_pipe_rejects_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit pipe mode cannot silently become an echoing terminal read."""
    stream = io.StringIO(SUBSCRIPTION)
    monkeypatch.setattr(stream, "isatty", lambda: True)
    monkeypatch.setattr(sys, "stdin", stream)
    with pytest.raises(VerificationError, match="redirected operator pipe"):
        deployment.private_subscription(from_stdin=True)


def test_interactive_channel_ignores_redirected_data(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without the switch only the private prompt supplies independent authority."""
    monkeypatch.setattr(sys, "stdin", io.StringIO("untrusted observed state"))
    monkeypatch.setattr(deployment.getpass, "getpass", lambda *a: SUBSCRIPTION)
    assert deployment.private_subscription() == SUBSCRIPTION


@pytest.mark.parametrize("field", ["registries", "identitySettings", "app", "environment"])
@pytest.mark.parametrize("uppercase", [False, True])
def test_resource_id_case_compatibility(field: str, uppercase: bool) -> None:
    """Full identity/environment paths accept case alone without changing raw evidence."""
    state = observed()
    app = state["app"]
    if field == "app":
        entries = app["identity"]["userAssignedIdentities"]
        key = next(iter(entries))
        app["identity"]["userAssignedIdentities"] = {key.upper() if uppercase else key: {}}
    elif field == "environment":
        key = "environmentId" if "environmentId" in app["properties"] else "managedEnvironmentId"
        value = app["properties"][key]
        app["properties"][key] = value.upper() if uppercase else value
    else:
        entry = app["properties"]["configuration"][field][0]
        if uppercase:
            entry["identity"] = entry["identity"].upper()
    original = copy.deepcopy(state)
    assert validate_state(CONFIG, DIGEST, state, SUBSCRIPTION)
    assert state == original


@pytest.mark.parametrize("bad", [None, True, 0, [], {}, "", "suffix", "trailing", "space",
                                 "subscription", "group", "provider", "type", "name", "path"])
def test_registry_identity_fail_closed(bad: object) -> None:
    """Malformed IDs and any changed authority/path segment cannot pass."""
    state = observed()
    entry = state["app"]["properties"]["configuration"]["registries"][0]
    value = entry["identity"]
    parts = value.split("/")
    index = {"subscription": 2, "group": 4, "provider": 6, "type": 7, "name": 8}
    if isinstance(bad, str) and bad in index:
        parts[index[bad]] = "different"
        bad = "/".join(parts)
    elif bad == "suffix":
        bad = value.split("/providers/")[1]
    elif bad == "trailing":
        bad = value + "/"
    elif bad == "space":
        bad = " " + value
    elif bad == "path":
        bad = value + "/extra/name"
    entry["identity"] = bad
    with pytest.raises(VerificationError):
        validate_state(CONFIG, DIGEST, state, SUBSCRIPTION)


@pytest.mark.parametrize("value", [None, {"enabled": False}])
def test_disabled_dapr_observations(value: object) -> None:
    """Diagnosed null and explicit false are disabled; the fixture also covers absence."""
    state = observed()
    state["app"]["properties"]["configuration"]["dapr"] = value
    assert validate_state(CONFIG, DIGEST, state, SUBSCRIPTION)


@pytest.mark.parametrize("value", [True, False, 0, "", "false", [], {},
                                 {"enabled": True}, {"enabled": None}, {"enabled": 0}])
def test_unrecognized_dapr_fails_closed(value: object) -> None:
    """Falsey scalars and mappings without explicit boolean false cannot disable Dapr."""
    state = observed()
    state["app"]["properties"]["configuration"]["dapr"] = value
    with pytest.raises(VerificationError):
        validate_state(CONFIG, DIGEST, state, SUBSCRIPTION)


@pytest.mark.parametrize("server", ["upper", "suffix"])
def test_registry_hostname_stays_exact(server: str) -> None:
    """Resource-ID compatibility must not relax hostname or generic subset comparisons."""
    state = observed()
    entry = state["app"]["properties"]["configuration"]["registries"][0]
    original = entry["server"]
    entry["server"] = original.upper() if server == "upper" else original + ".example"
    assert not subset({"identity": "ABC"}, {"identity": "abc"})
    with pytest.raises(VerificationError):
        validate_state(CONFIG, DIGEST, state, SUBSCRIPTION)


def test_diagnosed_registry_and_dapr_combination() -> None:
    """The original short-circuit failure is repaired with both Azure differences present."""
    state = observed()
    settings = state["app"]["properties"]["configuration"]
    settings["registries"][0].update(identity=state["identity"]["id"].upper(),
                                      passwordSecretRef=None, username=None)
    settings["dapr"] = None
    assert validate_state(CONFIG, DIGEST, state, SUBSCRIPTION)


PROBE_ORDERS = list(permutations(range(3)))


@pytest.mark.parametrize("app_order", PROBE_ORDERS)
@pytest.mark.parametrize("revision_order", PROBE_ORDERS)
def test_probe_order_permutations(app_order: tuple[int, ...],
                                  revision_order: tuple[int, ...]) -> None:
    """Every independent app/revision probe order passes without mutating observations."""
    state = observed()
    templates = [state["app"]["properties"]["template"],
                 state["revisions"][0]["properties"]["template"]]
    for template, order in zip(templates, (app_order, revision_order), strict=True):
        probes = template["containers"][0]["probes"]
        template["containers"][0]["probes"] = [probes[i] for i in order]
    original = copy.deepcopy(state)
    assert validate_state(CONFIG, DIGEST, state, SUBSCRIPTION)
    assert state == original


@pytest.mark.parametrize("target", ["app", "revision", "both"])
@pytest.mark.parametrize("damage", [
    "missing-0", "missing-1", "missing-2", "duplicate-0", "duplicate-1", "duplicate-2",
    "fourth", "unknown", "entry-null", "entry-list", "entry-scalar", "entry-empty",
    "type-list", "type-absent", "type-null", "absent", "null", "mapping", "scalar",
    "path", "port", "scheme", "initialDelaySeconds", "periodSeconds", "timeoutSeconds",
    "failureThreshold", "successThreshold", "extra", "boolean-threshold",
])
def test_probe_order_security_boundaries(target: str, damage: str) -> None:
    """Order compatibility preserves exact probe cardinality, fields, values and types."""
    state = observed()
    templates = []
    if target in ("app", "both"):
        templates.append(state["app"]["properties"]["template"])
    if target in ("revision", "both"):
        templates.append(state["revisions"][0]["properties"]["template"])
    for template in templates:
        item = template["containers"][0]
        probes = item["probes"]
        if damage.startswith("missing-"):
            del probes[int(damage[-1])]
        elif damage.startswith("duplicate-"):
            index = int(damage[-1])
            probes[(index + 1) % 3] = copy.deepcopy(probes[index])
        elif damage == "fourth":
            probes.append({"type": "Unexpected"})
        elif damage == "unknown":
            probes[0]["type"] = "Unexpected"
        elif damage.startswith("entry-"):
            probes[0] = {"entry-null": None, "entry-list": [], "entry-scalar": "Startup",
                         "entry-empty": {}}[damage]
        elif damage == "type-list":
            probes[0]["type"] = []
        elif damage == "type-null":
            probes[0]["type"] = None
        elif damage == "type-absent":
            del probes[0]["type"]
        elif damage == "absent":
            del item["probes"]
        elif damage in ("null", "mapping", "scalar"):
            item["probes"] = {"null": None, "mapping": {}, "scalar": "Startup"}[damage]
        elif damage in ("path", "port", "scheme"):
            probes[0]["httpGet"][damage] = {"path": "/unapproved", "port": 9000,
                                           "scheme": "HTTPS"}[damage]
        elif damage == "extra":
            probes[0]["unexpected"] = "unapproved"
        elif damage == "boolean-threshold":
            probes[0]["successThreshold"] = True
        else:
            probes[0][damage] += 1
    original = copy.deepcopy(state)
    with pytest.raises(VerificationError):
        validate_state(CONFIG, DIGEST, state, SUBSCRIPTION)
    assert state == original


def test_probe_order_leaves_other_lists_positional() -> None:
    """Neither ordinary lists nor nested container/rule lists acquire set semantics."""
    first, second = {"name": "first"}, {"name": "second"}
    assert not subset([first, second], [second, first])
    assert not subset({"containers": [first, second]}, {"containers": [second, first]})
    assert not subset({"rules": [first, second]}, {"rules": [second, first]})


@pytest.mark.parametrize("difference", ["ephemeralStorage", "revisionSuffix", "cooldownPeriod",
                                      "pollingInterval", "all"])
@pytest.mark.parametrize("omit", [False, True])
def test_revision_default_projection_compatibility(difference: str, omit: bool) -> None:
    """Server-filled app defaults need not appear in the revision's material projection."""
    state = observed()
    app = state["app"]["properties"]["template"]
    revision = state["revisions"][0]["properties"]["template"]
    fields = [(("containers", 0, "resources", "ephemeralStorage"), "1Gi"),
              (("revisionSuffix",), ""), (("scale", "cooldownPeriod"), 300),
              (("scale", "pollingInterval"), 30)]
    for path, default in fields:
        if difference not in (path[-1], "all"):
            continue
        app_target, revision_target = app, revision
        for key in path[:-1]:
            app_target, revision_target = app_target[key], revision_target[key]
        app_target[path[-1]] = default
        if not omit:
            revision_target[path[-1]] = None
    # Match the diagnosed mixed projection exactly in the compound case.
    if difference == "all" and not omit:
        del revision["containers"][0]["resources"]["ephemeralStorage"]
    original = copy.deepcopy(state)
    assert validate_state(CONFIG, DIGEST, state, SUBSCRIPTION)
    assert state == original


@pytest.mark.parametrize("target", ["revision", "both"])
@pytest.mark.parametrize("path,value", [
    (("containers", 0, "image"), "unapproved:image"),
    (("containers", 0, "name"), "foreign"),
    (("containers", 0, "resources", "cpu"), 0.5),
    (("containers", 0, "resources", "cpu"), "0.25"),
    (("containers", 0, "resources", "memory"), "1Gi"),
    (("scale", "minReplicas"), 1),
    (("scale", "maxReplicas"), 3),
    (("scale", "rules", 0, "http", "metadata", "concurrentRequests"), "5"),
    (("scale", "rules", 0, "http", "metadata", "concurrentRequests"), 4),
    (("terminationGracePeriodSeconds",), 30),
    (("initContainers",), [{"name": "unapproved"}]),
    (("volumes",), [{"name": "unapproved"}]),
    (("serviceBinds",), [{"name": "unapproved"}]),
    (("containers", 0, "env"), [{"name": "UNAPPROVED", "value": "synthetic"}]),
    (("containers", 0, "command"), ["unapproved"]),
    (("containers", 0, "args"), ["unapproved"]),
    (("containers", 0, "volumeMounts"), [{"volumeName": "unapproved"}]),
])
def test_revision_material_contract_drift(target: str, path: tuple, value: object) -> None:
    """Revision drift fails even when both projections agree on unapproved material values."""
    state = observed()
    templates = [state["revisions"][0]["properties"]["template"]]
    if target == "both":
        templates.append(state["app"]["properties"]["template"])
    for template in templates:
        item = template
        for key in path[:-1]:
            item = item[key]
        item[path[-1]] = copy.deepcopy(value)
    original = copy.deepcopy(state)
    with pytest.raises(VerificationError):
        validate_state(CONFIG, DIGEST, state, SUBSCRIPTION)
    assert state == original


@pytest.mark.parametrize("field,value", [
    ("name", "other"), ("healthState", "Unhealthy"), ("runningState", "ScaledToZero"),
    ("runningState", None), ("trafficWeight", 0), ("provisioningState", "Failed"),
    ("active", False), ("ambiguous", True),
])
def test_revision_material_repair_preserves_state_gate(field: str, value: object) -> None:
    """Material projection compatibility cannot relax any of the six revision-state operands."""
    state = observed()
    revision = state["revisions"][0]
    if field == "ambiguous":
        state["revisions"].append(copy.deepcopy(revision))
    elif field == "name":
        revision["name"] = CONFIG.names["app"] + "--other"
    else:
        revision["properties"][field] = value
    with pytest.raises(VerificationError, match="Active revision is unhealthy"):
        validate_state(CONFIG, DIGEST, state, SUBSCRIPTION)
