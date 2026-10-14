"""Story 9.3 local vision tests: real pixel analysis, port conformance, and failure paths."""

import asyncio
import inspect
import time

import pytest
from media_builders import encode, png_header_only, quadrant_image
from PIL import Image

from multimodal_voice_platform.adapters.deterministic import ContentNotFoundError
from multimodal_voice_platform.adapters.deterministic.content_store import SessionContentStore
from multimodal_voice_platform.adapters.local import (
    LOCAL_VISION_ID,
    LocalProcessingLimits,
    LocalVisionProvider,
    MalformedContentError,
    ProcessingLimitError,
    ProcessingTimeoutError,
    UnsupportedContentError,
    analyze_image,
    color_name,
)
from multimodal_voice_platform.adapters.local import providers as local_providers
from multimodal_voice_platform.contracts.errors import ErrorCode
from multimodal_voice_platform.contracts.limits import ResourceBudget
from multimodal_voice_platform.contracts.modality import Modality, ModalityInput, TrustLevel
from multimodal_voice_platform.contracts.providers import ProviderPort, VisionRequest, VisionResult
from multimodal_voice_platform.contracts.session import ExecutionMode
from multimodal_voice_platform.ingestion import MediaMismatchError, stage_content

LIMITS = LocalProcessingLimits.from_budget(ResourceBudget())
SESSION = "sess-vision"


def _request(
    data: bytes, media_type: str, name: str, question: str | None = None
) -> tuple[LocalVisionProvider, VisionRequest]:
    store = SessionContentStore()
    item = stage_content(
        store,
        session_id=SESSION,
        budget=ResourceBudget(),
        modality=Modality.IMAGE,
        media_type=media_type,
        display_name=name,
        data=data,
    )
    return LocalVisionProvider(store, LIMITS), VisionRequest(image=item, question=question)


@pytest.mark.parametrize(
    ("fmt", "media_type", "name", "options"),
    [
        ("PNG", "image/png", "q.png", {}),
        ("WEBP", "image/webp", "q.webp", {"lossless": True}),
        ("JPEG", "image/jpeg", "q.jpg", {"quality": 95}),
    ],
)
def test_quadrant_colors_are_recovered_from_pixels_in_every_format(
    fmt: str, media_type: str, name: str, options: dict[str, object]
) -> None:
    provider, request = _request(encode(quadrant_image(32), fmt, **options), media_type, name)
    output = asyncio.run(provider.inspect(request))
    regions = {region.region: region.color for region in output.analysis.regions}
    assert regions == {
        "top-left": "red",
        "top-right": "green",
        "bottom-left": "blue",
        "bottom-right": "white",
    }
    assert output.analysis.decoder_format == fmt
    assert (output.analysis.width, output.analysis.height) == (32, 32)
    top_four = {c.color for c in output.analysis.dominant_colors[:4]}
    assert top_four == {"red", "green", "blue", "white"}
    assert "Top-left region is mostly red" in output.result.observations[0]


def test_result_is_typed_attributed_untrusted_and_says_no_model_ran() -> None:
    provider, request = _request(encode(quadrant_image(), "PNG"), "image/png", "q.png")
    result = asyncio.run(provider.analyze(request))
    assert isinstance(result, VisionResult)
    assert result.trust is TrustLevel.UNTRUSTED_MODEL_OUTPUT
    assert result.provider == provider.descriptor
    assert result.provider.provider_id == LOCAL_VISION_ID
    assert result.provider.port is ProviderPort.VISION
    assert result.provider.mode is ExecutionMode.DETERMINISTIC
    assert result.description.startswith("16 x 16 pixel PNG image (square)")
    assert result.observations[-1] == local_providers.NO_MODEL_NOTE


def test_analysis_is_reproducible_for_identical_bytes() -> None:
    data = encode(quadrant_image(), "PNG")
    first = analyze_image(data, "image/png", LIMITS)
    second = analyze_image(data, "image/png", LIMITS)
    assert first == second


def test_analysis_reflects_actual_pixels_not_metadata() -> None:
    dark = analyze_image(
        encode(Image.new("RGB", (40, 20), (10, 10, 10)), "PNG"), "image/png", LIMITS
    )
    assert dark.brightness == "dark"
    assert dark.orientation == "landscape"
    assert dark.contrast == "low contrast"
    assert dark.detail == "low detail with large uniform regions"
    assert [c.color for c in dark.dominant_colors] == ["black"]
    noisy = Image.new("L", (20, 40))
    noisy.putdata([255 * ((x + y) % 2) for y in range(40) for x in range(20)])
    checker = analyze_image(encode(noisy, "PNG"), "image/png", LIMITS)
    assert checker.orientation == "portrait"
    assert checker.detail == "high detail"
    assert checker.colorfulness_label == "nearly monochrome"


def test_large_images_are_analyzed_through_a_bounded_thumbnail() -> None:
    analysis = analyze_image(encode(quadrant_image(400), "PNG"), "image/png", LIMITS)
    assert (analysis.width, analysis.height) == (400, 400)
    assert max(analysis.analyzed_width, analysis.analyzed_height) <= 128


def test_transparency_and_animation_are_reported() -> None:
    rgba = Image.new("RGBA", (10, 10), (255, 0, 0, 0))
    analysis = analyze_image(encode(rgba, "PNG"), "image/png", LIMITS)
    assert analysis.has_alpha and analysis.transparent_share == 1.0
    frames = [quadrant_image(), quadrant_image().rotate(90)]
    animated = encode(frames[0], "WEBP", save_all=True, append_images=frames[1:], lossless=True)
    provider, request = _request(animated, "image/webp", "anim.webp")
    output = asyncio.run(provider.inspect(request))
    assert output.analysis.frame_count == 2
    assert any("only the first was analyzed" in line for line in output.result.observations)


def test_questions_are_not_answered_by_pixel_analysis() -> None:
    provider, request = _request(
        encode(quadrant_image(), "PNG"), "image/png", "q.png", question="What animal is this?"
    )
    result = asyncio.run(provider.analyze(request))
    assert any("does not answer questions" in line for line in result.observations)
    assert "animal" not in result.description


@pytest.mark.parametrize(
    ("rgb", "name"),
    [
        ((0, 0, 0), "black"),
        ((255, 255, 255), "white"),
        ((128, 128, 128), "gray"),
        ((255, 0, 0), "red"),
        ((255, 140, 0), "orange"),
        ((120, 60, 10), "brown"),
        ((255, 255, 0), "yellow"),
        ((0, 200, 0), "green"),
        ((0, 255, 255), "cyan"),
        ((0, 0, 255), "blue"),
        ((128, 0, 255), "purple"),
        ((255, 0, 200), "magenta"),
    ],
)
def test_color_naming(rgb: tuple[int, int, int], name: str) -> None:
    assert color_name(*rgb) == name


@pytest.mark.parametrize(
    "data",
    [
        b"\x89PNG\r\n\x1a\n" + b"\x00" * 40,
        encode(quadrant_image(), "PNG")[:60],
        b"\xff\xd8\xff\xe0" + b"garbage" * 10,
        b"RIFF\x10\x00\x00\x00WEBPVP8 junk",
    ],
)
def test_malformed_images_fail_safely_with_a_chained_cause(data: bytes) -> None:
    media_type = {b"\x89P": "image/png", b"\xff\xd8": "image/jpeg", b"RI": "image/webp"}[data[:2]]
    with pytest.raises(MalformedContentError) as caught:
        analyze_image(data, media_type, LIMITS)
    assert caught.value.code is ErrorCode.INPUT_REJECTED
    assert caught.value.__cause__ is not None


def test_only_the_declared_decoder_is_enabled() -> None:
    with pytest.raises(MalformedContentError, match="as JPEG"):
        analyze_image(encode(quadrant_image(), "PNG"), "image/jpeg", LIMITS)
    with pytest.raises(UnsupportedContentError):
        analyze_image(encode(quadrant_image(), "GIF"), "image/gif", LIMITS)


def test_pixel_bombs_are_rejected_from_the_header_before_decoding() -> None:
    with pytest.raises(ProcessingLimitError) as caught:
        analyze_image(png_header_only(20_000, 20_000), "image/png", LIMITS)
    assert caught.value.code is ErrorCode.LIMIT_EXCEEDED
    small = LIMITS.model_copy(update={"max_image_pixels": 100})
    with pytest.raises(ProcessingLimitError):
        analyze_image(encode(quadrant_image(11), "PNG"), "image/png", small)


def test_byte_limit_is_enforced_by_the_adapter_itself() -> None:
    data = encode(quadrant_image(), "PNG")
    with pytest.raises(ProcessingLimitError):
        analyze_image(data, "image/png", LIMITS.model_copy(update={"max_image_bytes": 10}))


def test_unknown_or_released_content_is_rejected() -> None:
    provider, request = _request(encode(quadrant_image(), "PNG"), "image/png", "q.png")
    provider._store.release(SESSION)
    with pytest.raises(ContentNotFoundError):
        asyncio.run(provider.analyze(request))


def test_stored_bytes_are_reverified_against_the_declared_type() -> None:
    store = SessionContentStore()
    data = encode(quadrant_image(), "PNG")
    ref = store.put(SESSION, "forged", b"%PDF-" + b"x" * (len(data) - 5))
    forged = ModalityInput(
        input_id="forged",
        session_id=SESSION,
        modality=Modality.IMAGE,
        media_type="image/png",
        source="user_upload",
        size_bytes=len(data),
        display_name="forged.png",
        content_ref=ref,
    )
    with pytest.raises(MediaMismatchError, match="does not match the declared media type"):
        asyncio.run(LocalVisionProvider(store, LIMITS).analyze(VisionRequest(image=forged)))


def test_processing_is_bounded_by_the_request_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def slow(*_args: object) -> None:
        time.sleep(0.5)

    monkeypatch.setattr(local_providers, "analyze_image", slow)
    store = SessionContentStore()
    _, request = _request(encode(quadrant_image(), "PNG"), "image/png", "q.png")
    provider = LocalVisionProvider(store, LIMITS.model_copy(update={"timeout_s": 0.05}))
    store.put(SESSION, request.image.input_id, encode(quadrant_image(), "PNG"))
    with pytest.raises(ProcessingTimeoutError) as caught:
        asyncio.run(provider.analyze(request))
    assert caught.value.code is ErrorCode.PROVIDER_TIMEOUT
    assert isinstance(caught.value.__cause__, TimeoutError)


def test_adapter_conforms_to_the_vision_port_and_exposes_nothing_else() -> None:
    provider = LocalVisionProvider(SessionContentStore(), LIMITS)
    assert inspect.iscoroutinefunction(provider.analyze)
    assert inspect.iscoroutinefunction(provider.inspect)
    public = {name for name in dir(provider) if not name.startswith("_")}
    assert public == {"descriptor", "analyze", "inspect"}


def test_exif_orientation_is_applied_before_analysis() -> None:
    exif = Image.Exif()
    exif[0x0112] = 6
    rotated = encode(quadrant_image(16).resize((32, 16)), "JPEG", quality=95, exif=exif)
    analysis = analyze_image(rotated, "image/jpeg", LIMITS)
    assert (analysis.width, analysis.height) == (16, 32)
    assert analysis.orientation == "portrait"
