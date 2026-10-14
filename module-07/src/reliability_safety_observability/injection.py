"""Prompt-injection detection and containment for untrusted content.

Containment keeps trusted policy and untrusted content in separate channels.
Untrusted content is only ever rendered as delimited, escaped data and is never
parsed for instructions, roles, grants, or policy changes.
"""

import re
import unicodedata
from typing import Final

from pydantic import BaseModel, ConfigDict

from .domain import Identifier, UntrustedContent

_ZERO_WIDTH: Final = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff"))

# Each marker names a class of attempt to redefine policy or authority.
_INJECTION_MARKERS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    (
        "instruction_override",
        re.compile(
            r"\b(ignore|disregard|forget|override|bypass)\b.{0,40}"
            r"\b(previous|prior|above|earlier|all|system|your)\b.{0,40}"
            r"\b(instructions?|rules|polic(y|ies)|prompt|guardrails?)\b"
        ),
    ),
    (
        "policy_redefinition",
        re.compile(
            r"\b(new|updated|revised|real)\s+(system\s+)?(instructions?|polic(y|ies)|rules)\b"
            r"|\bsystem\s+prompt\b"
        ),
    ),
    (
        "role_escalation",
        re.compile(
            r"\b(you are now|act as|pretend to be|switch to)\b.{0,30}"
            r"\b(admin(istrator)?|root|developer mode|superuser|unrestricted)\b"
        ),
    ),
    (
        "authority_claim",
        re.compile(
            r"\b(grant|give|add|enable|elevate|unlock|allowlist|whitelist)\b.{0,40}"
            r"\b(permissions?|access|privileges?|tools?|authori[sz]ation|role)\b"
            r"|\b(authori[sz]ed|approved)[\"']?\s*[:=]\s*[\"']?(true|yes|1)\b"
        ),
    ),
    (
        "role_delimiter",
        re.compile(r"(^|\n)\s*(system|assistant|developer)\s*:|<\|?\s*(system|im_start)"),
    ),
    (
        "containment_breakout",
        re.compile(r"</?\s*(untrusted_data|trusted_policy)\b"),
    ),
)


def normalize_for_inspection(text: str) -> str:
    """Normalize text so trivially obfuscated markers remain detectable.

    Args:
        text: Untrusted text.

    Returns:
        NFKC-normalized, case-folded text without zero-width characters and with
        collapsed horizontal whitespace.
    """
    normalized = unicodedata.normalize("NFKC", text).translate(_ZERO_WIDTH).casefold()
    return re.sub(r"[ \t\f\v]+", " ", normalized)


class InjectionAssessment(BaseModel):
    """Deterministic result of inspecting untrusted content for injection.

    Attributes:
        detected: Whether any injection marker matched.
        markers: Names of the matched marker classes, never the matched text.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    detected: bool
    markers: tuple[Identifier, ...] = ()


def inspect_for_injection(content: UntrustedContent) -> InjectionAssessment:
    """Detect attempts by untrusted content to redefine policy or authority.

    Args:
        content: Untrusted content from users, retrieval, tools, or models.

    Returns:
        The marker classes detected in the content.
    """
    text = normalize_for_inspection(content.value)
    markers = tuple(name for name, pattern in _INJECTION_MARKERS if pattern.search(text))
    return InjectionAssessment(detected=bool(markers), markers=markers)


class ContainedPrompt(BaseModel):
    """Model context whose trusted and untrusted channels cannot be merged.

    Attributes:
        trusted_policy: Committed application policy text.
        untrusted_data: Escaped, delimited rendering of untrusted content.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    trusted_policy: str
    untrusted_data: str


def contain(trusted_policy: str, content: UntrustedContent) -> ContainedPrompt:
    """Place untrusted content into an inert data channel beside trusted policy.

    The trusted policy is taken verbatim from the caller's committed policy and
    is never derived from, appended to, or modified by the untrusted content.
    Markup in the untrusted content is escaped so it cannot close the data
    delimiter or impersonate the trusted channel.

    Args:
        trusted_policy: Committed application policy text.
        content: Untrusted content to contain.

    Returns:
        Separate trusted-policy and untrusted-data channels.
    """
    escaped = content.value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    source = re.sub(r"[^a-z0-9_.-]", "_", content.source.casefold())
    return ContainedPrompt(
        trusted_policy=trusted_policy,
        untrusted_data=f'<untrusted_data source="{source}">\n{escaped}\n</untrusted_data>',
    )
