"""Closed-vocabulary claim extraction from untrusted statements (Story 9.5).

A claim is a statement fragment that asserts a property some other modality can measure: an image
region's color, an image's colors, brightness, or orientation, or an audio clip's content,
duration, or tone frequency. Extraction is a small, fixed set of lexical rules over lowercase word
tokens. It does not understand language: it reads only the vocabulary below, and anything outside
it is ignored. Text is never executed, followed, or treated as instructions.
"""

import re
from dataclasses import dataclass
from typing import Final

from multimodal_voice_platform.contracts.reasoning import MAX_QUOTE_CHARS, ObservationView

MAX_CLAIMS_PER_OBSERVATION: Final = 32

COLOR_WORDS: Final = {
    "black": "black",
    "white": "white",
    "gray": "gray",
    "grey": "gray",
    "red": "red",
    "orange": "orange",
    "brown": "brown",
    "yellow": "yellow",
    "green": "green",
    "cyan": "cyan",
    "blue": "blue",
    "purple": "purple",
    "magenta": "magenta",
}
"""Words mapped onto the named colors the local image analysis reports."""

REGION_WORDS: Final = {
    "top-left": "top-left",
    "upper-left": "top-left",
    "top-right": "top-right",
    "upper-right": "top-right",
    "bottom-left": "bottom-left",
    "lower-left": "bottom-left",
    "bottom-right": "bottom-right",
    "lower-right": "bottom-right",
}
REGION_PAIRS: Final = {
    (vertical, horizontal): f"{'top' if vertical in {'top', 'upper'} else 'bottom'}-{horizontal}"
    for vertical in ("top", "upper", "bottom", "lower")
    for horizontal in ("left", "right")
}
IMAGE_WORDS: Final = frozenset(
    {"image", "picture", "photo", "photograph", "diagram", "graphic", "pattern", "figure"}
)
AUDIO_WORDS: Final = frozenset(
    {"audio", "recording", "clip", "sound", "track", "tone", "beep", "signal"}
)
SILENT_WORDS: Final = frozenset({"silent", "silence", "mute", "muted"})
SIGNAL_WORDS: Final = frozenset({"tone", "tones", "beep", "beeps", "audible", "noise", "hum"})
BRIGHTNESS_WORDS: Final = frozenset({"dark", "bright"})
ORIENTATION_WORDS: Final = frozenset({"square", "landscape", "portrait"})
NEGATORS: Final = frozenset(
    {"not", "no", "never", "without", "nor", "neither", "isn", "aren", "wasn", "weren", "doesn"}
)
NEGATION_WINDOW: Final = 2
"""How many tokens before a claimed value are checked for a negator."""

_CLAUSE_SPLIT: Final = re.compile(
    r"[.!?:]+(?=\s|$)|[;\n]+|,\s+(?:but|while|whereas)\s+"
)
"""Clause boundaries. Periods and colons split only before whitespace, so ``1.5 s`` stays whole."""
_TOKEN: Final = re.compile(r"[a-z]+(?:-[a-z]+)*|\d+(?:\.\d+)?")
_DURATION: Final = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*(milliseconds?|ms|seconds?|secs?|s)\b", re.IGNORECASE
)
_FREQUENCY: Final = re.compile(r"\b(\d+(?:\.\d+)?)\s*(khz|kilohertz|hz|hertz)\b", re.IGNORECASE)
_DURATION_CUES: Final = AUDIO_WORDS | {"lasts", "long", "duration"}


@dataclass(frozen=True)
class Claim:
    """One property assertion read from a statement.

    Attributes:
        observation_id: Observation the statement belongs to.
        statement_id: Statement the claim was read from.
        quote: The clause the claim was read from, verbatim from the statement.
        property: Claimed property, in the same vocabulary as measured facts.
        value: Claimed value (a color, label, or number as text).
        negated: Whether the clause negates the value.
        numeric: The claimed number for numeric properties, in fact units.
    """

    observation_id: str
    statement_id: str
    quote: str
    property: str
    value: str
    negated: bool = False
    numeric: float | None = None

    @property
    def key(self) -> tuple[str, str, bool]:
        """Identify the claim within its observation for de-duplication."""
        return (self.property, self.value, self.negated)


def extract_claims(view: ObservationView) -> tuple[Claim, ...]:
    """Read every vocabulary claim from an observation's statements.

    Args:
        view: The observation to read.

    Returns:
        De-duplicated claims in statement order, at most ``MAX_CLAIMS_PER_OBSERVATION``.
    """
    claims: list[Claim] = []
    seen: set[tuple[str, str, bool]] = set()
    for statement in view.statements:
        for clause in _clauses(statement.text):
            for prop, value, negated, numeric in _clause_claims(clause):
                claim = Claim(
                    observation_id=view.observation_id,
                    statement_id=statement.statement_id,
                    quote=clause[:MAX_QUOTE_CHARS].strip(),
                    property=prop,
                    value=value,
                    negated=negated,
                    numeric=numeric,
                )
                if claim.key in seen:
                    continue
                seen.add(claim.key)
                claims.append(claim)
                if len(claims) >= MAX_CLAIMS_PER_OBSERVATION:
                    return tuple(claims)
    return tuple(claims)


def content_terms(view: ObservationView) -> frozenset[str]:
    """Return the distinctive words an observation's statements use.

    Args:
        view: The observation to read.

    Returns:
        Lowercase alphabetic words of four or more letters that are not stopwords.
    """
    words: set[str] = set()
    for statement in view.statements:
        for token in _TOKEN.findall(statement.text.lower()):
            if token.isalpha() and len(token) >= 4 and token not in _STOPWORDS:
                words.add(token)
    return frozenset(words)


def _clauses(text: str) -> list[str]:
    return [part.strip() for part in _CLAUSE_SPLIT.split(text) if part.strip()]


def _negated(tokens: list[str], index: int) -> bool:
    return any(token in NEGATORS for token in tokens[max(0, index - NEGATION_WINDOW) : index])


def _preceded_by_negator(text: str, offset: int) -> bool:
    before = _TOKEN.findall(text[:offset])
    return _negated(before, len(before))


def _clause_claims(clause: str) -> list[tuple[str, str, bool, float | None]]:
    tokens = _TOKEN.findall(clause.lower())
    words = set(tokens)
    found: list[tuple[str, str, bool, float | None]] = []
    regions = _region_mentions(tokens)
    found.extend(_region_claims(tokens, regions))
    image_cue = bool(words & IMAGE_WORDS)
    if image_cue and not regions:
        for index, token in enumerate(tokens):
            if token in COLOR_WORDS:
                found.append(("image.color", COLOR_WORDS[token], _negated(tokens, index), None))
    if image_cue:
        for index, token in enumerate(tokens):
            following = tokens[index + 1] if index + 1 < len(tokens) else ""
            if token in BRIGHTNESS_WORDS and following not in COLOR_WORDS:
                found.append(("image.brightness", token, _negated(tokens, index), None))
            elif token in ORIENTATION_WORDS:
                found.append(("image.orientation", token, _negated(tokens, index), None))
    if words & AUDIO_WORDS:
        for index, token in enumerate(tokens):
            if token in SILENT_WORDS:
                found.append(("audio.content", "silent", _negated(tokens, index), None))
            elif token in SIGNAL_WORDS:
                found.append(("audio.content", "signal", _negated(tokens, index), None))
    found.extend(_numeric_claims(clause, words))
    return found


def _region_mentions(tokens: list[str]) -> list[tuple[int, int, str]]:
    """Return (start, end, region) for each region phrase, in token order."""
    mentions: list[tuple[int, int, str]] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        pair = (token, tokens[index + 1]) if index + 1 < len(tokens) else None
        if token in REGION_WORDS:
            mentions.append((index, index + 1, REGION_WORDS[token]))
            index += 1
        elif pair in REGION_PAIRS:
            mentions.append((index, index + 2, REGION_PAIRS[pair]))
            index += 2
        else:
            index += 1
    return mentions


def _region_claims(
    tokens: list[str], mentions: list[tuple[int, int, str]]
) -> list[tuple[str, str, bool, float | None]]:
    """Pair each region with the first color after it, else the nearest color before it."""
    claims: list[tuple[str, str, bool, float | None]] = []
    used: set[int] = set()
    for position, (start, end, region) in enumerate(mentions):
        limit = mentions[position + 1][0] if position + 1 < len(mentions) else len(tokens)
        floor = mentions[position - 1][1] if position > 0 else 0
        forward = [i for i in range(end, limit) if tokens[i] in COLOR_WORDS and i not in used]
        backward = [i for i in range(start - 1, floor - 1, -1) if tokens[i] in COLOR_WORDS]
        candidates = forward or [i for i in backward if i not in used]
        if candidates:
            index = candidates[0]
            used.add(index)
            color = COLOR_WORDS[tokens[index]]
            claims.append((f"image.region.{region}", color, _negated(tokens, index), None))
    return claims


def _numeric_claims(clause: str, words: set[str]) -> list[tuple[str, str, bool, float | None]]:
    claims: list[tuple[str, str, bool, float | None]] = []
    lowered = clause.lower()
    if words & _DURATION_CUES:
        for match in _DURATION.finditer(lowered):
            if _preceded_by_negator(lowered, match.start()):
                continue
            amount = float(match.group(1))
            unit = match.group(2)
            millis = amount if unit.startswith("m") else amount * 1000
            claims.append(("audio.duration_ms", f"{millis:g}", False, millis))
    for match in _FREQUENCY.finditer(lowered):
        if _preceded_by_negator(lowered, match.start()):
            continue
        amount = float(match.group(1))
        hertz = amount * 1000 if match.group(2).startswith("k") else amount
        claims.append(("audio.tone_hz", f"{hertz:g}", False, hertz))
    return claims


_STOPWORDS: Final = frozenset(
    {
        "about",
        "above",
        "after",
        "again",
        "also",
        "been",
        "before",
        "being",
        "both",
        "could",
        "does",
        "down",
        "each",
        "from",
        "have",
        "having",
        "here",
        "into",
        "just",
        "more",
        "most",
        "must",
        "only",
        "other",
        "over",
        "same",
        "should",
        "some",
        "such",
        "than",
        "that",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "through",
        "under",
        "very",
        "were",
        "what",
        "when",
        "where",
        "which",
        "while",
        "will",
        "with",
        "would",
        "your",
    }
)
