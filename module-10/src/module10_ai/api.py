"""FastAPI transport around the unchanged Story 10.2 application service."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

from module10_ai.config import RuntimeConfig
from module10_ai.errors import ConfigurationError, ContractError, InferenceFailure
from module10_ai.http_boundary import HttpBoundary, error_response, record_failure
from module10_ai.http_config import HttpConfig
from module10_ai.http_schemas import ErrorOutput, HealthOutput, InferenceInput, InferenceOutput
from module10_ai.service import InferenceService


def create_app(
    config: HttpConfig | None = None,
    service: InferenceService | None = None,
) -> FastAPI:
    """Construct an isolated, no-key deterministic HTTP application.

    Args:
        config: Trusted validated HTTP limits, or secure defaults.
        service: Accepted application service; trusted injection supports failure testing.

    Returns:
        FastAPI application with health, inference, and OpenAPI contracts.

    Raises:
        ConfigurationError: HTTP configuration or service contract is invalid.
    """
    settings = HttpConfig() if config is None else config
    if type(settings) is not HttpConfig:
        raise ConfigurationError("Application requires HttpConfig.")
    settings.__post_init__()
    execution = (
        InferenceService(RuntimeConfig(max_text_characters=settings.max_text_characters))
        if service is None
        else service
    )
    if not isinstance(execution, InferenceService):
        raise ConfigurationError("Application requires InferenceService.")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Declare readiness only while the constructed service is accepting work."""
        app.state.ready = True
        try:
            yield
        finally:
            app.state.ready = False

    app = FastAPI(
        title="Module 10 deterministic inference",
        version="1.0.0",
        description="Lexical fixture analysis. No live provider or deployment evidence.",
        lifespan=lifespan,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url=None,
    )
    app.state.ready = False
    app.add_middleware(HttpBoundary, config=settings)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        """Return fixed-size validation errors without attacker-controlled details."""
        return error_response(
            422,
            "invalid_request",
            "Request does not satisfy the input contract.",
            request.state.request_id,
        )

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        """Sanitize routing and JSON parser failures using the same envelope."""
        return error_response(
            exc.status_code,
            "http_error",
            "HTTP request cannot be processed.",
            request.state.request_id,
        )

    @app.get("/health/live", response_model=HealthOutput)
    async def liveness() -> HealthOutput:
        """Report HTTP process liveness without checking dependencies."""
        return HealthOutput(status="alive")

    @app.get("/health/ready", response_model=HealthOutput, responses={503: {"model": HealthOutput}})
    async def readiness() -> HealthOutput | JSONResponse:
        """Report constructed deterministic service lifecycle readiness only."""
        if not app.state.ready:
            return JSONResponse(HealthOutput(status="not-ready").model_dump(), status_code=503)
        return HealthOutput(status="ready")

    errors = {
        status: {"model": ErrorOutput} for status in (400, 408, 413, 415, 422, 431, 500, 503, 504)
    }

    for contract in errors.values():
        contract["headers"] = {
            "X-Request-ID": {
                "schema": {"type": "string"},
                "description": "Validated or generated correlation ID",
            }
        }
    errors[200] = {"headers": errors[422]["headers"]}

    @app.post(
        "/api/v1/inference",
        response_model=InferenceOutput,
        responses=errors,
        description=(
            f"Deterministic lexical analysis; body limit {settings.max_body_bytes} "
            f"bytes, text limit {settings.max_text_characters} characters. "
            "Malformed JSON returns a sanitized 400 or 422. No authentication; "
            "restrict ingress before external exposure. "
        ),
        openapi_extra={
            "parameters": [
                {
                    "name": "X-Request-ID",
                    "in": "header",
                    "required": False,
                    "schema": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": settings.max_request_id_characters,
                        "pattern": "^[A-Za-z0-9_-]+$",
                    },
                    "description": "Malformed or duplicate values are replaced; not identity.",
                }
            ]
        },
    )
    async def inference(
        payload: InferenceInput, request: Request
    ) -> InferenceOutput | JSONResponse:
        """Convert HTTP contracts and invoke the service once under a cooperative deadline."""
        request_id = request.state.request_id
        if not app.state.ready:
            return error_response(503, "not_ready", "Service is not accepting work.", request_id)
        if len(payload.text) > settings.max_text_characters:
            return error_response(
                422, "invalid_request", "Input exceeds configured bounds.", request_id
            )
        deadline = asyncio.timeout(settings.inference_timeout_seconds)
        try:
            async with deadline:
                result = await execution.infer(payload.to_domain())
        except TimeoutError:
            if not deadline.expired():
                raise
            return error_response(
                504, "inference_timeout", "Inference deadline exceeded.", request_id
            )
        except ContractError:
            return error_response(
                422, "invalid_request", "Input violates the application contract.", request_id
            )
        except InferenceFailure as exc:
            record_failure(exc, request_id)
            return error_response(
                503, "inference_unavailable", "Inference could not be completed.", request_id
            )
        return InferenceOutput.from_domain(result, request_id)

    return app
