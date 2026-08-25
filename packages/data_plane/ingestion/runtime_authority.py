"""Trusted ingestion runtime — sole holder of receipt signing keys.

Production ingestion receives a private governed service, never the private-key
issuer.  The service re-parses persisted immutable raw bytes with the canonical
source adapter, re-runs the canonical normalizer, rereads those exact natural
keys from the still-open structured transaction, and only then signs and
commits the fact/receipt transaction.
"""

from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import dataclass
import json
from pathlib import Path
from threading import Lock
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Callable, Mapping, Sequence
from weakref import WeakKeyDictionary, WeakSet

from data_contracts import coverage_contract_for
from storage.coverage_ledger import (
    CollectionReceipt,
    RequiredCoverageSegment,
    record_collection_receipt,
)
from storage.receipt_crypto import (
    ReceiptSigningKey,
    STANDARD_CLAIM_KEYS,
    build_signed_digest_fields,
    canonical_evidence_digest,
    load_signing_key,
)

if TYPE_CHECKING:
    from storage.sqlite_store import SqliteStore

# Run states for governed ingestion (Phase 6.2.3 §2).
RUN_ACQUIRED = "ACQUIRED"
RUN_RAW_STORED = "RAW_STORED"
RUN_STRUCTURED_COMMITTED = "STRUCTURED_COMMITTED"
RUN_RECEIPT_VERIFIED = "RECEIPT_VERIFIED"
RUN_COVERAGE_COMPLETE = "COVERAGE_COMPLETE"
RUN_PARTIAL = "PARTIAL"
RUN_FAILED = "FAILED"


_SERVICE_SEAL = object()
_PERSISTED_JQUANTS_SEAL = object()
_COLLECTION_CONTEXT_SEAL = object()
_GOVERNED_JQUANTS_CLIENT_SEAL = object()
_TRUSTED_JQUANTS_FETCHES: WeakKeyDictionary[Any, dict[str, Any]] = (
    WeakKeyDictionary()
)
_TRUSTED_JQUANTS_FETCHES_LOCK = Lock()
_GOVERNED_SERVICES: WeakSet[Any] = WeakSet()
_GOVERNED_CONTEXTS: WeakKeyDictionary[Any, dict[str, Any]] = WeakKeyDictionary()
_GOVERNED_JQUANTS_CLIENTS: WeakSet[Any] = WeakSet()
_PERSISTED_JQUANTS_COLLECTIONS: WeakKeyDictionary[Any, dict[str, Any]] = (
    WeakKeyDictionary()
)
_CAPABILITY_REGISTRY_LOCK = Lock()
_MAX_CONTEXT_AGE_SECONDS = 15 * 60
_MAX_CLOCK_SKEW_SECONDS = 5


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True, eq=False)
class _GovernedCollectionContext:
    """Authority-minted timestamp/correlation capability for one transaction."""

    _seal: object
    _authority_id: object
    checked_at: str

    def __post_init__(self) -> None:
        if self._seal is not _COLLECTION_CONTEXT_SEAL:
            raise TypeError("collection context must be minted by receipt authority")


@dataclass(frozen=True, eq=False)
class _PersistedJQuantsCollection:
    """Opaque handle binding client-minted fetch evidence to immutable files."""

    _seal: object
    dataset: str
    base_params: Mapping[str, Any]
    raw_paths: tuple[Path, ...]
    manifest_path: Path
    raw_page_digests: tuple[str, ...]
    manifest_digest: str
    fetch_identity_digest: str

    def __post_init__(self) -> None:
        if self._seal is not _PERSISTED_JQUANTS_SEAL:
            raise TypeError("persisted J-Quants evidence is minted by ingestion runtime")


def _seal_persisted_jquants_collection(
    *,
    authority_id: object,
    fetch_result: Any,
    raw_paths: Sequence[Path | str],
    manifest_path: Path | str,
) -> _PersistedJQuantsCollection:
    """Seal client fetch evidence only after exact immutable persistence."""
    from ingestion.jquants import catalog
    from ingestion.jquants.client import _JQuantsFetchResult
    from urllib.parse import urlsplit

    if not isinstance(fetch_result, _JQuantsFetchResult):
        raise TypeError("J-Quants persisted evidence requires client-minted result")
    with _TRUSTED_JQUANTS_FETCHES_LOCK:
        fetch_state = _TRUSTED_JQUANTS_FETCHES.get(fetch_result)
        if fetch_state is None or fetch_state["authority_id"] is not authority_id:
            raise TypeError(
                "J-Quants COMPLETE requires a governed runtime transport fetch"
            )
        if fetch_state["consumed"]:
            raise TypeError("governed J-Quants fetch has already been persisted")
        fetch_state["consumed"] = True
    paths = tuple(Path(item).expanduser().resolve() for item in raw_paths)
    if len(paths) != len(fetch_result.pages) or not paths:
        raise ValueError("persisted pages do not match client fetch result")
    expected_path = catalog.path_of(fetch_result.dataset_id)
    allowed_params = set(catalog.get(fetch_result.dataset_id).get("params") or ())
    if not set(fetch_result.base_params).issubset(allowed_params):
        raise ValueError("J-Quants fetch used parameters outside the catalog contract")
    proxy_endpoint = None
    if fetch_result.transport_name == "cf-jquants-proxy":
        from ingestion.common.secrets import resolve_proxy_config

        proxy = resolve_proxy_config()
        if proxy is None:
            raise ValueError("J-Quants proxy evidence has no resolved trusted endpoint")
        proxy_endpoint = urlsplit(proxy.url.rstrip("/") + "/v1/proxy/jquants")
    persisted_page_bytes: list[bytes] = []
    for page, path in zip(fetch_result.pages, paths, strict=True):
        if page.request_path != expected_path:
            raise ValueError("J-Quants fetch used a non-canonical catalog path")
        parsed_url = urlsplit(page.response_url)
        if fetch_result.transport_name == "cf-jquants-proxy":
            assert proxy_endpoint is not None
            if (
                parsed_url.scheme,
                parsed_url.netloc,
                parsed_url.path.rstrip("/"),
            ) != (
                proxy_endpoint.scheme,
                proxy_endpoint.netloc,
                proxy_endpoint.path.rstrip("/"),
            ):
                raise ValueError("J-Quants proxy response URL is not trusted")
        elif (
            parsed_url.scheme != "https"
            or parsed_url.hostname != "api.jquants.com"
            or parsed_url.port not in (None, 443)
            or parsed_url.path != expected_path
        ):
            raise ValueError("J-Quants direct response URL differs from catalog path")
        if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o222:
            raise ValueError("persisted J-Quants page must be immutable")
        persisted_body = path.read_bytes()
        if persisted_body != page.response_body:
            raise ValueError("persisted J-Quants page differs from fetched response")
        persisted_page_bytes.append(persisted_body)
    manifest = Path(manifest_path).expanduser().resolve()
    if manifest.is_symlink() or not manifest.is_file() or manifest.stat().st_mode & 0o222:
        raise ValueError("persisted J-Quants manifest must be immutable")
    manifest_bytes = manifest.read_bytes()
    try:
        payload = json.loads(manifest_bytes)
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError) as exc:
        raise ValueError("persisted J-Quants manifest is not JSON") from exc
    entries = payload.get("pages") if isinstance(payload, Mapping) else None
    if (
        not isinstance(entries, list)
        or len(entries) != len(fetch_result.pages)
        or payload.get("schema_version") != "jquants-pagination-evidence/v1"
        or payload.get("source") != "jquants"
        or payload.get("dataset") != fetch_result.dataset_id
        or dict(payload.get("base_params") or {}) != dict(fetch_result.base_params)
    ):
        raise ValueError("persisted manifest differs from client fetch identity")
    for index, (entry, page, raw_path) in enumerate(
        zip(entries, fetch_result.pages, paths, strict=True)
    ):
        expected = {
            "index": index,
            "raw_path": str(raw_path),
            "body_digest": _digest(page.response_body),
            "request_path": page.request_path,
            "request_params": dict(page.request_params),
            "response_url": page.response_url,
            "response_status": page.response_status,
            "pagination_in": page.pagination_in,
            "pagination_out": page.pagination_out,
        }
        if not isinstance(entry, Mapping) or any(
            entry.get(field) != value for field, value in expected.items()
        ):
            raise ValueError("persisted manifest was not minted from fetched pages")
    fetch_identity = {
        "dataset": fetch_result.dataset_id,
        "base_params": dict(fetch_result.base_params),
        "pages": [
            {
                "request_path": page.request_path,
                "request_params": dict(page.request_params),
                "response_url": page.response_url,
                "response_status": page.response_status,
                "pagination_in": page.pagination_in,
                "pagination_out": page.pagination_out,
                "body_digest": _digest(page.response_body),
            }
            for page in fetch_result.pages
        ],
    }
    collection = _PersistedJQuantsCollection(
        _seal=_PERSISTED_JQUANTS_SEAL,
        dataset=fetch_result.dataset_id,
        base_params=MappingProxyType(dict(fetch_result.base_params)),
        raw_paths=paths,
        manifest_path=manifest,
        raw_page_digests=tuple(_digest(page) for page in persisted_page_bytes),
        manifest_digest=_digest(manifest_bytes),
        fetch_identity_digest=_digest(fetch_identity),
    )
    with _CAPABILITY_REGISTRY_LOCK:
        _PERSISTED_JQUANTS_COLLECTIONS[collection] = {
            "authority_id": authority_id,
            "consumed": False,
        }
    return collection


@dataclass(frozen=True, eq=False)
class _GovernedJQuantsClient:
    """Runtime-created facade; public JQuantsClient instances cannot attest."""

    _seal: object
    _authority_id: object
    _client: Any

    def __post_init__(self) -> None:
        if self._seal is not _GOVERNED_JQUANTS_CLIENT_SEAL:
            raise TypeError("governed J-Quants client is runtime-minted")

    def fetch_dataset_evidenced(self, dataset_id: str, **params: Any) -> Any:
        with _CAPABILITY_REGISTRY_LOCK:
            if self not in _GOVERNED_JQUANTS_CLIENTS:
                raise TypeError("governed J-Quants client is not runtime-registered")
        result = self._client.fetch_dataset_evidenced(dataset_id, **params)
        with _TRUSTED_JQUANTS_FETCHES_LOCK:
            _TRUSTED_JQUANTS_FETCHES[result] = {
                "authority_id": self._authority_id,
                "consumed": False,
            }
        return result

    def fetch_dataset(self, dataset_id: str, **params: Any) -> list[dict[str, Any]]:
        return list(self.fetch_dataset_evidenced(dataset_id, **params).rows)


@dataclass(frozen=True, eq=False)
class _GovernedReceiptService:
    """Positive capability for DB/raw reconciliation and receipt persistence."""

    _seal: object
    _signing_key: ReceiptSigningKey
    _clock: Callable[[], str]
    _authority_id: object

    def __post_init__(self) -> None:
        if self._seal is not _SERVICE_SEAL:
            raise TypeError("receipt service must be opened by ingestion runtime")

    def begin_collection(self) -> _GovernedCollectionContext:
        """Mint the only timestamp accepted by a governed transaction."""
        self._assert_registered()
        checked_at = str(self._clock())
        parsed = datetime.fromisoformat(checked_at.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("governed collection clock must be timezone-aware")
        context = _GovernedCollectionContext(
            _seal=_COLLECTION_CONTEXT_SEAL,
            _authority_id=self._authority_id,
            checked_at=checked_at,
        )
        with _CAPABILITY_REGISTRY_LOCK:
            _GOVERNED_CONTEXTS[context] = {
                "authority_id": self._authority_id,
                "consumed": False,
            }
        return context

    def _assert_registered(self) -> None:
        with _CAPABILITY_REGISTRY_LOCK:
            if self not in _GOVERNED_SERVICES:
                raise TypeError("receipt service is not runtime-registered")

    def open_jquants_client(
        self,
        *,
        api_key: str = "",
        via_cf_proxy: bool | None = None,
    ) -> _GovernedJQuantsClient:
        """Create the network transport inside the signing runtime boundary.

        No caller-supplied HttpClient is accepted.  This prevents a public
        JQuantsClient wrapped around a canned/fake transport from minting fetch
        provenance merely by choosing a plausible response URL or client name.
        """
        self._assert_registered()
        from ingestion.jquants.client import JQuantsClient

        if via_cf_proxy:
            raise RuntimeError(
                "governed COMPLETE uses direct api.jquants.com acquisition"
            )
        http = _direct_jquants_http()
        facade = _GovernedJQuantsClient(
            _seal=_GOVERNED_JQUANTS_CLIENT_SEAL,
            _authority_id=self._authority_id,
            _client=JQuantsClient(http, api_key),
        )
        with _CAPABILITY_REGISTRY_LOCK:
            _GOVERNED_JQUANTS_CLIENTS.add(facade)
        return facade

    def persist_jquants_collection(
        self,
        *,
        fetch_result: Any,
        raw_paths: Sequence[Path | str],
        manifest_path: Path | str,
    ) -> _PersistedJQuantsCollection:
        """Bind one governed fetch to exact create-only persisted bytes."""
        self._assert_registered()
        return _seal_persisted_jquants_collection(
            authority_id=self._authority_id,
            fetch_result=fetch_result,
            raw_paths=raw_paths,
            manifest_path=manifest_path,
        )

    def record_persisted_success(
        self,
        store: SqliteStore,
        *,
        required: RequiredCoverageSegment,
        run_id: int,
        collection_context: _GovernedCollectionContext,
        raw_artifact_paths: Sequence[Path | str] = (),
        jquants_collection: _PersistedJQuantsCollection | None = None,
        source_request: Mapping[str, Any] | None = None,
        extra_evidence: Mapping[str, Any] | None = None,
    ) -> CollectionReceipt:
        """Commit, independently remeasure persisted state, sign, and record.

        Counts, digests, parsed/normalized rows, table names, and exhaustion
        claims are never parameters.  They are derived from the required
        contract and immutable raw bytes.  The caller's canonical fact writes
        remain uncommitted until this method independently reproduces them and
        records the receipt in the same transaction.  Any mismatch rolls the
        transaction back and cannot create COMPLETE-eligible evidence.
        """
        from storage.sqlite_store import SqliteStore

        self._assert_registered()
        if not isinstance(store, SqliteStore):
            raise TypeError("governed receipt service requires SqliteStore")
        if not isinstance(required, RequiredCoverageSegment):
            raise TypeError("required must be RequiredCoverageSegment")
        if (
            not isinstance(collection_context, _GovernedCollectionContext)
            or collection_context._seal is not _COLLECTION_CONTEXT_SEAL
        ):
            raise TypeError("governed SUCCESS requires an authority-minted context")
        with _CAPABILITY_REGISTRY_LOCK:
            context_state = _GOVERNED_CONTEXTS.get(collection_context)
            if context_state is None:
                raise TypeError(
                    "governed SUCCESS requires a registered collection context"
                )
            if context_state["authority_id"] is not self._authority_id:
                raise TypeError("collection context belongs to another authority")
            if context_state["consumed"]:
                raise TypeError("collection context has already been consumed")
            context_state["consumed"] = True
        checked_at = collection_context.checked_at
        checked_dt = datetime.fromisoformat(checked_at.replace("Z", "+00:00"))
        now_dt = datetime.fromisoformat(str(self._clock()).replace("Z", "+00:00"))
        if checked_dt.tzinfo is None or now_dt.tzinfo is None:
            raise ValueError("governed collection clock must be timezone-aware")
        age = (now_dt.astimezone(timezone.utc) - checked_dt.astimezone(timezone.utc))
        if age.total_seconds() < -_MAX_CLOCK_SKEW_SECONDS:
            raise ValueError("collection context timestamp is in the future")
        if age.total_seconds() > _MAX_CONTEXT_AGE_SECONDS:
            raise ValueError("collection context is stale")

        if required.source == "jquants":
            if not isinstance(jquants_collection, _PersistedJQuantsCollection):
                raise TypeError(
                    "J-Quants COMPLETE requires runtime-minted persisted evidence"
                )
            if raw_artifact_paths:
                raise TypeError("J-Quants raw paths cannot bypass the opaque handle")
            if jquants_collection.dataset != required.dataset:
                raise ValueError("persisted J-Quants dataset differs from required")
            trusted_raw_pages, trusted_manifest = _consume_persisted_jquants_handle(
                jquants_collection,
                authority_id=self._authority_id,
            )
            _assert_jquants_request_scope(
                required=required,
                base_params=jquants_collection.base_params,
                source_request=source_request,
            )
            candidates = jquants_collection.raw_paths
        else:
            # JSDA acquisition has not yet been migrated to a fetcher-minted,
            # redirect/host/discovery-bound opaque handle.  Local readonly
            # files plus a caller URL are recovery evidence, never signable.
            raise RuntimeError(
                "JSDA governed SUCCESS requires opaque official-fetch evidence; "
                "raw path recovery is RECOVERED_RAW_ONLY"
            )
        if not candidates:
            raise ValueError("persisted raw artifact path is required")
        if any(path.is_symlink() for path in candidates):
            raise ValueError("raw evidence symlinks are not trusted")
        paths = tuple(path.resolve() for path in candidates)
        for path in paths:
            if not path.is_file():
                raise ValueError(f"raw evidence must be a regular persisted file: {path}")
            if path.stat().st_mode & 0o222:
                raise ValueError(f"raw evidence artifact is writable: {path}")

        try:
            raw_pages = trusted_raw_pages
            if any(not page for page in raw_pages):
                raise ValueError("reconciled SUCCESS requires non-empty raw pages")
            if required.source == "jquants":
                _verify_jquants_pagination_chain(
                    required=required,
                    raw_paths=paths,
                    raw_pages=raw_pages,
                    manifest_bytes=trusted_manifest,
                    source_request=source_request,
                )
            trusted_extras = _trusted_extra_evidence(required, extra_evidence)
            raw_records, normalized_records, structured_table = (
                _canonical_collection_from_raw(
                    store=store,
                    required=required,
                    raw_pages=raw_pages,
                    raw_paths=paths,
                    checked_at=checked_at,
                    source_request=source_request,
                    extra_evidence=trusted_extras,
                )
            )
            structured_rows = _fetch_exact_segment_rows(
                store=store,
                required=required,
                structured_table=structured_table,
            )
            prior_available = _prior_verified_available_at(
                store=store,
                required=required,
                raw_records=raw_records,
                raw_pages=raw_pages,
            )
            _assert_canonical_structured_projection(
                required=required,
                expected_rows=normalized_records,
                persisted_rows=structured_rows,
                prior_verified_available_at=prior_available,
            )
            _assert_trusted_exhaustion(required)
            claims = _measure_collection_claims(
                required=required,
                run_id=run_id,
                raw_pages=raw_pages,
                raw_records=raw_records,
                structured_records=structured_rows,
                checked_at=checked_at,
                source_request=source_request,
                extra_evidence=trusted_extras,
            )
            signed = build_signed_digest_fields(
                signing_key=self._signing_key,
                closure_claims=claims,
            )
            receipt = CollectionReceipt(
                source=required.source,
                dataset=required.dataset,
                segment_id=required.segment_id,
                segment_start=required.segment_start,
                segment_end=required.segment_end,
                expected_scope=dict(required.expected_scope),
                expected_items=required.expected_items,
                observed_items=int(claims["observed_items"]),
                raw_page_count=int(claims["raw_page_count"]),
                raw_row_count=int(claims["raw_count"]),
                structured_row_count=int(claims["structured_count"]),
                pagination_exhausted=True,
                digests=MappingProxyType(dict(signed)),
                run_id=int(run_id),
                status="SUCCESS",
                error=None,
                checked_at=checked_at,
            )
            record_collection_receipt(store._conn, receipt)  # noqa: SLF001
            store._conn.commit()  # noqa: SLF001
        except Exception:
            store._conn.rollback()  # noqa: SLF001
            raise
        return receipt


def _open_governed_receipt_service() -> _GovernedReceiptService:
    """Open the only production capability that can persist signed SUCCESS.

    The factory is deliberately argument-free: private material comes only
    from the dedicated runtime configuration, and ``load_signing_key`` derives
    the issuer id by exact match against the committed verifier registry.
    """
    key = load_signing_key()
    if key is None:
        raise RuntimeError("receipt signing authority is not configured")
    service = _GovernedReceiptService(
        _seal=_SERVICE_SEAL,
        _signing_key=key,
        _clock=_utc_now,
        _authority_id=object(),
    )
    with _CAPABILITY_REGISTRY_LOCK:
        _GOVERNED_SERVICES.add(service)
    return service


def _direct_jquants_http() -> Any:
    """Construct the only production transport eligible for COMPLETE."""
    from ingestion.common.http import LocalHttpClient

    return LocalHttpClient(verify=True, trust_env=False)


def _digest(payload: Any) -> str:
    return canonical_evidence_digest(payload)


def _consume_persisted_jquants_handle(
    collection: _PersistedJQuantsCollection,
    *,
    authority_id: object,
) -> tuple[tuple[bytes, ...], bytes]:
    """Read/check mint-time bytes once, then return that exact signing input."""
    if (
        not isinstance(collection, _PersistedJQuantsCollection)
        or collection._seal is not _PERSISTED_JQUANTS_SEAL
    ):
        raise TypeError("persisted J-Quants evidence is not runtime-minted")
    with _CAPABILITY_REGISTRY_LOCK:
        state = _PERSISTED_JQUANTS_COLLECTIONS.get(collection)
        if state is None:
            raise TypeError("persisted J-Quants evidence is not runtime-registered")
        if state["authority_id"] is not authority_id:
            raise TypeError("persisted J-Quants evidence belongs to another authority")
        if state["consumed"]:
            raise TypeError("persisted J-Quants evidence has already been consumed")
        state["consumed"] = True
    if len(collection.raw_paths) != len(collection.raw_page_digests):
        raise ValueError("persisted J-Quants page identity is inconsistent")
    pages: list[bytes] = []
    for path, expected in zip(
        collection.raw_paths, collection.raw_page_digests, strict=True
    ):
        if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o222:
            raise ValueError("persisted J-Quants page lost immutable state")
        page = path.read_bytes()
        if _digest(page) != expected:
            raise ValueError("persisted J-Quants page changed after mint")
        pages.append(page)
    manifest = collection.manifest_path
    if (
        manifest.is_symlink()
        or not manifest.is_file()
        or manifest.stat().st_mode & 0o222
    ):
        raise ValueError("persisted J-Quants manifest lost immutable state")
    manifest_bytes = manifest.read_bytes()
    if _digest(manifest_bytes) != collection.manifest_digest:
        raise ValueError("persisted J-Quants manifest changed after mint")
    try:
        manifest_payload = json.loads(manifest_bytes)
        entries = manifest_payload["pages"]
        identity = {
            "dataset": collection.dataset,
            "base_params": dict(collection.base_params),
            "pages": [
                {
                    "request_path": entry["request_path"],
                    "request_params": entry["request_params"],
                    "response_url": entry["response_url"],
                    "response_status": entry["response_status"],
                    "pagination_in": entry["pagination_in"],
                    "pagination_out": entry["pagination_out"],
                    "body_digest": entry["body_digest"],
                }
                for entry in entries
            ],
        }
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise ValueError("persisted J-Quants manifest identity is invalid") from exc
    if _digest(identity) != collection.fetch_identity_digest:
        raise ValueError("persisted J-Quants fetch identity changed after mint")
    return tuple(pages), manifest_bytes


def _trusted_extra_evidence(
    required: RequiredCoverageSegment,
    extra_evidence: Mapping[str, Any] | None,
) -> Mapping[str, Any]:
    """Accept no caller policy/authority claims on the trusted JQ path.

    Provenance is already closed by the persisted page manifest and signed
    source-request digest.  Arbitrary caller annotations (especially
    EXPECTED_EMPTY_WITH_EVIDENCE, eligibility, issuer, counts, or digests)
    therefore have no place in a COMPLETE-eligible closure.
    """
    extras = dict(extra_evidence or {})
    if required.source == "jquants" and extras:
        raise ValueError(
            "trusted J-Quants SUCCESS does not accept caller extra_evidence"
        )
    overlap = sorted(set(extras) & STANDARD_CLAIM_KEYS)
    if overlap:
        raise ValueError(f"extra_evidence attempts to override claims: {overlap}")
    if "EXPECTED_EMPTY_WITH_EVIDENCE" in extras:
        raise ValueError("caller expected-empty evidence is not trusted")
    return MappingProxyType(extras)


def _assert_jquants_request_scope(
    *,
    required: RequiredCoverageSegment,
    base_params: Mapping[str, Any],
    source_request: Mapping[str, Any] | None,
) -> None:
    """Require the opaque fetch query to cover the exact required time scope."""
    params = dict(base_params)
    temporal_keys = {"date", "from", "to"}
    narrowing = sorted(set(params) - temporal_keys)
    scope = dict(required.expected_scope)
    for key in narrowing:
        if key not in scope or scope[key] != params[key]:
            raise ValueError(
                f"J-Quants narrowing filter {key!r} is not in required scope"
            )
    request = dict(source_request or {})
    if request:
        if request.get("dataset", required.dataset) != required.dataset:
            raise ValueError("source request dataset differs from required segment")
        request_params = request.get("params")
        if not isinstance(request_params, Mapping) or dict(request_params) != params:
            raise ValueError("source request params differ from opaque fetch evidence")

    start = required.segment_start[:10]
    end = required.segment_end[:10]
    date_value = str(params.get("date") or "")[:10]
    from_value = str(params.get("from") or "")[:10]
    to_value = str(params.get("to") or "")[:10]
    if date_value:
        policy = coverage_contract_for(required.dataset)
        if (
            policy.segment_granularity == "calendar_month"
            or start != end
            or date_value != start
        ):
            raise ValueError(
                "single-date J-Quants query cannot prove a wider required segment"
            )
        if from_value or to_value:
            raise ValueError("J-Quants temporal query shape is ambiguous")
        return
    if from_value or to_value:
        if not from_value or not to_value or (from_value, to_value) != (start, end):
            raise ValueError(
                "J-Quants query window must exactly equal the required segment"
            )
        return
    if start != end:
        raise ValueError(
            "unbounded J-Quants query cannot prove a multi-day required segment"
        )
    policy = coverage_contract_for(required.dataset)
    if policy.history_mode not in {
        "recent_snapshot",
        "next_business_day_snapshot",
    }:
        raise ValueError(
            "vendor-default J-Quants query is trusted only for tip snapshots"
        )


def _fetch_exact_segment_rows(
    *,
    store: SqliteStore,
    required: RequiredCoverageSegment,
    structured_table: str,
) -> tuple[Mapping[str, Any], ...]:
    """Reread the complete contract-derived segment, including extra keys."""
    conn = store._conn  # noqa: SLF001
    if structured_table == "jquants_records":
        rows = conn.execute(
            "SELECT * FROM jquants_records WHERE source=? AND dataset=? "
            "AND substr(event_time,1,10) BETWEEN ? AND ? ORDER BY natural_key",
            (
                required.source,
                required.dataset,
                required.segment_start[:10],
                required.segment_end[:10],
            ),
        ).fetchall()
    elif structured_table == "jsda_otc_bond_reference_prices":
        if required.segment_id.startswith("correction:"):
            rows = conn.execute(
                "SELECT * FROM jsda_otc_bond_reference_prices "
                "WHERE source=? AND segment_id=?",
                (required.source, required.segment_id),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM jsda_otc_bond_reference_prices "
                "WHERE source=? AND publication_label_date BETWEEN ? AND ?",
                (
                    required.source,
                    required.segment_start[:10],
                    required.segment_end[:10],
                ),
            ).fetchall()
    elif structured_table == "jsda_repo_rates":
        rows = conn.execute(
            "SELECT * FROM jsda_repo_rates WHERE source=? "
            "AND as_of_date BETWEEN ? AND ?",
            (
                required.source,
                required.segment_start[:10],
                required.segment_end[:10],
            ),
        ).fetchall()
    else:
        raise ValueError("no exact segment reread contract for structured table")
    return tuple(dict(row) for row in rows)


def _prior_verified_available_at(
    *,
    store: SqliteStore,
    required: RequiredCoverageSegment,
    raw_records: Sequence[Any],
    raw_pages: Sequence[bytes],
) -> Mapping[tuple[Any, ...], Any]:
    """Recover PIT availability only from a prior current-version proof.

    SqliteStore keeps the earliest available_at for an unchanged natural key.
    A later v4 reproof may reuse that value only when the prior verified
    closure signed the same raw artifact and canonical normalization at its
    authority-minted checked_at reproduces it.
    """
    if required.source != "jquants":
        return MappingProxyType({})
    row = store._conn.execute(  # noqa: SLF001
        "SELECT * FROM collection_receipts WHERE source=? AND dataset=? "
        "AND segment_id=? AND status='SUCCESS' "
        "ORDER BY checked_at DESC, run_id DESC LIMIT 1",
        (required.source, required.dataset, required.segment_id),
    ).fetchone()
    if row is None:
        return MappingProxyType({})
    try:
        from ingestion.jquants.normalize import normalize_generic
        from storage.schema import NATURAL_KEYS
        from storage.verified_receipt import require_verified_collection_closure

        receipt = CollectionReceipt(
            source=str(row["source"]),
            dataset=str(row["dataset"]),
            segment_id=str(row["segment_id"]),
            segment_start=str(row["segment_start"]),
            segment_end=str(row["segment_end"]),
            expected_scope=json.loads(str(row["expected_scope"])),
            expected_items=(
                None if row["expected_items"] is None else int(row["expected_items"])
            ),
            observed_items=int(row["observed_items"]),
            raw_page_count=int(row["raw_page_count"]),
            raw_row_count=int(row["raw_row_count"]),
            structured_row_count=int(row["structured_row_count"]),
            pagination_exhausted=bool(row["pagination_exhausted"]),
            digests=json.loads(str(row["digests_json"])),
            run_id=int(row["run_id"]),
            status=str(row["status"]),
            error=None if row["error"] is None else str(row["error"]),
            checked_at=str(row["checked_at"]),
        )
        closure = require_verified_collection_closure(receipt, required=required)
        page_manifest = [
            {"index": index, "digest": _digest(page), "size": len(page)}
            for index, page in enumerate(raw_pages)
        ]
        current_raw_digest = (
            page_manifest[0]["digest"]
            if len(page_manifest) == 1
            else _digest({"pages": page_manifest})
        )
        if closure.raw_digest != current_raw_digest:
            return MappingProxyType({})
        normalized = normalize_generic(
            (dict(item) for item in raw_records),
            dataset=required.dataset,
            ingested_at=closure.checked_at,
        )
        keys = NATURAL_KEYS["jquants_records"]
        return MappingProxyType(
            {
                tuple(item[key] for key in keys): item.get("available_at")
                for item in normalized
            }
        )
    except Exception:
        return MappingProxyType({})


def _json_records_from_pages(raw_pages: Sequence[bytes]) -> tuple[Any, ...] | None:
    """Return records decoded from JSON artifacts, or ``None`` for binary raw.

    Returning the records rather than only a count prevents a caller from
    substituting same-sized parsed content while asking the runtime to sign
    the genuine raw artifact digest.
    """
    measured: list[Any] = []
    saw_json = False
    for raw in raw_pages:
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError):
            continue
        saw_json = True
        if isinstance(payload, list):
            measured.extend(payload)
            continue
        if isinstance(payload, dict):
            rows = next(
                (
                    payload.get(key)
                    for key in ("data", "rows", "results", "records")
                    if isinstance(payload.get(key), list)
                ),
                None,
            )
            measured.extend(rows or ())
    return tuple(measured) if saw_json else None


def _verify_jquants_pagination_chain(
    *,
    required: RequiredCoverageSegment,
    raw_paths: Sequence[Path],
    raw_pages: Sequence[bytes],
    manifest_bytes: bytes,
    source_request: Mapping[str, Any] | None,
) -> None:
    """Derive terminal pagination from verbatim page envelopes and chain."""
    from ingestion.jquants import catalog

    try:
        manifest = json.loads(manifest_bytes)
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError) as exc:
        raise ValueError("pagination manifest is not canonical JSON") from exc
    if not isinstance(manifest, Mapping):
        raise ValueError("pagination manifest must be an object")
    if manifest.get("schema_version") != "jquants-pagination-evidence/v1":
        raise ValueError("unsupported J-Quants pagination manifest")
    if manifest.get("source") != "jquants" or manifest.get("dataset") != required.dataset:
        raise ValueError("pagination manifest source/dataset mismatch")
    entries = manifest.get("pages")
    if not isinstance(entries, list) or len(entries) != len(raw_pages):
        raise ValueError("pagination manifest does not enumerate every raw page")
    request = dict(source_request or {})
    request_params = request.get("params")
    if isinstance(request_params, Mapping) and dict(
        manifest.get("base_params") or {}
    ) != dict(request_params):
        raise ValueError("pagination manifest base request mismatch")

    previous_out: str | None = None
    seen_out: set[str] = set()
    expected_path = catalog.path_of(required.dataset)
    for index, (entry, raw_path, raw_page) in enumerate(
        zip(entries, raw_paths, raw_pages, strict=True)
    ):
        if not isinstance(entry, Mapping) or int(entry.get("index", -1)) != index:
            raise ValueError("pagination manifest page order is invalid")
        if Path(str(entry.get("raw_path") or "")).expanduser().resolve() != raw_path:
            raise ValueError("pagination manifest raw path mismatch")
        if entry.get("body_digest") != _digest(raw_page):
            raise ValueError("pagination manifest page digest mismatch")
        if entry.get("request_path") != expected_path:
            raise ValueError("pagination manifest catalog path mismatch")
        if int(entry.get("response_status", 0)) != 200:
            raise ValueError("non-success J-Quants response cannot be signed")
        try:
            payload = json.loads(raw_page)
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError) as exc:
            raise ValueError("J-Quants raw response page is not JSON") from exc
        if not isinstance(payload, Mapping):
            raise ValueError("J-Quants raw response page must be an envelope")
        actual_out = payload.get("pagination_key") or payload.get("pagination_token")
        actual_out = str(actual_out) if actual_out else None
        recorded_in = entry.get("pagination_in")
        recorded_in = str(recorded_in) if recorded_in else None
        recorded_out = entry.get("pagination_out")
        recorded_out = str(recorded_out) if recorded_out else None
        if recorded_in != previous_out or recorded_out != actual_out:
            raise ValueError("J-Quants continuation chain does not reconcile")
        params = entry.get("request_params")
        if not isinstance(params, Mapping):
            raise ValueError("pagination page request params are missing")
        param_token = params.get("pagination_key")
        param_token = str(param_token) if param_token else None
        if param_token != recorded_in:
            raise ValueError("pagination request token does not match prior response")
        if index < len(entries) - 1 and actual_out is None:
            raise ValueError("pagination manifest continues after a terminal page")
        if actual_out is not None:
            if actual_out in seen_out:
                raise ValueError("pagination continuation token repeated")
            seen_out.add(actual_out)
        previous_out = actual_out
    if previous_out is not None:
        raise ValueError("J-Quants pagination is not exhausted at terminal page")


def _canonical_json_value(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError, ValueError):
            return value
    return value


def _canonical_collection_from_raw(
    *,
    store: SqliteStore,
    required: RequiredCoverageSegment,
    raw_pages: Sequence[bytes],
    raw_paths: Sequence[Path],
    checked_at: str,
    source_request: Mapping[str, Any] | None,
    extra_evidence: Mapping[str, Any] | None,
) -> tuple[tuple[Any, ...], tuple[Mapping[str, Any], ...], str]:
    """Reproduce the governed parser/normalizer output from persisted bytes.

    This dispatch is deliberately closed.  A caller cannot provide a parser,
    normalizer, fact table, parsed rows, or natural keys.
    """
    if not checked_at or not isinstance(checked_at, str):
        raise ValueError("checked_at is required for canonical normalization")
    pages = tuple(bytes(page) for page in raw_pages)
    request = dict(source_request or {})
    extras = dict(extra_evidence or {})

    if required.source == "jquants":
        from ingestion.jquants.normalize import normalize_generic

        decoded = _json_records_from_pages(pages)
        if decoded is None:
            raise ValueError("J-Quants governed raw must be a JSON record envelope")
        if any(not isinstance(row, Mapping) for row in decoded):
            raise ValueError("J-Quants governed raw contains a non-object record")
        records = tuple(dict(row) for row in decoded)
        normalized = tuple(
            normalize_generic(
                records,
                dataset=required.dataset,
                ingested_at=checked_at,
            )
        )
        return records, normalized, "jquants_records"

    if required.source != "jsda":
        raise ValueError(f"no governed canonical adapter for source: {required.source}")

    scope = dict(required.expected_scope)
    source_format = str(scope.get("source_format") or "").lower()
    if not source_format and len(raw_paths) == 1:
        source_format = raw_paths[0].suffix.lower().lstrip(".")

    if required.dataset == "jsda_otc_bond_reference_prices":
        if required.segment_id.startswith("correction:"):
            return _canonical_otc_correction_from_raw(
                store=store,
                required=required,
                raw_pages=pages,
                raw_paths=raw_paths,
                checked_at=checked_at,
                extra_evidence=extras,
            )
        if len(pages) != 1:
            raise ValueError("one official OTC archive file is required per segment")
        publication_label = str(
            scope.get("publication_label_date") or required.segment_id
        )[:10]
        quote_effective_date = str(request.get("quote_effective_date") or "")[:10]
        if not quote_effective_date:
            raise ValueError(
                "calendar-resolved quote_effective_date is required for OTC proof"
            )
        from ingestion.jsda.normalize import normalize_otc_reference_prices
        from ingestion.jsda.parse import (
            parse_otc_reference_csv,
            parse_otc_reference_xlsx,
        )

        parser = {
            "csv": parse_otc_reference_csv,
            "xlsx": parse_otc_reference_xlsx,
        }.get(source_format)
        if parser is None:
            raise ValueError(f"unsupported governed OTC format: {source_format}")
        records = tuple(
            parser(
                pages[0],
                publication_label_date=publication_label,
                quote_effective_date=quote_effective_date,
            )
        )
        source_url = str(scope.get("source_url") or request.get("source_url") or "")
        if not source_url:
            raise ValueError("official OTC source_url is required for governed proof")
        normalized = tuple(
            normalize_otc_reference_prices(
                records,
                ingested_at=checked_at,
                publication_label_date=publication_label,
                quote_effective_date=quote_effective_date,
                source_url=source_url,
                raw_digest=_digest(pages[0]),
                segment_id=required.segment_id,
                source_format=source_format,
            )
        )
        return records, normalized, "jsda_otc_bond_reference_prices"

    if required.dataset == "jsda_tokyo_repo_rates":
        if len(pages) != 1:
            raise ValueError("one official Tokyo Repo file is required per segment")
        from ingestion.jsda.normalize import normalize_repo_rates
        from ingestion.jsda.parse import (
            parse_repo_csv,
            parse_repo_xls,
            parse_repo_xlsx,
        )

        parser = {
            "csv": parse_repo_csv,
            "xls": parse_repo_xls,
            "xlsx": parse_repo_xlsx,
        }.get(source_format)
        if parser is None:
            raise ValueError(f"unsupported governed Tokyo Repo format: {source_format}")
        parsed = tuple(parser(pages[0]))
        latest = str(scope.get("latest_publication_date") or required.segment_end)[:10]
        records = tuple(
            row
            for row in parsed
            if required.segment_start
            <= str(row.get("as_of_date") or "")[:10]
            <= latest
        )
        if not records:
            raise ValueError("official Tokyo Repo file contains no governed records")
        dates = sorted({str(row.get("as_of_date") or "")[:10] for row in records})
        if dates[0] != required.segment_start or dates[-1] != latest:
            raise ValueError("Tokyo Repo source does not exhaust the governed date range")
        keys = [
            (str(row.get("as_of_date") or "")[:10], str(row.get("tenor") or ""))
            for row in records
        ]
        if len(keys) != len(set(keys)):
            raise ValueError("Tokyo Repo source contains duplicate natural keys")
        normalized = tuple(normalize_repo_rates(records, ingested_at=checked_at))
        return records, normalized, "jsda_repo_rates"

    raise ValueError(
        f"no governed canonical JSDA adapter for dataset: {required.dataset}"
    )


def _canonical_otc_correction_from_raw(
    *,
    store: SqliteStore,
    required: RequiredCoverageSegment,
    raw_pages: Sequence[bytes],
    raw_paths: Sequence[Path],
    checked_at: str,
    extra_evidence: Mapping[str, Any],
) -> tuple[tuple[Any, ...], tuple[Mapping[str, Any], ...], str]:
    """Rebuild a correction delta from official daily files and revisions."""
    from ingestion.jsda.corrections import _available_at, _changed_records
    from ingestion.jsda.normalize import normalize_otc_reference_prices
    from ingestion.jsda.parse import (
        parse_otc_reference_csv,
        parse_otc_reference_xlsx,
    )

    scope = dict(required.expected_scope)
    corrected_sources = extra_evidence.get("corrected_sources")
    if not isinstance(corrected_sources, Sequence) or not corrected_sources:
        raise ValueError("governed correction requires corrected source evidence")
    path_pages = {
        path.resolve(): page for path, page in zip(raw_paths, raw_pages, strict=True)
    }
    artifact_path_value = extra_evidence.get("raw_path")
    artifact_digest = str(extra_evidence.get("raw") or "")
    if not artifact_path_value or not artifact_digest:
        raise ValueError("official correction artifact evidence is required")
    artifact_path = Path(str(artifact_path_value)).expanduser().resolve()
    artifact_page = path_pages.get(artifact_path)
    if artifact_page is None or _digest(artifact_page) != artifact_digest:
        raise ValueError("official correction artifact does not match persisted raw")

    current_rows = store._conn.execute(  # noqa: SLF001
        "SELECT * FROM jsda_otc_bond_reference_prices "
        "WHERE publication_label_date BETWEEN ? AND ?",
        (required.segment_start, required.segment_end),
    ).fetchall()
    baseline: dict[tuple[str, str, str], dict[str, Any]] = {
        (
            str(row["publication_label_date"]),
            str(row["security_code"]),
            str(row["bond_name"]),
        ): dict(row)
        for row in current_rows
    }
    revision_rows = store._conn.execute(  # noqa: SLF001
        "SELECT * FROM jsda_otc_bond_reference_prices_revisions "
        "WHERE publication_label_date BETWEEN ? AND ? "
        "ORDER BY available_at",
        (required.segment_start, required.segment_end),
    ).fetchall()
    # The newest archived version is the immediate pre-correction baseline.
    for row in revision_rows:
        key = (
            str(row["publication_label_date"]),
            str(row["security_code"]),
            str(row["bond_name"]),
        )
        baseline[key] = dict(row)
    if not baseline:
        raise ValueError("correction proof has no captured pre-correction baseline")

    correction_url = str(scope.get("source_url") or "")
    correction_label = str(scope.get("correction_publication_label") or "")
    correction_published_at = scope.get("correction_published_at")
    availability = _available_at(checked_at, correction_published_at)
    all_changed: list[dict[str, Any]] = []
    all_normalized: list[dict[str, Any]] = []
    used_paths: set[Path] = set()
    for item in corrected_sources:
        if not isinstance(item, Mapping):
            raise ValueError("corrected source evidence entry must be an object")
        source_path = Path(str(item.get("raw_path") or "")).expanduser().resolve()
        page = path_pages.get(source_path)
        if page is None:
            raise ValueError("corrected source path is outside persisted raw manifest")
        used_paths.add(source_path)
        expected_digest = str(item.get("digest") or "")
        if not expected_digest or _digest(page) != expected_digest:
            raise ValueError("corrected source digest differs from persisted raw")
        publication_label = str(item.get("publication_label_date") or "")[:10]
        if not publication_label:
            raise ValueError("corrected source publication label is required")
        effective_dates = {
            str(row.get("quote_effective_date") or "")[:10]
            for key, row in baseline.items()
            if key[0] == publication_label
        }
        if len(effective_dates) != 1:
            raise ValueError("baseline does not prove one quote effective date")
        effective_date = next(iter(effective_dates))
        source_url = str(item.get("url") or "")
        suffix = source_path.suffix.lower()
        parser = {
            ".csv": parse_otc_reference_csv,
            ".xlsx": parse_otc_reference_xlsx,
        }.get(suffix)
        if parser is None:
            raise ValueError(f"unsupported governed correction source: {suffix}")
        parsed = parser(
            page,
            publication_label_date=publication_label,
            quote_effective_date=effective_date,
        )
        changed = _changed_records(parsed, baseline)
        all_changed.extend(changed)
        all_normalized.extend(
            normalize_otc_reference_prices(
                changed,
                ingested_at=checked_at,
                available_at=availability,
                source_url=source_url,
                raw_digest=expected_digest,
                segment_id=required.segment_id,
                source_format=suffix.lstrip("."),
                correction_publication_label=correction_label,
                correction_published_at=correction_published_at,
                correction_source_url=correction_url,
                correction_raw_digest=artifact_digest,
            )
        )
    if not all_changed:
        raise ValueError("correction source contains no independently measured delta")
    if len(used_paths) != len(corrected_sources):
        raise ValueError("correction source manifest contains duplicate paths")
    return (
        tuple(all_changed),
        tuple(all_normalized),
        "jsda_otc_bond_reference_prices",
    )


def _assert_canonical_structured_projection(
    *,
    required: RequiredCoverageSegment,
    expected_rows: Sequence[Mapping[str, Any]],
    persisted_rows: Sequence[Mapping[str, Any]],
    prior_verified_available_at: Mapping[tuple[Any, ...], Any] | None = None,
) -> None:
    """Bind exact persisted natural keys and payload fields to normalization."""
    from storage.schema import NATURAL_KEYS

    table = (
        "jquants_records"
        if required.source == "jquants"
        else {
            "jsda_otc_bond_reference_prices": "jsda_otc_bond_reference_prices",
            "jsda_tokyo_repo_rates": "jsda_repo_rates",
        }.get(required.dataset, "")
    )
    keys = NATURAL_KEYS.get(table)
    if not keys:
        raise ValueError("canonical projection has no natural-key contract")
    expected = {
        tuple(row[key] for key in keys): dict(row) for row in expected_rows
    }
    persisted = {
        tuple(row[key] for key in keys): dict(row) for row in persisted_rows
    }
    if expected.keys() != persisted.keys():
        raise ValueError("persisted natural keys differ from canonical normalization")
    for natural_key, canonical in expected.items():
        actual = persisted[natural_key]
        if str(actual.get("source") or "") != required.source:
            raise ValueError("structured source differs from required segment")
        if "dataset" in actual and str(actual.get("dataset") or "") != required.dataset:
            raise ValueError("structured dataset differs from required segment")
        if "segment_id" in actual and str(actual.get("segment_id") or "") != required.segment_id:
            raise ValueError("structured row escaped the exact required segment")
        for field, expected_value in canonical.items():
            actual_value = actual.get(field)
            if field in {"payload", "raw_payload"}:
                expected_value = _canonical_json_value(expected_value)
                actual_value = _canonical_json_value(actual_value)
            if (
                field == "available_at"
                and actual_value != expected_value
                and dict(prior_verified_available_at or {}).get(natural_key)
                == actual_value
            ):
                continue
            if actual_value != expected_value:
                raise ValueError(
                    "persisted structured payload differs from canonical "
                    f"normalization at {natural_key!r} field={field}"
                )


def _assert_trusted_exhaustion(required: RequiredCoverageSegment) -> None:
    """Derive exhaustion from the closed adapter contract, never a boolean."""
    unit = str(required.expected_scope.get("expected_item_unit") or "")
    if required.source == "jquants":
        # The verbatim response/token chain was independently verified before
        # canonical parsing; reaching here means the final page had no token.
        return
    if unit not in {
        "official_archive_file",
        "official_full_timeseries_file",
        "official_correction_artifact",
    }:
        raise ValueError("collection contract is not exhaustible by this adapter")
    scope = dict(required.expected_scope)
    if not scope.get("source_url"):
        raise ValueError("official discovery evidence is incomplete")
    if unit != "official_correction_artifact" and not scope.get("index_url"):
        raise ValueError("official index discovery evidence is incomplete")


def _measure_collection_claims(
    *,
    required: RequiredCoverageSegment,
    run_id: int,
    raw_pages: Sequence[bytes],
    raw_records: Sequence[Any],
    structured_records: Sequence[Mapping[str, Any]],
    checked_at: str,
    source_request: Mapping[str, Any] | None = None,
    extra_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Measure closed claims from concrete runtime state.

    Counts and digests are derived here from concrete raw pages and normalized
    records.  Callers cannot supply either.  A JSON envelope is also counted
    independently and must agree with ``raw_records``.  Binary source parsers
    supply their parsed record sequence as the measured raw evidence.
    """
    if not isinstance(required, RequiredCoverageSegment):
        raise TypeError("required must be RequiredCoverageSegment")
    pages = tuple(bytes(page) for page in raw_pages)
    if not pages or any(not page for page in pages):
        raise ValueError("reconciled SUCCESS requires non-empty raw pages")
    raw_rows = tuple(raw_records)
    structured_rows = tuple(dict(row) for row in structured_records)
    measured_json = _json_records_from_pages(pages)
    if measured_json is not None and _digest(list(measured_json)) != _digest(
        list(raw_rows)
    ):
        raise ValueError(
            "raw_records do not match content measured from the raw JSON envelope"
        )

    extras = dict(_trusted_extra_evidence(required, extra_evidence))
    if not raw_rows:
        raise ValueError("zero-row SUCCESS is not trusted")
    # Reaching this private function means the closed adapter's exhaustion
    # invariant has already passed.  There is no caller-supplied boolean.
    exhausted = True
    discovered = True

    page_manifest = [
        {"index": index, "digest": _digest(page), "size": len(page)}
        for index, page in enumerate(pages)
    ]
    raw_digest = page_manifest[0]["digest"] if len(page_manifest) == 1 else _digest(
        {"pages": page_manifest}
    )
    raw_manifest_digest = _digest({"pages": page_manifest})
    structured_digest = _digest(list(structured_rows))
    policy = coverage_contract_for(required.dataset)
    if (
        policy.structured_reconciliation_required
        and len(raw_rows) != len(structured_rows)
    ):
        raise ValueError(
            "raw and structured records do not reconcile under dataset policy"
        )
    scope = {
        "coverage_policy_version": policy.policy_version,
        "source": required.source,
        "dataset": required.dataset,
        "segment_id": required.segment_id,
        "segment_start": required.segment_start,
        "segment_end": required.segment_end,
        "expected_scope": dict(required.expected_scope),
        "expected_items": required.expected_items,
    }
    scope_digest = _digest(scope)
    request = dict(source_request or scope)
    source_request_digest = _digest(request)

    unit = str(required.expected_scope.get("expected_item_unit") or "")
    if unit in {
        "source_query",
        "official_archive_file",
        "official_archive_index",
        "official_full_timeseries_file",
        "official_correction_artifact",
    }:
        observed_items = int(bool(raw_rows))
    else:
        observed_items = len(raw_rows)
    checked = checked_at
    observation = {
        **scope,
        "observed_items": observed_items,
        "raw_page_count": len(page_manifest),
        "raw_count": len(raw_rows),
        "structured_count": len(structured_rows),
        "status": "SUCCESS",
        "error": None,
        "pagination_exhausted": exhausted,
        "discovery_exhausted": discovered,
        "source_request_digest": source_request_digest,
        "raw_manifest_digest": raw_manifest_digest,
        "raw_digest": raw_digest,
        "structured_digest": structured_digest,
        "structured_generation": int(run_id),
        "scope_digest": scope_digest,
        "run_id": int(run_id),
        "checked_at": checked,
        "extra_digests": extras,
    }
    observation_digest = _digest(observation)
    return {
        **observation,
        "observation_digest": observation_digest,
    }


__all__ = [
    "RUN_ACQUIRED",
    "RUN_COVERAGE_COMPLETE",
    "RUN_FAILED",
    "RUN_PARTIAL",
    "RUN_RAW_STORED",
    "RUN_RECEIPT_VERIFIED",
    "RUN_STRUCTURED_COMMITTED",
]
