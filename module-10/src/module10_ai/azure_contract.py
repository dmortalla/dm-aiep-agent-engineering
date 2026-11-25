"""Data-only Azure deployment contract; never executes privileged operations."""

import hashlib
import ipaddress
import json
import re
from dataclasses import dataclass

REGION = "southcentralus"
ACR_PULL = "7f951dda-4ed3-4680-a7ca-43fe172d538d"
TAGS = {"module": "10", "purpose": "deterministic-acceptance", "managed-by": "human"}
REVIEWER_PORT = 8501


def footprint() -> dict[str, int]:
    """Return the human-approved footprint; counts are a contract, not Azure inventory.

    The approved S11-C01 amendment adds exactly one reviewer Container App
    reusing the existing group, environment, registry, workspace and
    registry-scoped pull identity; it adds no new identity or assignment.
    """
    return {"resource_groups": 1, "registries": 1, "workspaces": 1, "environments": 1,
            "container_apps": 1, "reviewer_container_apps": 1,
            "user_assigned_identities": 1, "registry_scoped_acrpull_assignments": 1}


@dataclass(frozen=True, slots=True)
class AzureConfig:
    """Account-independent names and a restricted reviewer ingress address.

    Args:
        suffix: Human-selected random lowercase letters/digits, never account data.
        reviewer_cidr: One public IPv4 reviewer address with /32 prefix.

    Raises:
        ValueError: Naming or ingress violates the frozen deployment contract.
    """

    suffix: str
    reviewer_cidr: str

    def __post_init__(self) -> None:
        """Reject shell syntax, account-shaped values and broad/public ingress."""
        if type(self.suffix) is not str or not re.fullmatch(r"[a-z][a-z0-9]{5,11}", self.suffix):
            raise ValueError("Use 6–12 lowercase random letters/digits starting with a letter.")
        if type(self.reviewer_cidr) is not str or not self.reviewer_cidr.endswith("/32"):
            raise ValueError("Use one public reviewer IPv4 address with explicit /32 prefix.")
        try:
            network = ipaddress.IPv4Network(self.reviewer_cidr, strict=True)
        except (ValueError, TypeError) as exc:
            raise ValueError("Use one public reviewer IPv4 address with /32 prefix.") from exc
        if network.prefixlen != 32 or not network.network_address.is_global:
            raise ValueError("Ingress requires one public reviewer IPv4 address with /32 prefix.")

    @property
    def names(self) -> dict[str, str]:
        """Return deterministic resource names without account identifiers."""
        return {"group": f"rg-module10-{self.suffix}", "registry": f"m10acr{self.suffix}",
                "workspace": f"m10-logs-{self.suffix}", "environment": f"m10-env-{self.suffix}",
                "app": f"m10-api-{self.suffix}", "reviewer": f"m10-ui-{self.suffix}",
                "identity": f"m10-pull-{self.suffix}"}

    def image(self, digest: str) -> str:
        """Require a registry manifest digest; tags and Docker IDs are not provenance."""
        if type(digest) is not str or not re.fullmatch(r"sha256:[a-f0-9]{64}", digest):
            raise ValueError("Require the independently reviewed ACR manifest SHA-256 digest.")
        return f"{self.names['registry']}.azurecr.io/module10-ai@{digest}"

    def reviewer_image(self, digest: str) -> str:
        """Require a registry manifest digest for the separate reviewer unit."""
        if type(digest) is not str or not re.fullmatch(r"sha256:[a-f0-9]{64}", digest):
            raise ValueError("Require the independently reviewed ACR manifest SHA-256 digest.")
        return f"{self.names['registry']}.azurecr.io/module10-ai-reviewer@{digest}"


def container(image: str) -> dict:
    """Define the unchanged accepted Docker command, minimal compute and HTTP probes."""
    return {"name": "api", "image": image, "resources": {"cpu": 0.25, "memory": "0.5Gi"},
            "probes": [
                {"type": kind, "httpGet": {"path": path, "port": 8000, "scheme": "HTTP"},
                 "initialDelaySeconds": 5, "periodSeconds": 10, "timeoutSeconds": 2,
                 "failureThreshold": failures, "successThreshold": 1}
                for kind, path, failures in (
                    ("Startup", "/health/ready", 10), ("Readiness", "/health/ready", 3),
                    ("Liveness", "/health/live", 3))]}


def reviewer_container(image: str) -> dict:
    """Define the approved separate reviewer unit: minimal compute and Streamlit probes.

    Streamlit's standard health endpoint serves the sole probe path; there is no
    command, environment, secret, volume or live-provider configuration.
    """
    return {"name": "reviewer", "image": image, "resources": {"cpu": 0.5, "memory": "1Gi"},
            "probes": [
                {"type": kind, "httpGet": {"path": "/_stcore/health", "port": REVIEWER_PORT,
                                           "scheme": "HTTP"},
                 "initialDelaySeconds": 10, "periodSeconds": 10, "timeoutSeconds": 2,
                 "failureThreshold": failures, "successThreshold": 1}
                for kind, failures in (("Startup", 10), ("Readiness", 3), ("Liveness", 3))]}


def scale() -> dict:
    """Bound replicas and use the managed HTTP activation/load-distribution boundary."""
    return {"minReplicas": 0, "maxReplicas": 2, "rules": [
        {"name": "http", "http": {"metadata": {"concurrentRequests": "4"}}}]}


def reviewer_scale() -> dict:
    """Bound the reviewer unit to one replica for the initial demonstration window.

    Minimum one keeps the personal human demonstration reachable without a
    cold start; scale-to-zero afterwards is a later human cost decision.
    """
    return {"minReplicas": 1, "maxReplicas": 1, "rules": [
        {"name": "http", "http": {"metadata": {"concurrentRequests": "128"}}}]}


def ingress(cidr: str) -> dict:
    """Require HTTPS and an IP allow rule because the accepted API has no authentication."""
    return {"external": True, "targetPort": 8000, "transport": "http", "allowInsecure": False,
            "traffic": [{"latestRevision": True, "weight": 100}],
            "ipSecurityRestrictions": [{"name": "reviewer", "action": "Allow",
                                        "ipAddressRange": cidr}]}


def reviewer_ingress(cidr: str) -> dict:
    """Require the same restricted HTTPS boundary for the reviewer console.

    The approved HTTP transport carries Streamlit's WebSocket traffic through
    the managed ingress; only the reviewer /32 address may reach the unit.
    """
    return {"external": True, "targetPort": REVIEWER_PORT, "transport": "http",
            "allowInsecure": False, "traffic": [{"latestRevision": True, "weight": 100}],
            "ipSecurityRestrictions": [{"name": "reviewer", "action": "Allow",
                                        "ipAddressRange": cidr}]}


def publication(candidate: dict, manifest_bytes: bytes) -> dict:
    """Bind a single-platform registry manifest to tested Docker content, without authority.

    Args:
        candidate: Untrusted Story 10.8 validation metadata reviewed by the operator.
        manifest_bytes: Exact raw registry manifest bytes, not reserialized JSON.

    Returns:
        Digest/content binding data; authenticity still requires independent operator review.

    Raises:
        ValueError: Validation stages, clean source, platform or manifest binding differs.
    """
    try:
        if (candidate["classification"] != "LOCAL CI/CD CONTRACT"
                or candidate["source_clean"] is not True
                or candidate["deployment_authorized"] is not False
                or not re.fullmatch(r"[a-f0-9]{40}", candidate["source_commit"])
                or not re.fullmatch(r"sha256:[a-f0-9]{64}", candidate["image_id"])
                or candidate["build"] != "passed" or candidate["container_acceptance"] != "passed"
                or candidate["gates"] != {"ruff": "passed", "pytest": "passed",
                    "compileall": "passed",
                    "security_contract": "passed/targeted-not-vulnerability-audit"}):
            raise ValueError("Require a clean, reviewed successful pipeline candidate.")
        if type(manifest_bytes) is not bytes or len(manifest_bytes) > 65536:
            raise ValueError("Require at most 64 KiB of exact registry manifest bytes.")
        manifest = json.loads(manifest_bytes)
        if (manifest["schemaVersion"] != 2 or manifest["mediaType"] not in (
                "application/vnd.docker.distribution.manifest.v2+json",
                "application/vnd.oci.image.manifest.v1+json")
                or manifest["config"]["digest"] != candidate["image_id"]
                or not manifest["layers"] or "manifests" in manifest):
            raise ValueError("Require a single-platform manifest bound to the tested Docker ID.")
        return {"source_commit": candidate["source_commit"], "image_id": candidate["image_id"],
                "registry_manifest_digest": "sha256:" + hashlib.sha256(manifest_bytes).hexdigest(),
                "classification": "PUBLICATION BINDING CONTRACT / OPERATOR REVIEW REQUIRED",
                "deployment_authorized": False}
    except (KeyError, TypeError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Malformed publication metadata; inspect candidate/manifest.") from exc


def arm_template(config: AzureConfig, digest: str | None = None,
                 reviewer_digest: str | None = None) -> dict:
    """Render incremental resource-group ARM templates without executing Azure.

    Args:
        config: Strict approved configuration.
        digest: None renders foundation; a reviewed digest renders the API unit.
        reviewer_digest: Required with digest; renders the separate reviewer unit
            in the same incremental phase, reusing the environment, registry,
            workspace and registry-scoped pull identity without new privileges.

    Returns:
        ARM JSON with server-side identity/key references and no secret outputs.

    Raises:
        ValueError: The app phase lacks either reviewed manifest digest.
    """
    n = config.names

    def rid(kind: str, name: str) -> str:
        return f"[resourceId('{kind}', '{name}')]"

    registry_id = rid("Microsoft.ContainerRegistry/registries", n["registry"])
    identity_id = rid("Microsoft.ManagedIdentity/userAssignedIdentities", n["identity"])
    workspace_id = rid("Microsoft.OperationalInsights/workspaces", n["workspace"])
    resources = []
    if digest is None:
        if reviewer_digest is not None:
            raise ValueError("Foundation rendering does not accept a reviewer digest.")
        resources = [
            {"type": "Microsoft.ContainerRegistry/registries", "apiVersion": "2023-07-01",
             "name": n["registry"], "location": REGION, "tags": TAGS,
             "sku": {"name": "Basic"}, "properties": {"adminUserEnabled": False,
                 "anonymousPullEnabled": False, "publicNetworkAccess": "Enabled"}},
            {"type": "Microsoft.OperationalInsights/workspaces", "apiVersion": "2023-09-01",
             "name": n["workspace"], "location": REGION, "tags": TAGS,
             "properties": {"sku": {"name": "PerGB2018"}, "retentionInDays": 30,
                            "workspaceCapping": {"dailyQuotaGb": 0.1}}},
            {"type": "Microsoft.ManagedIdentity/userAssignedIdentities",
             "apiVersion": "2023-01-31", "name": n["identity"], "location": REGION,
             "tags": TAGS, "properties": {}},
            {"type": "Microsoft.Authorization/roleAssignments", "apiVersion": "2022-04-01",
             "name": f"[guid(resourceId('Microsoft.ContainerRegistry/registries', "
                     f"'{n['registry']}'), '{n['identity']}', '{ACR_PULL}')]",
             "scope": registry_id, "dependsOn": [registry_id, identity_id],
             "properties": {
                 "roleDefinitionId": f"[subscriptionResourceId('Microsoft.Authorization/"
                                     f"roleDefinitions', '{ACR_PULL}')]",
                 "principalId": f"[reference(resourceId('Microsoft.ManagedIdentity/"
                                f"userAssignedIdentities', '{n['identity']}'), "
                                "'2023-01-31').principalId]", "principalType": "ServicePrincipal"}},
            {"type": "Microsoft.App/managedEnvironments", "apiVersion": "2025-01-01",
             "name": n["environment"], "location": REGION, "tags": TAGS,
             "dependsOn": [workspace_id], "properties": {
                 "workloadProfiles": [{"name": "Consumption",
                                       "workloadProfileType": "Consumption"}],
                 "appLogsConfiguration": {"destination": "log-analytics",
                     "logAnalyticsConfiguration": {
                         "customerId": f"[reference(resourceId('Microsoft.OperationalInsights/"
                                       f"workspaces', '{n['workspace']}'), "
                                       "'2023-09-01').customerId]",
                         "sharedKey": f"[listKeys(resourceId('Microsoft.OperationalInsights/"
                                      f"workspaces', '{n['workspace']}'), "
                                      "'2023-09-01').primarySharedKey]"}}}},
        ]
    else:
        if reviewer_digest is None:
            raise ValueError("App rendering requires the reviewed reviewer manifest digest.")
        resources = [{"type": "Microsoft.App/containerApps", "apiVersion": "2025-01-01",
            "name": n["app"], "location": REGION, "tags": TAGS,
            "identity": {"type": "UserAssigned", "userAssignedIdentities": {identity_id: {}}},
            "properties": {
                "environmentId": rid("Microsoft.App/managedEnvironments", n["environment"]),
                "workloadProfileName": "Consumption",
                "configuration": {"activeRevisionsMode": "Single", "maxInactiveRevisions": 2,
                    "ingress": ingress(config.reviewer_cidr),
                    "identitySettings": [{"identity": identity_id, "lifecycle": "None"}],
                    "registries": [{"server": n["registry"] + ".azurecr.io",
                                    "identity": identity_id}]},
                "template": {"containers": [container(config.image(digest))], "scale": scale(),
                             "terminationGracePeriodSeconds": 15}}},
            {"type": "Microsoft.App/containerApps", "apiVersion": "2025-01-01",
             "name": n["reviewer"], "location": REGION, "tags": TAGS,
             "identity": {"type": "UserAssigned", "userAssignedIdentities": {identity_id: {}}},
             "properties": {
                 "environmentId": rid("Microsoft.App/managedEnvironments", n["environment"]),
                 "workloadProfileName": "Consumption",
                 "configuration": {"activeRevisionsMode": "Single", "maxInactiveRevisions": 2,
                     "ingress": reviewer_ingress(config.reviewer_cidr),
                     "identitySettings": [{"identity": identity_id, "lifecycle": "None"}],
                     "registries": [{"server": n["registry"] + ".azurecr.io",
                                     "identity": identity_id}]},
                 "template": {"containers": [reviewer_container(config.reviewer_image(
                     reviewer_digest))], "scale": reviewer_scale(),
                     "terminationGracePeriodSeconds": 15}}}]
    return {"$schema": "https://schema.management.azure.com/schemas/2019-04-01/"
                       "deploymentTemplate.json#", "contentVersion": "1.0.0.0",
            "resources": resources, "outputs": {}}
