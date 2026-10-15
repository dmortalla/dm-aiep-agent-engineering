"""Bounds for the cross-modal workflow (ADR-009-008). From application configuration only."""

from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from multimodal_voice_platform.contracts.reasoning import (
    MAX_FINDINGS,
    MAX_STATEMENT_CHARS,
    MAX_STATEMENTS_PER_OBSERVATION,
)

MAX_WORKFLOW_ITEMS: Final = 8
"""Hard ceiling on inputs per run. One reasoning part per input, within ``MAX_REASONING_PARTS``."""
MAX_ITEMS_PER_MODALITY: Final = 4
MAX_AGGREGATE_BYTES: Final = 48 * 1024 * 1024
MAX_OBSERVATION_CHARS: Final = 16_000
MAX_CONTEXT_CHARS: Final = 96_000
MAX_OUTPUT_CHARS: Final = 128_000
MAX_OUTPUT_CHUNKS: Final = 64


class CrossModalLimits(BaseModel):
    """Bounds on one cross-modal run. Every field has a hard ceiling."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_items: int = Field(default=6, ge=2, le=MAX_WORKFLOW_ITEMS)
    max_items_per_modality: int = Field(default=2, ge=1, le=MAX_ITEMS_PER_MODALITY)
    max_aggregate_bytes: int = Field(default=24 * 1024 * 1024, gt=0, le=MAX_AGGREGATE_BYTES)
    max_statements_per_observation: int = Field(
        default=24, gt=0, le=MAX_STATEMENTS_PER_OBSERVATION
    )
    max_statement_chars: int = Field(default=500, ge=20, le=MAX_STATEMENT_CHARS)
    max_observation_chars: int = Field(default=4_000, gt=0, le=MAX_OBSERVATION_CHARS)
    max_context_chars: int = Field(default=48_000, gt=0, le=MAX_CONTEXT_CHARS)
    max_output_chars: int = Field(default=64_000, gt=0, le=MAX_OUTPUT_CHARS)
    max_output_chunks: int = Field(default=32, gt=0, le=MAX_OUTPUT_CHUNKS)
    max_findings: int = Field(default=48, gt=0, le=MAX_FINDINGS)
