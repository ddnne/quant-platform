FROM python:3.12.11-slim-bookworm

# Match the pinned CI bootstrap without another image-registry dependency.
RUN python -m pip install --no-cache-dir --only-binary=:all: uv==0.11.26

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

RUN command -v timeout && \
    uv sync --frozen --no-dev && \
    apt-get update && apt-get install -y --no-install-recommends sqlite3 && \
    rm -rf /var/lib/apt/lists/* && \
    chmod 0555 \
      /app/platform/workers/research-mass-eval/container/personal_research_service.py && \
    PYTHONPATH=/app:/app/platform/workers/research-mass-eval/container \
      python -c "import personal_vol_am_pm_panel_job, personal_research_service, d1_backup_encrypt_job, research, research.experiment_plans, research.phase7_pilot, research.scheduler, agents.mass_research, research.personal_service, execution.paper_service; from scripts.encrypt_d1_backup import _governed_database as gdb; s=gdb('staging'); p=gdb('production'); assert s['id']=='d448d1c6-27c8-4aeb-8702-3e7a8b6bf2bb' and s['name']=='quant-ingest-staging'; assert p['id']=='be6fdcf8-40be-41fc-9535-7facd1fc2ffc' and p['name']=='quant-ingest'"

EXPOSE 8080
# Bound the whole image lifetime, including startup and terminal-upload retries.
# Leave five seconds for TERM before KILL at 180 minutes; no in-image restart.
CMD ["timeout", "--signal=TERM", "--kill-after=5s", "10795s", "python", "platform/workers/research-mass-eval/container/personal_research_service.py"]
