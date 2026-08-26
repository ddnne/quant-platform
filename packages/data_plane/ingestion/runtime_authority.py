"""Trusted ingestion reconciliation runtime (verify-only client process).

The acquisition process never holds receipt private material.  It re-parses
persisted immutable raw bytes with the canonical source adapter, re-runs the
canonical normalizer, rereads exact natural keys, and only then creates a
one-shot opaque reconciliation handle.  A separately provisioned evidence
authority must consume that handle.  Until that authority exists, production
fails closed and no COMPLETE-eligible receipt is committed.
"""

from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import dataclass
from functools import wraps
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
from storage.receipt_crypto import STANDARD_CLAIM_KEYS, canonical_evidence_digest

from ingestion.jquants.acquisition_collection import (
    _LiveJQuantsAcquisitionCapture,
    _VerifiedJQuantsAcquisitionCollection,
    _assert_verified_jquants_session_current,
    _canonical_required_segment,
    _consume_verified_jquants_collection,
    _next_authority_event_sequence,
    _records_from_verified_pages,
    _reread_verified_jquants_state,
    _verify_live_jquants_capture,
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
_RECONCILED_COLLECTION_SEAL = object()
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
_RECONCILED_COLLECTIONS: WeakKeyDictionary[Any, dict[str, Any]] = (
    WeakKeyDictionary()
)
_CAPABILITY_REGISTRY_LOCK = Lock()
_MAX_CONTEXT_AGE_SECONDS = 15 * 60
_MAX_CLOCK_SKEW_SECONDS = 5
_JQUANTS_ACQUISITION_EXTRA_DIGESTS = frozenset(
    {
        "acquisition_collection_manifest_file_digest",
        "acquisition_collection_digest",
        "acquisition_terminal_chain_digest",
    }
)


class ReceiptEvidenceAuthorityPending(RuntimeError):
    """The dedicated receipt evidence authority has not been provisioned."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rollback_store_on_failure(method: Callable[..., Any]) -> Callable[..., Any]:
    """Rollback every failed authority operation after a store is supplied.

    Callers stage canonical structured writes before asking this authority to
    reconcile them.  Validation of the context, opaque acquisition capability,
    immutable paths, parser output, signature handoff, receipt insert, and
    commit are therefore all part of one failure boundary.  Keeping this guard
    outside the method signature also covers Python argument-binding failures
    from prohibited caller-supplied claim fields.
    """

    @wraps(method)
    def guarded(self: Any, store: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            return method(self, store, *args, **kwargs)
        except Exception:
            from storage.sqlite_store import SqliteStore

            if isinstance(store, SqliteStore):
                store._conn.rollback()  # noqa: SLF001
            raise

    return guarded


@dataclass(frozen=True, eq=False)
class _GovernedCollectionContext:
    """Authority-minted timestamp/correlation capability for one transaction."""

    _seal: object
    _authority_id: object
    checked_at: str
    run_id: int | None = None
    required_identity_digest: str | None = None

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


@dataclass(frozen=True, eq=False)
class _ReconciledCollectionEvidence:
    """Opaque one-shot handle; scalar claims are never an authority API."""

    _seal: object
    _authority_id: object

    def __post_init__(self) -> None:
        if self._seal is not _RECONCILED_COLLECTION_SEAL:
            raise TypeError("reconciled evidence must be minted by ingestion runtime")


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
    _clock: Callable[[], str]
    _authority_id: object

    def __post_init__(self) -> None:
        if self._seal is not _SERVICE_SEAL:
            raise TypeError("receipt service must be opened by ingestion runtime")

    def begin_collection(
        self,
        *,
        store: SqliteStore | None = None,
        required: RequiredCoverageSegment | None = None,
    ) -> _GovernedCollectionContext:
        """Mint timestamp/run authority for one local reconciliation transaction.

        For J-Quants, live capture verification must finish before this call;
        private authority ordering enforces that the context timestamp cannot
        predate acquisition completion.  Passing both ``store`` and
        ``required`` inserts the authority-owned run row and starts the first
        explicit transaction for caller-staged structured facts.  Receipt
        verification/finalization uses a later transaction after that
        structured state commits.  A no-argument context remains useful for
        negative capability tests but is deliberately ineligible for SUCCESS.
        """
        self._assert_registered()
        checked_at = str(self._clock())
        parsed = datetime.fromisoformat(checked_at.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("governed collection clock must be timezone-aware")
        if (store is None) != (required is None):
            raise TypeError("store and required must be supplied together")
        run_id: int | None = None
        required_identity_digest: str | None = None
        run_detail: str | None = None
        store_connection: Any | None = None
        context_sequence: int | None = None
        if store is not None and required is not None:
            from storage.sqlite_store import SqliteStore

            if not isinstance(store, SqliteStore):
                raise TypeError("governed collection transaction requires SqliteStore")
            if store._conn.isolation_level is None:  # noqa: SLF001
                raise TypeError("governed collection rejects SQLite autocommit mode")
            if not store._conn.in_transaction:  # noqa: SLF001
                store._conn.execute("BEGIN IMMEDIATE")  # noqa: SLF001
            canonical = _canonical_required_segment(required)
            required_identity_digest = _required_segment_identity_digest(canonical)
            run_detail = json.dumps(
                {
                    "schema_version": "trusted-jquants-reconciliation-run/v2",
                    "required_identity_digest": required_identity_digest,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            cursor = store._conn.execute(  # noqa: SLF001
                "INSERT INTO ingestion_run_log "
                "(ran_at,source,runtime,status,detail) VALUES (?,?,?,?,?)",
                (
                    checked_at,
                    "jquants",
                    "trusted-jquants-reconciliation/v2",
                    RUN_ACQUIRED,
                    run_detail,
                ),
            )
            run_id = int(cursor.lastrowid)
            store_connection = store._conn  # noqa: SLF001
            context_sequence = _next_authority_event_sequence()
        context = _GovernedCollectionContext(
            _seal=_COLLECTION_CONTEXT_SEAL,
            _authority_id=self._authority_id,
            checked_at=checked_at,
            run_id=run_id,
            required_identity_digest=required_identity_digest,
        )
        with _CAPABILITY_REGISTRY_LOCK:
            _GOVERNED_CONTEXTS[context] = {
                "authority_id": self._authority_id,
                "consumed": False,
                "checked_at": checked_at,
                "run_id": run_id,
                "required_identity_digest": required_identity_digest,
                "run_detail": run_detail,
                "store_connection": store_connection,
                "context_sequence": context_sequence,
            }
        return context

    def _assert_registered(self) -> None:
        with _CAPABILITY_REGISTRY_LOCK:
            if self not in _GOVERNED_SERVICES:
                raise TypeError("receipt service is not runtime-registered")

    def _consume_reconciled_evidence(
        self, evidence: _ReconciledCollectionEvidence
    ) -> Mapping[str, Any]:
        """Consume one runtime-registered handle exactly once.

        A copied object is not present in the registry even when a caller can
        import private implementation names.  The authority identity and
        consumed bit also prevent cross-service use and replay.
        """
        self._assert_registered()
        if (
            type(evidence) is not _ReconciledCollectionEvidence
            or evidence._seal is not _RECONCILED_COLLECTION_SEAL
        ):
            raise TypeError("receipt authority requires opaque reconciled evidence")
        with _CAPABILITY_REGISTRY_LOCK:
            state = _RECONCILED_COLLECTIONS.get(evidence)
            if state is None:
                raise TypeError("reconciled evidence is not runtime-registered")
            if state["authority_id"] is not self._authority_id:
                raise TypeError("reconciled evidence belongs to another authority")
            if state["consumed"]:
                raise TypeError("reconciled evidence has already been consumed")
            state["consumed"] = True
            claims = state["claims"]
        if not isinstance(claims, Mapping):  # pragma: no cover - registry invariant
            raise TypeError("reconciled evidence registry is invalid")
        return claims

    def _issue_reconciled_evidence(
        self, evidence: _ReconciledCollectionEvidence
    ) -> Mapping[str, Any]:
        """Production base has no local receipt-minting implementation."""
        del evidence
        raise ReceiptEvidenceAuthorityPending(
            "receipt evidence authority is PENDING: no local signer exists"
        )

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
        """Bind legacy v1 fetch evidence for audit/recovery only.

        ``jquants-pagination-evidence/v1`` predates the typed acquisition
        target and is never accepted by :meth:`record_persisted_success` for a
        new COMPLETE receipt.
        """
        self._assert_registered()
        return _seal_persisted_jquants_collection(
            authority_id=self._authority_id,
            fetch_result=fetch_result,
            raw_paths=raw_paths,
            manifest_path=manifest_path,
        )

    def verify_live_jquants_collection(
        self,
        *,
        capture: _LiveJQuantsAcquisitionCapture,
        required: RequiredCoverageSegment,
    ) -> _VerifiedJQuantsAcquisitionCollection:
        """Verify one live Service-Binding capture into an opaque capability.

        There is deliberately no product constructor for ``capture`` yet.
        The separate Receipt Worker/binding remains PENDING; persisted headers
        and raw files cannot invoke this method without its registered live
        authority capability.  Full raw/state-machine verification pins its
        completion clock before a governed collection context may be created.
        """
        self._assert_registered()
        if not isinstance(required, RequiredCoverageSegment):
            raise TypeError("required must be RequiredCoverageSegment")
        canonical_required = (
            _canonical_required_segment(required)
            if required.source == "jquants"
            else required
        )
        return _verify_live_jquants_capture(
            capture,
            authority_id=self._authority_id,
            required=canonical_required,
            clock=self._clock,
        )

    @_rollback_store_on_failure
    def record_persisted_success(
        self,
        store: SqliteStore,
        *,
        required: RequiredCoverageSegment,
        run_id: int,
        collection_context: _GovernedCollectionContext,
        raw_artifact_paths: Sequence[Path | str] = (),
        jquants_capture: _LiveJQuantsAcquisitionCapture | None = None,
        jquants_collection: _VerifiedJQuantsAcquisitionCollection | None = None,
        source_request: Mapping[str, Any] | None = None,
        extra_evidence: Mapping[str, Any] | None = None,
    ) -> CollectionReceipt:
        """Independently remeasure state, request issuance, and atomically record.

        Counts, digests, parsed/normalized rows, table names, and exhaustion
        claims are never parameters.  They are derived from the required
        contract and immutable raw bytes.  The caller's canonical fact writes
        are committed only after the first reconciliation.  A fresh
        transaction then repeats immutable-raw and natural-key readback before
        issuance and receipt persistence.  Failures before the structured
        commit roll everything back; later failures leave structured facts but
        never a local COMPLETE-eligible receipt.  Authority-clock observations
        must remain nondecreasing from capture verification through the final
        local precommit check.
        """
        from storage.sqlite_store import SqliteStore

        self._assert_registered()
        if not isinstance(store, SqliteStore):
            raise TypeError("governed receipt service requires SqliteStore")
        if not isinstance(required, RequiredCoverageSegment):
            raise TypeError("required must be RequiredCoverageSegment")
        canonical_required = (
            _canonical_required_segment(required)
            if required.source == "jquants"
            else required
        )
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
            context_run_id = context_state["run_id"]
            context_checked_at = context_state["checked_at"]
            context_required_digest = context_state["required_identity_digest"]
            context_run_detail = context_state["run_detail"]
            context_store_connection = context_state["store_connection"]
            context_sequence = context_state["context_sequence"]
        if (
            context_run_id is None
            or context_checked_at is None
            or context_required_digest is None
            or context_run_detail is None
            or context_sequence is None
        ):
            raise TypeError(
                "governed SUCCESS requires an authority-owned ingestion transaction"
            )
        if context_store_connection is not store._conn:  # noqa: SLF001
            if context_store_connection is not None:
                context_store_connection.rollback()
            raise TypeError("collection transaction belongs to another store")
        if (
            store._conn.isolation_level is None  # noqa: SLF001
            or not store._conn.in_transaction  # noqa: SLF001
        ):
            raise TypeError("governed SUCCESS requires an explicit SQLite transaction")
        if type(run_id) is not int or run_id != context_run_id:
            raise ValueError("caller run_id differs from authority-owned transaction")
        if collection_context.checked_at != context_checked_at:
            raise ValueError("collection context timestamp was mutated")
        if context_required_digest != _required_segment_identity_digest(
            canonical_required
        ):
            raise ValueError("collection transaction required scope was substituted")
        run_row = store._conn.execute(  # noqa: SLF001
            "SELECT ran_at,source,runtime,status,detail FROM ingestion_run_log WHERE id=?",
            (context_run_id,),
        ).fetchone()
        if (
            run_row is None
            or str(run_row["ran_at"]) != context_checked_at
            or str(run_row["source"]) != "jquants"
            or str(run_row["runtime"]) != "trusted-jquants-reconciliation/v2"
            or str(run_row["status"]) != RUN_ACQUIRED
            or str(run_row["detail"]) != context_run_detail
        ):
            raise ValueError("authority-owned ingestion transaction state drifted")
        run_id = context_run_id
        checked_at = str(context_checked_at)
        checked_dt = _parse_authority_clock(checked_at)
        now_dt = _parse_authority_clock(str(self._clock()))
        _assert_authority_clock_nondecreasing(
            checked_dt,
            now_dt,
            stage="record entry",
        )
        _assert_context_clock_fresh(checked_dt, now_dt)

        if required.source == "jquants":
            if jquants_capture is not None:
                raise TypeError(
                    "live capture must be fully verified before beginning the "
                    "authority-owned collection transaction"
                )
            if isinstance(jquants_collection, _PersistedJQuantsCollection):
                raise TypeError(
                    "jquants-pagination-evidence/v1 is audit/recovery-only and "
                    "cannot mint a new COMPLETE receipt"
                )
            if not isinstance(
                jquants_collection, _VerifiedJQuantsAcquisitionCollection
            ):
                raise TypeError(
                    "J-Quants COMPLETE requires a verified live acquisition collection"
                )
            if raw_artifact_paths:
                raise TypeError("J-Quants raw paths cannot bypass the opaque handle")
            if source_request is not None:
                raise TypeError(
                    "J-Quants v2 does not accept a caller-supplied source_request"
                )
            trusted_raw_pages, verified_state = _consume_verified_jquants_collection(
                jquants_collection,
                authority_id=self._authority_id,
                now=now_dt,
            )
            if (
                context_sequence <= verified_state.verified_sequence
            ):
                raise ValueError(
                    "collection transaction predates live acquisition verification"
                )
            _assert_authority_clock_nondecreasing(
                verified_state.verified_at,
                checked_dt,
                stage="collection context",
            )
            if verified_state.dataset != required.dataset:
                raise ValueError("verified J-Quants dataset differs from required")
            if verified_state.required != canonical_required:
                raise ValueError(
                    "verified J-Quants segment differs from canonical required scope"
                )
            # Downstream claims are derived from the frozen verifier-owned
            # canonical segment, never from the fresh caller mapping.
            frozen_required = verified_state.required
            required = RequiredCoverageSegment(
                source=frozen_required.source,
                dataset=frozen_required.dataset,
                segment_id=frozen_required.segment_id,
                segment_start=frozen_required.segment_start,
                segment_end=frozen_required.segment_end,
                expected_scope=dict(frozen_required.expected_scope),
                expected_items=frozen_required.expected_items,
            )
            candidates = verified_state.raw_paths
            trusted_source_request = dict(verified_state.initial_request)
            trusted_source_request_digest = verified_state.initial_request_digest
            trusted_acquisition_digests = MappingProxyType(
                {
                    "acquisition_collection_manifest_file_digest": (
                        verified_state.manifest_file_digest
                    ),
                    "acquisition_collection_digest": verified_state.collection_digest,
                    "acquisition_terminal_chain_digest": (
                        verified_state.terminal_chain_digest
                    ),
                }
            )
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
        updated = store._conn.execute(  # noqa: SLF001
            "UPDATE ingestion_run_log SET status=? WHERE id=? AND status=?",
            (RUN_RAW_STORED, run_id, RUN_ACQUIRED),
        )
        if updated.rowcount != 1:
            raise ValueError("raw evidence transaction transition failed")

        try:
            raw_pages = trusted_raw_pages
            if any(not page for page in raw_pages):
                raise ValueError("reconciled SUCCESS requires non-empty raw pages")
            caller_extras = _trusted_extra_evidence(required, extra_evidence)

            def reconcile_pages(
                pages_to_reconcile: Sequence[bytes],
            ) -> tuple[tuple[Any, ...], tuple[Mapping[str, Any], ...]]:
                raw_records, normalized_records, structured_table = (
                    _canonical_collection_from_raw(
                        store=store,
                        required=required,
                        raw_pages=pages_to_reconcile,
                        raw_paths=paths,
                        checked_at=checked_at,
                        source_request=trusted_source_request,
                        extra_evidence=caller_extras,
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
                    raw_pages=pages_to_reconcile,
                )
                _assert_canonical_structured_projection(
                    required=required,
                    expected_rows=normalized_records,
                    persisted_rows=structured_rows,
                    prior_verified_available_at=prior_available,
                )
                _assert_trusted_exhaustion(required)
                return raw_records, structured_rows

            # First pass validates caller-staged facts, then commits the
            # structured generation before any receipt issuer is invoked.
            reconcile_pages(raw_pages)
            updated = store._conn.execute(  # noqa: SLF001
                "UPDATE ingestion_run_log SET status=? WHERE id=? AND status=?",
                (RUN_STRUCTURED_COMMITTED, run_id, RUN_RAW_STORED),
            )
            if updated.rowcount != 1:
                raise ValueError("authority-owned ingestion transaction transition failed")
            store._conn.commit()  # noqa: SLF001

            # The issuer sees only a fresh transaction: immutable raw is read
            # again, exact natural keys are reloaded from the committed DB,
            # and canonical parsing/normalization is repeated.
            _begin_receipt_verification_transaction(store)
            post_commit_now = _parse_authority_clock(str(self._clock()))
            _assert_authority_clock_nondecreasing(
                now_dt,
                post_commit_now,
                stage="post-structured-commit",
            )
            _assert_context_clock_fresh(checked_dt, post_commit_now)
            raw_pages = _reread_verified_jquants_state(
                verified_state,
                now=post_commit_now,
            )
            if any(not page for page in raw_pages):
                raise ValueError("committed reconciliation lost immutable raw pages")
            raw_records, structured_rows = reconcile_pages(raw_pages)
            committed_run = store._conn.execute(  # noqa: SLF001
                "SELECT status FROM ingestion_run_log WHERE id=?", (run_id,)
            ).fetchone()
            if committed_run is None or committed_run["status"] != RUN_STRUCTURED_COMMITTED:
                raise ValueError("committed structured transaction state drifted")
            claims = _measure_collection_claims(
                required=required,
                run_id=run_id,
                raw_pages=raw_pages,
                raw_records=raw_records,
                structured_records=structured_rows,
                checked_at=checked_at,
                source_request=trusted_source_request,
                extra_evidence=caller_extras,
                trusted_extra_evidence=trusted_acquisition_digests,
                trusted_source_request_digest=trusted_source_request_digest,
            )
            pre_issue_now = _parse_authority_clock(str(self._clock()))
            _assert_authority_clock_nondecreasing(
                post_commit_now,
                pre_issue_now,
                stage="pre-issuer",
            )
            _assert_context_clock_fresh(checked_dt, pre_issue_now)
            _assert_verified_jquants_session_current(
                verified_state,
                now=pre_issue_now,
            )
            # Registration deliberately stays inline at the end of the trusted
            # reconciliation sequence.  A module-level claims-to-capability
            # helper would be an importable mint oracle.
            evidence = _ReconciledCollectionEvidence(
                _seal=_RECONCILED_COLLECTION_SEAL,
                _authority_id=self._authority_id,
            )
            with _CAPABILITY_REGISTRY_LOCK:
                _RECONCILED_COLLECTIONS[evidence] = {
                    "authority_id": self._authority_id,
                    "claims": MappingProxyType(dict(claims)),
                    "consumed": False,
                }
            signed = dict(self._issue_reconciled_evidence(evidence))
            post_issue_now = _parse_authority_clock(str(self._clock()))
            _assert_authority_clock_nondecreasing(
                pre_issue_now,
                post_issue_now,
                stage="post-issuer",
            )
            _assert_context_clock_fresh(checked_dt, post_issue_now)
            _assert_verified_jquants_session_current(
                verified_state,
                now=post_issue_now,
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
                digests=dict(signed),
                run_id=int(run_id),
                status="SUCCESS",
                error=None,
                checked_at=checked_at,
            )
            _verify_issued_receipt_matches_measurement(
                receipt,
                required=required,
                claims=claims,
            )
            record_collection_receipt(store._conn, receipt)  # noqa: SLF001
            updated = store._conn.execute(  # noqa: SLF001
                "UPDATE ingestion_run_log SET status=? WHERE id=? AND status=?",
                (
                    RUN_RECEIPT_VERIFIED,
                    run_id,
                    RUN_STRUCTURED_COMMITTED,
                ),
            )
            if updated.rowcount != 1:
                raise ValueError("receipt transaction finalization failed")
            if not store._conn.in_transaction:  # noqa: SLF001
                raise RuntimeError("receipt transaction escaped explicit commit control")
            final_precommit_now = _parse_authority_clock(str(self._clock()))
            _assert_authority_clock_nondecreasing(
                post_issue_now,
                final_precommit_now,
                stage="final-precommit",
            )
            _assert_context_clock_fresh(checked_dt, final_precommit_now)
            _assert_verified_jquants_session_current(
                verified_state,
                now=final_precommit_now,
            )
            store._conn.commit()  # noqa: SLF001
        except Exception:
            store._conn.rollback()  # noqa: SLF001
            raise
        return receipt


def _open_governed_receipt_service() -> _GovernedReceiptService:
    """Fail closed until a separate receipt evidence service is provisioned.

    There is intentionally no HOME/env PEM fallback and no local signer.  The
    future service must run under a dedicated principal, independently repeat
    raw/parser/structured reconciliation, and consume only the opaque handle.
    """
    raise ReceiptEvidenceAuthorityPending(
        "receipt evidence authority is PENDING: dedicated principal/service "
        "with independent raw/parser/structured readback is not provisioned"
    )


def _direct_jquants_http() -> Any:
    """Construct the only production transport eligible for COMPLETE."""
    from ingestion.common.http import LocalHttpClient

    return LocalHttpClient(verify=True, trust_env=False)


def _begin_receipt_verification_transaction(store: SqliteStore) -> None:
    """Start the post-structured-commit readback transaction."""
    if store._conn.isolation_level is None:  # noqa: SLF001
        raise TypeError("receipt verification rejects SQLite autocommit mode")
    if store._conn.in_transaction:  # noqa: SLF001
        raise RuntimeError("receipt verification transaction already active")
    store._conn.execute("BEGIN IMMEDIATE")  # noqa: SLF001


def _digest(payload: Any) -> str:
    return canonical_evidence_digest(payload)


def _required_segment_identity_digest(
    required: RequiredCoverageSegment,
) -> str:
    return _digest(
        {
            "source": required.source,
            "dataset": required.dataset,
            "segment_id": required.segment_id,
            "segment_start": required.segment_start,
            "segment_end": required.segment_end,
            "expected_scope": dict(required.expected_scope),
            "expected_items": required.expected_items,
        }
    )


def _parse_authority_clock(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("governed collection clock must be timezone-aware")
    return parsed


def _assert_context_clock_fresh(checked_at: datetime, now: datetime) -> None:
    age = now.astimezone(timezone.utc) - checked_at.astimezone(timezone.utc)
    if age.total_seconds() < -_MAX_CLOCK_SKEW_SECONDS:
        raise ValueError("collection context timestamp is in the future")
    if age.total_seconds() > _MAX_CONTEXT_AGE_SECONDS:
        raise ValueError("collection context is stale")


def _assert_authority_clock_nondecreasing(
    previous: datetime,
    current: datetime,
    *,
    stage: str,
) -> None:
    if current.astimezone(timezone.utc) < previous.astimezone(timezone.utc):
        raise ValueError(f"authority clock moved backwards at {stage}")


def _verify_issued_receipt_matches_measurement(
    receipt: CollectionReceipt,
    *,
    required: RequiredCoverageSegment,
    claims: Mapping[str, Any],
) -> None:
    """Reject a stale, malformed, or differently bound signer response.

    The receipt principal is a separate trust boundary.  Its returned envelope
    is therefore verified with the public registry before the local receipt is
    inserted or the run is labelled ``RECEIPT_VERIFIED``.  Signature validity
    alone is insufficient: every exposed closure field must equal the fresh
    local raw/parser/natural-key measurement.
    """
    from storage.verified_receipt import require_verified_collection_closure

    closure = require_verified_collection_closure(
        receipt,
        required=required,
        expected_policy_version=str(claims["coverage_policy_version"]),
        structured_digest=str(claims["structured_digest"]),
    )
    proof = closure.to_proof_dict()
    expected = {
        "coverage_policy_version": claims["coverage_policy_version"],
        "source": claims["source"],
        "dataset": claims["dataset"],
        "segment_id": claims["segment_id"],
        "segment_start": claims["segment_start"],
        "segment_end": claims["segment_end"],
        "scope_digest": claims["scope_digest"],
        "expected_items": claims["expected_items"],
        "observed_items": claims["observed_items"],
        "raw_page_count": claims["raw_page_count"],
        "raw_row_count": claims["raw_count"],
        "structured_row_count": claims["structured_count"],
        "pagination_exhausted": claims["pagination_exhausted"],
        "discovery_exhausted": claims["discovery_exhausted"],
        "raw_manifest_digest": claims["raw_manifest_digest"],
        "raw_digest": claims["raw_digest"],
        "structured_digest": claims["structured_digest"],
        "structured_generation": claims["structured_generation"],
        "observation_digest": claims["observation_digest"],
        "run_id": claims["run_id"],
        "checked_at": claims["checked_at"],
    }
    if {name: proof.get(name) for name in expected} != expected:
        raise ValueError("receipt authority response differs from local measurement")
    if dict(closure.extra_digests) != dict(claims["extra_digests"]):
        raise ValueError("receipt authority extra digests differ from local measurement")
    if receipt.digests.get("source_request_digest") != claims["source_request_digest"]:
        raise ValueError("receipt authority source request differs from local measurement")


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
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f"J-Quants raw page contains duplicate key {key!r}")
            value[key] = item
        return value

    def reject_nonfinite(value: str) -> None:
        raise ValueError(f"J-Quants raw page contains non-finite value {value!r}")

    measured: list[Any] = []
    for index, raw in enumerate(raw_pages):
        try:
            payload = json.loads(
                raw,
                object_pairs_hook=reject_duplicates,
                parse_constant=reject_nonfinite,
            )
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError) as exc:
            raise ValueError(
                f"J-Quants raw response page {index} is not strict UTF-8 JSON"
            ) from exc
        allowed_envelope_fields = {
            "data",
            "pagination_key",
            "pagination_token",
            "cursor",
        }
        if (
            type(payload) is not dict
            or "data" not in payload
            or not set(payload).issubset(allowed_envelope_fields)
        ):
            raise ValueError(
                f"J-Quants raw response page {index} is not the canonical data envelope"
            )
        for field in set(payload) - {"data"}:
            if payload[field] is not None and not isinstance(payload[field], str):
                raise ValueError(
                    f"J-Quants raw response page {index} has invalid {field} state"
                )
        rows = payload["data"]
        if not isinstance(rows, list):
            raise ValueError(
                f"J-Quants raw response page {index} data envelope is not an array"
            )
        measured.extend(rows)
    return tuple(measured)


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

        decoded = _records_from_verified_pages(required.dataset, pages)
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
    trusted_extra_evidence: Mapping[str, Any] | None = None,
    trusted_source_request_digest: str | None = None,
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
    measured_json = (
        _records_from_verified_pages(required.dataset, pages)
        if required.source == "jquants"
        else _json_records_from_pages(pages)
    )
    if measured_json is not None and _digest(list(measured_json)) != _digest(
        list(raw_rows)
    ):
        raise ValueError(
            "raw_records do not match content measured from the raw JSON envelope"
        )

    extras = dict(_trusted_extra_evidence(required, extra_evidence))
    authority_extras = dict(trusted_extra_evidence or {})
    if required.source == "jquants":
        if set(authority_extras) != _JQUANTS_ACQUISITION_EXTRA_DIGESTS:
            raise ValueError("verified J-Quants acquisition digest set is incomplete")
        if any(
            not isinstance(value, str) or not value.startswith("sha256:")
            for value in authority_extras.values()
        ):
            raise ValueError("verified J-Quants acquisition digest is invalid")
    elif authority_extras:
        raise ValueError("source does not accept J-Quants acquisition digests")
    overlap = sorted((set(extras) | set(authority_extras)) & STANDARD_CLAIM_KEYS)
    if overlap or set(extras) & set(authority_extras):
        raise ValueError("trusted extra digest namespace overlaps receipt claims")
    extras.update(authority_extras)
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
    measured_raw_manifest_digest = _digest({"pages": page_manifest})
    raw_manifest_digest = measured_raw_manifest_digest
    if not str(raw_manifest_digest).startswith("sha256:"):
        raise ValueError("trusted raw manifest digest is invalid")
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
    measured_source_request_digest = _digest(request)
    source_request_digest = (
        trusted_source_request_digest or measured_source_request_digest
    )
    if trusted_source_request_digest is not None and (
        trusted_source_request_digest != measured_source_request_digest
    ):
        raise ValueError("trusted source request digest does not reconcile")

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
