"""READY-snapshot adapter used by the Quant Data Access MCP.

This module deliberately exposes domain operations, never SQL, filesystem
paths, R2 listing, ingestion, approval, publication, or deletion.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import asdict, dataclass, fields
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

import features
import pit
from pit.query import normalize_as_of
from data_contracts import (
    all_contracts,
    contract_for,
    coverage_contract_for,
)
from paper_runtime.snapshot import (
    describe_snapshot as describe_ready_snapshot,
    latest_ready_snapshot as find_latest_ready_snapshot,
    list_ready_snapshots,
)
from storage.coverage_ledger import (
    coverage_gaps as read_coverage_gaps,
    coverage_summary as read_coverage_summary,
    read_dataset_coverage,
)


DEFAULT_SNAPSHOT_DIR = Path("data/research_snapshots")


def _jsonable(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


@dataclass(frozen=True)
class QuantDataConfig:
    snapshot_dir: Path = DEFAULT_SNAPSHOT_DIR
    allowed_datasets: frozenset[str] | None = None
    allowed_features: frozenset[tuple[str, str]] | None = None
    max_rows: int = 1_000
    default_page_size: int = 200
    max_date_span_days: int = 3_660
    daily_row_quota: int = 25_000

    def __post_init__(self) -> None:
        if not 1 <= self.default_page_size <= self.max_rows:
            raise ValueError("default_page_size must be within max_rows")
        if min(self.max_rows, self.max_date_span_days, self.daily_row_quota) < 1:
            raise ValueError("data-access limits must be positive")


class _DailyQuota:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.day = datetime.now(timezone.utc).date()
        self.used = 0

    def charge(self, rows: int) -> dict[str, int]:
        today = datetime.now(timezone.utc).date()
        if today != self.day:
            self.day = today
            self.used = 0
        if self.used + rows > self.limit:
            raise PermissionError("daily Quant Data Access row quota exceeded")
        self.used += rows
        return {"used": self.used, "remaining": self.limit - self.used}


class QuantDataAccess:
    """Policy adapter whose only fact source is an immutable READY snapshot."""

    def __init__(self, config: QuantDataConfig | None = None) -> None:
        self.config = config or QuantDataConfig()
        contracts = {item.dataset_id for item in all_contracts()}
        dataset_allowlist = (
            contracts
            if self.config.allowed_datasets is None
            else self.config.allowed_datasets
        )
        self._datasets = contracts.intersection(dataset_allowlist)
        registered = {
            (item.id, str(item.version)) for item in features.list_features()
            if item.status == "approved"
        }
        feature_allowlist = (
            registered
            if self.config.allowed_features is None
            else self.config.allowed_features
        )
        self._features = registered.intersection(feature_allowlist)
        self._quota = _DailyQuota(self.config.daily_row_quota)

    def _snapshot(self, snapshot_id: str | None = None):
        if snapshot_id is None:
            snapshot = find_latest_ready_snapshot(self.config.snapshot_dir)
        else:
            snapshot = describe_ready_snapshot(self.config.snapshot_dir, snapshot_id)
        if snapshot is None:
            raise FileNotFoundError("no READY research snapshot is published")
        return snapshot

    def _require_dataset(self, dataset: str) -> str:
        value = str(dataset).strip()
        if value not in self._datasets:
            raise PermissionError(f"dataset is not allowlisted: {value!r}")
        return value

    @staticmethod
    def _require_as_of(as_of: Any) -> str:
        return normalize_as_of(as_of)

    def _date_window(
        self, as_of: str, start: str | None, end: str | None
    ) -> tuple[str, str]:
        upper = date.fromisoformat((end or as_of[:10])[:10])
        lower = date.fromisoformat((start or upper.isoformat())[:10])
        if lower > upper:
            raise ValueError("start must be on or before end")
        if (upper - lower).days > self.config.max_date_span_days:
            raise ValueError(
                f"date window exceeds {self.config.max_date_span_days} days"
            )
        return lower.isoformat(), upper.isoformat()

    @staticmethod
    def _request_hash(payload: Mapping[str, Any]) -> str:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def _page(
        self,
        rows: list[dict[str, Any]],
        *,
        request: Mapping[str, Any],
        page_size: int | None,
        page_token: str | None,
    ) -> dict[str, Any]:
        size = self.config.default_page_size if page_size is None else int(page_size)
        if not 1 <= size <= self.config.max_rows:
            raise ValueError(f"page_size must be between 1 and {self.config.max_rows}")
        request_hash = self._request_hash({**request, "page_size": size})
        offset = 0
        if page_token:
            try:
                decoded = json.loads(
                    base64.urlsafe_b64decode(page_token.encode("ascii")).decode("utf-8")
                )
                offset = int(decoded["offset"])
                if decoded["request_hash"] != request_hash or offset < 0:
                    raise ValueError
            except Exception as exc:
                raise ValueError("invalid or mismatched page_token") from exc
        page = rows[offset : offset + size]
        next_offset = offset + len(page)
        next_token = None
        if next_offset < len(rows):
            token = {"offset": next_offset, "request_hash": request_hash}
            next_token = base64.urlsafe_b64encode(
                json.dumps(token, separators=(",", ":")).encode("utf-8")
            ).decode("ascii")
        quota = self._quota.charge(len(page))
        return {
            "rows": page,
            "returned": len(page),
            "next_page_token": next_token,
            "quota": quota,
        }

    def list_datasets(self) -> dict[str, Any]:
        return {
            "datasets": [self.describe_dataset(item) for item in sorted(self._datasets)]
        }

    def describe_dataset(self, dataset: str) -> dict[str, Any]:
        dataset = self._require_dataset(dataset)
        definition = contract_for(dataset)
        contract = {
            item.name: _jsonable(getattr(definition, item.name))
            for item in fields(definition)
        }
        return {
            "dataset": contract,
            "collection_coverage": asdict(coverage_contract_for(dataset)),
        }

    def coverage_summary(self, snapshot_id: str | None = None) -> dict[str, Any]:
        snapshot = self._snapshot(snapshot_id)
        return {
            "snapshot_id": snapshot.snapshot_id,
            **read_coverage_summary(snapshot.db_path),
        }

    def dataset_coverage(
        self, dataset: str, snapshot_id: str | None = None
    ) -> dict[str, Any]:
        dataset = self._require_dataset(dataset)
        snapshot = self._snapshot(snapshot_id)
        rows = read_dataset_coverage(snapshot.db_path, dataset=dataset)
        return {"snapshot_id": snapshot.snapshot_id, "coverage": rows[0] if rows else None}

    def coverage_gaps(self, snapshot_id: str | None = None) -> dict[str, Any]:
        snapshot = self._snapshot(snapshot_id)
        rows = [
            row for row in read_coverage_gaps(snapshot.db_path)
            if row["dataset"] in self._datasets
        ]
        return {"snapshot_id": snapshot.snapshot_id, "gaps": rows}

    def latest_ready_snapshot(self) -> dict[str, Any]:
        snapshot = self._snapshot()
        return self._snapshot_public(snapshot)

    @staticmethod
    def _snapshot_public(snapshot: Any) -> dict[str, Any]:
        return {
            "snapshot_id": snapshot.snapshot_id,
            "state": snapshot.manifest.get("state"),
            "committed_at": snapshot.manifest.get("committed_at"),
            "contract_version": snapshot.manifest.get("contract_version"),
            "source_run": snapshot.manifest.get("source_run"),
            "change_seq": snapshot.manifest.get("change_seq"),
            "coverage_policy_version": snapshot.manifest.get("coverage_policy_version"),
            "quality_policy_version": snapshot.manifest.get("quality_policy_version"),
            "dataset_watermarks": snapshot.manifest.get("dataset_watermarks", []),
        }

    def describe_snapshot(self, snapshot_id: str) -> dict[str, Any]:
        return self._snapshot_public(self._snapshot(snapshot_id))

    def diff_snapshots(self, from_snapshot_id: str, to_snapshot_id: str) -> dict[str, Any]:
        left = self._snapshot(from_snapshot_id)
        right = self._snapshot(to_snapshot_id)
        left_marks = {row["dataset"]: row for row in left.manifest.get("dataset_watermarks", [])}
        right_marks = {row["dataset"]: row for row in right.manifest.get("dataset_watermarks", [])}
        changed = []
        for dataset in sorted(set(left_marks) | set(right_marks)):
            if left_marks.get(dataset) != right_marks.get(dataset):
                changed.append({
                    "dataset": dataset,
                    "from": left_marks.get(dataset),
                    "to": right_marks.get(dataset),
                })
        return {
            "from_snapshot_id": left.snapshot_id,
            "to_snapshot_id": right.snapshot_id,
            "change_seq_delta": int(right.manifest.get("change_seq", 0)) - int(left.manifest.get("change_seq", 0)),
            "changed_watermarks": changed,
        }

    def quality_summary(self, snapshot_id: str | None = None) -> dict[str, Any]:
        snapshot = self._snapshot(snapshot_id)
        quality = snapshot.manifest.get("quality", {})
        return {
            "snapshot_id": snapshot.snapshot_id,
            "state": snapshot.manifest.get("state"),
            "quality_policy_version": snapshot.manifest.get("quality_policy_version"),
            "quality": quality,
        }

    def quality_failures(self, snapshot_id: str | None = None) -> dict[str, Any]:
        summary = self.quality_summary(snapshot_id)
        quality = summary.get("quality") or {}
        failures = quality.get("failures", []) if isinstance(quality, dict) else []
        return {**summary, "failures": failures}

    def query_dataset(
        self,
        *,
        dataset: str,
        as_of: Any,
        snapshot_id: str | None = None,
        code: str | None = None,
        start: str | None = None,
        end: str | None = None,
        page_size: int | None = None,
        page_token: str | None = None,
    ) -> dict[str, Any]:
        dataset = self._require_dataset(dataset)
        as_of_iso = self._require_as_of(as_of)
        start_day, end_day = self._date_window(as_of_iso, start, end)
        snapshot = self._snapshot(snapshot_id)
        result = pit.get_jquants_records(
            as_of=as_of_iso,
            dataset=dataset,
            code=code,
            from_event=start_day,
            to_event=end_day + "T23:59:59+09:00",
            db_path=snapshot.db_path,
        )
        request = {
            "snapshot_id": snapshot.snapshot_id,
            "dataset": dataset,
            "as_of": as_of_iso,
            "code": code,
            "start": start_day,
            "end": end_day,
        }
        page = self._page(
            result.rows,
            request=request,
            page_size=page_size,
            page_token=page_token,
        )
        return {**request, **page}

    def get_series(
        self,
        *,
        dataset: str,
        as_of: Any,
        code: str,
        value_field: str,
        snapshot_id: str | None = None,
        start: str | None = None,
        end: str | None = None,
        page_size: int | None = None,
        page_token: str | None = None,
    ) -> dict[str, Any]:
        result = self.query_dataset(
            dataset=dataset,
            as_of=as_of,
            snapshot_id=snapshot_id,
            code=code,
            start=start,
            end=end,
            page_size=page_size,
            page_token=page_token,
        )
        points = []
        for row in result.pop("rows"):
            payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
            points.append({
                "event_time": row.get("event_time"),
                "available_at": row.get("available_at"),
                "value": payload.get(value_field),
                "natural_key": row.get("natural_key"),
            })
        return {**result, "value_field": value_field, "points": points}

    def compute_feature(
        self,
        *,
        feature_id: str,
        version: str,
        as_of: Any,
        params: Mapping[str, Any],
        snapshot_id: str | None = None,
    ) -> dict[str, Any]:
        key = (str(feature_id), str(version))
        if key not in self._features:
            raise PermissionError(f"feature version is not allowlisted: {key!r}")
        definition = features.get_for_strategy(*key)
        snapshot = self._snapshot(snapshot_id)
        output = features.compute(
            definition,
            as_of=self._require_as_of(as_of),
            db_path=snapshot.db_path,
            **dict(params),
        )
        metadata = dict(output.metadata)
        metadata.pop("db_path", None)
        self._quota.charge(1)
        return {
            "snapshot_id": snapshot.snapshot_id,
            "feature_id": key[0],
            "version": key[1],
            "value": _jsonable(output.value),
            "metadata": _jsonable(metadata),
        }

    def compute_features(
        self,
        *,
        features: list[Mapping[str, Any]],
        as_of: Any,
        snapshot_id: str | None = None,
    ) -> dict[str, Any]:
        if not 1 <= len(features) <= 50:
            raise ValueError("features must contain between 1 and 50 calls")
        return {
            "results": [
                self.compute_feature(
                    feature_id=str(item["id"]),
                    version=str(item["version"]),
                    params=dict(item.get("params", {})),
                    as_of=as_of,
                    snapshot_id=snapshot_id,
                )
                for item in features
            ]
        }

    def raw_manifest(
        self, dataset: str, snapshot_id: str | None = None
    ) -> dict[str, Any]:
        dataset = self._require_dataset(dataset)
        snapshot = self._snapshot(snapshot_id)
        manifests = snapshot.manifest.get("raw_manifests", {})
        item = manifests.get(dataset) if isinstance(manifests, dict) else None
        source_run = snapshot.manifest.get("source_run", {})
        run_id = source_run.get("id") if isinstance(source_run, dict) else None
        reference = item or (
            {"key": f"raw/{dataset}/{run_id}/manifest.json", "verified": False}
            if run_id is not None else None
        )
        return {
            "snapshot_id": snapshot.snapshot_id,
            "dataset": dataset,
            "manifest": reference,
            "available": item is not None,
        }

    def trace_provenance(
        self,
        *,
        dataset: str,
        natural_key: str,
        as_of: Any,
        snapshot_id: str | None = None,
    ) -> dict[str, Any]:
        dataset = self._require_dataset(dataset)
        as_of_iso = self._require_as_of(as_of)
        snapshot = self._snapshot(snapshot_id)
        result = pit.get_jquants_records(
            as_of=as_of_iso,
            dataset=dataset,
            natural_key=natural_key,
            db_path=snapshot.db_path,
        )
        self._quota.charge(len(result.rows))
        row = result.rows[0] if result.rows else None
        if row is None:
            return {"snapshot_id": snapshot.snapshot_id, "found": False}
        return {
            "snapshot_id": snapshot.snapshot_id,
            "found": True,
            "dataset": dataset,
            "natural_key": natural_key,
            "event_time": row.get("event_time"),
            "available_at": row.get("available_at"),
            "ingested_at": row.get("ingested_at"),
            "raw_manifest": self.raw_manifest(dataset, snapshot.snapshot_id)["manifest"],
        }


__all__ = ["DEFAULT_SNAPSHOT_DIR", "QuantDataAccess", "QuantDataConfig"]
