"""J-Quants API V2 source.

ToS: data is for personal research; do not redistribute raw payloads. Respect
J-Quants rate limits and terms of use.

Phase 3.5 — the Premium **core** closed-loop filter
(:data:`ingestion.jquants.catalog.PREMIUM_CORE_DATASETS`) is re-exported here
so the existing CLI can target it via ``--dataset premiums`` (mapped to the
filter in :mod:`ingestion.pipeline`).
"""

from .catalog import PREMIUM_CORE_DATASETS, is_premium_core

__all__ = ["PREMIUM_CORE_DATASETS", "is_premium_core"]
