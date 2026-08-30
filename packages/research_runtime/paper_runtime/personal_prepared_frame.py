"""Job-scoped prepared feature frame for personal DRAFT research.

The frame is deliberately small in authority and lifetime.  It owns only an
ephemeral SQLite file containing already-computed :class:`FeatureOutput`
documents.  Source facts still enter through the PIT API on a cache miss, and
the personal execution service continues to verify the immutable source
snapshot before and after every paper run.

The cache key binds the logical data snapshot and the complete, exact feature
contract.  It can therefore reuse a value across validation folds, cost
stress, holdout, and exact-four candidates without turning the cache into a
persistent feature store or weakening ``available_at <= as_of``.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import threading
import zlib
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


PERSONAL_PREPARED_FRAME_SCHEMA = "personal-prepared-feature-frame/v1"
PERSONAL_PREPARED_FEATURE_KEY_SCHEMA = "personal-prepared-feature-key/v1"
PERSONAL_PREPARED_PRICE_KEY_SCHEMA = "personal-prepared-price-window-key/v1"
PERSONAL_PREPARED_FRAME_MAX_BYTES = 1024 * 1024 * 1024
PERSONAL_PREPARED_FRAME_MAX_ENTRY_BYTES = 8 * 1024 * 1024
PERSONAL_PREPARED_FRAME_MAX_FEATURE_CELLS = 2_000_000
PERSONAL_PREPARED_FRAME_MAX_PRICE_WINDOWS = 10_000
_COMMIT_INTERVAL = 2_048

_FRAME_STATE = threading.local()
_CACHE_MISS = object()


def _require_snapshot_id(value: str) -> str:
    snapshot_id = str(value or "").strip()
    if (
        len(snapshot_id) != 71
        or not snapshot_id.startswith("sha256:")
        or any(character not in "0123456789abcdef" for character in snapshot_id[7:])
    ):
        raise ValueError("snapshot_id must be a canonical sha256 digest")
    return snapshot_id


def _json_safe(value: Any) -> Any:
    """Encode containers with explicit tags and no marker-key ambiguity."""

    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not (value == value and abs(value) != float("inf")):
            raise ValueError("prepared feature values must be finite JSON numbers")
        return value
    if isinstance(value, tuple):
        return {
            "__qp_prepared_node__": "tuple",
            "items": [_json_safe(item) for item in value],
        }
    if isinstance(value, list):
        return {
            "__qp_prepared_node__": "list",
            "items": [_json_safe(item) for item in value],
        }
    if isinstance(value, Mapping):
        encoded: list[list[Any]] = []
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("prepared feature mappings require string keys")
            encoded.append([key, _json_safe(item)])
        encoded.sort(key=lambda item: item[0])
        return {"__qp_prepared_node__": "mapping", "items": encoded}
    raise TypeError(
        "prepared feature output is not JSON-safe: " + type(value).__name__
    )


def _json_restore(value: Any) -> Any:
    if isinstance(value, list):
        return [_json_restore(item) for item in value]
    if isinstance(value, dict):
        if set(value) != {"__qp_prepared_node__", "items"}:
            return {str(key): _json_restore(item) for key, item in value.items()}
        node_type = value.get("__qp_prepared_node__")
        if node_type == "tuple":
            items = value.get("items")
            if not isinstance(items, list):
                raise RuntimeError("invalid tuple payload in personal prepared frame")
            return tuple(_json_restore(item) for item in items)
        if node_type == "list":
            items = value.get("items")
            if not isinstance(items, list):
                raise RuntimeError("invalid list payload in personal prepared frame")
            return [_json_restore(item) for item in items]
        if node_type == "mapping":
            items = value.get("items")
            if not isinstance(items, list):
                raise RuntimeError("invalid mapping payload in personal prepared frame")
            restored: dict[str, Any] = {}
            for pair in items:
                if (
                    not isinstance(pair, list)
                    or len(pair) != 2
                    or not isinstance(pair[0], str)
                ):
                    raise RuntimeError(
                        "invalid mapping item in personal prepared frame"
                    )
                restored[pair[0]] = _json_restore(pair[1])
            return restored
        raise RuntimeError("unknown node type in personal prepared frame")
    return value


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        _json_safe(value),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _within_uncompressed_bound(value: Any, *, limit: int) -> bool:
    """Reject obviously oversized values before tagged JSON makes a copy."""

    remaining = limit
    pending = [value]
    seen_containers: set[int] = set()
    while pending:
        item = pending.pop()
        if item is None:
            remaining -= 4
        elif isinstance(item, bool):
            remaining -= 5
        elif isinstance(item, (int, float)):
            remaining -= 32
        elif isinstance(item, str):
            # Four bytes per code point is a conservative UTF-8 bound and
            # avoids allocating a second giant byte string during preflight.
            remaining -= 4 * len(item) + 2
        elif isinstance(item, Mapping):
            if id(item) in seen_containers:
                return False
            seen_containers.add(id(item))
            remaining -= 64 + 16 * len(item)
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, (list, tuple)):
            if id(item) in seen_containers:
                return False
            seen_containers.add(id(item))
            remaining -= 48 + 8 * len(item)
            pending.extend(item)
        else:
            return False
        if remaining < 0:
            return False
    return True


def _feature_cache_key_document(
    *,
    snapshot_id: str,
    as_of: str,
    code: Any,
    code_present: bool = True,
    feature_id: str,
    feature_version: str,
    definition_digest: str,
    params: Mapping[str, Any],
    session_view_digest: str | None = None,
) -> dict[str, Any]:
    """Return the complete auditable identity of one prepared feature cell."""

    document = {
        "schema_version": PERSONAL_PREPARED_FEATURE_KEY_SCHEMA,
        "snapshot_id": _require_snapshot_id(snapshot_id),
        "as_of": str(as_of),
        "code_present": bool(code_present),
        "code": code,
        "feature_id": str(feature_id),
        "feature_version": str(feature_version),
        "feature_definition_digest": str(definition_digest),
        "params": dict(params),
    }
    if session_view_digest is not None:
        document["session_view_digest"] = str(session_view_digest)
    return document


@dataclass(frozen=True, slots=True)
class PreparedFeatureValue:
    value: Any
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class PreparedPriceRows:
    rows: tuple[dict[str, Any], ...]


class PersonalPreparedFrame:
    """One serial job's ephemeral, snapshot-bound feature-value frame."""

    def __init__(self, *, db_path: str | Path, snapshot_id: str) -> None:
        self.db_path = Path(db_path).resolve()
        self.snapshot_id = _require_snapshot_id(snapshot_id)
        self._temporary_directory = tempfile.TemporaryDirectory(
            prefix="qp-personal-prepared-frame-"
        )
        self.cache_path = (
            Path(self._temporary_directory.name) / "prepared-features.sqlite"
        )
        self._connection = sqlite3.connect(self.cache_path)
        self._connection.execute("PRAGMA journal_mode=OFF")
        self._connection.execute("PRAGMA synchronous=OFF")
        self._connection.execute("PRAGMA temp_store=MEMORY")
        self._connection.execute(
            "CREATE TABLE feature_cells ("
            "key_digest TEXT PRIMARY KEY,"
            "key_json TEXT NOT NULL,"
            "payload BLOB NOT NULL"
            ") WITHOUT ROWID"
        )
        page_size = int(self._connection.execute("PRAGMA page_size").fetchone()[0])
        max_pages = max(1, PERSONAL_PREPARED_FRAME_MAX_BYTES // page_size)
        self._connection.execute(f"PRAGMA max_page_count={max_pages}")
        self._connection.execute(
            "CREATE TABLE price_windows ("
            "key_digest TEXT PRIMARY KEY,"
            "key_json TEXT NOT NULL,"
            "payload BLOB NOT NULL"
            ") WITHOUT ROWID"
        )
        self._definition_digests: dict[tuple[str, str, int], str] = {}
        self._stats = {
            "feature_requests": 0,
            "feature_hits": 0,
            "feature_misses": 0,
            "feature_writes": 0,
            "feature_uncacheable": 0,
            "price_window_requests": 0,
            "price_window_hits": 0,
            "price_window_misses": 0,
            "price_window_writes": 0,
            "price_rows_written": 0,
            "price_window_uncacheable": 0,
            "cache_saturated": 0,
        }
        self._writes_since_commit = 0
        self._closed = False

    def matches_db(self, db_path: str | Path) -> bool:
        return Path(db_path).resolve() == self.db_path

    def definition_digest(
        self,
        definition: Any,
        compute_digest: Callable[[], str],
    ) -> str:
        key = (
            str(getattr(definition, "id", "")),
            str(getattr(definition, "version", "")),
            id(definition),
        )
        digest = self._definition_digests.get(key)
        if digest is None:
            digest = str(compute_digest())
            self._definition_digests[key] = digest
        return digest

    def _key(
        self,
        *,
        as_of: str,
        feature_id: str,
        feature_version: str,
        definition_digest: str,
        inputs: Mapping[str, Any],
        session_view_digest: str | None = None,
    ) -> tuple[str, str]:
        code_present = "code" in inputs
        code = inputs.get("code")
        params = {key: value for key, value in inputs.items() if key != "code"}
        document = _feature_cache_key_document(
            snapshot_id=self.snapshot_id,
            as_of=as_of,
            code=code,
            code_present=code_present,
            feature_id=feature_id,
            feature_version=feature_version,
            definition_digest=definition_digest,
            params=params,
            session_view_digest=session_view_digest,
        )
        encoded = _canonical_json(document)
        digest = "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        return digest, encoded

    def load_feature(
        self,
        *,
        as_of: str,
        feature_id: str,
        feature_version: str,
        definition_digest: str,
        inputs: Mapping[str, Any],
        session_view_digest: str | None = None,
    ) -> PreparedFeatureValue | object:
        if self._closed:
            raise RuntimeError("personal prepared frame is closed")
        self._stats["feature_requests"] += 1
        digest, encoded_key = self._key(
            as_of=as_of,
            feature_id=feature_id,
            feature_version=feature_version,
            definition_digest=definition_digest,
            inputs=inputs,
            session_view_digest=session_view_digest,
        )
        row = self._connection.execute(
            "SELECT key_json,payload FROM feature_cells WHERE key_digest=?",
            (digest,),
        ).fetchone()
        if row is None:
            self._stats["feature_misses"] += 1
            return _CACHE_MISS
        if str(row[0]) != encoded_key:
            raise RuntimeError("personal prepared frame key digest collision")
        try:
            document = _json_restore(
                json.loads(zlib.decompress(bytes(row[1])).decode("utf-8"))
            )
        except (ValueError, TypeError, zlib.error) as exc:
            raise RuntimeError("invalid personal prepared feature payload") from exc
        if not isinstance(document, dict) or not isinstance(
            document.get("metadata"), dict
        ):
            raise RuntimeError("invalid personal prepared feature document")
        self._stats["feature_hits"] += 1
        return PreparedFeatureValue(
            value=document.get("value"),
            metadata=dict(document["metadata"]),
        )

    def store_feature(
        self,
        *,
        as_of: str,
        feature_id: str,
        feature_version: str,
        definition_digest: str,
        inputs: Mapping[str, Any],
        value: Any,
        metadata: Mapping[str, Any],
        session_view_digest: str | None = None,
    ) -> None:
        if self._closed:
            raise RuntimeError("personal prepared frame is closed")
        if (
            self._stats["cache_saturated"]
            or self._stats["feature_writes"]
            >= PERSONAL_PREPARED_FRAME_MAX_FEATURE_CELLS
        ):
            self._stats["cache_saturated"] = 1
            return
        if not _within_uncompressed_bound(
            {"value": value, "metadata": metadata},
            limit=PERSONAL_PREPARED_FRAME_MAX_ENTRY_BYTES,
        ):
            self._stats["feature_uncacheable"] += 1
            return
        document = {"value": value, "metadata": dict(metadata)}
        digest, encoded_key = self._key(
            as_of=as_of,
            feature_id=feature_id,
            feature_version=feature_version,
            definition_digest=definition_digest,
            inputs=inputs,
            session_view_digest=session_view_digest,
        )
        try:
            payload = _canonical_json(document).encode("utf-8")
        except (TypeError, ValueError):
            # A future exotic FeatureOutput must retain its exact live value;
            # skipping the cache is safer than lossy coercion.
            self._stats["feature_uncacheable"] += 1
            return
        if len(payload) > PERSONAL_PREPARED_FRAME_MAX_ENTRY_BYTES:
            self._stats["feature_uncacheable"] += 1
            return
        compressed = zlib.compress(payload, level=1)
        self._insert_cache_row(
            table="feature_cells",
            digest=digest,
            encoded_key=encoded_key,
            compressed=compressed,
            stat="feature_writes",
        )

    def _price_key(
        self,
        *,
        as_of: str,
        from_event: str,
        to_event: str,
        codes: tuple[str, ...],
        purpose: str,
    ) -> tuple[str, str]:
        document = {
            "schema_version": PERSONAL_PREPARED_PRICE_KEY_SCHEMA,
            "snapshot_id": self.snapshot_id,
            "as_of": str(as_of),
            "from_event": str(from_event),
            "to_event": str(to_event),
            "codes": list(codes),
            "purpose": str(purpose),
        }
        encoded = _canonical_json(document)
        digest = "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        return digest, encoded

    def load_price_rows(
        self,
        *,
        as_of: str,
        from_event: str,
        to_event: str,
        codes: tuple[str, ...],
        purpose: str = "rows",
    ) -> PreparedPriceRows | object:
        if self._closed:
            raise RuntimeError("personal prepared frame is closed")
        self._stats["price_window_requests"] += 1
        digest, encoded_key = self._price_key(
            as_of=as_of,
            from_event=from_event,
            to_event=to_event,
            codes=codes,
            purpose=purpose,
        )
        row = self._connection.execute(
            "SELECT key_json,payload FROM price_windows WHERE key_digest=?",
            (digest,),
        ).fetchone()
        if row is None:
            self._stats["price_window_misses"] += 1
            return _CACHE_MISS
        if str(row[0]) != encoded_key:
            raise RuntimeError("personal prepared price key digest collision")
        try:
            document = _json_restore(
                json.loads(zlib.decompress(bytes(row[1])).decode("utf-8"))
            )
        except (ValueError, TypeError, zlib.error) as exc:
            raise RuntimeError("invalid personal prepared price payload") from exc
        if (
            not isinstance(document, dict)
            or not isinstance(document.get("rows"), list)
            or any(not isinstance(item, dict) for item in document["rows"])
        ):
            raise RuntimeError("invalid personal prepared price document")
        self._stats["price_window_hits"] += 1
        return PreparedPriceRows(
            rows=tuple(dict(item) for item in document["rows"])
        )

    def store_price_rows(
        self,
        *,
        as_of: str,
        from_event: str,
        to_event: str,
        codes: tuple[str, ...],
        rows: tuple[dict[str, Any], ...],
        purpose: str = "rows",
    ) -> None:
        if self._closed:
            raise RuntimeError("personal prepared frame is closed")
        if (
            self._stats["cache_saturated"]
            or self._stats["price_window_writes"]
            >= PERSONAL_PREPARED_FRAME_MAX_PRICE_WINDOWS
        ):
            self._stats["cache_saturated"] = 1
            return
        if not _within_uncompressed_bound(
            {"rows": rows},
            limit=PERSONAL_PREPARED_FRAME_MAX_ENTRY_BYTES,
        ):
            self._stats["price_window_uncacheable"] += 1
            return
        document = {"rows": list(rows)}
        digest, encoded_key = self._price_key(
            as_of=as_of,
            from_event=from_event,
            to_event=to_event,
            codes=codes,
            purpose=purpose,
        )
        try:
            payload = _canonical_json(document)
        except (TypeError, ValueError):
            self._stats["price_window_uncacheable"] += 1
            return
        encoded_payload = payload.encode("utf-8")
        if len(encoded_payload) > PERSONAL_PREPARED_FRAME_MAX_ENTRY_BYTES:
            self._stats["price_window_uncacheable"] += 1
            return
        compressed = zlib.compress(encoded_payload, level=1)
        writes_before = self._stats["price_window_writes"]
        self._insert_cache_row(
            table="price_windows",
            digest=digest,
            encoded_key=encoded_key,
            compressed=compressed,
            stat="price_window_writes",
        )
        if self._stats["price_window_writes"] > writes_before:
            self._stats["price_rows_written"] += len(rows)

    def _insert_cache_row(
        self,
        *,
        table: str,
        digest: str,
        encoded_key: str,
        compressed: bytes,
        stat: str,
    ) -> None:
        try:
            cursor = self._connection.execute(
                f"INSERT OR IGNORE INTO {table}(key_digest,key_json,payload) "
                "VALUES (?,?,?)",
                (digest, encoded_key, compressed),
            )
        except sqlite3.OperationalError as exc:
            full = (
                getattr(exc, "sqlite_errorcode", None) == sqlite3.SQLITE_FULL
                or "full" in str(exc).lower()
            )
            if not full:
                raise
            self._connection.rollback()
            self._writes_since_commit = 0
            self._stats["cache_saturated"] = 1
            return
        if not cursor.rowcount:
            return
        self._stats[stat] += 1
        self._writes_since_commit += 1
        if self._writes_since_commit >= _COMMIT_INTERVAL:
            self._connection.commit()
            self._writes_since_commit = 0

    def stats(self) -> dict[str, int | str]:
        return {
            "schema_version": PERSONAL_PREPARED_FRAME_SCHEMA,
            **self._stats,
            "source_feature_computations_avoided": self._stats["feature_hits"],
            "source_price_queries_avoided": self._stats["price_window_hits"],
        }

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._connection.rollback()
        finally:
            self._connection.close()
            self._temporary_directory.cleanup()


def _active_personal_prepared_frame(
    db_path: str | Path,
) -> PersonalPreparedFrame | None:
    frame = getattr(_FRAME_STATE, "frame", None)
    if frame is None or not frame.matches_db(db_path):
        return None
    return frame


@contextmanager
def _personal_prepared_frame_scope(
    *, db_path: str | Path, snapshot_id: str
) -> Iterator[PersonalPreparedFrame]:
    """Open one serial, ephemeral frame or reuse an identical nested scope."""

    active = getattr(_FRAME_STATE, "frame", None)
    if active is not None:
        if not active.matches_db(db_path) or active.snapshot_id != snapshot_id:
            raise RuntimeError("a different personal prepared frame is already active")
        yield active
        return

    frame = PersonalPreparedFrame(db_path=db_path, snapshot_id=snapshot_id)
    _FRAME_STATE.frame = frame
    try:
        yield frame
    finally:
        try:
            del _FRAME_STATE.frame
        except AttributeError:
            pass
        frame.close()


def _is_cache_miss(value: object) -> bool:
    return value is _CACHE_MISS


__all__: list[str] = []
