# Multi-stage build for voice-agent.
# Targets Hetzner CX22 (2 vCPU / 4 GB RAM) running Debian-based base.

FROM python:3.11-slim-bookworm AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build
COPY pyproject.toml ./
COPY src ./src

RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --upgrade pip \
 && /opt/venv/bin/pip install .

# -----------------------------------------------------------------------------
FROM python:3.11-slim-bookworm AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        ffmpeg \
        libsndfile1 \
        ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Non-root user — never run the agent as root.
RUN useradd -r -u 1001 -m -d /home/agent agent
USER agent
WORKDIR /home/agent

COPY --from=builder /opt/venv /opt/venv
COPY --chown=agent:agent src ./src
# The Priya system prompt is loaded from this path at runtime.
COPY --chown=agent:agent ../../packages/shared/src/prompts ./packages/shared/src/prompts

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/healthz').read()" || exit 1

CMD ["uvicorn", "voice_agent.server:app", "--host", "0.0.0.0", "--port", "8080"]
