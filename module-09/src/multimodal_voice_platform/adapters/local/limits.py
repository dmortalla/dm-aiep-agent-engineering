"""Processing limits for the local adapters, derived from the session ``ResourceBudget``."""

from typing import Final, Self

from pydantic import BaseModel, ConfigDict, Field

from multimodal_voice_platform.contracts.limits import (
    MAX_DOCUMENT_BYTES,
    MAX_DOCUMENT_PAGES,
    MAX_IMAGE_BYTES,
    MAX_REQUEST_TIMEOUT_S,
    ResourceBudget,
)

MAX_IMAGE_PIXELS: Final = 40_000_000
"""Hard ceiling on decoded image pixels, checked from the header before decoding (SEC-005)."""

DEFAULT_IMAGE_PIXELS: Final = 25_000_000
MAX_EXTRACTED_CHARS: Final = 1_000_000
"""Hard ceiling on document text kept after extraction. Longer documents are truncated."""


class LocalProcessingLimits(BaseModel):
    """Bounds applied by the local adapters. Comes from application configuration only."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_image_bytes: int = Field(gt=0, le=MAX_IMAGE_BYTES)
    max_image_pixels: int = Field(default=DEFAULT_IMAGE_PIXELS, gt=0, le=MAX_IMAGE_PIXELS)
    max_document_bytes: int = Field(gt=0, le=MAX_DOCUMENT_BYTES)
    max_document_pages: int = Field(gt=0, le=MAX_DOCUMENT_PAGES)
    max_extracted_chars: int = Field(default=MAX_EXTRACTED_CHARS, gt=0, le=MAX_EXTRACTED_CHARS)
    timeout_s: float = Field(gt=0, le=MAX_REQUEST_TIMEOUT_S)

    @classmethod
    def from_budget(cls, budget: ResourceBudget) -> Self:
        """Derive local processing limits from a session budget.

        Args:
            budget: Application-owned session budget.

        Returns:
            Limits that never exceed the budget or the hard ceilings.
        """
        return cls(
            max_image_bytes=budget.max_image_bytes,
            max_document_bytes=budget.max_document_bytes,
            max_document_pages=budget.max_document_pages,
            timeout_s=budget.request_timeout_s,
        )
