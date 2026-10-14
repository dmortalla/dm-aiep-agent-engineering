# Module 9 Architecture

## Status

Frozen by the human-approved Story 9.1 specification (2026-10-14). Reopen only for a genuine
contradiction with the authoritative source or a serious production/security flaw.

This document describes the target architecture. Story 9.1 implements none of the runtime
components below. It provides only the typed contracts in
`src/multimodal_voice_platform/contracts/`. See [CONTRACTS.md](CONTRACTS.md).

## Goal

A production-grade, secure multimodal AI platform that provides a voice-enabled conversational
assistant; image, audio, document, and text processing; vision and document understanding;
cross-modal reasoning; STT and TTS; real-time conversations and voice orchestration; genuine
WebSocket streaming with measured low latency; a deterministic no-key reviewer mode; an explicit
opt-in live-provider mode; and a Streamlit reviewer experience showing real, classified evidence.

## Logical layers

```mermaid
flowchart TB
    subgraph P["1. Presentation (Streamlit)"]
        UI["Voice/audio controls<br/>Image, document, text inputs<br/>Evidence and metrics panels<br/>Built-in reviewer guidance"]
    end
    subgraph I["2. Application interface"]
        SVC["Application service boundary"]
        WS["WebSocket streaming gateway"]
    end
    subgraph C["3. Authoritative application core"]
        SESS["Conversation / session management"]
        ROUTE["Modality routing"]
        VOICE["Voice orchestration"]
        MM["Multimodal orchestration"]
        XR["Cross-modal reasoning"]
        STREAM["Streaming coordination"]
    end
    subgraph PORTS["4. Provider ports"]
        STT["SpeechToTextPort"]
        TTS["TextToSpeechPort"]
        VIS["VisionPort"]
        DOC["DocumentUnderstandingPort"]
        RSN["ReasoningPort"]
    end
    subgraph A["5. Adapters"]
        DET["Deterministic demo adapters<br/>(default, no network, no key)"]
        LIVE["Live provider adapters<br/>(explicit opt-in, allowlisted)"]
    end
    subgraph X["6. Production controls (cross-cutting)"]
        CTRL["Validation · Trust boundaries · Budgets<br/>Structured observability · Evidence classification"]
    end

    UI --> SVC
    UI <--> WS
    SVC --> SESS
    WS --> STREAM
    SESS --> ROUTE
    ROUTE --> VOICE
    ROUTE --> MM
    MM --> XR
    VOICE --> XR
    STREAM --> VOICE
    VOICE --> STT
    VOICE --> TTS
    MM --> VIS
    MM --> DOC
    XR --> RSN
    STT & TTS & VIS & DOC & RSN --> DET
    STT & TTS & VIS & DOC & RSN --> LIVE
    CTRL -.-> I
    CTRL -.-> C
    CTRL -.-> A
```

| Layer | Responsibility | Must not |
|---|---|---|
| Presentation | Collect input, render results, stream events, metrics, evidence, guidance | Hold business logic, call providers directly, persist credentials |
| Application interface | Typed service calls; WebSocket session lifecycle and typed stream protocol | Accept unvalidated payloads; leak internal errors |
| Application core | Sessions, routing, voice and multimodal orchestration, reasoning context, streaming | Trust content or provider output as instructions or authority |
| Provider ports | Typed contracts for STT, TTS, vision, document, reasoning | Expose tool execution or shell access |
| Adapters | Deterministic and live implementations of the ports | Deterministic: touch the network. Live: run without explicit opt-in |
| Production controls | Validation, trust, budgets, observability, evidence | Become a correctness dependency (observability) |

## Trust boundaries

```mermaid
flowchart LR
    U(["Reviewer / user"]) -->|"untrusted uploads, audio, text"| V["Validation &<br/>normalization"]
    V -->|"ModalityInput (UNTRUSTED_EXTERNAL)"| CORE["Application core"]
    CORE -->|"typed request"| AD["Adapter"]
    AD -->|"live mode only, allowlisted host"| EXT[("External provider")]
    EXT -->|"untrusted"| AD
    AD -->|"result (UNTRUSTED_MODEL_OUTPUT)"| CORE
    CFG["Application config<br/>(mode, budgets, allowlist)"] -->|"only source of authority"| CORE
    CRED["Ephemeral credential<br/>(session memory, SecretStr)"] -->|"live mode only"| AD
```

Authority comes only from application configuration and code. Content, transcripts, metadata, and
model output are data. See [SECURITY_THREAT_MODEL.md](SECURITY_THREAT_MODEL.md).

## Voice turn (target flow, Story 9.6/9.7)

```mermaid
sequenceDiagram
    participant UI as Streamlit
    participant WS as WebSocket gateway
    participant V as Voice orchestrator
    participant STT as SpeechToTextPort
    participant R as ReasoningPort
    participant TTS as TextToSpeechPort
    UI->>WS: connect + session config
    WS-->>UI: session_started
    UI->>WS: audio (validated ModalityInput)
    WS->>V: turn
    V->>STT: TranscriptionRequest
    STT-->>V: segments (partial ... final)
    V-->>UI: transcript_partial / transcript_final
    V->>R: ReasoningRequest (transcript + history)
    R-->>V: chunks
    V-->>UI: response_delta ... response_complete
    V->>TTS: SpeechSynthesisRequest
    TTS-->>V: SynthesizedAudio
    V-->>UI: audio_ready
    V-->>UI: metric (per stage, end_to_end)
    WS-->>UI: session_complete
```

## Multimodal workflow (target flow, Story 9.3/9.5)

```mermaid
flowchart LR
    IN["Text / image / audio / document"] --> VAL["Validate + normalize<br/>ModalityInput"]
    VAL --> R{"Modality router"}
    R -->|image| VIS["VisionPort"]
    R -->|document| DOC["DocumentUnderstandingPort"]
    R -->|audio| STT["SpeechToTextPort"]
    R -->|text| TXT["Text passthrough"]
    VIS & DOC & STT & TXT --> CTX["Reasoning context<br/>(all parts untrusted data)"]
    CTX --> RSN["ReasoningPort"]
    RSN --> OUT["Structured result + evidence"]
```

Modality-specific processing always precedes cross-modal reasoning (ADR-009-006).

## Execution modes

| Mode | Default | Network | Credentials | Evidence class produced |
|---|---|---|---|---|
| `deterministic` | Yes | None | None | `automated_test`, `deterministic_demo` |
| `live` | No; explicit opt-in | Allowlisted providers only | Ephemeral, user-supplied | `live_integration` |

Both modes use the same ports and application contracts (ADR-009-004).

## Package layout

```text
module-09/
  pyproject.toml                         standalone project (Python 3.12)
  src/multimodal_voice_platform/
    contracts/                           Story 9.1: typed contracts only
      modality.py   session.py   providers.py
      streaming.py  limits.py    evidence.py   errors.py
    (core/, adapters/, interface/, ui/)  later stories; not created yet
  tests/                                 contract and governance tests
  docs/                                  requirements, architecture, ADRs, governance
```

## Deferred decisions

These are implementation choices left to the owning story. They must fit the frozen architecture.

| Decision | Owning story |
|---|---|
| WebSocket server framework and hosting process | 9.7 |
| Deterministic fixture formats and generation | 9.2 |
| Image/document parsing libraries and magic-byte checks | 9.3 |
| Audio decoding library and sample formats | 9.4 |
| Specific live providers and models | 9.8 |
| Deployment target and packaging | 9.10 |
