"""Secret-minimizing structured local logging helpers."""

import json
import logging
import re
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from pydantic import SecretStr

_REDACTED = "[REDACTED]"
_UNSUPPORTED = "[UNSUPPORTED_TYPE]"
_SENSITIVE_KEY_MARKERS = (
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "credentials",
    "password",
    "passwd",
    "pwd",
    "passphrase",
    "private_key",
    "access_key",
    "ssh_key",
    "secret",
    "token",
    "auth",
    "cookie",
    "session",
    "signature",
    "jwt",
    "dsn",
    "connection_string",
)
_BEARER_PATTERN = re.compile(r"(?i)\bbearer\s+\S+")
_KEY_SEPARATOR_PATTERN = re.compile(r"[\s.\-]+")
_CAMEL_BOUNDARY_PATTERN = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_SENSITIVE_COMPOUNDS = (
    "accesstoken",
    "refreshtoken",
    "clientsecret",
    "secretkey",
    "dbpassword",
)


def _normalize_key(key: str) -> str:
    """Normalize a structured logging key for credential classification.

    Args:
        key: Structured field key.

    Returns:
        Lowercase underscore-separated key.
    """
    separated = _CAMEL_BOUNDARY_PATTERN.sub("_", key.strip())
    return _KEY_SEPARATOR_PATTERN.sub("_", separated.lower())


def _is_sensitive_key(key: object) -> bool:
    """Return whether a structured field name denotes privileged data.

    Args:
        key: Structured field key to classify.

    Returns:
        True when the normalized string key contains a credential marker.
    """
    if not isinstance(key, str):
        return False

    normalized = _normalize_key(key)
    tokens = tuple(token for token in normalized.split("_") if token)
    singular_tokens = tuple(
        token[:-1] if token.endswith("s") and len(token) > 1 else token
        for token in tokens
    )
    normalized_key = "_".join(singular_tokens)
    compact_key = "".join(singular_tokens)

    for marker in _SENSITIVE_KEY_MARKERS:
        marker_tokens = tuple(
            token[:-1] if token.endswith("s") and len(token) > 1 else token
            for token in _normalize_key(marker).split("_")
            if token
        )
        normalized_marker = "_".join(marker_tokens)

        if (
            normalized_key == normalized_marker
            or normalized_key.startswith(f"{normalized_marker}_")
            or normalized_key.endswith(f"_{normalized_marker}")
            or f"_{normalized_marker}_" in f"_{normalized_key}_"
        ):
            return True

    return compact_key in _SENSITIVE_COMPOUNDS


def _sanitize_string(value: str) -> str:
    """Remove recognized credential syntax from free-form text.

    Args:
        value: String crossing the local logging boundary.

    Returns:
        String with recognized bearer credentials removed.
    """
    return _BEARER_PATTERN.sub("Bearer [REDACTED]", value)


def _redact(value: Any) -> Any:
    """Return a logging-safe representation of structured data.

    Args:
        value: Arbitrary value destined for local structured logging.

    Returns:
        A recursively redacted, JSON-compatible representation.
    """
    if isinstance(value, SecretStr):
        return _REDACTED
    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            safe_key = key if isinstance(key, str) else _UNSUPPORTED
            sanitized[safe_key] = (
                _REDACTED if _is_sensitive_key(key) else _redact(item)
            )
        return sanitized
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_redact(item) for item in value]
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, str):
        return _sanitize_string(value)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return _UNSUPPORTED


def log_event(
    logger: logging.Logger,
    *,
    event: str,
    workflow_id: UUID,
    trace_id: UUID,
    fields: Mapping[str, Any] | None = None,
) -> None:
    """Emit one correlation-aware structured local log event.

    Args:
        logger: Logger receiving the serialized event.
        event: Event name.
        workflow_id: Workflow correlation identifier.
        trace_id: Trace correlation identifier.
        fields: Optional structured event fields.
    """
    record = {
        "event": _sanitize_string(event),
        "workflow_id": str(workflow_id),
        "trace_id": str(trace_id),
        "fields": _redact(fields or {}),
    }
    try:
        logger.info(json.dumps(record, sort_keys=True))
    except Exception:
        # Optional observation boundary: sink failures cannot change core semantics.
        # Never recursively log a sink error or propagate its secret-bearing text.
        return
