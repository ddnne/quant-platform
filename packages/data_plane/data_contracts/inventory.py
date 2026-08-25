"""Source / endpoint inventory derived only from the canonical registry.

Remote Ops and CLI status surfaces must use this module (or generated artifacts
from it) so membership is never hand-duplicated.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from data_contracts.canonical import (
    CANONICAL_REGISTRY_PATH,
    all_canonical_datasets,
    canonical_dataset_for,
    governed_datasets,
)
from data_contracts.coverage import coverage_contract_for
from data_contracts.source_capability import source_capability_contract_or_none

INVENTORY_STATUSES = frozenset(
    {
        "GOVERNED",
        "EXPERIMENTAL",
        "DISABLED",
        "UNAVAILABLE_BY_PLAN",
        "UNVERIFIED_ENDPOINT",
    }
)


def _load_raw() -> list[dict[str, Any]]:
    document = json.loads(CANONICAL_REGISTRY_PATH.read_text(encoding="utf-8"))
    datasets = document.get("datasets")
    if not isinstance(datasets, list):
        raise ValueError("canonical registry datasets must be an array")
    return [row for row in datasets if isinstance(row, dict)]


def source_inventory(*, as_of: str | None = None) -> dict[str, Any]:
    """Return the full known endpoint inventory (metadata only)."""
    rows = _load_raw()
    items = []
    for row in rows:
        dataset_id = str(row.get("dataset_id") or "")
        canonical = canonical_dataset_for(dataset_id)
        capability = source_capability_contract_or_none(dataset_id)
        try:
            coverage = coverage_contract_for(dataset_id)
        except KeyError:
            coverage = None
        status = str(row.get("inventory_status") or (
            "GOVERNED" if row.get("governance_tier") == "governed" else "EXPERIMENTAL"
        ))
        if status not in INVENTORY_STATUSES:
            status = "UNVERIFIED_ENDPOINT"
        collection_window = None
        available_at = None
        if capability is not None:
            collection_window = {
                "grain": capability.collection_window.grain,
                "open": capability.collection_window.open,
                "close": capability.collection_window.close,
            }
            available_at = {
                "policy": capability.available_at.policy,
                "field": capability.available_at.field,
                "known_publication_lag": (
                    capability.available_at.known_publication_lag
                ),
            }
        items.append(
            {
                "dataset": canonical.dataset_id,
                "source": canonical.source,
                "endpoint": (
                    capability.upstream_locator
                    if capability is not None
                    else row.get("path")
                    or canonical.contracts.get("primary")
                ),
                "tier": canonical.governance_tier,
                "inventory_status": status,
                "enabled": bool(row.get("enabled", True)),
                "entitlement": row.get("entitlement"),
                "collection_window": collection_window,
                "history_target": (
                    coverage.history_target_start if coverage is not None else None
                ),
                "research_eligible": bool(
                    capability is not None
                    and capability.historical_research_eligible
                ),
                "available_at": available_at,
                "sla": row.get("sla") or {},
                "reason": row.get("reason"),
            }
        )
    by_status: dict[str, int] = {}
    for item in items:
        by_status[item["inventory_status"]] = by_status.get(item["inventory_status"], 0) + 1
    return {
        "plane": "ops_current",
        "mutable": True,
        "as_of": as_of or datetime.now(timezone.utc).isoformat(),
        "total_known_endpoints": len(items),
        "governed_count": len(governed_datasets()),
        "status_counts": by_status,
        "datasets": items,
    }


def endpoint_status(dataset_id: str) -> dict[str, Any]:
    inventory = source_inventory()
    for item in inventory["datasets"]:
        if item["dataset"] == dataset_id:
            return {"plane": "ops_current", "mutable": True, "endpoint": item}
    raise KeyError(f"unknown endpoint dataset_id: {dataset_id!r}")


def collection_sla_status(dataset_id: str | None = None) -> dict[str, Any]:
    inventory = source_inventory()
    rows = inventory["datasets"]
    if dataset_id is not None:
        rows = [r for r in rows if r["dataset"] == dataset_id]
        if not rows:
            raise KeyError(dataset_id)
    return {
        "plane": "ops_current",
        "mutable": True,
        "datasets": [
            {
                "dataset": r["dataset"],
                "sla": r.get("sla") or {},
                "collection_window": r.get("collection_window"),
                "inventory_status": r["inventory_status"],
            }
            for r in rows
        ],
    }


def projection_status(meta: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Describe projection freshness. Caller may inject DB/meta fields."""
    meta = dict(meta or {})
    generated_at = meta.get("projection_generated_at")
    status = meta.get("projection_status") or (
        "AVAILABLE" if generated_at else "MISSING"
    )
    return {
        "plane": "ops_current",
        "mutable": True,
        "projection_status": status,
        "projection_generated_at": generated_at,
        "projection_source_generation": meta.get("projection_source_generation"),
        "projection_age_seconds": meta.get("projection_age_seconds"),
        "stale": bool(meta.get("stale", status in {"MISSING", "STALE"})),
        "reason": meta.get("reason"),
    }


__all__ = [
    "INVENTORY_STATUSES",
    "collection_sla_status",
    "endpoint_status",
    "projection_status",
    "source_inventory",
]
