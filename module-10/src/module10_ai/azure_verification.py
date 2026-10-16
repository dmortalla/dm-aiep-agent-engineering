"""Fail-closed interpretation of untrusted Azure observations; no cloud authority."""

import re
from datetime import UTC, datetime

from module10_ai.azure_contract import (
    ACR_PULL,
    REGION,
    TAGS,
    AzureConfig,
    container,
    ingress,
    scale,
)


class VerificationError(ValueError):
    """Fixed actionable failure without reflecting cloud identifiers or raw responses."""


def require(condition: bool, message: str) -> None:
    """Fail closed using application-controlled diagnostic text."""
    if not condition:
        raise VerificationError(message)


def subset(actual: object, expected: object) -> bool:
    """Match required ARM fields while allowing server-populated read-only defaults."""
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and subset(actual[key], value) for key, value in expected.items())
    if isinstance(expected, list):
        return isinstance(actual, list) and len(actual) == len(expected) and all(
            subset(a, b) for a, b in zip(actual, expected, strict=True))
    return type(actual) is type(expected) and actual == expected


def validate_state(config: AzureConfig, digest: str, state: dict) -> str:
    """Validate a fresh complete cloud snapshot and return only its safe FQDN.

    Args:
        config: Approved naming and ingress contract.
        digest: Operator-reviewed registry manifest identity.
        state: Raw read-only observations held only in memory.

    Returns:
        Validated Container Apps hostname for bounded HTTPS acceptance.

    Raises:
        VerificationError: Any resource, security, revision or cost contract differs.
    """
    n = config.names
    image = config.image(digest)
    try:
        kinds = {"registry": "Microsoft.ContainerRegistry/registries",
                 "workspace": "Microsoft.OperationalInsights/workspaces",
                 "environment": "Microsoft.App/managedEnvironments",
                 "app": "Microsoft.App/containerApps",
                 "identity": "Microsoft.ManagedIdentity/userAssignedIdentities"}
        expected = {(n[key], kind.lower()) for key, kind in kinds.items()}
        observed = {(r["name"], r["type"].lower()) for r in state["inventory"]
                    if r["type"].lower() != "microsoft.authorization/roleassignments"}
        require(observed == expected and len(state["inventory"]) <= 6,
                "Resource inventory differs; inspect the dedicated Module 10 group.")
        group = state["group"]
        require(group["name"] == n["group"] and group["location"] == REGION
                and subset(group["tags"], TAGS), "Resource-group ownership/region differs.")
        prefix = group["id"] + "/providers/"
        for key, kind in kinds.items():
            item = state[key]
            require(item["id"].lower() == (prefix + kind + "/" + n[key]).lower()
                    and item["name"] == n[key] and item["location"] == REGION
                    and subset(item["tags"], TAGS), "Resource ownership/region/tags differ.")
        registry = state["registry"]
        require(registry["sku"]["name"] == "Basic"
                and registry["properties"]["adminUserEnabled"] is False
                and not registry["properties"].get("anonymousPullEnabled", False)
                and registry["properties"]["provisioningState"] == "Succeeded"
                and registry["properties"]["loginServer"] == n["registry"] + ".azurecr.io",
                "ACR security/tier/state differs.")
        require(state["arm_auth"] == {"status": "enabled"},
                "ACR must permit ARM audience authentication for managed identity.")
        require(state["manifest"]["digest"] == digest,
                "ACR manifest identity differs from the reviewed digest.")
        workspace = state["workspace"]["properties"]
        require(workspace["sku"]["name"] == "PerGB2018"
                and workspace["retentionInDays"] == 30
                and workspace["workspaceCapping"]["dailyQuotaGb"] == 0.1
                and workspace["provisioningState"] == "Succeeded",
                "Log Analytics retention/ingestion/state differs.")
        environment = state["environment"]["properties"]
        require(environment["provisioningState"] == "Succeeded"
                and subset(environment["workloadProfiles"], [{"name": "Consumption",
                    "workloadProfileType": "Consumption"}])
                and not environment.get("vnetConfiguration")
                and not environment.get("zoneRedundant", False),
                "Environment must use the approved minimal Consumption configuration.")
        logs = environment["appLogsConfiguration"]
        require(logs["destination"] == "log-analytics"
                and logs["logAnalyticsConfiguration"]["customerId"] == workspace["customerId"],
                "Environment logs are not connected to the owned workspace.")
        identity_id = state["identity"]["id"]
        principal = state["identity"]["properties"]["principalId"]
        roles = state["roles"]
        require(len(roles) == 1 and roles[0]["principalId"] == principal
                and roles[0]["scope"].lower() == registry["id"].lower()
                and roles[0]["roleDefinitionId"].endswith("/" + ACR_PULL),
                "Pull identity must have only registry-scoped AcrPull; inspect inherited roles.")
        app = state["app"]
        require(app["identity"]["type"] == "UserAssigned"
                and set(app["identity"]["userAssignedIdentities"]) == {identity_id},
                "Container App identity differs.")
        props = app["properties"]
        require(props.get("environmentId", props.get("managedEnvironmentId"))
                == state["environment"]["id"] and props["workloadProfileName"] == "Consumption"
                and props["provisioningState"] == "Succeeded", "App environment/state differs.")
        settings = props["configuration"]
        require(settings["activeRevisionsMode"] == "Single"
                and settings["maxInactiveRevisions"] == 2
                and subset(settings["ingress"], ingress(config.reviewer_cidr))
                and subset(settings["registries"], [{"server": n["registry"] + ".azurecr.io",
                                                      "identity": identity_id}])
                and subset(settings["identitySettings"], [{"identity": identity_id,
                                                           "lifecycle": "None"}])
                and not settings.get("secrets") and not settings.get("dapr", {}).get("enabled"),
                "App ingress/identity/revisions/security differs.")
        require(not settings["ingress"].get("additionalPortMappings")
                and not settings["ingress"].get("customDomains"), "Unexpected ingress exposure.")
        require(all(not r.get("username") and not r.get("passwordSecretRef")
                    for r in settings["registries"]),
                "Registry password authentication is forbidden.")
        template = props["template"]
        expected_container = container(image)
        # Azure may return 0.25 as a float (the contract uses a float too).
        require(subset(template["containers"], [expected_container])
                and subset(template["scale"], scale())
                and template["terminationGracePeriodSeconds"] == 15
                and not template.get("initContainers") and not template.get("volumes")
                and not template.get("serviceBinds"), "App compute/probes/scaling/image differs.")
        for item in template["containers"]:
            require(not any(item.get(key) for key in
                            ("env", "command", "args", "volumeMounts")),
                    "Runtime overrides are forbidden; deploy the accepted Docker workload.")
        revision = props["latestRevisionName"]
        require(re.fullmatch(re.escape(n["app"]) + r"--[a-z0-9-]{1,64}", revision) is not None
                and props["latestReadyRevisionName"] == revision,
                "Latest revision is not the ready revision.")
        revisions = state["revisions"]
        active = [r for r in revisions if r["properties"]["active"]]
        require(len(active) == 1 and active[0]["name"] == revision
                and active[0]["properties"]["healthState"] == "Healthy"
                and active[0]["properties"]["runningState"] == "Running"
                and active[0]["properties"]["trafficWeight"] == 100
                and active[0]["properties"]["provisioningState"] == "Provisioned"
                and subset(active[0]["properties"]["template"], template),
                "Active revision is unhealthy, ambiguous or differs from the app template.")
        fqdn = settings["ingress"]["fqdn"]
        require(isinstance(fqdn, str) and re.fullmatch(
            re.escape(n["app"]) + r"\.[a-z0-9-]+\.southcentralus\.azurecontainerapps\.io", fqdn
        ) is not None, "Unexpected Azure hostname; HTTP verification blocked.")
        return fqdn
    except (KeyError, TypeError, AttributeError) as exc:
        raise VerificationError(
            "Incomplete Azure observation; inspect CLI/API compatibility.") from exc


def cloud_evidence(config: AzureConfig, digest: str, revision: str) -> dict:
    """Construct only minimized metadata after the trusted collector verifies every gate."""
    return {"schema_version": 1, "classification": "AZURE CLOUD / DETERMINISTIC INFERENCE",
            "verified_at": datetime.now(UTC).isoformat(), "deployment_authorized": False,
            "region": REGION, "image": config.image(digest), "revision": revision,
            "checks": {name: "passed" for name in (
                "inventory", "configuration", "registry_digest", "revision_health", "https_health",
                "deterministic_inference", "bounded_rejection", "azure_monitor_receipt")},
            "replicas": {"minimum": 0, "maximum": 2},
            "limits": ["point-in-time acceptance; no SLA or load-test claim",
                       "no live AI provider; queue/cache remain process-local",
                       "operator must separately establish tested-artifact provenance",
                       "C-026/C-027 final acceptance deferred"],
            "teardown": "human-controlled deletion of the validated dedicated resource group"}
