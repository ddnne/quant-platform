"""Verify live typed-RPC J-Quants acquisition collections.

The Worker cursor HMAC is deliberately unavailable here.  It authenticates
navigation only while the receipt authority is calling the target through a
Service Binding; it is not an offline receipt signature.  Consequently this
module accepts only an opaque, runtime-registered live-capture capability.
Persisted bodies, headers, or a collection manifest cannot mint that
capability and remain ``RAW_ONLY`` after a crash.

The verifier independently checks the closed collection document, exact raw
bytes, target header/metadata canonicalization, request and chain linkage, and
the complete closed-month state machine.  Only after those checks finish does
it pin an authority-clock completion time.  Its output is another opaque,
one-shot capability consumed by the canonical parser/normalizer/DB
reconciliation boundary in :mod:`ingestion.runtime_authority`.
"""

from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import base64
from functools import lru_cache
from itertools import count
import json
import os
from pathlib import Path
import re
import stat
from threading import Lock
from types import MappingProxyType
from typing import Any, Callable, Mapping, Sequence, TYPE_CHECKING
from weakref import WeakKeyDictionary

from storage.receipt_crypto import body_digest

from ingestion.jquants.official_business_calendar import (
    OfficialBusinessCalendar,
    derive_official_business_calendar,
    master_query_digest,
)

if TYPE_CHECKING:
    from storage.coverage_ledger import RequiredCoverageSegment


_LIVE_CAPTURE_SEAL = object()
_VERIFIED_COLLECTION_SEAL = object()
_CAPABILITY_LOCK = Lock()
_AUTHORITY_EVENT_SEQUENCE = count(1)
_LIVE_CAPTURES: WeakKeyDictionary[Any, dict[str, Any]] = WeakKeyDictionary()
_VERIFIED_COLLECTIONS: WeakKeyDictionary[Any, dict[str, Any]] = (
    WeakKeyDictionary()
)

_COLLECTION_SCHEMA = "jquants-acquisition-collection/v2"
_CAPTURE_MODE = "LIVE_SERVICE_BINDING_RESPONSE"
_REQUEST_SCHEMA = "jquants-acquisition-rpc-request/v2"
_RESPONSE_SCHEMA = "jquants-acquisition-rpc-response/v2"
_METADATA_SCHEMA = "jquants-acquisition-rpc-response-metadata/v2"
_CHAIN_GENESIS_SCHEMA = "jquants-acquisition-chain-genesis/v2"
_CHAIN_LINK_SCHEMA = "jquants-acquisition-chain-link/v2"
_MAX_COLLECTION_PAGES = 8192
_MAX_PROVIDER_PAGES_PER_SLICE = 256
_MAX_RAW_PAGE_BYTES = 16 * 1024 * 1024
_MAX_MANIFEST_BYTES = 64 * 1024 * 1024
_MAX_ACQUISITION_SECONDS = 6 * 60 * 60

_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_HMAC_RE = re.compile(r"^hmac-sha256:[0-9a-f]{64}$")
_NONCE_RE = re.compile(r"^[0-9a-f]{64}$")
_MONTH_RE = re.compile(r"^[0-9]{4}-[0-9]{2}$")
_DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_INSTANT_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z$"
)
_CONTINUATION_RE = re.compile(
    r"^jqa2\.([A-Za-z0-9_-]+)\.([A-Za-z0-9_-]+)$"
)


@dataclass(frozen=True)
class _RoutePin:
    mode: str
    earliest: str
    path: str
    pagination_fields: Mapping[str, str]
    ignored_response_fields: frozenset[str]
    source_capability_digest: str
    dataset_contract_digest: str
    coverage_policy_digest: str
    query_contract_digest: str
    requires_official_calendar: bool


@dataclass(frozen=True)
class _TargetRegistry:
    digest: str
    rpc_schema_digest: str
    rpc_surface: _RpcSurface
    routes: Mapping[str, _RoutePin]
    excluded: frozenset[str]


@dataclass(frozen=True)
class _RpcSurface:
    request_keys: tuple[str, ...]
    metadata_keys: tuple[str, ...]
    header_names: tuple[str, ...]


_SHARED_REGISTRY_PATH = (
    Path(__file__).resolve().parents[2]
    / "data_contracts"
    / "jquants_acquisition_target_registry.generated.json"
)
@dataclass(frozen=True, eq=False)
class _LiveJQuantsAcquisitionCapture:
    """Opaque proof that pages were captured live from the Service Binding."""

    _seal: object

    def __post_init__(self) -> None:
        if self._seal is not _LIVE_CAPTURE_SEAL:
            raise TypeError("live J-Quants capture must be minted by receipt authority")


@dataclass(frozen=True, eq=False)
class _VerifiedJQuantsAcquisitionCollection:
    """Opaque one-shot output of the live collection state-machine verifier."""

    _seal: object
    _authority_id: object

    def __post_init__(self) -> None:
        if self._seal is not _VERIFIED_COLLECTION_SEAL:
            raise TypeError("verified J-Quants collection must be verifier-minted")


@dataclass(frozen=True)
class _VerifiedState:
    dataset: str
    required: RequiredCoverageSegment
    raw_paths: tuple[Path, ...]
    raw_digests: tuple[str, ...]
    raw_sizes: tuple[int, ...]
    official_calendar_path: Path | None
    official_calendar_size: int | None
    official_calendar_digest: str | None
    official_business_dates_digest: str | None
    manifest_path: Path
    manifest_file_size: int
    manifest_file_digest: str
    collection_digest: str
    initial_request: Mapping[str, Any]
    initial_request_digest: str
    terminal_chain_digest: str
    acquisition_issued_at: str
    acquisition_expires_at: str
    verified_at: datetime
    verified_sequence: int


@dataclass(frozen=True)
class _ParsedProviderPage:
    records: tuple[Any, ...]
    state: str
    cursor: str | None


def _canonical_acquisition_bytes(value: Any) -> bytes:
    """Return exact bytes or the J-Quants v2 canonical JSON wire form.

    The acquisition RPC pins RFC 8259 UTF-8 with sorted object keys and no
    insignificant whitespace.  In particular, non-ASCII provider cursors stay
    as UTF-8 instead of Python's default ``\\u`` escaping so this verifier
    measures the same bytes as the Worker ``JSON.stringify`` canonicalizer.
    """
    return (
        value
        if isinstance(value, bytes)
        else json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    )


def _digest(value: Any) -> str:
    return body_digest(_canonical_acquisition_bytes(value))


def _next_authority_event_sequence() -> int:
    """Order verifier/context capabilities even when clocks have equal ticks."""
    with _CAPABILITY_LOCK:
        return next(_AUTHORITY_EVENT_SEQUENCE)


def _strict_json(raw: bytes, *, label: str = "collection manifest") -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"{label} contains duplicate key {key!r}")
            result[key] = value
        return result

    def nonfinite(value: str) -> None:
        raise ValueError(f"{label} contains non-finite value {value!r}")

    try:
        text = raw.decode("utf-8")
        value = json.loads(
            text,
            object_pairs_hook=pairs,
            parse_constant=nonfinite,
        )
    except ValueError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not strict UTF-8 JSON") from exc
    if type(value) is not dict:
        raise ValueError(f"{label} must be an object")
    return value


def _read_immutable_file(
    path: Path,
    *,
    label: str,
    expected_size: int | None,
    maximum_size: int,
) -> bytes:
    """Bound memory before reading and reject path/descriptor replacement races."""
    try:
        before = path.lstat()
    except OSError as exc:
        raise ValueError(f"{label} is unavailable") from exc
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise ValueError(f"{label} must be a regular file")
    if before.st_mode & 0o222:
        raise ValueError(f"{label} must be immutable")
    if before.st_size > maximum_size:
        raise ValueError(f"{label} exceeds the governed size bound")
    if expected_size is not None and before.st_size != expected_size:
        raise ValueError(f"{label} size differs from verified state")
    try:
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_mode & 0o222
                or opened.st_size != before.st_size
                or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
            ):
                raise ValueError(f"{label} changed before bounded read")
            raw = stream.read(opened.st_size + 1)
            after_fd = os.fstat(stream.fileno())
    except OSError as exc:
        raise ValueError(f"{label} could not be read") from exc
    try:
        after_path = path.lstat()
    except OSError as exc:
        raise ValueError(f"{label} disappeared after bounded read") from exc
    stable_identity = (
        opened.st_dev,
        opened.st_ino,
        opened.st_size,
        opened.st_mtime_ns,
    )
    if (
        len(raw) != opened.st_size
        or stable_identity
        != (
            after_fd.st_dev,
            after_fd.st_ino,
            after_fd.st_size,
            after_fd.st_mtime_ns,
        )
        or stable_identity
        != (
            after_path.st_dev,
            after_path.st_ino,
            after_path.st_size,
            after_path.st_mtime_ns,
        )
        or stat.S_ISLNK(after_path.st_mode)
        or after_path.st_mode & 0o222
    ):
        raise ValueError(f"{label} changed during bounded read")
    return raw


@lru_cache(maxsize=1)
def _rpc_surface() -> _RpcSurface:
    """Return the reviewed package-owned wire surface pinned by the registry."""
    return _target_registry().rpc_surface


@lru_cache(maxsize=1)
def _target_registry() -> _TargetRegistry:
    """Load the same generator-owned JSON imported by the target Worker."""
    document = _strict_json(
        _SHARED_REGISTRY_PATH.read_bytes(), label="J-Quants target registry"
    )
    digest = _require_digest(document.get("registry_digest"), "registry_digest")
    body = {key: value for key, value in document.items() if key != "registry_digest"}
    if digest != _digest(body):
        raise ValueError("J-Quants target registry self-digest drift")
    if (
        document.get("schema_version") != "jquants-acquisition-target-registry/v2"
        or document.get("maximum_redirects") != 0
        or document.get("maximum_page_bytes") != _MAX_RAW_PAGE_BYTES
        or document.get("maximum_segment_pages") != _MAX_COLLECTION_PAGES
        or document.get("maximum_provider_pages_per_slice")
        != _MAX_PROVIDER_PAGES_PER_SLICE
        or document.get("continuation_ttl_seconds") != _MAX_ACQUISITION_SECONDS
    ):
        raise ValueError("J-Quants target registry limits/schema drift")
    sources = document.get("sources")
    if type(sources) is not dict:
        raise ValueError("J-Quants target registry sources are invalid")
    if sources.get("jquants_acquisition_rpc_schema") != (
        "specs/authorities/jquants_acquisition_rpc.schema.json"
    ):
        raise ValueError("J-Quants target registry RPC schema locator drift")
    rpc_schema_digest = _require_digest(
        sources.get("jquants_acquisition_rpc_schema_digest"),
        "jquants_acquisition_rpc_schema_digest",
    )
    surface = document.get("rpc_surface")
    if type(surface) is not dict or set(surface) != {
        "request_fields",
        "response_metadata_fields",
        "response_header_fields",
    }:
        raise ValueError("J-Quants target registry RPC surface drift")
    surface_fields: list[tuple[str, ...]] = []
    for name, expected_count in (
        ("request_fields", 14),
        ("response_metadata_fields", 34),
        ("response_header_fields", 37),
    ):
        values = surface.get(name)
        if (
            type(values) is not list
            or len(values) != expected_count
            or len(set(values)) != expected_count
            or not all(type(value) is str and value for value in values)
        ):
            raise ValueError("J-Quants target registry RPC field inventory drift")
        surface_fields.append(tuple(values))
    rpc_surface = _RpcSurface(*surface_fields)
    rows = document.get("datasets")
    exclusions = document.get("excluded_datasets")
    if type(rows) is not list or type(exclusions) is not list:
        raise ValueError("J-Quants target registry inventory is invalid")
    routes: dict[str, _RoutePin] = {}
    for row in rows:
        if type(row) is not dict:
            raise ValueError("J-Quants target registry row is invalid")
        canonical = row.get("canonical_dataset")
        capability = row.get("source_capability")
        premium = row.get("premium_contract")
        coverage = row.get("coverage_policy")
        query = row.get("query_resolution")
        if not all(
            type(item) is dict
            for item in (canonical, capability, premium, coverage, query)
        ):
            raise ValueError("J-Quants target registry contract row is invalid")
        assert isinstance(canonical, dict)
        assert isinstance(capability, dict)
        assert isinstance(premium, dict)
        assert isinstance(coverage, dict)
        assert isinstance(query, dict)
        dataset = _require_string(canonical.get("dataset_id"), "registry dataset")
        if dataset in routes or capability.get("dataset_id") != dataset:
            raise ValueError("J-Quants target registry dataset identity drift")
        mode = query.get("mode")
        if mode not in {
            "calendar_month_sliced",
            "calendar_month_range",
            "official_business_day_sliced",
        }:
            raise ValueError("J-Quants target registry query mode drift")
        earliest = _parse_date(
            capability.get("earliest_official_availability"),
            "earliest_official_availability",
        ).isoformat()
        path = _require_string(premium.get("path"), "registry path")
        if re.fullmatch(r"/v2/[a-z0-9/-]+", path) is None:
            raise ValueError("J-Quants target registry path drift")
        pagination_rows = query.get("pagination")
        ignored_rows = query.get("allowed_ignored_response_fields")
        if type(pagination_rows) is not list or type(ignored_rows) is not list:
            raise ValueError("J-Quants target registry pagination contract drift")
        pagination_fields: dict[str, str] = {}
        for pagination in pagination_rows:
            if (
                type(pagination) is not dict
                or set(pagination) != {"response_field", "query_parameter"}
                or pagination.get("response_field") != "pagination_key"
                or pagination.get("query_parameter") != "pagination_key"
            ):
                raise ValueError("J-Quants target registry pagination mapping drift")
            if "pagination_key" in pagination_fields:
                raise ValueError("J-Quants target registry pagination mapping duplicated")
            pagination_fields["pagination_key"] = "pagination_key"
        if bool(pagination_fields) != (dataset != "markets_calendar"):
            raise ValueError("J-Quants target registry per-route pagination drift")
        ignored = frozenset(ignored_rows)
        if (
            any(type(item) is not str for item in ignored_rows)
            or len(ignored) != len(ignored_rows)
            or not ignored.issubset({"cursor"})
            or ("cursor" in ignored)
            != (dataset in {"fins_details", "fins_summary"})
        ):
            raise ValueError("J-Quants target registry ignored response fields drift")
        calendar_binding = query.get("official_calendar_binding")
        requires_official_calendar = mode == "official_business_day_sliced"
        if requires_official_calendar:
            if (
                type(calendar_binding) is not dict
                or set(calendar_binding)
                != {
                    "authority",
                    "path",
                    "ordered_parameters",
                    "response_data_field",
                    "date_field",
                    "holiday_division_field",
                    "tse_business_day_values",
                    "complete_calendar_day_sequence_required",
                    "cross_segment_resolution",
                }
                or calendar_binding.get("authority")
                != "target-and-receipt-independent-reproof/v1"
                or calendar_binding.get("path") != "/v2/markets/calendar"
                or calendar_binding.get("ordered_parameters") != ["from", "to"]
                or calendar_binding.get("response_data_field") != "data"
                or calendar_binding.get("date_field") != "Date"
                or calendar_binding.get("holiday_division_field") != "HolDiv"
                or calendar_binding.get("tse_business_day_values") != ["1", "2"]
                or calendar_binding.get("complete_calendar_day_sequence_required")
                is not True
                or calendar_binding.get("cross_segment_resolution") != "FORBIDDEN"
            ):
                raise ValueError("J-Quants official calendar contract drift")
        elif calendar_binding is not None:
            raise ValueError("unexpected official calendar contract")
        routes[dataset] = _RoutePin(
            mode=mode,
            earliest=earliest,
            path=path,
            pagination_fields=MappingProxyType(pagination_fields),
            ignored_response_fields=ignored,
            source_capability_digest=_digest(capability),
            dataset_contract_digest=_digest(
                {"canonical_dataset": canonical, "premium_contract": premium}
            ),
            coverage_policy_digest=_digest(coverage),
            query_contract_digest=_digest(query),
            requires_official_calendar=requires_official_calendar,
        )
    excluded: set[str] = set()
    for item in exclusions:
        if (
            type(item) is not dict
            or item.get("status") != "PENDING"
            or type(item.get("reason")) is not str
        ):
            raise ValueError("J-Quants target registry exclusion drift")
        dataset = _require_string(item.get("dataset_id"), "excluded dataset")
        if dataset in excluded:
            raise ValueError("J-Quants target registry exclusion duplicated")
        excluded.add(dataset)
    expected_active = {
        "equities_bars_daily",
        "equities_master",
        "fins_details",
        "fins_dividend",
        "fins_earnings_date",
        "fins_summary",
        "indices_bars_daily_topix",
        "markets_calendar",
    }
    expected_excluded = {
        "equities_bars_daily_am",
        "equities_earnings_calendar",
        "equities_master",
    }
    if set(routes) != expected_active or excluded != expected_excluded:
        raise ValueError("J-Quants target registry reviewed inventory drift")
    return _TargetRegistry(
        digest=digest,
        rpc_schema_digest=rpc_schema_digest,
        rpc_surface=rpc_surface,
        routes=MappingProxyType(routes),
        excluded=frozenset(excluded),
    )


def _exact_keys(value: Mapping[str, Any], expected: tuple[str, ...], name: str) -> None:
    if set(value) != set(expected):
        raise ValueError(f"{name} does not have the closed v2 field set")


def _require_string(value: Any, name: str) -> str:
    if type(value) is not str or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _require_digest(value: Any, name: str, *, hmac: bool = False) -> str:
    text = _require_string(value, name)
    pattern = _HMAC_RE if hmac else _SHA256_RE
    if pattern.fullmatch(text) is None:
        raise ValueError(f"{name} is not a canonical digest")
    return text


def _require_int(value: Any, name: str, *, maximum: int | None = None) -> int:
    if type(value) is not int or value < 0 or (maximum is not None and value > maximum):
        raise ValueError(f"{name} is outside the governed bound")
    return value


def _parse_date(value: Any, name: str) -> date:
    text = _require_string(value, name)
    if _DATE_RE.fullmatch(text) is None:
        raise ValueError(f"{name} is not YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{name} is not a calendar date") from exc
    if parsed.isoformat() != text:
        raise ValueError(f"{name} is not a canonical date")
    return parsed


def _parse_instant(value: Any, name: str) -> datetime:
    text = _require_string(value, name)
    if _INSTANT_RE.fullmatch(text) is None:
        raise ValueError(f"{name} is not a canonical millisecond UTC instant")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(f"{name} is not a valid UTC instant") from exc
    return parsed


def _parse_clock(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("receipt authority clock is invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError("receipt authority clock must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _canonical_base64url(value: str) -> bool:
    if not value or re.fullmatch(r"[A-Za-z0-9_-]+", value) is None:
        return False
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * ((4 - len(value) % 4) % 4))
    except (ValueError, TypeError):
        return False
    return base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=") == value


def _require_continuation(value: Any) -> str:
    token = _require_string(value, "continuation_token")
    if len(token) > 8192:
        raise ValueError("continuation_token exceeds the v2 bound")
    match = _CONTINUATION_RE.fullmatch(token)
    if match is None or not all(_canonical_base64url(item) for item in match.groups()):
        raise ValueError("continuation_token is not canonical jqa2 state")
    return token


def _valid_provider_cursor(value: Any) -> bool:
    if type(value) is not str or not 1 <= len(value) <= 2048:
        return False
    try:
        encoded = value.encode("utf-8")
        if encoded.decode("utf-8") != value:
            return False
    except (UnicodeEncodeError, UnicodeDecodeError):
        return False
    return len(encoded) <= 2048 and re.search(r"[\x00-\x1f\x7f]", value) is None


def _parse_provider_page(raw: bytes, route: _RoutePin) -> _ParsedProviderPage:
    """Strictly derive provider navigation from the exact upstream bytes."""
    payload = _strict_json(raw, label="J-Quants raw response page")
    allowed = {"data", *route.pagination_fields, *route.ignored_response_fields}
    if set(payload) - allowed or "data" not in payload:
        raise ValueError("J-Quants raw response page has an unknown envelope field")
    if type(payload["data"]) is not list:
        raise ValueError("J-Quants raw response data envelope is not an array")

    informational_cursor = False
    for field in route.ignored_response_fields:
        if field not in payload or payload[field] is None:
            continue
        if not _valid_provider_cursor(payload[field]):
            raise ValueError("J-Quants informational cursor is invalid")
        informational_cursor = True

    present = [field for field in route.pagination_fields if field in payload]
    if not present:
        return _ParsedProviderPage(tuple(payload["data"]), "EXHAUSTED", None)
    if len(present) != 1:
        raise ValueError("J-Quants provider pagination fields are ambiguous")
    cursor = payload[present[0]]
    if cursor is None:
        return _ParsedProviderPage(tuple(payload["data"]), "EXHAUSTED", None)
    if not _valid_provider_cursor(cursor):
        raise ValueError("J-Quants provider pagination cursor is invalid")
    if informational_cursor:
        raise ValueError(
            "J-Quants differential cursor contradicts historical pagination"
        )
    return _ParsedProviderPage(tuple(payload["data"]), "CONTINUATION", cursor)


def _records_from_verified_pages(
    dataset: str, raw_pages: Sequence[bytes]
) -> tuple[Any, ...]:
    registry = _target_registry()
    route = registry.routes.get(dataset)
    if route is None:
        raise ValueError("dataset is outside the reviewed J-Quants acquisition routes")
    records: list[Any] = []
    for raw in raw_pages:
        records.extend(_parse_provider_page(bytes(raw), route).records)
    return tuple(records)


def _month_end(month: str) -> date:
    if _MONTH_RE.fullmatch(month) is None:
        raise ValueError("segment_id must be a calendar month")
    year, number = (int(item) for item in month.split("-"))
    if year < 1900 or not 1 <= number <= 12:
        raise ValueError("segment_id must be a supported calendar month")
    return date(year, number, monthrange(year, number)[1])


def _canonical_required_segment(
    required: RequiredCoverageSegment,
    *,
    route: _RoutePin | None = None,
) -> RequiredCoverageSegment:
    """Re-derive the exact governed Coverage segment from checked-in policy.

    ``RequiredCoverageSegment`` is a public DTO.  Its scope and item count are
    receipt claims, so the authority must not sign the caller's instance even
    when its dataset and date fields look plausible.
    """
    from data_contracts import coverage_contract_for, coverage_policy_digest
    from storage.coverage_ledger import (
        RequiredCoverageSegment as RuntimeRequiredCoverageSegment,
        plan_required_segments,
    )

    if not isinstance(required, RuntimeRequiredCoverageSegment):
        raise TypeError("required must be RequiredCoverageSegment")
    registry = _target_registry()
    pinned_route = route or registry.routes.get(required.dataset)
    if pinned_route is None:
        raise ValueError("dataset is PENDING outside the closed historical RPC")
    if coverage_policy_digest(required.dataset) != pinned_route.coverage_policy_digest:
        raise ValueError("local Coverage policy differs from target registry pin")
    planned = tuple(
        segment
        for segment in plan_required_segments(
            coverage_contract_for(required.dataset),
            required.segment_end,
            source="jquants",
        )
        if segment.segment_id == required.segment_id
    )
    if len(planned) != 1:
        raise ValueError("required segment is not in the canonical Coverage plan")
    canonical = planned[0]
    if required != canonical:
        raise ValueError("required segment differs from canonical Coverage planning")
    return RuntimeRequiredCoverageSegment(
        source=canonical.source,
        dataset=canonical.dataset,
        segment_id=canonical.segment_id,
        segment_start=canonical.segment_start,
        segment_end=canonical.segment_end,
        expected_scope=MappingProxyType(dict(canonical.expected_scope)),
        expected_items=canonical.expected_items,
    )


def _validate_request(
    value: Any,
    *,
    required: RequiredCoverageSegment,
    allow_pending_calendar_reproof: bool = False,
) -> tuple[dict[str, Any], _RoutePin, RequiredCoverageSegment, str, str]:
    if type(value) is not dict:
        raise ValueError("initial_request must be an object")
    request_keys = _rpc_surface().request_keys
    _exact_keys(value, request_keys, "initial_request")
    request = dict(value)
    if request["schema_version"] != _REQUEST_SCHEMA:
        raise ValueError("initial_request schema is not v2")
    if request["environment"] != "production":
        raise ValueError("COMPLETE requires the production acquisition environment")
    if request["operation"] != "fetch_governed_page":
        raise ValueError("initial_request operation is not governed")
    dataset = _require_string(request["dataset_id"], "dataset_id")
    registry = _target_registry()
    route = registry.routes.get(dataset)
    if route is None or (
        dataset in registry.excluded
        and not (
            allow_pending_calendar_reproof
            and route.requires_official_calendar
            and dataset == "equities_master"
        )
    ):
        raise ValueError("dataset is PENDING outside the closed historical RPC")
    if required.source != "jquants" or required.dataset != dataset:
        raise ValueError("initial_request source/dataset differs from required")
    canonical_required = _canonical_required_segment(required, route=route)
    if request["segment_id"] != required.segment_id:
        raise ValueError("initial_request segment differs from required")
    if request["segment_start"] != required.segment_start:
        raise ValueError("initial_request segment_start differs from required")
    if request["segment_end"] != required.segment_end:
        raise ValueError("initial_request segment_end differs from required")
    if _NONCE_RE.fullmatch(str(request["acquisition_nonce"])) is None:
        raise ValueError("initial_request acquisition_nonce is invalid")
    if request["continuation_token"] is not None:
        raise ValueError("initial_request must not contain continuation state")
    expected = {
        "source_capability_digest": route.source_capability_digest,
        "dataset_contract_digest": route.dataset_contract_digest,
        "coverage_policy_digest": route.coverage_policy_digest,
        "query_contract_digest": route.query_contract_digest,
        "target_registry_digest": registry.digest,
    }
    for field, digest in expected.items():
        if request[field] != digest:
            raise ValueError(f"initial_request {field} differs from receipt-side pin")

    start = _parse_date(required.segment_start, "required.segment_start")
    end = _parse_date(required.segment_end, "required.segment_end")
    official = date.fromisoformat(route.earliest)
    month_end = _month_end(required.segment_id)
    month_start = month_end.replace(day=1)
    if start != max(month_start, official) or end != month_end:
        raise ValueError("required segment is partial or outside official availability")
    if start > end:
        raise ValueError("required segment is empty")
    if required.expected_scope.get("segment_granularity") != "calendar_month":
        raise ValueError("required Coverage scope is not a calendar month")

    identity = {
        key: request[key] for key in request_keys if key != "continuation_token"
    }
    identity_digest = _digest(identity)
    request_digest = _digest(request)
    return request, route, canonical_required, identity_digest, request_digest


def _nullable(value: str) -> str | None:
    return None if value == "NONE" else value


def _header_int(value: str, name: str) -> int | None:
    if value == "NONE":
        return None
    if re.fullmatch(r"(?:0|[1-9][0-9]*)", value) is None:
        raise ValueError(f"{name} is not a canonical header integer")
    return int(value)


def _metadata_from_headers(headers: Mapping[str, str]) -> dict[str, Any]:
    header_names = _rpc_surface().header_names
    if set(headers) != set(header_names) or len(headers) != len(header_names):
        raise ValueError("response headers are not the exact 37-field target surface")
    if any(type(key) is not str or type(value) is not str for key, value in headers.items()):
        raise ValueError("response header names and values must be strings")
    if headers["cache-control"] != "no-store":
        raise ValueError("target cache policy is not no-store")
    if headers["x-content-type-options"] != "nosniff":
        raise ValueError("target content type policy is not nosniff")
    if headers["x-quant-acquisition-schema"] != _RESPONSE_SCHEMA:
        raise ValueError("target response header schema is not v2")
    redirect = _header_int(headers["x-quant-acquisition-redirect-count"], "redirect_count")
    if redirect != 0:
        raise ValueError("redirected acquisition pages are not trusted")
    return {
        "schema_version": _METADATA_SCHEMA,
        "evidence_state": headers["x-quant-acquisition-evidence-state"],
        "environment": _nullable(headers["x-quant-acquisition-environment"]),
        "dataset_id": _nullable(headers["x-quant-acquisition-dataset"]),
        "segment_id": _nullable(headers["x-quant-acquisition-segment"]),
        "segment_start": _nullable(headers["x-quant-acquisition-segment-start"]),
        "segment_end": _nullable(headers["x-quant-acquisition-segment-end"]),
        "request_digest": _nullable(headers["x-quant-acquisition-request-digest"]),
        "request_identity_digest": _nullable(headers["x-quant-acquisition-request-identity-digest"]),
        "previous_request_digest": _nullable(headers["x-quant-acquisition-previous-request-digest"]),
        "acquisition_id": _nullable(headers["x-quant-acquisition-acquisition-id"]),
        "acquisition_issued_at": _nullable(headers["x-quant-acquisition-acquisition-issued-at"]),
        "acquisition_expires_at": _nullable(headers["x-quant-acquisition-acquisition-expires-at"]),
        "target_registry_digest": _nullable(headers["x-quant-acquisition-registry-digest"]),
        "source_capability_digest": _nullable(headers["x-quant-acquisition-source-capability-digest"]),
        "dataset_contract_digest": _nullable(headers["x-quant-acquisition-dataset-contract-digest"]),
        "coverage_policy_digest": _nullable(headers["x-quant-acquisition-coverage-policy-digest"]),
        "query_contract_digest": _nullable(headers["x-quant-acquisition-query-contract-digest"]),
        "cursor_key_id": _nullable(headers["x-quant-acquisition-cursor-key-id"]),
        "slice_date": _nullable(headers["x-quant-acquisition-slice-date"]),
        "query_digest": _nullable(headers["x-quant-acquisition-query-digest"]),
        "page_ordinal": _header_int(headers["x-quant-acquisition-page-ordinal"], "page_ordinal"),
        "slice_ordinal": _header_int(headers["x-quant-acquisition-slice-ordinal"], "slice_ordinal"),
        "provider_page_ordinal": _header_int(headers["x-quant-acquisition-provider-page-ordinal"], "provider_page_ordinal"),
        "provider_pagination_state": headers["x-quant-acquisition-provider-pagination-state"],
        "upstream_http_status": _header_int(headers["x-quant-acquisition-upstream-status"], "upstream_status"),
        "body_digest": headers["x-quant-acquisition-body-digest"],
        "body_kind": headers["x-quant-acquisition-body-kind"],
        "pagination_state": headers["x-quant-acquisition-pagination-state"],
        "continuation_token": _nullable(headers["x-quant-acquisition-continuation"]),
        "content_type": headers["content-type"],
        "redirect_count": redirect,
        "previous_chain_digest": _nullable(headers["x-quant-acquisition-previous-chain-digest"]),
        "chain_digest": _nullable(headers["x-quant-acquisition-chain-digest"]),
    }


def _validate_metadata(
    metadata: Any,
    *,
    headers: Mapping[str, str],
    request: Mapping[str, Any],
    route: _RoutePin,
    raw: bytes,
    response_status: int,
) -> dict[str, Any]:
    if type(metadata) is not dict:
        raise ValueError("response metadata must be an object")
    _exact_keys(metadata, _rpc_surface().metadata_keys, "response metadata")
    derived = _metadata_from_headers(headers)
    if metadata != derived:
        raise ValueError("response metadata differs from the exact target headers")
    if headers["x-quant-acquisition-metadata-digest"] != _digest(derived):
        raise ValueError("response metadata digest does not reconcile")
    if metadata["schema_version"] != _METADATA_SCHEMA:
        raise ValueError("response metadata schema is not v2")
    if metadata["evidence_state"] != "RAW_PAGE":
        raise ValueError("only RAW_PAGE is eligible for reconciliation")
    if metadata["body_kind"] != "UPSTREAM_EXACT_BYTES":
        raise ValueError("target response body is not exact upstream bytes")
    if metadata["content_type"] != "application/json":
        raise ValueError("target RAW_PAGE content type is not application/json")
    if response_status != 200 or metadata["upstream_http_status"] != 200:
        raise ValueError("non-200 target/upstream response cannot reconcile")
    if metadata["body_digest"] != _digest(raw):
        raise ValueError("target body digest differs from persisted exact bytes")
    fixed = {
        "environment": request["environment"],
        "dataset_id": request["dataset_id"],
        "segment_id": request["segment_id"],
        "segment_start": request["segment_start"],
        "segment_end": request["segment_end"],
        "target_registry_digest": request["target_registry_digest"],
        "source_capability_digest": route.source_capability_digest,
        "dataset_contract_digest": route.dataset_contract_digest,
        "coverage_policy_digest": route.coverage_policy_digest,
        "query_contract_digest": route.query_contract_digest,
    }
    for field, expected in fixed.items():
        if metadata[field] != expected:
            raise ValueError(f"response metadata {field} drifted across authority boundary")
    for field in (
        "request_digest",
        "request_identity_digest",
        "query_digest",
        "previous_chain_digest",
        "chain_digest",
    ):
        _require_digest(metadata[field], field)
    for field in ("acquisition_id", "cursor_key_id"):
        _require_digest(metadata[field], field, hmac=True)
    for field in ("page_ordinal", "slice_ordinal", "provider_page_ordinal"):
        _require_int(metadata[field], field, maximum=_MAX_COLLECTION_PAGES)
    if metadata["page_ordinal"] == 0:
        if metadata["previous_request_digest"] is not None:
            raise ValueError("initial page cannot have a previous request digest")
    else:
        _require_digest(
            metadata["previous_request_digest"], "previous_request_digest"
        )
    if metadata["provider_pagination_state"] not in {"CONTINUATION", "EXHAUSTED"}:
        raise ValueError("provider pagination state is not authoritative")
    if metadata["pagination_state"] not in {"CONTINUATION", "EXHAUSTED"}:
        raise ValueError("segment pagination state is not authoritative")
    return derived


def _next_date(value: str) -> str:
    return (date.fromisoformat(value) + timedelta(days=1)).isoformat()


def _validate_state_machine(
    *,
    request: dict[str, Any],
    route: _RoutePin,
    pages: list[tuple[Path, bytes, dict[str, Any], _ParsedProviderPage]],
    official_calendar: OfficialBusinessCalendar | None,
    now: datetime,
) -> tuple[str, str, str, str]:
    jst = now.astimezone(timezone(timedelta(hours=9)))
    current_month = f"{jst.year:04d}-{jst.month:02d}"
    previous_month_day = jst.replace(day=1) - timedelta(days=1)
    previous_month = (
        f"{previous_month_day.year:04d}-{previous_month_day.month:02d}"
    )
    segment_month = str(request["segment_id"])
    if segment_month >= current_month:
        raise ValueError("current or future month is not a closed acquisition segment")
    if (
        segment_month == previous_month
        and jst.day == 1
        and (jst.hour * 60 + jst.minute) < 60
    ):
        raise ValueError("prior month is not closed before the 01:00 JST safety cutoff")
    identity = {
        key: request[key]
        for key in _rpc_surface().request_keys
        if key != "continuation_token"
    }
    request_identity_digest = _digest(identity)
    initial_request_digest = _digest(request)
    seen_requests: set[str] = set()
    seen_queries: set[str] = set()
    seen_chains: set[str] = set()
    seen_tokens: set[str] = set()
    seen_provider_cursors: set[str] = set()
    expected_request = dict(request)
    expected_previous_request: str | None = None
    if route.requires_official_calendar:
        if official_calendar is None:
            raise ValueError("equities_master requires independent official calendar reproof")
        official_slices = official_calendar.business_dates
        expected_slice_date: str | None = official_slices[0]
    else:
        if official_calendar is not None:
            raise ValueError("official calendar reproof supplied for an unrelated route")
        official_slices = ()
        expected_slice_date = (
            request["segment_start"]
            if route.mode == "calendar_month_sliced"
            else None
        )
    expected_slice_ordinal = 0
    expected_provider_ordinal = 0
    expected_provider_cursor: str | None = None
    expected_previous_chain: str | None = None
    stable: dict[str, Any] | None = None

    for index, (_path, _raw, metadata, parsed_page) in enumerate(pages):
        if metadata["page_ordinal"] != index:
            raise ValueError("acquisition page ordinals are missing, duplicate, or reordered")
        if metadata["request_identity_digest"] != request_identity_digest:
            raise ValueError("request identity changed within acquisition")
        expected_digest = _digest(expected_request)
        if metadata["request_digest"] != expected_digest:
            raise ValueError("page request digest does not match prior target continuation")
        if metadata["request_digest"] in seen_requests:
            raise ValueError("page request digest repeated within acquisition")
        seen_requests.add(metadata["request_digest"])
        if metadata["previous_request_digest"] != expected_previous_request:
            raise ValueError("page request chain is missing, reordered, or spliced")
        if metadata["query_digest"] in seen_queries:
            raise ValueError("page query digest repeated within acquisition")
        seen_queries.add(metadata["query_digest"])

        current_stable = {
            "acquisition_id": metadata["acquisition_id"],
            "acquisition_issued_at": metadata["acquisition_issued_at"],
            "acquisition_expires_at": metadata["acquisition_expires_at"],
            "cursor_key_id": metadata["cursor_key_id"],
        }
        if stable is None:
            stable = current_stable
            issued = _parse_instant(metadata["acquisition_issued_at"], "acquisition_issued_at")
            expires = _parse_instant(metadata["acquisition_expires_at"], "acquisition_expires_at")
            if not issued <= now <= expires:
                raise ValueError("live acquisition is outside its target session window")
            if expires <= issued or (expires - issued).total_seconds() > _MAX_ACQUISITION_SECONDS:
                raise ValueError("target acquisition lifetime exceeds the pinned bound")
            genesis: dict[str, Any] = {
                "schema_version": (
                    "jquants-acquisition-chain-genesis/v3"
                    if official_calendar is not None
                    else _CHAIN_GENESIS_SCHEMA
                ),
                "acquisition_id": metadata["acquisition_id"],
                "request_identity_digest": request_identity_digest,
                "cursor_key_id": metadata["cursor_key_id"],
                "acquisition_issued_at": metadata["acquisition_issued_at"],
                "acquisition_expires_at": metadata["acquisition_expires_at"],
            }
            if official_calendar is not None:
                genesis.update(
                    {
                        "official_calendar_binding_digest": (
                            official_calendar.binding_digest
                        ),
                        "official_calendar_raw_body_digest": (
                            official_calendar.raw_body_digest
                        ),
                        "official_calendar_query_digest": (
                            official_calendar.calendar_query_digest
                        ),
                        "official_business_dates_digest": (
                            official_calendar.business_dates_digest
                        ),
                        "official_business_dates": list(
                            official_calendar.business_dates
                        ),
                    }
                )
            expected_previous_chain = _digest(genesis)
        elif current_stable != stable:
            raise ValueError("acquisition session identity changed between pages")
        if metadata["previous_chain_digest"] != expected_previous_chain:
            raise ValueError("acquisition chain predecessor is missing or spliced")
        if metadata["slice_date"] != expected_slice_date:
            raise ValueError("acquisition slice date is missing, reordered, or spliced")
        if metadata["slice_ordinal"] != expected_slice_ordinal:
            raise ValueError("acquisition slice ordinal is missing, reordered, or spliced")
        if metadata["provider_page_ordinal"] != expected_provider_ordinal:
            raise ValueError("provider page ordinal is missing, reordered, or spliced")
        if expected_provider_ordinal >= _MAX_PROVIDER_PAGES_PER_SLICE:
            raise ValueError("provider page count exceeds the pinned bound")

        ordered_query = (
            [
                ["from", request["segment_start"]],
                ["to", request["segment_end"]],
            ]
            if route.mode == "calendar_month_range"
            else [["date", expected_slice_date]]
        )
        if expected_provider_ordinal > 0:
            if expected_provider_cursor is None:
                raise ValueError("provider continuation query lost its raw cursor")
            ordered_query.append(["pagination_key", expected_provider_cursor])
        elif expected_provider_cursor is not None:
            raise ValueError("initial provider page unexpectedly has a cursor")
        expected_query_digest = (
            master_query_digest(
                path=route.path,
                slice_date=str(expected_slice_date),
                provider_cursor=expected_provider_cursor,
                calendar=official_calendar,
            )
            if official_calendar is not None
            else _digest(
                {
                    "schema_version": "jquants-acquisition-query/v2",
                    "path": route.path,
                    "ordered_query": ordered_query,
                }
            )
        )
        if metadata["query_digest"] != expected_query_digest:
            raise ValueError("target query digest differs from receipt-side resolution")

        provider = metadata["provider_pagination_state"]
        if provider != parsed_page.state:
            raise ValueError(
                "target provider pagination state differs from exact raw response"
            )
        segment = metadata["pagination_state"]
        token = metadata["continuation_token"]
        if provider == "CONTINUATION":
            assert parsed_page.cursor is not None
            if parsed_page.cursor in seen_provider_cursors:
                raise ValueError("provider pagination cursor repeated within acquisition")
            seen_provider_cursors.add(parsed_page.cursor)
            if segment != "CONTINUATION":
                raise ValueError("provider continuation cannot claim segment exhaustion")
            continuation = _require_continuation(token)
            next_slice_date = expected_slice_date
            next_slice_ordinal = expected_slice_ordinal
            next_provider_ordinal = expected_provider_ordinal + 1
            next_provider_cursor = parsed_page.cursor
        else:
            has_next_slice = (
                route.mode == "calendar_month_sliced"
                and expected_slice_date != request["segment_end"]
            ) or (
                route.requires_official_calendar
                and expected_slice_ordinal + 1 < len(official_slices)
            )
            if has_next_slice:
                if segment != "CONTINUATION":
                    raise ValueError("segment terminated before the final calendar slice")
                continuation = _require_continuation(token)
                assert expected_slice_date is not None
                next_slice_date = (
                    official_slices[expected_slice_ordinal + 1]
                    if route.requires_official_calendar
                    else _next_date(expected_slice_date)
                )
                next_slice_ordinal = expected_slice_ordinal + 1
                next_provider_ordinal = 0
                next_provider_cursor = None
            else:
                if segment != "EXHAUSTED" or token is not None:
                    raise ValueError("terminal page does not prove whole-segment exhaustion")
                if index != len(pages) - 1:
                    raise ValueError("acquisition continues after a terminal page")
                continuation = None
                next_slice_date = expected_slice_date
                next_slice_ordinal = expected_slice_ordinal
                next_provider_ordinal = expected_provider_ordinal
                next_provider_cursor = None
        if segment == "CONTINUATION" and index == len(pages) - 1:
            raise ValueError("acquisition manifest ends before terminal exhaustion")
        if continuation is not None:
            if continuation in seen_tokens:
                raise ValueError("continuation state repeated within acquisition")
            seen_tokens.add(continuation)

        link: dict[str, Any] = {
            "schema_version": (
                "jquants-acquisition-chain-link/v3"
                if official_calendar is not None
                else _CHAIN_LINK_SCHEMA
            ),
            "acquisition_id": metadata["acquisition_id"],
            "cursor_key_id": metadata["cursor_key_id"],
            "acquisition_issued_at": metadata["acquisition_issued_at"],
            "acquisition_expires_at": metadata["acquisition_expires_at"],
            "request_digest": metadata["request_digest"],
            "request_identity_digest": metadata["request_identity_digest"],
            "previous_request_digest": metadata["previous_request_digest"],
            "previous_chain_digest": metadata["previous_chain_digest"],
            "page_ordinal": metadata["page_ordinal"],
            "slice_date": metadata["slice_date"],
            "slice_ordinal": metadata["slice_ordinal"],
            "provider_page_ordinal": metadata["provider_page_ordinal"],
            "query_digest": metadata["query_digest"],
            "body_digest": metadata["body_digest"],
            "upstream_http_status": metadata["upstream_http_status"],
            "evidence_state": metadata["evidence_state"],
            "provider_pagination_state": provider,
            "pagination_state": segment,
        }
        if official_calendar is not None:
            link.update(
                {
                    "official_calendar_binding_digest": (
                        official_calendar.binding_digest
                    ),
                    "official_calendar_raw_body_digest": (
                        official_calendar.raw_body_digest
                    ),
                    "official_calendar_query_digest": (
                        official_calendar.calendar_query_digest
                    ),
                    "official_business_dates_digest": (
                        official_calendar.business_dates_digest
                    ),
                    "official_business_dates": list(
                        official_calendar.business_dates
                    ),
                }
            )
        actual_chain = _digest(link)
        if metadata["chain_digest"] != actual_chain:
            raise ValueError("acquisition chain digest does not reconcile")
        if actual_chain in seen_chains:
            raise ValueError("acquisition chain digest repeated within acquisition")
        seen_chains.add(actual_chain)
        expected_previous_chain = actual_chain
        expected_previous_request = metadata["request_digest"]
        expected_slice_date = next_slice_date
        expected_slice_ordinal = next_slice_ordinal
        expected_provider_ordinal = next_provider_ordinal
        expected_provider_cursor = next_provider_cursor
        expected_request = dict(request)
        expected_request["continuation_token"] = continuation

    assert expected_previous_chain is not None
    assert stable is not None
    return (
        initial_request_digest,
        expected_previous_chain,
        str(stable["acquisition_issued_at"]),
        str(stable["acquisition_expires_at"]),
    )


def _verify_manifest(
    *,
    manifest_path: Path,
    expected_manifest_size: int,
    expected_manifest_digest: str,
    required: RequiredCoverageSegment,
    official_calendar_path: Path | None,
    official_calendar_size: int | None,
    official_calendar_digest: str | None,
    clock: Callable[[], str],
) -> _VerifiedState:
    if not manifest_path.is_absolute() or manifest_path.resolve() != manifest_path:
        raise ValueError("live collection manifest path must be canonical and absolute")
    manifest_bytes = _read_immutable_file(
        manifest_path,
        label="live collection manifest",
        expected_size=expected_manifest_size,
        maximum_size=_MAX_MANIFEST_BYTES,
    )
    if _digest(manifest_bytes) != expected_manifest_digest:
        raise ValueError("live collection manifest changed after capture")
    document = _strict_json(manifest_bytes)
    _exact_keys(
        document,
        ("schema_version", "capture_mode", "initial_request", "pages", "collection_digest"),
        "collection manifest",
    )
    if document["schema_version"] != _COLLECTION_SCHEMA:
        raise ValueError("collection manifest schema is not v2")
    if document["capture_mode"] != _CAPTURE_MODE:
        raise ValueError("collection manifest was not captured through the live Service Binding")
    claimed_collection_digest = _require_digest(
        document["collection_digest"], "collection_digest"
    )
    body = {key: value for key, value in document.items() if key != "collection_digest"}
    if claimed_collection_digest != _digest(body):
        raise ValueError("collection manifest canonical digest does not reconcile")
    request, route, canonical_required, identity_digest, _initial_digest = _validate_request(
        document["initial_request"],
        required=required,
        allow_pending_calendar_reproof=(
            required.dataset == "equities_master"
            and official_calendar_path is not None
            and official_calendar_size is not None
            and official_calendar_digest is not None
        ),
    )
    official_calendar: OfficialBusinessCalendar | None = None
    if route.requires_official_calendar:
        if (
            not isinstance(official_calendar_path, Path)
            or type(official_calendar_size) is not int
            or type(official_calendar_digest) is not str
        ):
            raise ValueError(
                "equities_master requires receipt-authority official calendar capture"
            )
        if (
            not official_calendar_path.is_absolute()
            or official_calendar_path.resolve() != official_calendar_path
            or official_calendar_path == manifest_path
        ):
            raise ValueError(
                "official calendar capture path must be distinct, canonical, and absolute"
            )
        calendar_raw = _read_immutable_file(
            official_calendar_path,
            label="receipt-authority official calendar",
            expected_size=official_calendar_size,
            maximum_size=_MAX_RAW_PAGE_BYTES,
        )
        if _require_digest(
            official_calendar_digest, "official_calendar_digest"
        ) != _digest(calendar_raw):
            raise ValueError("official calendar capture digest differs from exact bytes")
        official_calendar = derive_official_business_calendar(
            calendar_raw,
            segment_start=request["segment_start"],
            segment_end=request["segment_end"],
        )
    elif any(
        value is not None
        for value in (
            official_calendar_path,
            official_calendar_size,
            official_calendar_digest,
        )
    ):
        raise ValueError("official calendar capture is not valid for this route")
    entries = document["pages"]
    if type(entries) is not list or not 1 <= len(entries) <= _MAX_COLLECTION_PAGES:
        raise ValueError("collection manifest must enumerate a bounded non-empty page list")
    paths: list[Path] = []
    raw_digests: list[str] = []
    raw_sizes: list[int] = []
    pages: list[tuple[Path, bytes, dict[str, Any], _ParsedProviderPage]] = []
    seen_paths: set[Path] = set()
    for entry in entries:
        if type(entry) is not dict:
            raise ValueError("collection page entry must be an object")
        _exact_keys(
            entry,
            ("raw_path", "raw_size", "raw_digest", "response_status", "headers", "metadata"),
            "collection page",
        )
        raw_path_text = _require_string(entry["raw_path"], "raw_path")
        if len(raw_path_text) > 2048 or not Path(raw_path_text).is_absolute():
            raise ValueError("raw_path must be a bounded absolute path")
        raw_path = Path(raw_path_text).resolve()
        if (
            str(raw_path) != raw_path_text
            or raw_path in seen_paths
            or raw_path == manifest_path
            or raw_path == official_calendar_path
        ):
            raise ValueError("raw_path is non-canonical or duplicated")
        seen_paths.add(raw_path)
        size = _require_int(entry["raw_size"], "raw_size", maximum=_MAX_RAW_PAGE_BYTES)
        raw = _read_immutable_file(
            raw_path,
            label="captured raw page",
            expected_size=size,
            maximum_size=_MAX_RAW_PAGE_BYTES,
        )
        raw_digest = _require_digest(entry["raw_digest"], "raw_digest")
        if _digest(raw) != raw_digest:
            raise ValueError("captured raw page digest differs from manifest")
        response_status = _require_int(entry["response_status"], "response_status", maximum=599)
        headers = entry["headers"]
        if type(headers) is not dict:
            raise ValueError("collection response headers must be an object")
        metadata = _validate_metadata(
            entry["metadata"],
            headers=headers,
            request=request,
            route=route,
            raw=raw,
            response_status=response_status,
        )
        if metadata["request_identity_digest"] != identity_digest:
            raise ValueError("target request identity digest does not reconcile")
        parsed_page = _parse_provider_page(raw, route)
        paths.append(raw_path)
        raw_digests.append(raw_digest)
        raw_sizes.append(size)
        pages.append((raw_path, raw, metadata, parsed_page))

    verification_now = _parse_clock(str(clock()))
    (
        initial_request_digest,
        terminal_chain,
        acquisition_issued_at,
        acquisition_expires_at,
    ) = _validate_state_machine(
        request=request,
        route=route,
        pages=pages,
        official_calendar=official_calendar,
        now=verification_now,
    )
    verified_at = _parse_clock(str(clock()))
    if verified_at < verification_now:
        raise ValueError("receipt authority clock moved backwards during verification")
    issued = _parse_instant(acquisition_issued_at, "acquisition_issued_at")
    expires = _parse_instant(acquisition_expires_at, "acquisition_expires_at")
    if not issued <= verified_at <= expires:
        raise ValueError("live acquisition verification completed outside its session")
    return _VerifiedState(
        dataset=required.dataset,
        required=canonical_required,
        raw_paths=tuple(paths),
        raw_digests=tuple(raw_digests),
        raw_sizes=tuple(raw_sizes),
        official_calendar_path=official_calendar_path,
        official_calendar_size=official_calendar_size,
        official_calendar_digest=official_calendar_digest,
        official_business_dates_digest=(
            None
            if official_calendar is None
            else official_calendar.business_dates_digest
        ),
        manifest_path=manifest_path,
        manifest_file_size=expected_manifest_size,
        manifest_file_digest=expected_manifest_digest,
        collection_digest=claimed_collection_digest,
        initial_request=MappingProxyType(dict(request)),
        initial_request_digest=initial_request_digest,
        terminal_chain_digest=terminal_chain,
        acquisition_issued_at=acquisition_issued_at,
        acquisition_expires_at=acquisition_expires_at,
        verified_at=verified_at,
        verified_sequence=_next_authority_event_sequence(),
    )


def _verify_live_jquants_capture(
    capture: _LiveJQuantsAcquisitionCapture,
    *,
    authority_id: object,
    required: RequiredCoverageSegment,
    clock: Callable[[], str],
) -> _VerifiedJQuantsAcquisitionCollection:
    """Consume one live capture and return a one-shot verified capability."""
    if type(capture) is not _LiveJQuantsAcquisitionCapture or capture._seal is not _LIVE_CAPTURE_SEAL:
        raise TypeError("J-Quants COMPLETE requires a live target capture capability")
    with _CAPABILITY_LOCK:
        capture_state = _LIVE_CAPTURES.get(capture)
        if capture_state is None:
            raise TypeError("live J-Quants capture is not receipt-authority registered")
        if capture_state["authority_id"] is not authority_id:
            raise TypeError("live J-Quants capture belongs to another authority")
        if capture_state["consumed"]:
            raise TypeError("live J-Quants capture has already been consumed")
        capture_state["consumed"] = True
        manifest_path = capture_state["manifest_path"]
        manifest_size = capture_state["manifest_size"]
        manifest_digest = capture_state["manifest_digest"]
        official_calendar_path = capture_state.get("official_calendar_path")
        official_calendar_size = capture_state.get("official_calendar_size")
        official_calendar_digest = capture_state.get("official_calendar_digest")
    state = _verify_manifest(
        manifest_path=manifest_path,
        expected_manifest_size=manifest_size,
        expected_manifest_digest=manifest_digest,
        required=required,
        official_calendar_path=official_calendar_path,
        official_calendar_size=official_calendar_size,
        official_calendar_digest=official_calendar_digest,
        clock=clock,
    )
    verified = _VerifiedJQuantsAcquisitionCollection(
        _seal=_VERIFIED_COLLECTION_SEAL,
        _authority_id=authority_id,
    )
    with _CAPABILITY_LOCK:
        _VERIFIED_COLLECTIONS[verified] = {
            "authority_id": authority_id,
            "consumed": False,
            "state": state,
        }
    return verified


def _consume_verified_jquants_collection(
    collection: _VerifiedJQuantsAcquisitionCollection,
    *,
    authority_id: object,
    now: datetime,
) -> tuple[tuple[bytes, ...], _VerifiedState]:
    """Consume once and recheck exact immutable bytes against live-verified state."""
    if (
        type(collection) is not _VerifiedJQuantsAcquisitionCollection
        or collection._seal is not _VERIFIED_COLLECTION_SEAL
    ):
        raise TypeError("J-Quants COMPLETE requires a verified live collection")
    with _CAPABILITY_LOCK:
        registered = _VERIFIED_COLLECTIONS.get(collection)
        if registered is None:
            raise TypeError("verified J-Quants collection is not runtime-registered")
        if registered["authority_id"] is not authority_id:
            raise TypeError("verified J-Quants collection belongs to another authority")
        if registered["consumed"]:
            raise TypeError("verified J-Quants collection has already been consumed")
        registered["consumed"] = True
        state = registered["state"]
    if not isinstance(state, _VerifiedState):  # pragma: no cover - registry invariant
        raise TypeError("verified J-Quants registry state is invalid")
    return _reread_verified_jquants_state(state, now=now), state


def _assert_verified_jquants_session_current(
    state: _VerifiedState,
    *,
    now: datetime,
) -> None:
    if not isinstance(state, _VerifiedState):
        raise TypeError("verified J-Quants state is invalid")
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise TypeError("verified J-Quants session check requires an aware clock")
    issued = _parse_instant(state.acquisition_issued_at, "acquisition_issued_at")
    expires = _parse_instant(state.acquisition_expires_at, "acquisition_expires_at")
    current = now.astimezone(timezone.utc)
    if not issued <= current <= expires:
        raise ValueError("verified live acquisition session has expired")


def _reread_verified_jquants_state(
    state: _VerifiedState,
    *,
    now: datetime,
) -> tuple[bytes, ...]:
    """Re-read the immutable collection after the structured commit boundary."""
    _assert_verified_jquants_session_current(state, now=now)
    manifest = state.manifest_path
    manifest_bytes = _read_immutable_file(
        manifest,
        label="verified collection manifest",
        expected_size=state.manifest_file_size,
        maximum_size=_MAX_MANIFEST_BYTES,
    )
    if _digest(manifest_bytes) != state.manifest_file_digest:
        raise ValueError("verified collection manifest changed after verification")
    pages: list[bytes] = []
    for path, expected_digest, expected_size in zip(
        state.raw_paths, state.raw_digests, state.raw_sizes, strict=True
    ):
        raw = _read_immutable_file(
            path,
            label="verified raw page",
            expected_size=expected_size,
            maximum_size=_MAX_RAW_PAGE_BYTES,
        )
        if _digest(raw) != expected_digest:
            raise ValueError("verified raw page changed after verification")
        pages.append(raw)
    if state.official_calendar_path is not None:
        if (
            state.official_calendar_size is None
            or state.official_calendar_digest is None
        ):
            raise TypeError("verified official calendar state is incomplete")
        calendar_raw = _read_immutable_file(
            state.official_calendar_path,
            label="verified receipt-authority official calendar",
            expected_size=state.official_calendar_size,
            maximum_size=_MAX_RAW_PAGE_BYTES,
        )
        if _digest(calendar_raw) != state.official_calendar_digest:
            raise ValueError("verified official calendar changed after verification")
        calendar = derive_official_business_calendar(
            calendar_raw,
            segment_start=state.required.segment_start,
            segment_end=state.required.segment_end,
        )
        if calendar.business_dates_digest != state.official_business_dates_digest:
            raise ValueError("verified official business dates changed after verification")
    return tuple(pages)


__all__: list[str] = []
