"""Pure catalog payload extraction and latest per-share financial observation.

PIT owns input order and revision selection. Payload values are accepted only
as ``dict`` (not a general Mapping). An empty payload dict stops raw-payload
fallback. Numeric conversion matches the historical helper: non-finite floats
are not rejected here.

Compact financial catalog state is accumulated from a PIT-owned raw-row
stream. Raw source identity/text is hashed incrementally before
``_decode_row``. The digest is observed-selection evidence, not a COMPLETE
claim or receipt substitute. Feature-visible state carries counts, selected
numerator/anchor, and no-value reason only.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from data_contracts.identity import canonical_finite_safe_json
from ops.receipt_product import PRODUCT_ARTIFACT_FIELDS, product_row_digest

from .query import _decode_row


FINANCIAL_SELECTION_EVIDENCE_FORMAT = "financial-selection-evidence/v1"
_COUNT_ONLY_STATE = "all_visible_existence_and_count"
_PER_SHARE_STATE = "latest_qualifying_bps_preferred_else_eps"
_FINANCIAL_STATES = frozenset({_COUNT_ONLY_STATE, _PER_SHARE_STATE})
_SOURCE_IDENTITY_FIELDS = (
    "available_at",
    "event_time",
    "ingested_at",
    "natural_key",
    "payload",
    "raw_payload",
    "source",
)


def catalog_row_payload(row: dict[str, Any]) -> dict[str, Any]:
    """Best-effort payload dict from a jquants_records (or flattened) row."""
    p = row.get("payload")
    if isinstance(p, dict):
        return p
    if isinstance(p, str) and p:
        try:
            loaded = json.loads(p)
            if isinstance(loaded, dict):
                return loaded
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
    raw = row.get("raw_payload")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw:
        try:
            loaded = json.loads(raw)
            if isinstance(loaded, dict):
                return loaded
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
    return {}


def _as_float_or_none(x: Any) -> float | None:
    if x is None or x == "":
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


class _PerShareObservationAccumulator:
    """Shared BPS-preferred-else-EPS walk used by the list helper and state."""

    __slots__ = (
        "latest_bps",
        "latest_eps",
        "parsed_rows",
        "selected_natural_key",
    )

    def __init__(self) -> None:
        self.latest_bps: dict[str, Any] | None = None
        self.latest_eps: dict[str, Any] | None = None
        self.parsed_rows = 0
        self.selected_natural_key: str | None = None

    def add(self, row: dict[str, Any]) -> bool:
        payload = catalog_row_payload(row)
        if not payload:
            return False
        self.parsed_rows += 1
        bps = _as_float_or_none(
            payload.get("BPS")
            if payload.get("BPS") is not None
            else payload.get("bps")
        )
        eps = _as_float_or_none(
            payload.get("EPS")
            if payload.get("EPS") is not None
            else payload.get("eps")
        )
        period_end = next(
            (
                str(payload.get(key))[:10]
                for key in (
                    "CurrentPeriodEndDate",
                    "CurPerEn",
                    "CurrentFiscalYearEndDate",
                    "CurFYEn",
                    "FiscalYearEndDate",
                    "PeriodEndDate",
                    "period_end",
                )
                if payload.get(key)
            ),
            None,
        )
        disclosure_date = next(
            (
                str(payload.get(key))[:10]
                for key in (
                    "DisclosedDate",
                    "DiscDate",
                    "disclosed_date",
                    "disc_date",
                )
                if payload.get(key)
            ),
            None,
        )
        anchor = period_end or disclosure_date
        common = {
            "statement_period_end": period_end,
            "disclosure_date": disclosure_date,
            "split_safety_anchor": anchor,
            "split_safety_anchor_source": (
                "statement_period_end" if period_end else "disclosure_date"
            ),
            "fins_rows": self.parsed_rows,
        }
        if bps is not None:
            self.latest_bps = {**common, "mode": "bps_over_price", "bps": bps}
        if eps is not None:
            self.latest_eps = {**common, "mode": "eps_over_price", "eps": eps}
        if bps is not None or (eps is not None and self.latest_bps is None):
            key = row.get("natural_key")
            self.selected_natural_key = None if key is None else str(key)
            return True
        return False

    def result(self) -> dict[str, Any] | None:
        selected = self.latest_bps or self.latest_eps
        if selected is None:
            return None
        return {**selected, "fins_rows": self.parsed_rows}


def latest_fins_per_share_observation(
    rows: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Select the exact BPS/EPS observation and its own split-safety anchor.

    Prefers BPS as the established value-feature contract does. Statement
    period end is preferred; disclosure date is the explicit fallback.
    ``fins_rows`` counts every nonempty parsed payload, including rows that
    are not per-share observations.
    """
    accumulator = _PerShareObservationAccumulator()
    for row in rows or []:
        accumulator.add(row)
    return accumulator.result()


@dataclass(frozen=True, slots=True)
class FinancialCatalogState:
    """Compute-facing financial catalog selection. No raw-row array."""

    dataset: str
    code: str
    initial_visible_state: str
    visible_row_count: int
    parsed_row_count: int | None
    observation: Mapping[str, Any] | None
    no_value_reason: str | None


@dataclass(frozen=True, slots=True)
class _FinancialSelectionEvidence:
    """Observed-selection evidence. Not a COMPLETE claim or receipt."""

    format: str
    digest: str
    selected_natural_key: str | None


@dataclass(frozen=True, slots=True)
class _OwnedFinancialSelection:
    """Private owned result: compute state plus owner provenance."""

    state: FinancialCatalogState
    evidence: _FinancialSelectionEvidence
    selected_product_digest: str | None = None
    payload_column_evidence: Mapping[str, str] | None = None
    visible_identities: tuple[tuple[str, str], ...] = ()
    visible_product_digests: tuple[str | None, ...] = ()


def _typed_raw_sql_value(value: Any) -> Any:
    """Preserve SQLite storage class. TEXT and BLOB with the same bytes differ.

    Count-only hashing must not UTF-8-decode BLOB. JSON null is SQL NULL.
    """
    if value is None:
        return None
    if isinstance(value, memoryview):
        value = value.tobytes()
    elif isinstance(value, bytearray):
        value = bytes(value)
    if isinstance(value, bytes):
        return {"hex": value.hex(), "storage": "blob"}
    if isinstance(value, str):
        return {"storage": "text", "value": value}
    if type(value) is int:
        return {"storage": "integer", "value": value}
    if type(value) is float:
        return {"storage": "real", "value": value}
    raise TypeError(
        f"unsupported SQLite value type for selection evidence: {type(value).__name__}"
    )


def _raw_source_identity(row: Any) -> dict[str, Any]:
    identity: dict[str, Any] = {}
    for field in _SOURCE_IDENTITY_FIELDS:
        try:
            value = row[field]
        except (KeyError, IndexError, TypeError):
            value = None
        identity[field] = _typed_raw_sql_value(value)
    return identity


def _framed_canonical_record(record: Mapping[str, Any]) -> bytes:
    encoded = canonical_finite_safe_json(record).encode("utf-8")
    return str(len(encoded)).encode("ascii") + b":" + encoded


class _IncrementalSelectionEvidence:
    """Constant-size hasher: versioned header, per-row records, footer."""

    __slots__ = ("_hasher", "_count")

    def __init__(
        self,
        *,
        dataset: str,
        code: str,
        initial_visible_state: str,
    ) -> None:
        self._hasher = hashlib.sha256()
        self._count = 0
        self._hasher.update(
            _framed_canonical_record(
                {
                    "code": code,
                    "dataset": dataset,
                    "format": FINANCIAL_SELECTION_EVIDENCE_FORMAT,
                    "initial_visible_state": initial_visible_state,
                    "record": "header",
                }
            )
        )

    @property
    def visible_row_count(self) -> int:
        return self._count

    def add_raw_row(self, row: Any) -> None:
        identity = _raw_source_identity(row)
        self._hasher.update(
            _framed_canonical_record({"record": "row", **identity})
        )
        self._count += 1

    def finish(
        self, selected_natural_key: str | None
    ) -> _FinancialSelectionEvidence:
        self._hasher.update(
            _framed_canonical_record(
                {
                    "record": "footer",
                    "selected_natural_key": selected_natural_key,
                    "visible_row_count": self._count,
                }
            )
        )
        return _FinancialSelectionEvidence(
            format=FINANCIAL_SELECTION_EVIDENCE_FORMAT,
            digest="sha256:" + self._hasher.hexdigest(),
            selected_natural_key=selected_natural_key,
        )


def _payload_column_evidence(raw: Any) -> dict[str, str]:
    """Inspect original SQL payload columns. Not a row-count inference."""

    evidence: dict[str, str] = {}
    for field in ("payload", "raw_payload"):
        try:
            value = raw[field]
        except (KeyError, IndexError, TypeError):
            evidence[field] = "missing"
            continue
        evidence[field] = "present_null" if value is None else "present_value"
    return evidence


def _product_digest_from_raw(raw: Any) -> str | None:
    """Digest the selected source version. Not a COMPLETE or receipt claim."""

    try:
        fields = {field: raw[field] for field in PRODUCT_ARTIFACT_FIELDS}
    except (KeyError, IndexError, TypeError):
        return None
    if any(type(value) is not str for value in fields.values()):
        return None
    try:
        return product_row_digest(fields)
    except ValueError:
        return None


def _owned_selection_from_raw_rows(
    raw_rows: Iterator[Any],
    *,
    dataset: str,
    code: str,
    initial_visible_state: str,
) -> _OwnedFinancialSelection:
    """Hash raw source identity/text, decode, then accumulate compact state."""

    if initial_visible_state not in _FINANCIAL_STATES:
        raise ValueError(
            f"unsupported initial_visible_state: {initial_visible_state!r}"
        )
    count_only = initial_visible_state == _COUNT_ONLY_STATE
    evidence = _IncrementalSelectionEvidence(
        dataset=dataset,
        code=code,
        initial_visible_state=initial_visible_state,
    )
    accumulator = None if count_only else _PerShareObservationAccumulator()
    selected_product_digest: str | None = None
    payload_column_evidence: dict[str, str] | None = None
    last_column_evidence: dict[str, str] | None = None
    visible_identities: list[tuple[str, str]] = []
    visible_product_digests: list[str | None] = []
    try:
        for raw in raw_rows:
            evidence.add_raw_row(raw)
            last_column_evidence = _payload_column_evidence(raw)
            visible_product_digests.append(_product_digest_from_raw(raw))
            try:
                key = raw["natural_key"]
                event_time = raw["event_time"]
            except (KeyError, IndexError, TypeError):
                key = None
                event_time = None
            if key is not None and str(key):
                visible_identities.append((str(key), str(event_time or "")[:10]))
            decoded = _decode_row(raw)
            if accumulator is None:
                payload_column_evidence = last_column_evidence
            elif accumulator.add(decoded):
                selected_product_digest = _product_digest_from_raw(raw)
                payload_column_evidence = last_column_evidence
    finally:
        close = getattr(raw_rows, "close", None)
        if close is not None:
            close()
    observation = None if accumulator is None else accumulator.result()
    selected_natural_key = (
        None if accumulator is None else accumulator.selected_natural_key
    )
    no_value_reason = None
    if not count_only and observation is None:
        no_value_reason = "no BPS or EPS"
        selected_product_digest = None
        payload_column_evidence = last_column_evidence
    state = FinancialCatalogState(
        dataset=dataset,
        code=code,
        initial_visible_state=initial_visible_state,
        visible_row_count=evidence.visible_row_count,
        parsed_row_count=None if count_only else accumulator.parsed_rows,
        observation=(
            None if observation is None else MappingProxyType(observation)
        ),
        no_value_reason=no_value_reason,
    )
    return _OwnedFinancialSelection(
        state=state,
        evidence=evidence.finish(selected_natural_key),
        selected_product_digest=selected_product_digest,
        payload_column_evidence=(
            None
            if payload_column_evidence is None
            else MappingProxyType(payload_column_evidence)
        ),
        visible_identities=tuple(visible_identities),
        visible_product_digests=tuple(visible_product_digests),
    )


__all__ = [
    "FINANCIAL_SELECTION_EVIDENCE_FORMAT",
    "FinancialCatalogState",
    "catalog_row_payload",
    "latest_fins_per_share_observation",
]
