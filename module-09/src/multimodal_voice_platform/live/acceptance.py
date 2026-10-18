"""Minimal real-provider acceptance exercise for Story 9.8. Never run by pytest.

Run it explicitly, once, after every deterministic gate is green::

    uv run python -m multimodal_voice_platform.live.acceptance --confirm-paid-call \\
        --out ../../EVIDENCE/module-09-story-9-8-live-acceptance.json

It makes six small paid calls to the real OpenAI API with project-owned, benign content only:

1. cross-modal workflow: the committed four-quadrant PNG (live vision, call 1) and one committed
   text claim, related by live model reasoning streamed from the provider (call 2);
2. live text-to-speech of one fixed sentence, validated locally as WAV (call 3);
3. one voice turn over a real loopback WebSocket: the step-2 audio is sent as the user's turn,
   transcribed by live speech-to-text (call 4), answered by live reasoning whose reply fragments
   are released as the provider streams them and arrive as ``response_delta`` before
   ``response_complete`` (call 5), and spoken by live text-to-speech, validated locally (call 6).

The API key is read with a hidden prompt (or from one environment variable named with
``--key-env``), held only in memory for the run, and never printed, logged, or written. The
evidence artifact is redacted and checked for the key before it is written.
"""

import argparse
import asyncio
import base64
import getpass
import json
import logging
import re
import sys
import time
from pathlib import Path
from typing import Any, Final

from pydantic import SecretStr
from websockets.asyncio.client import connect

from multimodal_voice_platform.adapters.deterministic.fixtures import FixtureCatalog
from multimodal_voice_platform.adapters.openai import openai_bindings
from multimodal_voice_platform.contracts.evidence import EvidenceClass
from multimodal_voice_platform.contracts.limits import ResourceBudget
from multimodal_voice_platform.contracts.modality import Modality
from multimodal_voice_platform.crossmodal.service import CrossModalWorkflow, ModalitySubmission
from multimodal_voice_platform.interface.server import bound_port, build_server
from multimodal_voice_platform.interface.websocket import GatewaySettings, create_app
from multimodal_voice_platform.live.config import LiveProviderConfig
from multimodal_voice_platform.live.credentials import (
    credential_from_environment,
    live_session,
)
from multimodal_voice_platform.live.errors import LiveCredentialError
from multimodal_voice_platform.live.redaction import RedactingFilter, redact
from multimodal_voice_platform.speech.service import SpeechService
from multimodal_voice_platform.streaming.coordinator import StreamingVoiceCoordinator
from multimodal_voice_platform.understanding.service import UnderstandingService
from multimodal_voice_platform.voice.fixtures import load_voice_catalog
from multimodal_voice_platform.voice.orchestrator import VoiceAssistant

LIVE: Final = EvidenceClass.LIVE_INTEGRATION
IMAGE_FIXTURE: Final = "image-quadrants"
TEXT_CLAIM: Final = "The top-left quadrant of the image is red."
SPOKEN: Final = "Please remember that the project code word is falcon."
PLANNED_CALLS: Final = 6
NOTICE: Final = f"""Story 9.8 live acceptance
This makes {PLANNED_CALLS} real, paid OpenAI API calls (small: one tiny image, a few short
sentences, about one second of speech in and out) and sends project-owned fixture content to
OpenAI: the committed four-quadrant test image, one fixed text claim, and one fixed spoken
sentence. No other data is sent. Automatic retries are off. Nothing is persisted except the
redacted evidence file you name with --out."""


def _budget() -> ResourceBudget:
    return ResourceBudget(
        request_timeout_s=45.0,
        session_timeout_s=300.0,
        max_output_tokens=1_200,
        max_provider_calls_per_session=8,
        max_retries=0,
        max_audio_bytes=2 * 1024 * 1024,
    )


def _words(text: str) -> list[str]:
    """Normalize the fixed acceptance sentence for transcript comparison."""
    normalized = re.sub(r"\bcodeword\b", "code word", text.lower())
    return re.findall(r"[a-z0-9]+", normalized)


def _call_view(call: Any) -> dict[str, Any]:
    return call.model_dump(mode="json")


async def _cross_modal(key: SecretStr, config: LiveProviderConfig) -> dict[str, Any]:
    bindings = openai_bindings(config)
    catalog = FixtureCatalog.load_default()
    workflow = CrossModalWorkflow(
        catalog,
        understanding=UnderstandingService(catalog, live_vision=bindings.vision),
        speech=SpeechService(catalog, live=bindings.speech),
        live_reasoning=bindings.cross_modal,
    )
    session = live_session("acc-crossmodal", key, budget=_budget())
    record = await workflow.run(
        session,
        [
            ModalitySubmission(modality=Modality.TEXT, text=TEXT_CLAIM),
            ModalitySubmission(
                modality=Modality.IMAGE,
                media_type="image/png",
                display_name="image-quadrants.png",
                data=catalog.content(IMAGE_FIXTURE),
            ),
        ],
        evidence_class=LIVE,
    )
    image = next((o.understanding for o in record.outcomes if o.understanding is not None), None)
    vision = image.model_vision if image is not None else None
    local = image.image_analysis if image is not None else None
    reasoning_calls = [c for c in record.live_calls if c.capability.value == "reasoning"]
    return {
        "status": record.status.value,
        "error": record.error.model_dump(mode="json") if record.error else None,
        "evidence_class": record.evidence.evidence_class.value,
        "vision": {
            "succeeded": vision is not None,
            "model_description": vision.description if vision else None,
            "model_observations": list(vision.observations) if vision else [],
            "local_top_left_region": (
                next((r.color for r in local.regions if r.region == "top_left"), None)
                if local
                else None
            ),
            "evidence_class": image.evidence.evidence_class.value if image else None,
        },
        "reasoning": {
            "succeeded": record.model_inference_performed,
            "findings": [f.model_dump(mode="json") for f in record.findings],
            "conclusion": record.conclusion.model_dump(mode="json") if record.conclusion else None,
            "streamed": any(c.streamed for c in reasoning_calls),
            "provider_output_events": sum(c.output_events for c in reasoning_calls),
        },
        "calls": [_call_view(c) for c in record.all_live_calls()],
    }


async def _speech(key: SecretStr, config: LiveProviderConfig) -> tuple[dict[str, Any], bytes]:
    bindings = openai_bindings(config)
    service = SpeechService(load_voice_catalog(), live=bindings.speech)
    session = live_session("acc-tts", key, budget=_budget())
    record = await service.synthesize_text(session, SPOKEN, evidence_class=LIVE)
    audio = record.synthesis.wav_bytes if record.synthesis is not None else b""
    return (
        {
            "status": record.status.value,
            "error": record.error.model_dump(mode="json") if record.error else None,
            "evidence_class": record.evidence.evidence_class.value,
            "speech_synthesis_performed": record.speech_synthesis_performed,
            "local_validation": record.audio.model_dump(mode="json") if record.audio else None,
            "audio_sha256": record.synthesis.audio_sha256 if record.synthesis else None,
            "calls": [_call_view(c) for c in record.live_calls],
        },
        audio,
    )


async def _voice_turn(key: SecretStr, config: LiveProviderConfig, audio: bytes) -> dict[str, Any]:
    bindings = openai_bindings(config)
    catalog = load_voice_catalog()
    voice = VoiceAssistant(
        catalog,
        speech=SpeechService(catalog, live=bindings.speech),
        live_reasoning=bindings.conversation,
    )
    coordinator = StreamingVoiceCoordinator(
        voice,
        budget=_budget(),
        live_reply=bindings.conversation,
        live_credential=lambda: key,
    )
    app = create_app(coordinator, settings=GatewaySettings(evidence_class=LIVE))
    server = build_server(app, host="127.0.0.1", port=0)
    task = asyncio.create_task(server.serve())
    events: list[dict[str, Any]] = []
    try:
        while not server.started:
            if task.done():
                raise RuntimeError("the loopback gateway failed to start")
            await asyncio.sleep(0.02)
        url = f"ws://127.0.0.1:{bound_port(server)}/ws/voice"
        sent = 0.0
        async with connect(url, max_size=2**20) as ws:
            message = {
                "type": "voice_turn",
                "turn_id": "turn-1",
                "media_type": "audio/wav",
                "display_name": "spoken.wav",
                "audio_base64": base64.b64encode(audio).decode("ascii"),
            }
            while True:
                event = json.loads(await asyncio.wait_for(ws.recv(), 120))
                event["client_elapsed_ms"] = round((time.perf_counter() - sent) * 1000, 3)
                events.append(event)
                if event["type"] == "metric" and event.get("stage") == "session_setup":
                    sent = time.perf_counter()
                    await ws.send(json.dumps(message))
                if event["type"] == "turn_complete":
                    events.append(json.loads(await asyncio.wait_for(ws.recv(), 30)))
                    break
            await ws.send(json.dumps({"type": "end_session"}))
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, 30)
    order = [e["type"] for e in events]
    transcript = next((e["text"] for e in events if e["type"] == "transcript_final"), "")
    deltas = [e for e in events if e["type"] == "response_delta"]
    complete = order.index("response_complete") if "response_complete" in order else None
    first_delta = order.index("response_delta") if deltas else None
    return {
        "event_order": order,
        "transcript": transcript,
        "transcript_matches_spoken_sentence": _words(transcript) == _words(SPOKEN),
        "response_deltas": [e["text"] for e in deltas],
        "delta_before_complete": (
            first_delta is not None and complete is not None and first_delta < complete
        ),
        "turn_complete": next((e for e in events if e["type"] == "turn_complete"), None),
        "metrics": [e for e in events if e["type"] == "metric"],
        "errors": [e for e in events if e["type"] == "error"],
    }


async def _exercise(key: SecretStr) -> dict[str, Any]:
    config = LiveProviderConfig()
    started = time.perf_counter()
    cross_modal = await _cross_modal(key, config)
    tts, audio = await _speech(key, config)
    voice = await _voice_turn(key, config, audio) if audio else {"skipped": "no TTS audio"}
    turn = voice.get("turn_complete") or {}
    return {
        "story": "9.8",
        "kind": "live_acceptance",
        "provider_family": "openai",
        "configuration": config.model_dump(mode="json"),
        "planned_calls": PLANNED_CALLS,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        "A_vision": cross_modal["vision"],
        "C_cross_modal_reasoning": cross_modal["reasoning"],
        "cross_modal_run": {
            k: cross_modal[k] for k in ("status", "error", "evidence_class", "calls")
        },
        "D_text_to_speech": tts,
        "B_C_D_E_streamed_voice_turn": voice,
        "established": {
            "A_vision": cross_modal["vision"]["succeeded"]
            and cross_modal["vision"]["evidence_class"] == LIVE.value,
            "B_speech_to_text": turn.get("stt_processing") == "speech_recognition"
            and voice.get("transcript_matches_spoken_sentence") is True,
            "C_model_reasoning": cross_modal["reasoning"]["succeeded"]
            and turn.get("reasoning_processing") == "model_inference",
            "D_text_to_speech": tts["speech_synthesis_performed"]
            and turn.get("tts_processing") == "speech_synthesis",
            "E_provider_streaming": voice.get("delta_before_complete") is True
            and turn.get("committed") is True,
        },
        "credential_recorded": False,
    }


def _key(args: argparse.Namespace) -> SecretStr:
    if args.key_env:
        return credential_from_environment(args.key_env)
    value = getpass.getpass("OpenAI API key (input hidden, not stored): ")
    return SecretStr(value.strip())


def main(argv: list[str] | None = None) -> int:
    """Run the live acceptance exercise.

    Args:
        argv: Command-line arguments.

    Returns:
        Process exit code: 0 when every capability was established, 1 otherwise, 2 on refusal.
    """
    parser = argparse.ArgumentParser(description="Story 9.8 minimal live acceptance (paid).")
    parser.add_argument("--confirm-paid-call", action="store_true", required=False)
    parser.add_argument("--key-env", default=None, help="read the key from this variable")
    parser.add_argument("--out", type=Path, required=True, help="evidence JSON to write")
    args = parser.parse_args(argv)
    print(NOTICE)
    if not args.confirm_paid_call:
        print("Refused: pass --confirm-paid-call to authorize the paid calls.")
        return 2
    try:
        key = _key(args)
        live_session("acc-check", key)
    except LiveCredentialError as exc:
        print(f"Refused: {exc.safe_message}")
        return 2
    redactor = RedactingFilter([key])
    logging.getLogger().addFilter(redactor)
    for handler in logging.getLogger().handlers:
        handler.addFilter(redactor)
    try:
        artifact = asyncio.run(_exercise(key))
    except Exception as exc:  # The run's boundary: report safely, never the raw exception.
        print(f"Live acceptance aborted: {type(exc).__name__}: {redact(str(exc), [key])}")
        return 1
    text = redact(json.dumps(artifact, indent=2, ensure_ascii=False), [key])
    if key.get_secret_value() in text:
        print("Refused to write evidence: the credential appeared in it.")
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text + "\n", encoding="utf-8")
    established = artifact["established"]
    for name, ok in established.items():
        print(f"{name}: {'established' if ok else 'NOT established'}")
    print(f"Evidence written to {args.out}")
    return 0 if all(established.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
