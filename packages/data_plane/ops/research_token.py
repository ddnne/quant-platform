"""Env-bound research run token. Not a filesystem or HOME capability."""

from __future__ import annotations

import os


def resolve_research_run_token() -> str | None:
    for env_name in (
        "RESEARCH_RUN_TOKEN",
        "INGESTION_RUN_TOKEN",
        "MASS_EVAL_RUN_TOKEN",
    ):
        value = (os.environ.get(env_name) or "").strip()
        if value:
            return value
    return None


__all__ = ["resolve_research_run_token"]
