"""Inert MCP SDK discovery translation (REQ-MCP-002/003, REQ-TECH-003).

This boundary accepts already-received JSON, not a transport or a session. The
deliberately restricted schema profile has no references, regexes, executable
configuration, or authority semantics. No registry or permission state is held.
"""

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from mcp.types import Implementation, ListToolsResult
from pydantic import ValidationError

from harness_engineering.errors import ContractValidationError

MAX_DISCOVERY_BYTES = 65_536
MAX_SERVICE_BYTES = 4096
MAX_CAPABILITIES = 100
MAX_SCHEMA_BYTES = 16_384
MAX_DEPTH = 16
MAX_NODES = 4096


class DiscoveryEventKind(StrEnum):
    """Finite, local event vocabulary; no remote text enters audit records."""

    RECEIVED = "received"
    VALIDATED = "validated"
    TRANSLATED = "translated"
    REJECTED = "rejected"


class DiscoveryFailure(StrEnum):
    """Bounded failure codes without remote names, payloads, or errors."""

    PAYLOAD = "payload"
    STRUCTURE = "structure"
    SCHEMA = "schema"
    DUPLICATE = "duplicate"


@dataclass(frozen=True, slots=True)
class DiscoveryAuditEvent:
    """Inert operation-local audit evidence, never an authorization decision."""

    kind: DiscoveryEventKind
    capability_count: int = 0
    failure: DiscoveryFailure | None = None


class MCPDiscoveryError(ContractValidationError):
    """Rejected discovery, with bounded audit and no partial candidate snapshot."""

    def __init__(self, failure: DiscoveryFailure) -> None:
        """Create a sanitized application error from a local finite code."""
        super().__init__(f"MCP discovery rejected: {failure.value}.")
        self.audit = (
            DiscoveryAuditEvent(DiscoveryEventKind.RECEIVED),
            DiscoveryAuditEvent(DiscoveryEventKind.REJECTED, failure=failure),
        )


@dataclass(frozen=True, slots=True)
class MCPServiceMetadata:
    """Untrusted advertised service identity; not authenticated server identity."""

    name: str
    version: str


@dataclass(frozen=True, slots=True)
class MCPCapabilityCandidate:
    """Immutable data distinct from CapabilityDefinition and executable bindings.

    Schemas are canonical JSON strings to avoid nested mutable dictionaries.
    Names are remote names, never application capability registration keys.
    """

    service: MCPServiceMetadata
    remote_name: str
    description: str | None
    input_schema_json: str
    output_schema_json: str | None
    trust: Literal["untrusted_mcp"] = "untrusted_mcp"

    @property
    def grants_authority(self) -> bool:
        """Return False regardless of schema validity or advertised identity."""
        return False


@dataclass(frozen=True, slots=True)
class MCPDiscoverySnapshot:
    """Atomic, bounded discovery result; no partial results survive rejection."""

    service: MCPServiceMetadata
    candidates: tuple[MCPCapabilityCandidate, ...]
    audit: tuple[DiscoveryAuditEvent, ...]


def _reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject duplicate JSON keys, including conflicting nested schema keys."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise MCPDiscoveryError(DiscoveryFailure.DUPLICATE)
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    """Reject non-finite JSON constants without incorporating their text."""
    raise MCPDiscoveryError(DiscoveryFailure.PAYLOAD)


def _decode(payload: bytes, limit: int) -> dict[str, object]:
    """Decode finite UTF-8 JSON after byte, nesting, and structural bounds."""
    if type(payload) is not bytes or len(payload) > limit:
        raise MCPDiscoveryError(DiscoveryFailure.PAYLOAD)
    # Bound nesting before the JSON decoder allocates recursive containers.
    depth = 0
    quoted = escaped = False
    for char in payload:
        if quoted:
            if escaped:
                escaped = False
            elif char == 92:
                escaped = True
            elif char == 34:
                quoted = False
        elif char == 34:
            quoted = True
        elif char in (91, 123):
            depth += 1
            if depth > MAX_DEPTH:
                raise MCPDiscoveryError(DiscoveryFailure.PAYLOAD)
        elif char in (93, 125):
            depth -= 1
    try:
        decoded = json.loads(
            payload, object_pairs_hook=_reject_duplicate_pairs, parse_constant=_reject_constant
        )
    except (ValueError, UnicodeError) as exc:
        raise MCPDiscoveryError(DiscoveryFailure.PAYLOAD) from exc
    pending = [decoded]
    nodes = 0
    while pending:
        value = pending.pop()
        nodes += 1
        if nodes > MAX_NODES:
            raise MCPDiscoveryError(DiscoveryFailure.PAYLOAD)
        if type(value) is dict:
            pending.extend(value.values())
        elif type(value) is list:
            pending.extend(value)
        elif type(value) is float and not (-float("inf") < value < float("inf")):
            raise MCPDiscoveryError(DiscoveryFailure.PAYLOAD)
    if type(decoded) is not dict:
        raise MCPDiscoveryError(DiscoveryFailure.STRUCTURE)
    return decoded


def _text(value: object, limit: int, *, optional: bool = False) -> None:
    """Validate bounded text without normalization or executing its contents."""
    if optional and value is None:
        return
    if type(value) is not str or not 1 <= len(value) <= limit:
        raise MCPDiscoveryError(DiscoveryFailure.STRUCTURE)
    if any(ord(char) < 32 for char in value):
        raise MCPDiscoveryError(DiscoveryFailure.STRUCTURE)


def _schema(value: object) -> str:
    """Validate a bounded closed-object JSON Schema subset without resolution."""
    if type(value) is not dict:
        raise MCPDiscoveryError(DiscoveryFailure.SCHEMA)
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    if len(encoded.encode()) > MAX_SCHEMA_BYTES:
        raise MCPDiscoveryError(DiscoveryFailure.SCHEMA)
    pending = [value]
    while pending:
        node = pending.pop()
        if type(node) is not dict:
            raise MCPDiscoveryError(DiscoveryFailure.SCHEMA)
        kind = node.get("type")
        common = {"type", "description", "title"}
        if type(kind) is not str:
            raise MCPDiscoveryError(DiscoveryFailure.SCHEMA)
        if kind == "object":
            allowed = common | {"properties", "required", "additionalProperties"}
            props = node.get("properties")
            required = node.get("required", [])
            if (
                type(props) is not dict
                or len(props) > 32
                or node.get("additionalProperties") is not False
                or type(required) is not list
                or any(type(key) is not str for key in required)
                or len(required) != len(set(required))
                or not set(required).issubset(props)
            ):
                raise MCPDiscoveryError(DiscoveryFailure.SCHEMA)
            for key in props:
                _text(key, 128)
            pending.extend(props.values())
        elif kind == "array":
            allowed = common | {"items", "minItems", "maxItems"}
            maximum = node.get("maxItems")
            if type(maximum) is not int or not 0 <= maximum <= 100:
                raise MCPDiscoveryError(DiscoveryFailure.SCHEMA)
            pending.append(node.get("items"))
        elif kind == "string":
            allowed = common | {"minLength", "maxLength", "enum"}
            maximum = node.get("maxLength")
            if type(maximum) is not int or not 0 <= maximum <= 4096:
                raise MCPDiscoveryError(DiscoveryFailure.SCHEMA)
        elif kind in {"integer", "number", "boolean", "null"}:
            allowed = common | {"minimum", "maximum", "enum"}
        else:
            raise MCPDiscoveryError(DiscoveryFailure.SCHEMA)
        if set(node) - allowed:
            raise MCPDiscoveryError(DiscoveryFailure.SCHEMA)
        for key in ("description", "title"):
            if key in node:
                _text(node[key], 2000)
    if value.get("type") != "object":
        raise MCPDiscoveryError(DiscoveryFailure.SCHEMA)
    try:
        Draft202012Validator.check_schema(value)
    except SchemaError as exc:
        raise MCPDiscoveryError(DiscoveryFailure.SCHEMA) from exc
    return encoded


def translate_discovery(service_json: bytes, discovery_json: bytes) -> MCPDiscoverySnapshot:
    """Translate untrusted MCP wire metadata into inert application candidates.

    Args:
        service_json: Already-received advertised Implementation JSON, not identity proof.
        discovery_json: One complete ListToolsResult page of already-received JSON.

    Returns:
        An atomic immutable snapshot sorted by exact remote name, with local audit.

    Raises:
        MCPDiscoveryError: On malformed, duplicate, oversized, paginated, or
            unsupported metadata/schema. No retry, registration, or invocation occurs.
    """
    service = _decode(service_json, MAX_SERVICE_BYTES)
    data = _decode(discovery_json, MAX_DISCOVERY_BYTES)
    if set(service) - {"name", "version"} or not {"name", "version"}.issubset(service):
        raise MCPDiscoveryError(DiscoveryFailure.STRUCTURE)
    _text(service["name"], 128)
    _text(service["version"], 128)
    if set(data) - {"tools", "nextCursor", "resultType"}:
        raise MCPDiscoveryError(DiscoveryFailure.STRUCTURE)
    if data.get("nextCursor") is not None or data.get("resultType", "complete") != "complete":
        raise MCPDiscoveryError(DiscoveryFailure.STRUCTURE)
    tools = data.get("tools")
    if type(tools) is not list or len(tools) > MAX_CAPABILITIES:
        raise MCPDiscoveryError(DiscoveryFailure.STRUCTURE)
    names: set[str] = set()
    schemas: dict[str, tuple[str, str | None]] = {}
    for tool in tools:
        if type(tool) is not dict or set(tool) - {
            "name",
            "description",
            "inputSchema",
            "outputSchema",
        }:
            raise MCPDiscoveryError(DiscoveryFailure.STRUCTURE)
        _text(tool.get("name"), 128)
        _text(tool.get("description"), 2000, optional=True)
        name = tool["name"]
        if name != name.strip() or any(
            char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._:-"
            for char in name
        ):
            raise MCPDiscoveryError(DiscoveryFailure.STRUCTURE)
        if name in names:
            raise MCPDiscoveryError(DiscoveryFailure.DUPLICATE)
        names.add(name)
        schemas[name] = (
            _schema(tool.get("inputSchema")),
            _schema(tool["outputSchema"]) if tool.get("outputSchema") is not None else None,
        )
    try:
        sdk_service = Implementation.model_validate(service, strict=True)
        sdk_result = ListToolsResult.model_validate(data, strict=True)
    except ValidationError as exc:
        raise MCPDiscoveryError(DiscoveryFailure.STRUCTURE) from exc
    metadata = MCPServiceMetadata(sdk_service.name, sdk_service.version)
    candidates = tuple(
        MCPCapabilityCandidate(metadata, tool.name, tool.description, *schemas[tool.name])
        for tool in sorted(sdk_result.tools, key=lambda item: item.name)
    )
    return MCPDiscoverySnapshot(
        metadata,
        candidates,
        (
            DiscoveryAuditEvent(DiscoveryEventKind.RECEIVED),
            DiscoveryAuditEvent(DiscoveryEventKind.VALIDATED, len(candidates)),
            DiscoveryAuditEvent(DiscoveryEventKind.TRANSLATED, len(candidates)),
        ),
    )
