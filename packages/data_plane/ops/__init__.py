"""Ops control-plane helpers (projection metadata, backfill planner, etc.)."""

from __future__ import annotations

from importlib import import_module


_EXPORT_MODULES = {
    "BackfillJob": ".backfill_planner",
    "BackfillPlan": ".backfill_planner",
    "BackfillPlanner": ".backfill_planner",
    "RangeBatchScheduler": ".range_batch_scheduler",
    "SchedulerConfig": ".range_batch_scheduler",
    "TRACK_A_DATASETS": ".range_batch_scheduler",
    "plan_and_queue": ".range_batch_scheduler",
}


def __getattr__(name: str):
    """Keep trust-domain imports from loading the backfill scheduler."""
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(name)
    value = getattr(import_module(module_name, __name__), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))

__all__ = [
    "BackfillJob",
    "BackfillPlan",
    "BackfillPlanner",
    "RangeBatchScheduler",
    "SchedulerConfig",
    "TRACK_A_DATASETS",
    "plan_and_queue",
]
