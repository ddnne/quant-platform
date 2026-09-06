"""Wrangler worker deploy process. Not a signing or READY authority."""

from __future__ import annotations

import subprocess
from pathlib import Path


DEFAULT_RESEARCH_WORKER_URL = (
    "https://quant-platform-research-mass-eval.taku-haga.workers.dev"
)


class WranglerDeployError(ValueError):
    """Pinned wrangler deploy failed closed."""


def deploy_wrangler_worker(
    *,
    wrangler: str | Path,
    config: str | Path,
    cwd: str | Path,
    timeout: int = 300,
) -> str:
    wr = Path(wrangler)
    cfg = Path(config)
    if not wr.is_file():
        raise WranglerDeployError(f"wrangler not found: {wr}")
    if not cfg.is_file():
        raise WranglerDeployError(f"worker config missing: {cfg}")
    proc = subprocess.run(
        [str(wr), "deploy", f"--config={cfg}"],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(cwd),
    )
    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    if proc.returncode != 0:
        raise WranglerDeployError(
            f"wrangler deploy failed rc={proc.returncode}: {combined[-2000:]}"
        )
    return combined
