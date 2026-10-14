# Module 9 Document and Vision Understanding (Story 9.3)

## What this is

Story 9.3 adds a genuine processing path for image and document input. It validates untrusted
bytes, decodes and analyzes them in-process, and returns typed, evidence-classified records that the
later Streamlit layer (Story 9.9) can show directly. It lives in three packages:

| Package | Role |
|---|---|
| `ingestion/` | Validation boundary: modality, media type, magic bytes, UTF-8 text checks, byte budget, safe display name, staging |
| `adapters/local/` | `LocalVisionProvider` (`VisionPort`) and `LocalDocumentProvider` (`DocumentUnderstandingPort`) |
| `understanding/` | `UnderstandingService` and `UnderstandingRecord`: the application-facing entry point and reviewer-visible result |

Unlike Story 9.2 fixture playback, nothing is looked up or replayed. Any valid image or document is
processed from its actual bytes.

## What it is not

There is **no model inference**. Story 9.3 performs parsing, extraction, and structural analysis
only. Its output is **not semantic understanding**: it does not recognize objects, people, scenes,
or text in images; it does not summarize, interpret, classify, or answer questions about documents.
Semantic, model-derived vision and document understanding needs either a live provider (Story 9.8,
which owns provider selection) or a bundled local model; neither is part of Story 9.3.

## Processing kinds

Every record states which kinds of processing produced it, so they are never confused.

| Kind | Meaning | Produced by |
|---|---|---|
| `fixture_playback` | Scripted output for a committed fixture, matched by digest | Story 9.2 deterministic adapters |
| `local_extraction` | Bytes decoded or parsed into pixels, text, and metadata | Story 9.3 local adapters |
| `local_structural_analysis` | Measured structure: colors, regions, detail; headings, sections, counts | Story 9.3 local adapters |
| `model_inference` | Output produced by a vision, document, or language model | Not implemented. Reserved for Story 9.8 |

`UnderstandingRecord` rejects any Story 9.3 record that claims `fixture_playback` or
`model_inference`, and its `model_inference_performed` and `live_provider_called` flags are fixed to
`False`.

## Vision path

`LocalVisionProvider` decodes PNG, JPEG, and WebP with Pillow and computes classical pixel statistics.

| Step | Behavior |
|---|---|
| Decoder | Pillow opened from an in-memory buffer, restricted to the one decoder for the declared media type |
| Pixel bound | Dimensions read from the header and checked against the pixel limit (25 MP default, 40 MP hard ceiling) before decoding; Pillow decompression-bomb errors map to `limit_exceeded` |
| Orientation | EXIF orientation applied; animated images report their frame count and only the first frame is analyzed |
| Analysis | Thumbnail of at most 128 px per edge: mean luma and contrast, Hasler-Suesstrunk colorfulness, named dominant colors, dominant color per quadrant, edge density, transparency share |
| Output | `VisionResult` (description and observations) plus the full `ImageAnalysis`. Observations always end with "No vision model interpreted the image content." A supplied question is acknowledged as unanswered |

Example: the committed `image-quadrants` fixture yields "Top-left region is mostly red (100%)" and so
on for green, blue, and white. These are measured from pixels, not read from the manifest.

## Document path

`LocalDocumentProvider` handles the allowlisted document types.

| Format | Extraction and structure |
|---|---|
| Markdown (`text/markdown`) | Strict UTF-8 decode; ATX and setext headings; heading outline and title (first level-1 heading); heading-delimited sections; fenced code kept as text and never parsed as headings; counts of list items, code blocks, tables, and links. Links are counted, never fetched |
| Plain text (`text/plain`) | Strict UTF-8 decode; paragraphs grouped into sections of about 4,000 characters |
| PDF (`application/pdf`) | pypdf from an in-memory buffer; encrypted PDFs rejected; page count checked against the session page budget before extraction; text extracted per page into `Page N` sections; metadata title kept as untrusted text; pages without text counted; a PDF with no text layer is rejected because OCR is not supported |

Sections longer than 20,000 characters are split into parts, at most 200 sections are kept, and
extracted text is capped at 1,000,000 characters. Any cut sets `truncated` in `DocumentAnalysis`.

## Controls

| Control | Behavior |
|---|---|
| Mode | Live sessions are refused with `live_mode_not_authorized` before any processing. Local adapters run in `deterministic` mode: in-process, no network, no key, no spend |
| Media type and content | Declared media type must be allowlisted and match the bytes: magic bytes for PNG, JPEG, WebP, PDF; strict UTF-8 with no NUL or binary control characters for Markdown and text. Adapters re-verify stored bytes (SEC-002, SEC-003) |
| Size | Session `ResourceBudget` byte limits at ingestion and again in the adapter; pixel, page, section, and character limits during processing (SEC-005, SEC-007) |
| Names and paths | Display names validated by the `ModalityInput` contract; content held by opaque reference; decoders read only `io.BytesIO` buffers, never paths (SEC-004) |
| Time | Decoding runs in a worker thread bounded by `request_timeout_s`. A timeout returns a retryable `provider_timeout` failure. The worker thread cannot be forcibly stopped in-process; byte, pixel, and page limits bound how long it runs. Process isolation is a Story 9.10 hardening candidate |
| Retention | Each call stages content in its own store and releases it before returning, so uploaded bytes are not retained after processing (SEC-022). EXIF and PNG text metadata are never copied into results |
| Trust | Inputs stay `untrusted_external`; results stay `untrusted_model_output`. Embedded instructions in documents are extracted as data and change nothing (SEC-001, SEC-011, ENG-006) |
| Errors | Failures are `Module9Error` subclasses with stable codes, safe messages, and chained causes. Decoder exceptions are caught by explicit type lists at the decode boundary only. The service turns them into `rejected` or `failed` records with a `SafeError`; anything else is a defect and propagates |
| Commands | No shell, subprocess, eval, or dynamic import; AST tests enforce this and confine Pillow and pypdf to their one parsing module each |

## Reviewer-visible record

`UnderstandingRecord` serializes to JSON and shows: input modality and media type, the validated
input, the processing path and adapter, the processing kinds, the structured result
(`VisionResult` + `ImageAnalysis`, or `DocumentResult` + `DocumentAnalysis`), stage timings
(`ingestion`, then `vision` or `document_understanding`), the safe error for rejected or failed
runs, and an `EvidenceRecord` for Story 9.3. `understand_fixture` runs a committed fixture's bytes
through the same genuine path, so reviewers can compare it with Story 9.2 playback.

```python
import asyncio

from multimodal_voice_platform.contracts.modality import Modality
from multimodal_voice_platform.contracts.session import SessionConfig
from multimodal_voice_platform.understanding import UnderstandingService

service = UnderstandingService()
session = SessionConfig(session_id="demo")
with open("report.pdf", "rb") as handle:  # the caller reads the upload, never the service
    data = handle.read()
record = asyncio.run(
    service.understand_upload(
        session,
        modality=Modality.DOCUMENT,
        media_type="application/pdf",
        display_name="report.pdf",
        data=data,
    )
)
print(record.model_dump_json(indent=2))
```

## Dependencies

| Package | Version | Purpose | Why this one |
|---|---|---|---|
| `pillow` | 12.3.0 (`>=12.3,<13`) | Decode PNG, JPEG, WebP | JPEG and WebP cannot reasonably be decoded with the standard library; Pillow allows restricting decoders per call and has decompression-bomb protection |
| `pypdf` | 6.19.0 (`>=6.19,<7`) | Parse PDFs and extract text | Pure Python with no required native dependencies; supports in-memory streams and encryption detection |

Both are imported by exactly one source module each, enforced by a governance test.

## Evidence

Story 9.3 evidence is `automated_test`: the suite processes generated PNG, JPEG, WebP, PDF,
Markdown, and text inputs through the real local path with sockets blocked and no credentials.
`UnderstandingRecord` can also emit `deterministic_demo` records for reviewer runs, and rejects every
other evidence class. No `live_integration` evidence exists.

This evidence proves validated ingestion, genuine local image analysis, and genuine local document
extraction and structural analysis. It does not prove model-based vision, semantic document
understanding, or anything reviewer-visible in Streamlit.

## Requirement status

| Requirement | Status | Justification |
|---|---|---|
| SRC-002 Vision models | Partially implemented | Validated image ingestion and genuine local pixel analysis are implemented and tested. No vision model runs, so "use vision models" is not satisfied. Model-based vision is Story 9.8 (live) and needs reviewer-visible evidence (Story 9.9) |
| SRC-004 Document understanding | Partially implemented | Structured extraction and structural understanding of Markdown, text, and PDF are implemented and tested. Semantic understanding and reviewer-visible `deterministic_demo` evidence are not yet delivered |
| ENG-006 Untrusted content never grants authority | Partially implemented | Enforced and tested at runtime for the image and document path. Cross-modal reasoning (9.5) and release acceptance (9.10) remain |

## Out of scope

Audio, speech-to-text, and text-to-speech (9.4); cross-modal reasoning (9.5); voice orchestration
(9.6); WebSocket streaming (9.7); live providers and BYOK (9.8); Streamlit (9.9); release (9.10);
OCR of scanned documents; DOCX and other unlisted formats.
