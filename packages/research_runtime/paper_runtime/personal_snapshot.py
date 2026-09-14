"""Small, unsigned SQLite snapshots for personal paper research.

This module deliberately does not publish product ``READY`` and does not use
receipt or signing authorities.  It takes one transactionally consistent
SQLite backup, binds the copied bytes and the caller's research scope into a
content address, and publishes read-only database/manifest siblings.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Sequence

from pit._draft_storage import (
    PersonalSnapshotError,
    _SHA256_RE,
    _backup_sqlite,
    _canonical_bytes,
    _file_digest,
    _personal_policy_document,
    _publish_file_without_replace,
    _stem,
)
from pit.personal_catalog_observations import (
    PersonalCatalogObservations,
    observe_personal_draft_copy,
    observe_personal_published_snapshot,
)

from .snapshot_identity import data_snapshot_id


PERSONAL_SNAPSHOT_FORMAT = "personal-paper-snapshot/v1"
_MANIFEST_IDENTITY_FIELDS = frozenset(
    {
        "format",
        "database_sha256",
        "logical_data_snapshot_id",
        "required_datasets",
        "period",
        "closure_digests",
        "personal_policy",
        "source_policy_provenance",
        "observed_datasets",
    }
)


@dataclass(frozen=True, slots=True)
class PersonalSnapshot:
    """Verified value object for one immutable personal SQLite snapshot."""

    snapshot_id: str
    db_path: Path
    manifest_path: Path
    database_sha256: str
    logical_data_snapshot_id: str
    required_datasets: tuple[str, ...]
    period_start: str
    period_end: str
    closure_digests: tuple[str, ...]

    def verify(self) -> "PersonalSnapshot":
        """Re-read both artifacts and reject any drift from this value."""
        return verify_personal_snapshot(self)


def _digest_payload(payload: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def _iso_date(value: str, label: str) -> str:
    text = str(value).strip()
    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO date (YYYY-MM-DD)") from exc
    if parsed.isoformat() != text:
        raise ValueError(f"{label} must be an ISO date (YYYY-MM-DD)")
    return text


def _dataset_ids(values: Sequence[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError("required_datasets must be an array")
    normalized = tuple(sorted({str(value).strip() for value in values}))
    if not normalized or any(not value for value in normalized):
        raise ValueError("required_datasets must contain non-empty dataset ids")
    return normalized


def _closure_ids(values: Sequence[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError("closure_digests must be an array")
    normalized = tuple(sorted({str(value).strip() for value in values}))
    if not normalized or any(
        _SHA256_RE.fullmatch(value) is None for value in normalized
    ):
        raise ValueError("closure_digests must contain canonical sha256 digests")
    return normalized


def _identity_from_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    return {key: manifest.get(key) for key in sorted(_MANIFEST_IDENTITY_FIELDS)}


def _write_manifest_without_replace(path: Path, payload: Mapping[str, Any]) -> None:
    data = _canonical_bytes(payload) + b"\n"
    fd, raw_temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(raw_temporary)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o444)
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != data:
                raise PersonalSnapshotError(
                    f"personal snapshot manifest collision: {path}"
                )
    finally:
        temporary.unlink(missing_ok=True)


def _observed_dataset_evidence(
    observations: PersonalCatalogObservations,
    required_datasets: Sequence[str],
    *,
    period_start: str,
    period_end: str,
) -> list[dict[str, Any]]:
    compact_state = observations.compact_state
    if compact_state == "invalid":
        raise PersonalSnapshotError(
            "personal snapshot compact v7 marker or schema is invalid"
        )
    if compact_state == "mixed":
        raise PersonalSnapshotError(
            "personal snapshot cannot mix compact with typed or generic "
            "equity master or bars"
        )

    by_dataset: dict[str, dict[str, Any]] = {
        key: dict(value)
        for key, value in observations.generic_by_dataset.items()
    }
    if compact_state == "compact":
        if observations.compact_master is not None:
            by_dataset["equities_master"] = dict(observations.compact_master)
        if observations.compact_bars is not None:
            by_dataset["equities_bars_daily"] = dict(observations.compact_bars)
    elif "equities_bars_daily" in required_datasets:
        if observations.typed_daily_bars is not None:
            # The personal hydrator promotes its largest/query-hot partition into
            # the existing indexed typed table at completion. Prefer that
            # representation, while retaining generic observations for older
            # fixtures and snapshots.
            generic_bars = by_dataset.get("equities_bars_daily")
            if generic_bars is not None and int(generic_bars["row_count"] or 0) > 0:
                raise PersonalSnapshotError(
                    "personal snapshot cannot mix generic and typed daily bars"
                )
            by_dataset["equities_bars_daily"] = dict(observations.typed_daily_bars)

    evidence: list[dict[str, Any]] = []
    for dataset_id in required_datasets:
        row = by_dataset.get(dataset_id)
        if row is None or int(row["row_count"] or 0) < 1:
            raise PersonalSnapshotError(
                f"required dataset {dataset_id!r} has no observed rows"
            )
        try:
            minimum = _iso_date(str(row["min_event_date"] or ""), "min_event_date")
            maximum = _iso_date(str(row["max_event_date"] or ""), "max_event_date")
        except ValueError as exc:
            raise PersonalSnapshotError(
                f"required dataset {dataset_id!r} has invalid event dates"
            ) from exc
        evidence.append(
            {
                "dataset_id": dataset_id,
                "evidence_status": "OBSERVED",
                "row_count": int(row["row_count"]),
                "min_event_date": minimum,
                "max_event_date": maximum,
            }
        )

    observed = {item["dataset_id"]: item for item in evidence}
    calendar_evidence = observed.get("markets_calendar")
    if calendar_evidence is not None and (
        calendar_evidence["min_event_date"] > period_start
        or calendar_evidence["max_event_date"] < period_end
    ):
        raise PersonalSnapshotError(
            "markets_calendar observed range does not cover the requested period"
        )

    bars_evidence = observed.get("equities_bars_daily")
    if bars_evidence is not None:
        if calendar_evidence is None:
            raise PersonalSnapshotError(
                "equities_bars_daily range requires observed markets_calendar rows"
            )
        trading_days: list[str] = []
        for row in observations.calendar_period_rows:
            try:
                payload = json.loads(str(row["payload"]))
            except (TypeError, json.JSONDecodeError) as exc:
                raise PersonalSnapshotError(
                    "markets_calendar contains an invalid observed payload"
                ) from exc
            if not isinstance(payload, Mapping):
                raise PersonalSnapshotError(
                    "markets_calendar contains a non-object observed payload"
                )
            holiday = next(
                (
                    str(payload[name])
                    for name in ("HolidayDivision", "HolDiv", "holiday_division")
                    if payload.get(name) is not None
                ),
                "",
            )
            if holiday == "1":
                trading_days.append(str(row["event_date"]))
        if not trading_days:
            raise PersonalSnapshotError(
                "markets_calendar has no observed trading day in the requested period"
            )
        if (
            bars_evidence["min_event_date"] > trading_days[0]
            or bars_evidence["max_event_date"] < trading_days[-1]
        ):
            raise PersonalSnapshotError(
                "equities_bars_daily observed range does not cover requested "
                "trading days"
            )
    return evidence


def materialize_personal_snapshot(
    source_db: str | Path,
    snapshot_dir: str | Path,
    *,
    required_datasets: Sequence[str],
    period_start: str,
    period_end: str,
    closure_digests: Sequence[str],
) -> PersonalSnapshot:
    """Create or reopen one idempotent, unsigned personal research snapshot."""
    source_path = Path(source_db).resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"personal snapshot source is missing: {source_path}")
    start = _iso_date(period_start, "period_start")
    end = _iso_date(period_end, "period_end")
    if start > end:
        raise ValueError("personal snapshot period_start must be <= period_end")
    datasets = _dataset_ids(required_datasets)
    closures = _closure_ids(closure_digests)

    destination = Path(snapshot_dir).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    fd, raw_temporary = tempfile.mkstemp(
        prefix=".personal-snapshot.", suffix=".sqlite.tmp", dir=destination
    )
    os.close(fd)
    temporary = Path(raw_temporary)
    try:
        source_provenance = _backup_sqlite(source_path, temporary)
        observations = observe_personal_draft_copy(
            temporary,
            datasets,
            period_start=start,
            period_end=end,
            personal_policy=_personal_policy_document(),
            source_provenance=source_provenance,
        )
        observed_datasets = _observed_dataset_evidence(
            observations,
            datasets,
            period_start=start,
            period_end=end,
        )
        # The existing logical ``data_snapshot_id`` has a legacy fallback that
        # includes main-file mtime when a small fixture has no watermarks.
        # Normalize it so byte-identical personal artifacts remain idempotent.
        os.utime(temporary, ns=(0, 0))
        database_sha256 = _file_digest(temporary)
        database_path = destination / f"{_stem(database_sha256)}.sqlite"
        os.chmod(temporary, 0o444)
        _publish_file_without_replace(temporary, database_path)
        if _file_digest(database_path) != database_sha256:
            raise PersonalSnapshotError(
                f"personal snapshot database collision or tamper: {database_path}"
            )
        os.chmod(database_path, 0o444)
        try:
            logical_id = data_snapshot_id(database_path)
        except (OSError, RuntimeError, sqlite3.Error) as exc:
            raise PersonalSnapshotError(
                f"personal logical data_snapshot_id failed: {exc}"
            ) from exc
        identity: dict[str, Any] = {
            "format": PERSONAL_SNAPSHOT_FORMAT,
            "database_sha256": database_sha256,
            "logical_data_snapshot_id": logical_id,
            "required_datasets": list(datasets),
            "period": {"start": start, "end": end},
            "closure_digests": list(closures),
            "personal_policy": _personal_policy_document(),
            "source_policy_provenance": source_provenance,
            "observed_datasets": observed_datasets,
        }
        snapshot_id = _digest_payload(identity)
        stem = _stem(snapshot_id)
        manifest_path = destination / f"{stem}.manifest.json"
        manifest = {
            **identity,
            "snapshot_id": snapshot_id,
            "database_file": database_path.name,
        }

        _write_manifest_without_replace(manifest_path, manifest)
        os.chmod(manifest_path, 0o444)
        return verify_personal_snapshot(manifest_path)
    finally:
        temporary.unlink(missing_ok=True)


def verify_personal_snapshot(
    snapshot: PersonalSnapshot | str | Path,
) -> PersonalSnapshot:
    """Verify filenames, hashes, scope identity, permissions, and SQLite health."""
    expected = snapshot if isinstance(snapshot, PersonalSnapshot) else None
    manifest_file = Path(
        expected.manifest_path if expected is not None else snapshot
    ).resolve()
    try:
        raw = json.loads(manifest_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PersonalSnapshotError(
            f"personal snapshot manifest is unreadable: {manifest_file}"
        ) from exc
    if not isinstance(raw, dict) or raw.get("format") != PERSONAL_SNAPSHOT_FORMAT:
        raise PersonalSnapshotError("unsupported personal snapshot manifest")

    snapshot_id = str(raw.get("snapshot_id") or "")
    stem = _stem(snapshot_id)
    expected_manifest_name = f"{stem}.manifest.json"
    if manifest_file.name != expected_manifest_name:
        raise PersonalSnapshotError("personal snapshot manifest filename/id mismatch")

    if not _MANIFEST_IDENTITY_FIELDS.issubset(raw):
        raise PersonalSnapshotError("personal snapshot identity is incomplete")
    identity = _identity_from_manifest(raw)
    if _digest_payload(identity) != snapshot_id:
        raise PersonalSnapshotError("personal snapshot manifest/id mismatch")

    database_sha256 = str(raw.get("database_sha256") or "")
    if _SHA256_RE.fullmatch(database_sha256) is None:
        raise PersonalSnapshotError("personal snapshot database_sha256 is invalid")
    expected_database_name = f"{_stem(database_sha256)}.sqlite"
    if raw.get("database_file") != expected_database_name:
        raise PersonalSnapshotError("personal snapshot database filename/hash mismatch")
    database_path = manifest_file.parent / expected_database_name
    if not database_path.is_file():
        raise PersonalSnapshotError(
            f"personal snapshot database is missing: {database_path}"
        )
    if _file_digest(database_path) != database_sha256:
        raise PersonalSnapshotError("personal snapshot database hash mismatch")
    logical_id = str(raw.get("logical_data_snapshot_id") or "")
    try:
        actual_logical_id = data_snapshot_id(database_path)
    except (OSError, RuntimeError, sqlite3.Error) as exc:
        raise PersonalSnapshotError(
            f"personal logical data_snapshot_id failed: {exc}"
        ) from exc
    if logical_id != actual_logical_id:
        raise PersonalSnapshotError("personal logical data_snapshot_id mismatch")

    period = raw.get("period")
    if not isinstance(period, Mapping):
        raise PersonalSnapshotError("personal snapshot period is missing")
    try:
        start = _iso_date(str(period.get("start") or ""), "period.start")
        end = _iso_date(str(period.get("end") or ""), "period.end")
        datasets = _dataset_ids(raw.get("required_datasets") or ())
        closures = _closure_ids(raw.get("closure_digests") or ())
    except (TypeError, ValueError) as exc:
        raise PersonalSnapshotError(str(exc)) from exc
    if start > end:
        raise PersonalSnapshotError("personal snapshot period is reversed")
    if list(datasets) != raw.get("required_datasets"):
        raise PersonalSnapshotError("personal snapshot datasets are not canonical")
    if list(closures) != raw.get("closure_digests"):
        raise PersonalSnapshotError(
            "personal snapshot closure digests are not canonical"
        )

    for path in (database_path, manifest_file):
        if path.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH):
            raise PersonalSnapshotError(
                f"personal snapshot artifact is writable: {path}"
            )
    observations = observe_personal_published_snapshot(
        database_path,
        datasets,
        period_start=start,
        period_end=end,
        personal_policy=raw.get("personal_policy"),
        source_provenance=raw.get("source_policy_provenance"),
    )
    observed_datasets = _observed_dataset_evidence(
        observations,
        datasets,
        period_start=start,
        period_end=end,
    )
    if raw.get("observed_datasets") != observed_datasets:
        raise PersonalSnapshotError(
            "personal snapshot observed dataset evidence mismatch"
        )

    verified = PersonalSnapshot(
        snapshot_id=snapshot_id,
        db_path=database_path.resolve(),
        manifest_path=manifest_file,
        database_sha256=database_sha256,
        logical_data_snapshot_id=logical_id,
        required_datasets=datasets,
        period_start=start,
        period_end=end,
        closure_digests=closures,
    )
    if expected is not None and verified != expected:
        raise PersonalSnapshotError(
            "personal snapshot value does not match its artifacts"
        )
    return verified


__all__ = [
    "PERSONAL_SNAPSHOT_FORMAT",
    "PersonalSnapshot",
    "PersonalSnapshotError",
    "materialize_personal_snapshot",
    "verify_personal_snapshot",
]
