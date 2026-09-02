"""Typed personal DRAFT research view. Product never receives storage Paths.

Cloud composition injects this handle. Path-backed sqlite lives only behind
:class:`OfflineFixtureDataView` (host tests / opt-in recovery) or the
Container adapter in ``cf_platform.container_data_view``. Neither kind is
Controlled-eligible. Adapters implement the same typed operations and never
expose a storage path, DB filename, SQL connection, R2 key, URL, or token.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import sys
import tempfile
from abc import ABC, abstractmethod
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from ingestion.jquants.normalize import CLOSE_CHANGE_DATE

from .compact_reads import compact_surface_or_error, iter_compact_decision_pages
from .cooperative_deadline import DeadlineExceeded, check_deadline
from .errors import HistoryReadError, PitError
from .query import _open_readonly_sqlite, _require_unmanaged_draft
from .history_reads import (
    HISTORY_CODE_BATCH,
    HISTORY_READ_PAGE_SIZE,
    iter_unmanaged_draft_catalog_pages,
    iter_unmanaged_draft_revision_pages,
)
from .read_clock import (
    DRAFT_OBSERVATION_LABEL,
    SNAPSHOT_OBSERVATION_LABEL,
    PitReadClock,
    draft_observation_clock,
    install_read_clock,
    read_snapshot_observed_through,
)
from .personal_draft import (
    _compact_fail_reason,
    _corporate_fail,
    _corporate_unknown,
    classify_corporate_action_observations,
    observed_market_bar_coverage,
    source_sync_evidence,
    universe_corporate_action_check,
)
from .universe_pit import UniverseDaySlice, resolve_universe_day_slices

UNMANAGED_DRAFT_STATE = "UNMANAGED_DRAFT"
OFFLINE_FIXTURE_KIND = "offline_fixture"
CONTAINER_EPHEMERAL_KIND = "container_ephemeral"
LOCAL_MARKET_DATA_ENV = "QP_ALLOW_LOCAL_MARKET_DATA"
DEFAULT_DECISION_CUTOFF = "morning_close"
LEGACY_SESSION_CLOSE_CUTOFF = "session_close"
_ALLOWED_CUTOFFS = frozenset({DEFAULT_DECISION_CUTOFF, LEGACY_SESSION_CLOSE_CUTOFF})
OPTION_SIDECAR_MANIFEST_SCHEMA = "personal-n225-option-sidecar-manifest/v1"
OPTION_SIDECAR_OBJECT_SCHEMA = "personal-n225-option-sidecar/v1"
_OPTION_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_AM_BAR_DATASET = "equities_bars_daily_am"
_AM_SIGNAL_FIELDS = frozenset(
    {
        "Code",
        "code",
        "Date",
        "date",
        "MO",
        "MH",
        "ML",
        "MC",
        "MVo",
        "MVa",
        "MAdjO",
        "MAdjH",
        "MAdjL",
        "MAdjC",
        "MAdjVo",
        "MorningOpen",
        "MorningHigh",
        "MorningLow",
        "MorningClose",
        "MorningVolume",
        "MorningTurnoverValue",
        "MorningAdjustmentOpen",
        "MorningAdjustmentHigh",
        "MorningAdjustmentLow",
        "MorningAdjustmentClose",
        "MorningAdjustmentVolume",
    }
)
_HOST_TMP_MARKERS = ("/tmp/", "/var/folders/", "/private/var/folders/")
_HIDDEN = frozenset(
    {
        "draft_sqlite_path",
        "artifact_directory",
        "db_path",
        "sqlite_path",
        "output_root",
        "source_path",
    }
)


class PersonalResearchViewError(PitError):
    """The research view is missing, mis-typed, or not legal for this path."""


def _require_cutoff(value: str) -> str:
    cutoff = str(value)
    if cutoff not in _ALLOWED_CUTOFFS:
        raise PersonalResearchViewError(
            "decision_cutoff must be morning_close or session_close"
        )
    return cutoff


def _morning_close_as_of(day: str) -> str:
    return f"{str(day)[:10]}T11:30:00+09:00"


def _morning_acquisition_as_of(day: str) -> str:
    return f"{str(day)[:10]}T12:30:00+09:00"


def _session_close_as_of(day: str) -> str:
    text = str(day)[:10]
    hhmmss = "15:30:00" if text >= CLOSE_CHANGE_DATE else "15:00:00"
    return f"{text}T{hhmmss}+09:00"


def decision_cutoff_as_of(day: str, cutoff: str) -> str:
    if _require_cutoff(cutoff) == DEFAULT_DECISION_CUTOFF:
        return _morning_close_as_of(day)
    return _session_close_as_of(day)


def platform_temp_root() -> Path:
    return Path(tempfile.gettempdir()).resolve()


def is_path_descendant(path: Path, root: Path) -> bool:
    try:
        resolved = Path(path).expanduser().resolve()
        base = Path(root).expanduser().resolve()
    except (OSError, RuntimeError):
        return False
    try:
        resolved.relative_to(base)
    except ValueError:
        return False
    try:
        return os.path.commonpath([str(resolved), str(base)]) == str(base)
    except ValueError:
        return False


def _is_ephemeral_fs(path: Path, *, owned_root: Path | None = None) -> bool:
    resolved = Path(path).expanduser().resolve()
    if not is_path_descendant(resolved, platform_temp_root()):
        return False
    if owned_root is not None and not is_path_descendant(resolved, owned_root):
        return False
    return True


def require_ephemeral_path(
    path: Path, *, owned_root: Path | None = None
) -> Path:
    resolved = Path(path).expanduser().resolve()
    if not _is_ephemeral_fs(resolved, owned_root=owned_root):
        raise PersonalResearchViewError(
            "container view requires ephemeral temporary storage"
        )
    return resolved


def _capture_observation(source: Path) -> tuple[str, str, bool]:
    """Bind a DRAFT observation cutoff. It is never promotion authority."""

    conn = _open_readonly_sqlite(source)
    try:
        _require_unmanaged_draft(conn)
        stamped = read_snapshot_observed_through(conn)
    finally:
        conn.close()
    if stamped:
        return stamped, DRAFT_OBSERVATION_LABEL, False
    observed, label = draft_observation_clock()
    return observed, label, False


def _bind_draft_source(source: Path, artifacts: Path) -> Path:
    """Copy stable managed input to PERSONAL_DRAFT before typed binding."""

    from paper_runtime.personal_snapshot import _bind_personal_draft_source

    bound, _copied = _bind_personal_draft_source(
        source,
        artifacts / ".draft-bind",
    )
    return bound


def _looks_like_host_market_sqlite(path: Path) -> bool:
    text = str(path.resolve())
    if _is_ephemeral_fs(path):
        return False
    return (
        "data/structured" in text
        or text.endswith("ingestion.sqlite")
        or "/data/personal" in text
    )


def _calendar_dates(start: str, end: str) -> tuple[str, ...]:
    cursor = date.fromisoformat(start)
    stop = date.fromisoformat(end)
    if cursor > stop:
        raise PersonalResearchViewError("research period is reversed")
    values: list[str] = []
    while cursor <= stop:
        values.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return tuple(values)


@dataclass(frozen=True, slots=True)
class SnapshotIdentity:
    """Immutable snapshot metadata. Not a filesystem capability."""

    snapshot_id: str
    logical_data_snapshot_id: str
    database_sha256: str
    required_datasets: tuple[str, ...]
    period_start: str
    period_end: str
    closure_digests: tuple[str, ...]
    manifest: Mapping[str, Any]
    observed_through: str = ""
    observation_label: str = DRAFT_OBSERVATION_LABEL
    observation_promotable: bool = False


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    """Content-addressed artifact locator. Bytes only; never a Path."""

    archive_member: str
    sha256: str

    def read_bytes(self, view: PersonalResearchDataView) -> bytes:
        return view.read_artifact(self.archive_member)

    def read_text(
        self, view: PersonalResearchDataView, *, encoding: str = "utf-8"
    ) -> str:
        return self.read_bytes(view).decode(encoding)


def _canonical_sidecar_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        dict(value),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sidecar_digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _payload_mapping(raw: Any) -> Mapping[str, Any] | None:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return None
    return raw if isinstance(raw, Mapping) else None


def _am_bar_observation(row: Mapping[str, Any]) -> dict[str, Any] | None:
    payload = _payload_mapping(row.get("payload") or row.get("raw_payload"))
    if payload is None:
        return None
    code = str(payload.get("Code") or payload.get("code") or "").strip()
    day = str(
        payload.get("Date")
        or payload.get("date")
        or str(row.get("event_time") or "")[:10]
    )[:10]
    if not code or not day:
        return None

    def _num(*keys: str) -> float | None:
        for key in keys:
            if key not in payload:
                continue
            value = payload.get(key)
            if value is None or value == "":
                continue
            try:
                number = float(value)
                return number if math.isfinite(number) else None
            except (TypeError, ValueError):
                return None
        return None

    adjustment = _num("MAdjC", "MorningAdjustmentClose")
    if adjustment is None:
        return None
    close = _num("MC", "MorningClose")
    factor_proven = close is not None and close > 0.0
    if close is None:
        # MAdjC is still useful for an adjusted-price move advisory, but it
        # cannot prove an adjustment-factor change without the raw AM close.
        close = adjustment
    volume = _num("MVo", "MorningVolume")
    adjustment_volume = _num("MAdjVo", "MorningAdjustmentVolume")
    return {
        "code": code,
        "date": day,
        "close": close,
        "adjustment_close": adjustment,
        "volume": volume,
        "adjustment_volume": adjustment_volume,
        "factor_proven": factor_proven,
    }


def _am_signal_row(row: Mapping[str, Any]) -> Mapping[str, Any]:
    """Expose the closed AM signal surface; PM/full-day fields never escape."""

    payload = _payload_mapping(row.get("payload") or row.get("raw_payload"))
    sanitized = {
        str(key): value
        for key, value in (payload or {}).items()
        if str(key) in _AM_SIGNAL_FIELDS
    }
    visible = dict(row)
    visible["payload"] = sanitized
    visible["raw_payload"] = dict(sanitized)
    return visible


class PersonalResearchDataView(ABC):
    """Bounded DRAFT operations. Not a Controlled or READY authority."""

    @property
    @abstractmethod
    def kind(self) -> str: ...

    @property
    @abstractmethod
    def research_state(self) -> str: ...

    @property
    @abstractmethod
    def controlled_eligible(self) -> bool: ...

    @property
    @abstractmethod
    def decision_cutoff(self) -> str: ...

    @property
    def allows_legacy_session_close(self) -> bool:
        return False

    def __getattr__(self, name: str) -> Any:
        if name in _HIDDEN:
            raise AttributeError(
                "personal research views do not expose storage paths"
            )
        raise AttributeError(name)

    @abstractmethod
    def iter_decision_pages(
        self,
        *,
        decision_date: str,
        dataset: str,
        codes: Sequence[str],
        start: str,
        end: str,
        lookback_days: int = 0,
        page_size: int = HISTORY_READ_PAGE_SIZE,
    ) -> Iterator[tuple[Mapping[str, Any], ...]]:
        """Yield one decision vintage. A period-end panel is forbidden."""

    def iter_revision_pages(
        self,
        *,
        dataset: str,
        codes: Sequence[str],
        start: str,
        end: str,
        page_size: int = HISTORY_READ_PAGE_SIZE,
    ) -> Iterator[tuple[Mapping[str, Any], ...]]:
        """Forward immutable revisions at the view cutoff for ``end``."""
        raise PersonalResearchViewError("revision stream is not available")

    def read_option_sidecar(self) -> Mapping[str, Any] | None:
        """Return a fresh decoded bound sidecar, or ``None`` for HOLD."""
        return None

    @abstractmethod
    def universe_slices(
        self, *, period_start: str, period_end: str
    ) -> tuple[UniverseDaySlice, ...]:
        """PIT master/fins slices at this view's decision cutoff."""

    @abstractmethod
    def write_artifact(
        self, *, category: str, suffix: str, payload: bytes
    ) -> ArtifactRef: ...

    @abstractmethod
    def read_artifact(self, archive_member: str) -> bytes: ...

    @abstractmethod
    def observed_bar_coverage(
        self, universe: Any, *, minimum_ratio: float
    ) -> dict[str, Any]: ...

    @abstractmethod
    def source_sync_evidence(
        self,
        snapshot_manifest: Mapping[str, Any],
        *,
        required_datasets: Sequence[str],
    ) -> dict[str, Any]: ...

    @abstractmethod
    def corporate_action_check(
        self, *, universe: Any, lookback_days: int
    ) -> dict[str, Any]: ...

    @abstractmethod
    def snapshot_identity(self) -> SnapshotIdentity: ...


def refuse_offline_fixture_for_controlled(view: Any) -> None:
    """Controlled / READY composition cannot consume a DRAFT data view."""

    if isinstance(view, PersonalResearchDataView):
        raise PersonalResearchViewError(
            "DRAFT research views cannot be passed to Controlled or READY composition"
        )


_ARTIFACT_CATEGORY_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
_ARTIFACT_CATEGORIES = frozenset(
    {"reports", "paper", "risk", "base-sleeve", "candidates"}
)


def _validated_artifact_directory(root: Path, category: str) -> Path:
    if not isinstance(category, str) or not _ARTIFACT_CATEGORY_RE.fullmatch(category):
        raise PersonalResearchViewError("artifact category is invalid")
    if category not in _ARTIFACT_CATEGORIES:
        raise PersonalResearchViewError("artifact category is invalid")
    if any(part in {"", ".", ".."} for part in Path(category).parts):
        raise PersonalResearchViewError("artifact category is invalid")
    root_resolved = Path(root).resolve()
    if root_resolved.is_symlink():
        raise PersonalResearchViewError("artifact root must not be a symlink")
    candidate = root_resolved / category
    if candidate.exists() and (candidate.is_symlink() or candidate.is_absolute() and not candidate.is_dir()):
        raise PersonalResearchViewError("artifact category path is invalid")
    if candidate.is_symlink():
        raise PersonalResearchViewError("artifact category path is invalid")
    candidate.mkdir(parents=True, exist_ok=True)
    if candidate.is_symlink() or not candidate.is_dir():
        raise PersonalResearchViewError("artifact category path is invalid")
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise PersonalResearchViewError("artifact category escapes artifact root") from exc
    try:
        if os.path.commonpath([str(resolved), str(root_resolved)]) != str(root_resolved):
            raise PersonalResearchViewError("artifact category escapes artifact root")
    except ValueError as exc:
        raise PersonalResearchViewError("artifact category escapes artifact root") from exc
    return resolved


def _write_bytes(root: Path, *, category: str, suffix: str, payload: bytes) -> ArtifactRef:
    check_deadline()
    digest = hashlib.sha256(payload).hexdigest()
    root_resolved = Path(root).resolve()
    directory = _validated_artifact_directory(root_resolved, category)
    if not str(suffix).isalnum():
        raise PersonalResearchViewError("artifact suffix is invalid")
    path = directory / f"{digest}.{suffix}"
    tmp = directory / f".{digest}.{suffix}.partial"
    created_final = False
    try:
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        fd = os.open(tmp, flags, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            check_deadline()
            handle.flush()
            os.fsync(handle.fileno())
        check_deadline()
        try:
            os.link(tmp, path)
            created_final = True
        except FileExistsError:
            if path.read_bytes() != payload:
                raise PersonalResearchViewError(
                    f"content-address collision for {path.name}"
                )
        if created_final:
            path.chmod(0o444)
        check_deadline()
    except FileExistsError:
        if path.exists() and path.read_bytes() == payload:
            pass
        else:
            raise
    except BaseException:
        if created_final:
            try:
                if path.is_file() and not path.is_symlink() and path.read_bytes() == payload:
                    path.unlink()
            except OSError:
                pass
        raise
    finally:
        tmp.unlink(missing_ok=True)
    return ArtifactRef(
        archive_member=path.relative_to(root_resolved).as_posix(),
        sha256="sha256:" + digest,
    )


class _SqliteDraftDataView(PersonalResearchDataView):
    """Shared sqlite-backed DRAFT operations. Storage path stays private."""

    __slots__ = (
        "_kind",
        "_cutoff",
        "_source",
        "_artifacts",
        "_identity",
        "_legacy_session_close",
        "_prepared_snapshot",
        "_surface",
        "_observed_through",
        "_observation_label",
        "_observation_promotable",
        "_option_sidecar_bytes",
        "_option_sidecar_digest",
        "_typed_query_count",
    )

    def __init__(
        self,
        *,
        kind: str,
        source: Path,
        artifacts: Path,
        decision_cutoff: str,
        allow_legacy_session_close: bool,
        observed_through: str,
        observation_label: str,
        observation_promotable: bool,
    ) -> None:
        cutoff = _require_cutoff(decision_cutoff)
        if cutoff == LEGACY_SESSION_CLOSE_CUTOFF and not allow_legacy_session_close:
            raise PersonalResearchViewError(
                "session_close is legacy OfflineFixture DRAFT and is not "
                "selectable by cloud or container composition"
            )
        self._kind = kind
        self._cutoff = cutoff
        self._source = source
        self._artifacts = artifacts
        self._identity: SnapshotIdentity | None = None
        self._legacy_session_close = bool(allow_legacy_session_close)
        self._prepared_snapshot = None
        self._surface: str | None = None
        self._observed_through = observed_through
        self._observation_label = observation_label
        self._observation_promotable = bool(observation_promotable)
        self._option_sidecar_bytes: bytes | None = None
        self._option_sidecar_digest: str | None = None
        self._typed_query_count = 0

    def _decision_clock(self, decision_at: str) -> PitReadClock:
        return PitReadClock(
            decision_at=decision_at,
            observed_through=self._observed_through,
            observation_label=self._observation_label,
            promotable=self._observation_promotable,
        )

    @property
    def kind(self) -> str:
        return self._kind

    @property
    def research_state(self) -> str:
        return UNMANAGED_DRAFT_STATE

    @property
    def controlled_eligible(self) -> bool:
        return False

    @property
    def decision_cutoff(self) -> str:
        return self._cutoff

    @property
    def allows_legacy_session_close(self) -> bool:
        return self._legacy_session_close

    def bind_snapshot_identity(self, identity: SnapshotIdentity) -> None:
        if identity.observation_promotable:
            raise PersonalResearchViewError(
                "DRAFT snapshot observation cannot be promotable"
            )
        self._identity = identity
        if identity.observed_through:
            self._observed_through = identity.observed_through
            self._observation_label = (
                identity.observation_label or SNAPSHOT_OBSERVATION_LABEL
            )
            self._observation_promotable = bool(identity.observation_promotable)

    def snapshot_identity(self) -> SnapshotIdentity:
        if self._identity is None:
            raise PersonalResearchViewError("draft snapshot has not been prepared")
        return self._identity

    def _draft_surface(self) -> str:
        if self._surface is None:
            self._surface = compact_surface_or_error(self._source)
        if self._surface in {"invalid", "mixed"}:
            from data_contracts.personal_history_compact import compact_rebuild_reason

            conn = _open_readonly_sqlite(self._source)
            try:
                _require_unmanaged_draft(conn)
                reason = compact_rebuild_reason(conn)
            finally:
                conn.close()
            raise PersonalResearchViewError(
                reason
                or (
                    "compact schema is invalid; rebuild as personal-draft-history/v8"
                    if self._surface == "invalid"
                    else "cannot mix compact with typed or generic equity master or bars"
                )
            )
        return self._surface

    def iter_decision_pages(
        self,
        *,
        decision_date: str,
        dataset: str,
        codes: Sequence[str],
        start: str,
        end: str,
        lookback_days: int = 0,
        page_size: int = HISTORY_READ_PAGE_SIZE,
    ) -> Iterator[tuple[Mapping[str, Any], ...]]:
        decision = str(decision_date)[:10]
        if not decision:
            raise PersonalResearchViewError("decision_date is required")
        window_start = str(start)[:10]
        window_end = str(end)[:10]
        if lookback_days:
            window_start = (
                date.fromisoformat(window_start) - timedelta(days=int(lookback_days))
            ).isoformat()
        if window_end > decision:
            window_end = decision
        if window_start > window_end:
            return
        check_deadline()
        self._typed_query_count += 1
        information_cutoff = decision_cutoff_as_of(decision, self._cutoff)
        acquisition_cutoff = (
            _morning_acquisition_as_of(decision)
            if self._cutoff == DEFAULT_DECISION_CUTOFF
            and dataset == _AM_BAR_DATASET
            else information_cutoff
        )
        wanted = [str(code).strip() for code in codes if str(code).strip()]
        size = min(max(int(page_size), 1), HISTORY_READ_PAGE_SIZE)
        surface = self._draft_surface()
        clock = self._decision_clock(acquisition_cutoff)
        use_compact = surface == "compact" and dataset in {
            "equities_bars_daily",
            "equities_master",
        }
        with install_read_clock(clock):
            for offset in range(0, max(len(wanted), 1), HISTORY_CODE_BATCH):
                check_deadline()
                batch = wanted[offset : offset + HISTORY_CODE_BATCH]
                pages = (
                    iter_compact_decision_pages(
                        self._source,
                        as_of=acquisition_cutoff,
                        dataset=dataset,
                        start=window_start,
                        end=window_end,
                        codes=batch,
                        page_size=size,
                    )
                    if use_compact
                    else iter_unmanaged_draft_catalog_pages(
                        self._source,
                        as_of=acquisition_cutoff,
                        dataset=dataset,
                        start=window_start,
                        end=window_end,
                        codes=batch,
                        include_available_at=True,
                        versions=False,
                        page_size=size,
                        event_as_of=information_cutoff,
                        ingested_as_of=(
                            acquisition_cutoff
                            if self._cutoff == DEFAULT_DECISION_CUTOFF
                            else None
                        ),
                    )
                )
                for page in pages:
                    check_deadline()
                    if len(page) > size:
                        raise PersonalResearchViewError(
                            "history catalog page exceeded the fixed bound"
                        )
                    visible: list[Mapping[str, Any]] = []
                    seen: set[str] = set()
                    for row in page:
                        available = str(row.get("available_at") or "")
                        event_time = str(row.get("event_time") or "")
                        ingested = str(row.get("ingested_at") or "")
                        if not available or available > acquisition_cutoff:
                            continue
                        if not event_time or event_time > information_cutoff:
                            continue
                        if (
                            not ingested
                            or ingested > clock.observed_through
                            or (
                                self._cutoff == DEFAULT_DECISION_CUTOFF
                                and ingested > acquisition_cutoff
                            )
                        ):
                            continue
                        key = str(row.get("natural_key") or "")
                        if key in seen:
                            raise PersonalResearchViewError(
                                "decision page emitted duplicate vintages for one natural key"
                            )
                        if key:
                            seen.add(key)
                        visible.append(
                            _am_signal_row(row)
                            if dataset == _AM_BAR_DATASET
                            else row
                        )
                    yield tuple(visible)

    def iter_revision_pages(
        self,
        *,
        dataset: str,
        codes: Sequence[str],
        start: str,
        end: str,
        page_size: int = HISTORY_READ_PAGE_SIZE,
    ) -> Iterator[tuple[Mapping[str, Any], ...]]:
        window_start = str(start)[:10]
        window_end = str(end)[:10]
        if not window_start or not window_end:
            raise PersonalResearchViewError("revision stream requires start and end")
        if window_start > window_end:
            return
        check_deadline()
        self._typed_query_count += 1
        cutoff = decision_cutoff_as_of(window_end, self._cutoff)
        wanted = [str(code).strip() for code in codes if str(code).strip()]
        size = min(max(int(page_size), 1), HISTORY_READ_PAGE_SIZE)
        clock = self._decision_clock(cutoff)
        with install_read_clock(clock):
            for page in iter_unmanaged_draft_revision_pages(
                self._source,
                as_of=cutoff,
                dataset=dataset,
                start=window_start,
                end=window_end,
                codes=wanted,
                page_size=size,
            ):
                check_deadline()
                visible: list[Mapping[str, Any]] = []
                for row in page:
                    available = str(row.get("available_at") or "")
                    event_time = str(row.get("event_time") or "")
                    ingested = str(row.get("ingested_at") or "")
                    if not available or available > cutoff:
                        continue
                    if not event_time or event_time > cutoff:
                        continue
                    if (
                        not ingested
                        or ingested > cutoff
                        or ingested > clock.observed_through
                    ):
                        continue
                    visible.append(row)
                yield tuple(visible)

    @property
    def typed_query_count(self) -> int:
        return int(self._typed_query_count)

    def read_option_sidecar(self) -> Mapping[str, Any] | None:
        payload = self._option_sidecar_bytes
        digest = self._option_sidecar_digest
        if payload is None or digest is None:
            return None
        if _sidecar_digest(payload) != digest:
            raise PersonalResearchViewError("option sidecar digest drift")
        try:
            decoded = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise PersonalResearchViewError("option sidecar is invalid") from exc
        if not isinstance(decoded, dict):
            raise PersonalResearchViewError("option sidecar is invalid")
        return decoded

    def seal_option_sidecar(
        self, *, manifest: Mapping[str, Any], obj: Mapping[str, Any]
    ) -> str:
        """Bind a digest-locked closed sidecar. Fixture/container adapters only."""
        if not isinstance(manifest, Mapping) or not isinstance(obj, Mapping):
            raise PersonalResearchViewError("option sidecar envelope is invalid")
        object_bytes = _canonical_sidecar_bytes(obj)
        object_digest = _sidecar_digest(object_bytes)
        _canonical_sidecar_bytes(manifest)
        declared = str(manifest.get("object_digest") or "")
        if _OPTION_DIGEST_RE.fullmatch(object_digest) is None:
            raise PersonalResearchViewError("option sidecar object digest is invalid")
        if declared != object_digest:
            raise PersonalResearchViewError("option sidecar object digest mismatch")
        if str(manifest.get("schema_version") or "") != OPTION_SIDECAR_MANIFEST_SCHEMA:
            raise PersonalResearchViewError("option sidecar manifest schema mismatch")
        if str(obj.get("schema_version") or "") != OPTION_SIDECAR_OBJECT_SCHEMA:
            raise PersonalResearchViewError("option sidecar object schema mismatch")
        cutoff = str(manifest.get("cutoff") or "")
        if cutoff != self._cutoff:
            raise PersonalResearchViewError("option sidecar cutoff mismatch")
        pit_cutoff = str(manifest.get("pit_cutoff") or "")
        if pit_cutoff and pit_cutoff > self._observed_through:
            raise PersonalResearchViewError("option sidecar exceeds observation cutoff")
        self._option_sidecar_bytes = bytes(object_bytes)
        self._option_sidecar_digest = object_digest
        return object_digest

    def universe_slices(
        self, *, period_start: str, period_end: str
    ) -> tuple[UniverseDaySlice, ...]:
        check_deadline()
        days = _calendar_dates(period_start, period_end)
        as_of_for_day = {
            day: decision_cutoff_as_of(day, self._cutoff) for day in days
        }
        last_as_of = as_of_for_day[days[-1]]
        with install_read_clock(self._decision_clock(last_as_of)):
            return resolve_universe_day_slices(
                self._source,
                period_start=period_start,
                period_end=period_end,
                as_of_for_day=as_of_for_day,
            )

    def write_artifact(
        self, *, category: str, suffix: str, payload: bytes
    ) -> ArtifactRef:
        check_deadline()
        return _write_bytes(
            self._artifacts, category=category, suffix=suffix, payload=payload
        )

    def read_artifact(self, archive_member: str) -> bytes:
        member = str(archive_member)
        if (
            not member
            or member.startswith("/")
            or ".." in Path(member).parts
        ):
            raise PersonalResearchViewError("artifact member is invalid")
        path = (self._artifacts / member).resolve()
        try:
            path.relative_to(self._artifacts.resolve())
        except ValueError as exc:
            raise PersonalResearchViewError("artifact member is invalid") from exc
        return path.read_bytes()

    def observed_bar_coverage(
        self, universe: Any, *, minimum_ratio: float
    ) -> dict[str, Any]:
        check_deadline()
        memberships = tuple(getattr(universe, "decision_memberships", ()) or ())
        if not memberships:
            return observed_market_bar_coverage(
                self._source,
                universe,
                minimum_ratio=minimum_ratio,
                bar_dataset=(
                    "equities_bars_daily_am"
                    if self._cutoff == DEFAULT_DECISION_CUTOFF
                    else "equities_bars_daily"
                ),
                as_of_for_day={},
            )
        as_of_for_day = {
            str(day)[:10]: decision_cutoff_as_of(str(day)[:10], self._cutoff)
            for day, _codes in memberships
        }
        last_as_of = as_of_for_day[str(memberships[-1][0])[:10]]
        bar_dataset = (
            "equities_bars_daily_am"
            if self._cutoff == DEFAULT_DECISION_CUTOFF
            else "equities_bars_daily"
        )
        with install_read_clock(self._decision_clock(last_as_of)):
            return observed_market_bar_coverage(
                self._source,
                universe,
                minimum_ratio=minimum_ratio,
                bar_dataset=bar_dataset,
                as_of_for_day=as_of_for_day,
            )

    def source_sync_evidence(
        self,
        snapshot_manifest: Mapping[str, Any],
        *,
        required_datasets: Sequence[str],
    ) -> dict[str, Any]:
        return source_sync_evidence(
            self._source,
            snapshot_manifest,
            required_datasets=required_datasets,
        )

    def corporate_action_check(
        self, *, universe: Any, lookback_days: int
    ) -> dict[str, Any]:
        check_deadline()
        period_end = str(getattr(universe, "period_end", "") or "")[:10]
        if self._cutoff == DEFAULT_DECISION_CUTOFF:
            return self._morning_corporate_action_check(
                universe=universe, lookback_days=lookback_days
            )
        if not period_end:
            return universe_corporate_action_check(
                self._source,
                universe=universe,
                lookback_days=lookback_days,
                decision_cutoff=self._cutoff,
            )
        cutoff = decision_cutoff_as_of(period_end, self._cutoff)
        with install_read_clock(self._decision_clock(cutoff)):
            return universe_corporate_action_check(
                self._source,
                universe=universe,
                lookback_days=lookback_days,
                decision_cutoff=self._cutoff,
            )

    def _morning_corporate_action_check(
        self, *, universe: Any, lookback_days: int
    ) -> dict[str, Any]:
        period_start = str(getattr(universe, "period_start", "") or "")[:10]
        period_end = str(getattr(universe, "period_end", "") or "")[:10]
        if not period_start or not period_end:
            return _corporate_unknown("morning_corporate_action_evidence_unavailable")
        memberships = tuple(
            getattr(universe, "decision_memberships", ()) or ()
        )
        expected_codes = next(
            (
                {str(code) for code in codes if str(code)}
                for day, codes in memberships
                if str(day)[:10] == period_end
            ),
            set(),
        )
        if not expected_codes:
            return _corporate_unknown("resolved_universe_end_day_empty")
        start = (
            date.fromisoformat(period_start) - timedelta(days=int(lookback_days))
        ).isoformat()
        observations: list[dict[str, Any]] = []
        try:
            for page in self.iter_decision_pages(
                decision_date=period_end,
                dataset=_AM_BAR_DATASET,
                codes=tuple(sorted(expected_codes)),
                start=start,
                end=period_end,
            ):
                for row in page:
                    item = _am_bar_observation(row)
                    if item is not None:
                        observations.append(item)
        except (HistoryReadError, sqlite3.Error):
            return _corporate_unknown("morning_corporate_action_evidence_unavailable")
        except PitError as exc:
            reason = _compact_fail_reason(exc)
            if reason is not None:
                return _corporate_fail(reason)
            if "history catalog" in str(exc).lower():
                return _corporate_unknown(
                    "morning_corporate_action_evidence_unavailable"
                )
            raise
        if not observations:
            return _corporate_unknown("morning_corporate_action_evidence_unavailable")
        decision_day_codes = {
            str(item["code"])
            for item in observations
            if str(item.get("date") or "")[:10] == period_end
        }
        missing_decision_codes = sorted(expected_codes - decision_day_codes)
        if missing_decision_codes:
            evidence = _corporate_unknown(
                "morning_decision_date_evidence_incomplete"
            )
            evidence.update(
                {
                    "bar_dataset": _AM_BAR_DATASET,
                    "decision_cutoff": DEFAULT_DECISION_CUTOFF,
                    "decision_date": period_end,
                    "missing_codes": missing_decision_codes,
                }
            )
            return evidence
        evidence = classify_corporate_action_observations(
            observations,
            expected_codes=tuple(sorted(expected_codes)),
            lookback_start=start,
            period_end=period_end,
        )
        factor_unproven_codes = sorted(
            {
                str(item.get("code") or "")
                for item in observations
                if str(item.get("code") or "")
                and not bool(item.get("factor_proven"))
            }
        )
        evidence["adjustment_factor_proof"] = (
            "COMPLETE" if not factor_unproven_codes else "INCOMPLETE"
        )
        evidence["factor_unproven_codes"] = factor_unproven_codes
        if factor_unproven_codes:
            if evidence.get("extreme_price_move_events"):
                evidence["status"] = "WARN"
                evidence["reason"] = (
                    "morning_adjustment_factor_unproven_with_extreme_adjusted_move"
                )
            elif evidence.get("status") == "WARN":
                evidence["reason"] = (
                    "morning_adjustment_factor_unproven_or_missing_evidence"
                )
            else:
                evidence["status"] = "UNKNOWN"
                evidence["reason"] = "morning_adjustment_factor_unproven"
        evidence["bar_dataset"] = _AM_BAR_DATASET
        evidence["decision_cutoff"] = DEFAULT_DECISION_CUTOFF
        return evidence


class OfflineFixtureDataView(_SqliteDraftDataView):
    """Test/opt-in DRAFT sqlite adapter. Never exposes its storage path."""

    @classmethod
    def bind(
        cls,
        source: str | Path,
        *,
        artifact_root: str | Path,
        decision_cutoff: str = DEFAULT_DECISION_CUTOFF,
    ) -> OfflineFixtureDataView:
        source_path = Path(source).expanduser().resolve()
        artifacts = Path(artifact_root).expanduser().resolve()
        if not source_path.is_file():
            raise PersonalResearchViewError(
                f"offline fixture database does not exist: {source_path}"
            )
        host = sys.platform == "darwin"
        allow = os.environ.get(LOCAL_MARKET_DATA_ENV) == "1"
        if host and _looks_like_host_market_sqlite(source_path) and not allow:
            raise PersonalResearchViewError(
                "host-persistent market sqlite is disallowed; use Cloudflare "
                "or a Container temporary snapshot"
            )
        artifacts.mkdir(parents=True, exist_ok=True)
        source_path = _bind_draft_source(source_path, artifacts)
        observed, label, promotable = _capture_observation(source_path)
        return cls(
            kind=OFFLINE_FIXTURE_KIND,
            source=source_path,
            artifacts=artifacts,
            decision_cutoff=decision_cutoff,
            allow_legacy_session_close=True,
            observed_through=observed,
            observation_label=label,
            observation_promotable=promotable,
        )


class OfflineFixture:
    """Composition helper that binds :class:`OfflineFixtureDataView`."""

    def __init__(self, *, artifact_root: str | Path) -> None:
        self._artifacts = Path(artifact_root).expanduser().resolve()
        self._artifacts.mkdir(parents=True, exist_ok=True)

    def bind(
        self,
        source: str | Path,
        *,
        decision_cutoff: str = DEFAULT_DECISION_CUTOFF,
    ) -> OfflineFixtureDataView:
        return OfflineFixtureDataView.bind(
            source,
            artifact_root=self._artifacts,
            decision_cutoff=decision_cutoff,
        )


__all__ = [
    "CONTAINER_EPHEMERAL_KIND",
    "DEFAULT_DECISION_CUTOFF",
    "LEGACY_SESSION_CLOSE_CUTOFF",
    "LOCAL_MARKET_DATA_ENV",
    "OFFLINE_FIXTURE_KIND",
    "OPTION_SIDECAR_MANIFEST_SCHEMA",
    "OPTION_SIDECAR_OBJECT_SCHEMA",
    "ArtifactRef",
    "OfflineFixture",
    "OfflineFixtureDataView",
    "PersonalResearchDataView",
    "PersonalResearchViewError",
    "SnapshotIdentity",
    "UNMANAGED_DRAFT_STATE",
    "decision_cutoff_as_of",
    "is_path_descendant",
    "platform_temp_root",
    "refuse_offline_fixture_for_controlled",
    "require_ephemeral_path",
]
