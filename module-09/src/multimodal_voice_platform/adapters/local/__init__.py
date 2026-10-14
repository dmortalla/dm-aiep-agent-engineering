"""Local, in-process image and document processing adapters (Story 9.3).

These adapters genuinely process submitted content (image decoding and pixel analysis; document
parsing, text extraction, and structural analysis) with no network, credentials, or model. Their
output is local extraction and structural understanding, never semantic model inference.
"""

from multimodal_voice_platform.adapters.local.document_parsing import (
    DocumentAnalysis,
    DocumentFormat,
    OutlineEntry,
    parse_document,
)
from multimodal_voice_platform.adapters.local.errors import (
    EmptyDocumentError,
    LocalProcessingError,
    MalformedContentError,
    ProcessingLimitError,
    ProcessingTimeoutError,
    UnsupportedContentError,
)
from multimodal_voice_platform.adapters.local.image_analysis import (
    ColorShare,
    ImageAnalysis,
    RegionColor,
    analyze_image,
    color_name,
)
from multimodal_voice_platform.adapters.local.limits import LocalProcessingLimits
from multimodal_voice_platform.adapters.local.providers import (
    LOCAL_DOCUMENT_ID,
    LOCAL_VISION_ID,
    LocalDocumentOutput,
    LocalDocumentProvider,
    LocalVisionOutput,
    LocalVisionProvider,
)

__all__ = [
    "LOCAL_DOCUMENT_ID",
    "LOCAL_VISION_ID",
    "ColorShare",
    "DocumentAnalysis",
    "DocumentFormat",
    "EmptyDocumentError",
    "ImageAnalysis",
    "LocalDocumentOutput",
    "LocalDocumentProvider",
    "LocalProcessingError",
    "LocalProcessingLimits",
    "LocalVisionOutput",
    "LocalVisionProvider",
    "MalformedContentError",
    "OutlineEntry",
    "ProcessingLimitError",
    "ProcessingTimeoutError",
    "RegionColor",
    "UnsupportedContentError",
    "analyze_image",
    "color_name",
    "parse_document",
]
