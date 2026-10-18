"""Central secret redaction for live execution (Story 9.8).

Credentials are ``SecretStr`` and are excluded from serialization and ``repr`` by the session
contract; translated provider errors carry fixed messages. This module is the last line of defence
for text that leaves the process anyway (acceptance output, log records): it removes the known
secret values and anything shaped like a provider key or bearer token.
"""

import logging
import re
from collections.abc import Iterable
from typing import Final

from pydantic import SecretStr

REDACTED: Final = "[REDACTED]"
SECRET_PATTERNS: Final = (
    re.compile(r"sk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"(?i)(api[_-]?key|authorization)\s*[:=]\s*\S+"),
)


def _values(secrets: Iterable[str | SecretStr]) -> list[str]:
    values = [s.get_secret_value() if isinstance(s, SecretStr) else s for s in secrets]
    return sorted((v for v in values if v), key=len, reverse=True)


def redact(text: str, secrets: Iterable[str | SecretStr] = ()) -> str:
    """Remove known secrets and secret-shaped tokens from text.

    Args:
        text: Text that may leave the process.
        secrets: Known secret values to remove verbatim.

    Returns:
        The text with every secret replaced by ``[REDACTED]``.
    """
    for value in _values(secrets):
        text = text.replace(value, REDACTED)
    for pattern in SECRET_PATTERNS:
        text = pattern.sub(REDACTED, text)
    return text


class RedactingFilter(logging.Filter):
    """Logging filter that redacts secrets from every record before it is emitted."""

    def __init__(self, secrets: Iterable[str | SecretStr] = ()) -> None:
        """Create the filter.

        Args:
            secrets: Known secret values to remove verbatim.
        """
        super().__init__()
        self._secrets = list(secrets)

    def filter(self, record: logging.LogRecord) -> bool:
        """Replace the record's message with its redacted, fully formatted form.

        Args:
            record: The log record.

        Returns:
            Always ``True``; the record is kept, redacted.
        """
        message = record.getMessage()
        if record.exc_info:
            record.exc_text = redact(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        record.msg = redact(message, self._secrets)
        record.args = None
        if record.exc_text:
            record.exc_text = redact(record.exc_text, self._secrets)
        return True
