FROM ghcr.io/astral-sh/uv:0.11.26 AS uv

FROM python:3.12.11-slim-bookworm

COPY --from=uv /uv /uvx /bin/

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    QP_REPO_ROOT=/app \
    QP_RESEARCH_COMMAND=/app/scripts/qp-research \
    PATH=/app/.venv/bin:$PATH

COPY pyproject.toml uv.lock README.md qp_paths.py qp_ofd_continuity.py ./
COPY packages ./packages
COPY specs ./specs
COPY scripts/qp-research ./scripts/qp-research
COPY platform/workers/research-mass-eval/container ./platform/workers/research-mass-eval/container

RUN uv sync --frozen --no-dev && \
    chmod 0555 /app/scripts/qp-research \
      /app/platform/workers/research-mass-eval/container/personal_research_service.py

EXPOSE 8080
CMD ["python", "platform/workers/research-mass-eval/container/personal_research_service.py"]
