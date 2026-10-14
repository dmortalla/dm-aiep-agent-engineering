"""Local, deterministic document extraction and structural analysis (Story 9.3).

Supported formats are the allowlisted document media types: Markdown, plain text, and PDF.

- Markdown is parsed line by line into a heading outline and heading-delimited sections, with
  counts of list items, fenced code blocks, tables, and links. Links are counted, never fetched.
- Plain text is split into paragraph-grouped sections.
- PDF text is extracted page by page with pypdf from an in-memory buffer. Encrypted PDFs are
  rejected, the page count is checked before extraction, and documents with no text layer are
  rejected because OCR is not supported.

This is parsing, extraction, and structural understanding. No model runs, so nothing here
summarizes, interprets, or answers questions about the content. Extracted text is untrusted data.
"""

import io
import re
import struct
from enum import StrEnum
from typing import Final

from pydantic import BaseModel, ConfigDict, Field
from pypdf import PdfReader
from pypdf.errors import PyPdfError

from multimodal_voice_platform.adapters.local.errors import (
    EmptyDocumentError,
    MalformedContentError,
    ProcessingLimitError,
    UnsupportedContentError,
)
from multimodal_voice_platform.adapters.local.limits import LocalProcessingLimits
from multimodal_voice_platform.contracts.limits import MAX_TEXT_CHARS
from multimodal_voice_platform.contracts.providers import DocumentSection
from multimodal_voice_platform.ingestion.errors import MediaMismatchError
from multimodal_voice_platform.ingestion.media import decode_text_content

MAX_SECTIONS: Final = 200
MAX_OUTLINE_ENTRIES: Final = 200
MAX_HEADING_CHARS: Final = 300
PLAIN_TEXT_SECTION_CHARS: Final = 4_000

_PDF_ERRORS: Final = (
    PyPdfError,
    ValueError,
    KeyError,
    TypeError,
    IndexError,
    AttributeError,
    OSError,
    RecursionError,
    ZeroDivisionError,
    struct.error,
)
"""Exceptions pypdf raises for malformed or hostile PDF structure."""

_ATX_HEADING: Final = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*$")
_SETEXT_UNDERLINE: Final = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
_FENCE: Final = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_LIST_ITEM: Final = re.compile(r"^ {0,3}(?:[-*+]|\d{1,9}[.)])[ \t]+\S")
_TABLE_SEPARATOR: Final = re.compile(
    r"^ {0,3}\|?[ \t]*:?-{3,}:?[ \t]*(\|[ \t]*:?-{3,}:?[ \t]*)+\|?[ \t]*$"
)
_LINK: Final = re.compile(r"\[[^\]\n]*\]\([^)\s]+(?:[ \t]+\"[^\"]*\")?\)")
_CONTROL_CHARS: Final = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class DocumentFormat(StrEnum):
    """Document formats the local adapter parses."""

    MARKDOWN = "markdown"
    PLAIN_TEXT = "plain_text"
    PDF = "pdf"


FORMAT_FOR_MEDIA_TYPE: Final = {
    "text/markdown": DocumentFormat.MARKDOWN,
    "text/plain": DocumentFormat.PLAIN_TEXT,
    "application/pdf": DocumentFormat.PDF,
}


class OutlineEntry(BaseModel):
    """One heading in a document outline."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    level: int = Field(ge=1, le=6)
    text: str = Field(min_length=1, max_length=MAX_HEADING_CHARS)


class DocumentAnalysis(BaseModel):
    """Structured result of local document extraction. Derived from untrusted content."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    format: DocumentFormat
    media_type: str
    title: str | None = Field(default=None, max_length=MAX_HEADING_CHARS)
    page_count: int | None = Field(default=None, gt=0)
    pages_without_text: int = Field(default=0, ge=0)
    outline: tuple[OutlineEntry, ...] = Field(default=(), max_length=MAX_OUTLINE_ENTRIES)
    section_count: int = Field(gt=0, le=MAX_SECTIONS)
    character_count: int = Field(ge=0)
    word_count: int = Field(ge=0)
    list_item_count: int = Field(default=0, ge=0)
    code_block_count: int = Field(default=0, ge=0)
    table_count: int = Field(default=0, ge=0)
    link_count: int = Field(default=0, ge=0)
    truncated: bool = False


class ParsedDocument(BaseModel):
    """Extracted sections plus their structural analysis."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str | None = Field(default=None, max_length=MAX_HEADING_CHARS)
    sections: tuple[DocumentSection, ...] = Field(min_length=1, max_length=MAX_SECTIONS)
    analysis: DocumentAnalysis


class _Sections:
    """Accumulates bounded sections and records truncation."""

    def __init__(self, max_chars: int) -> None:
        self.items: list[DocumentSection] = []
        self.remaining = max_chars
        self.truncated = False

    def add(self, heading: str | None, text: str) -> None:
        text = text.strip()
        if not text:
            return
        if len(text) > self.remaining:
            text = text[: self.remaining].rstrip()
            self.truncated = True
        chunks = [text[i : i + MAX_TEXT_CHARS] for i in range(0, len(text), MAX_TEXT_CHARS)]
        for index, chunk in enumerate(chunks, start=1):
            if not chunk.strip():
                continue
            if len(self.items) >= MAX_SECTIONS:
                self.truncated = True
                return
            label = heading
            if len(chunks) > 1:
                label = _bound_heading(f"{heading or 'Section'} (part {index})")
            self.items.append(DocumentSection(heading=label, text=chunk))
            self.remaining -= len(chunk)
        if self.remaining <= 0:
            self.truncated = True


def _bound_heading(text: str) -> str | None:
    cleaned = " ".join(_CONTROL_CHARS.sub(" ", text).split())
    return cleaned[:MAX_HEADING_CHARS] or None


def parse_document(data: bytes, media_type: str, limits: LocalProcessingLimits) -> ParsedDocument:
    """Extract sections and structure from a document.

    Args:
        data: Document bytes, already verified against the declared media type.
        media_type: Declared, allowlisted document media type.
        limits: Processing limits from application configuration.

    Returns:
        The extracted sections and structural analysis.

    Raises:
        UnsupportedContentError: If the media type is unsupported or the PDF is encrypted.
        ProcessingLimitError: If the document exceeds the byte or page limit.
        MalformedContentError: If the document cannot be decoded or parsed.
        EmptyDocumentError: If the document yields no extractable text.
    """
    document_format = FORMAT_FOR_MEDIA_TYPE.get(media_type)
    if document_format is None:
        raise UnsupportedContentError("document media type has no enabled parser")
    if len(data) > limits.max_document_bytes:
        raise ProcessingLimitError("document exceeds the processing byte limit")
    if document_format is DocumentFormat.PDF:
        return _parse_pdf(data, limits)
    try:
        text = decode_text_content(data)
    except MediaMismatchError as exc:
        raise MalformedContentError("document is not valid UTF-8 text") from exc
    if document_format is DocumentFormat.MARKDOWN:
        return _parse_markdown(text, media_type, limits)
    return _parse_plain_text(text, media_type, limits)


def _counts(text: str) -> dict[str, int]:
    return {"character_count": len(text), "word_count": len(text.split())}


def _finish(
    sections: _Sections,
    *,
    title: str | None,
    analysis: dict[str, object],
) -> ParsedDocument:
    if not sections.items:
        raise EmptyDocumentError("document contains no extractable text")
    return ParsedDocument(
        title=title,
        sections=tuple(sections.items),
        analysis=DocumentAnalysis.model_validate(
            {
                **analysis,
                "title": title,
                "section_count": len(sections.items),
                "truncated": sections.truncated,
            }
        ),
    )


def _parse_markdown(text: str, media_type: str, limits: LocalProcessingLimits) -> ParsedDocument:
    sections = _Sections(limits.max_extracted_chars)
    outline: list[OutlineEntry] = []
    blocks: list[str] = []
    paragraph: list[str] = []
    code: list[str] = []
    heading: str | None = None
    fence: str | None = None
    counts = {"list_item_count": 0, "code_block_count": 0, "table_count": 0}

    def close_paragraph() -> None:
        if paragraph:
            blocks.append(" ".join(line.strip() for line in paragraph))
            paragraph.clear()

    def start_section(level: int, raw_heading: str) -> None:
        nonlocal heading
        close_paragraph()
        sections.add(heading, "\n\n".join(blocks))
        blocks.clear()
        heading = _bound_heading(raw_heading)
        if heading is not None and len(outline) < MAX_OUTLINE_ENTRIES:
            outline.append(OutlineEntry(level=level, text=heading))

    for line in text.splitlines():
        if fence is not None:
            if line.strip().startswith(fence):
                blocks.append("\n".join(code))
                code.clear()
                fence = None
            else:
                code.append(line)
            continue
        fence_match = _FENCE.match(line)
        if fence_match:
            close_paragraph()
            fence = fence_match.group(1)
            counts["code_block_count"] += 1
            continue
        atx = _ATX_HEADING.match(line)
        if atx:
            start_section(len(atx.group(1)), atx.group(2) or "")
            continue
        underline = _SETEXT_UNDERLINE.match(line)
        if underline and len(paragraph) == 1 and not _LIST_ITEM.match(paragraph[0]):
            raw = paragraph.pop()
            start_section(1 if underline.group(1)[0] == "=" else 2, raw)
            continue
        if not line.strip():
            close_paragraph()
            continue
        if _LIST_ITEM.match(line):
            counts["list_item_count"] += 1
        if _TABLE_SEPARATOR.match(line):
            counts["table_count"] += 1
        paragraph.append(line)
    if code:
        blocks.append("\n".join(code))
    close_paragraph()
    sections.add(heading, "\n\n".join(blocks))
    level_one = [entry.text for entry in outline if entry.level == 1]
    title = level_one[0] if level_one else (outline[0].text if outline else None)
    return _finish(
        sections,
        title=title,
        analysis={
            "format": DocumentFormat.MARKDOWN,
            "media_type": media_type,
            "outline": tuple(outline),
            "link_count": len(_LINK.findall(text)),
            **counts,
            **_counts(text),
        },
    )


def _parse_plain_text(text: str, media_type: str, limits: LocalProcessingLimits) -> ParsedDocument:
    sections = _Sections(limits.max_extracted_chars)
    paragraphs = [p.strip() for p in re.split(r"\n[ \t]*\n", text) if p.strip()]
    group: list[str] = []
    size = 0
    for paragraph in paragraphs:
        if group and size + len(paragraph) > PLAIN_TEXT_SECTION_CHARS:
            sections.add(None, "\n\n".join(group))
            group, size = [], 0
        group.append(paragraph)
        size += len(paragraph) + 2
    sections.add(None, "\n\n".join(group))
    return _finish(
        sections,
        title=None,
        analysis={"format": DocumentFormat.PLAIN_TEXT, "media_type": media_type, **_counts(text)},
    )


def _parse_pdf(data: bytes, limits: LocalProcessingLimits) -> ParsedDocument:
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            raise UnsupportedContentError("encrypted PDF documents are not supported")
        page_count = len(reader.pages)
        if page_count > limits.max_document_pages:
            raise ProcessingLimitError("PDF exceeds the session page budget")
        page_texts = [page.extract_text() or "" for page in reader.pages]
        metadata = reader.metadata
        raw_title = metadata.title if metadata is not None else None
    except _PDF_ERRORS as exc:
        raise MalformedContentError("PDF could not be parsed") from exc
    if page_count == 0:
        raise MalformedContentError("PDF has no pages")
    sections = _Sections(limits.max_extracted_chars)
    without_text = 0
    combined: list[str] = []
    for number, page_text in enumerate(page_texts, start=1):
        cleaned = _CONTROL_CHARS.sub(" ", page_text).strip()
        if not cleaned:
            without_text += 1
            continue
        combined.append(cleaned)
        sections.add(f"Page {number}", cleaned)
    if not sections.items:
        raise EmptyDocumentError("PDF has no extractable text layer; OCR is not supported")
    title = _bound_heading(raw_title) if isinstance(raw_title, str) else None
    return _finish(
        sections,
        title=title,
        analysis={
            "format": DocumentFormat.PDF,
            "media_type": "application/pdf",
            "page_count": page_count,
            "pages_without_text": without_text,
            **_counts("\n".join(combined)),
        },
    )
