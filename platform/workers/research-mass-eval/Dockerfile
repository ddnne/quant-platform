FROM ghcr.io/astral-sh/uv:0.11.26 AS uv

FROM python:3.12.11-slim-bookworm

COPY --from=uv /uv /uvx /bin/

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    QP_REPO_ROOT=/app \
    PATH=/app/.venv/bin:$PATH

COPY pyproject.toml uv.lock README.md qp_paths.py qp_ofd_continuity.py ./
COPY scripts/qp-research ./scripts/qp-research
COPY scripts/encrypt_d1_backup.py scripts/cloudflare_d1_migration_manifest.py ./scripts/
COPY packages ./packages
COPY specs ./specs
COPY platform/workers/research-mass-eval/container ./platform/workers/research-mass-eval/container

RUN uv sync --frozen --no-dev && \
    apt-get update && apt-get install -y --no-install-recommends sqlite3 && \
    rm -rf /var/lib/apt/lists/* && \
    chmod 0555 \
      /app/platform/workers/research-mass-eval/container/personal_research_service.py && \
    PYTHONPATH=/app:/app/platform/workers/research-mass-eval/container \
      python -c "from pathlib import Path; import importlib.util; assert not Path('/app/packages/product/research/offline').exists(); assert not Path('/app/packages/product/research/unique_logic').exists(); assert importlib.util.find_spec('research.offline') is None; assert importlib.util.find_spec('research.unique_logic') is None; import personal_vol_am_pm_panel_job, personal_research_service, d1_backup_encrypt_job, research, research.experiment_plans, research.phase7_pilot, research.scheduler, agents.mass_research, research.personal_service, execution.paper_service; from scripts.encrypt_d1_backup import _governed_database as gdb; s=gdb('staging'); p=gdb('production'); assert s['id']=='d448d1c6-27c8-4aeb-8702-3e7a8b6bf2bb' and s['name']=='quant-ingest-staging'; assert p['id']=='be6fdcf8-40be-41fc-9535-7facd1fc2ffc' and p['name']=='quant-ingest'"

EXPOSE 8080
CMD ["python", "platform/workers/research-mass-eval/container/personal_research_service.py"]
