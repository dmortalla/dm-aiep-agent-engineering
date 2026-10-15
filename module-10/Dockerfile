FROM ghcr.io/astral-sh/uv:0.12.5 AS uv
FROM python:3.12.14-slim-bookworm AS builder
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /build
COPY pyproject.toml uv.lock ./
# Dependencies only: no isolated, floating Hatchling build environment is needed.
RUN uv sync --locked --no-dev --no-install-project --no-cache

FROM python:3.12.14-slim-bookworm AS runtime
ENV PATH="/opt/venv/bin:$PATH" PYTHONPATH=/app/src \
    PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN groupadd --gid 10001 service && useradd --uid 10001 --gid service \
    --no-create-home --shell /usr/sbin/nologin service
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY src/module10_ai /app/src/module10_ai
RUN chmod -R a-w /app /opt/venv
USER 10001:10001
EXPOSE 8000
STOPSIGNAL SIGTERM
# Readiness includes the worker lifecycle. Liveness remains a separate endpoint.
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=2).close()"]
CMD ["python", "-m", "uvicorn", "module10_ai.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--timeout-graceful-shutdown", "10", "--no-access-log"]
