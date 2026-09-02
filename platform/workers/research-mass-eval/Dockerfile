FROM ghcr.io/astral-sh/uv:0.11.26 AS uv

FROM python:3.12.11-slim-bookworm

COPY --from=uv /uv /uvx /bin/

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    QP_REPO_ROOT=/app \
    PATH=/app/.venv/bin:$PATH

COPY pyproject.toml uv.lock README.md qp_paths.py qp_ofd_continuity.py ./
COPY packages ./packages
COPY specs ./specs
COPY platform/workers/research-mass-eval/container ./platform/workers/research-mass-eval/container

RUN uv sync --frozen --no-dev && \
    chmod 0555 \
      /app/platform/workers/research-mass-eval/container/personal_research_service.py && \
    PYTHONPATH=/app/platform/workers/research-mass-eval/container \
      python -c "import personal_research_service"

EXPOSE 8080
CMD ["python", "platform/workers/research-mass-eval/container/personal_research_service.py"]
