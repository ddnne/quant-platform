"""DataPlane-owned compact financial selection and payload aliases.

PIT owns input order and revision selection. Payload values are accepted only
as ``dict`` (not a general Mapping). An empty payload dict stops raw-payload
fallback. Numeric conversion matches the historical helper: non-finite floats
are not rejected by the legacy per-share selector. The ratio selector uses
finite values and latest-statement/comparable-prior semantics instead; the
two policies are not interchangeable.

Compact financial catalog state is accumulated from a PIT-owned raw-row
stream. Raw source identity/text is hashed incrementally before
``_decode_row``. The digest is observed-selection evidence, not a COMPLETE
claim or receipt substitute. Feature-visible state carries counts, selected
numerator/anchor, and no-value reason only.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from data_contracts.identity import canonical_finite_safe_json
from ops.receipt_product import PRODUCT_ARTIFACT_FIELDS, product_row_digest

from .query import _decode_row


FINANCIAL_SELECTION_EVIDENCE_FORMAT = "financial-selection-evidence/v1"
MARKET_CAP_ALIASES = ("MarketCapitalization", "MarketCap", "MktCap")
_COUNT_ONLY_STATE = "all_visible_existence_and_count"
_PER_SHARE_STATE = "latest_qualifying_bps_preferred_else_eps"
STATEMENT_RATIO_STATE = "latest_statement_plus_comparable_prior"
_FINANCIAL_STATES = frozenset({_COUNT_ONLY_STATE, _PER_SHARE_STATE, STATEMENT_RATIO_STATE})
FINS_ALIASES = {
    "book_value_per_share": ("BPS", "BookValuePerShare"),
    "earnings_per_share": ("EPS", "EarningsPerShare"),
    "roe": ("ROE", "ReturnOnEquity"),
    "sales": ("Sales", "NetSales"),
    "profit": ("NP", "Profit"),
    "total_assets": ("TA", "TotalAssets"),
    "equity": ("Eq", "Equity"),
    "equity_ratio": ("EqAR", "EquityToAssetRatio"),
    "period_type": ("CurPerType", "TypeOfCurrentPeriod"),
    "period_end": ("CurPerEn", "CurrentPeriodEndDate"),
    "document_type": ("DocType", "TypeOfDocument"),
    "disclosed_date": ("DiscDate", "DisclosedDate"),
    "disclosed_time": ("DiscTime", "DisclosedTime"),
}
_STATEMENT_VALUE_KEYS = tuple(
    key for name in ("book_value_per_share", "earnings_per_share", "roe", "sales",
                     "profit", "total_assets", "equity", "equity_ratio")
    for key in FINS_ALIASES[name]
)
_STATEMENT_FIELDS = frozenset(key for aliases in FINS_ALIASES.values() for key in aliases)
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


def bar_size_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    """Preserve size alias priority without exposing unrelated vendor fields."""
    payload = catalog_row_payload(row)
    return {key: payload[key] for key in MARKET_CAP_ALIASES if key in payload}


def financial_number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def financial_value(payload: Mapping[str, Any], alias_name: str) -> tuple[float | None, str | None]:
    for key in FINS_ALIASES[alias_name]:
        if key in payload and (value := financial_number(payload[key])) is not None:
            return value, key
    return None, None


def financial_text(payload: Mapping[str, Any], alias_name: str) -> str | None:
    for key in FINS_ALIASES[alias_name]:
        value = payload.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _comparable_statement(payload: Mapping[str, Any]) -> tuple[str, str] | None:
    period_type = financial_text(payload, "period_type")
    if not period_type:
        return None
    document = (financial_text(payload, "document_type") or "").lower().replace("-", "")
    consolidation = ("nonconsolidated" if "nonconsolidated" in document else
                     "consolidated" if "consolidated" in document else "unspecified")
    return period_type.lower(), consolidation


class _StatementRatioAccumulator:
    """Exact latest statement plus prior comparable period, without a history sort.

    Same-period corrections cannot become a growth denominator. Retaining the
    latest two distinct periods per comparison class suffices, including a
    missing prior period end (the historical ratio policy permits that row).
    """

    def __init__(self) -> None:
        self.parsed_rows = 0
        self.latest: dict[str, Any] | None = None
        self.comparable: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self.selected_natural_key: str | None = None

    def add(self, row: dict[str, Any]) -> bool:
        payload = catalog_row_payload(row)
        if not payload or not any(financial_number(payload.get(key)) is not None
                                  for key in _STATEMENT_VALUE_KEYS):
            return False
        self.parsed_rows += 1
        disclosed_date = financial_text(payload, "disclosed_date") or str(row.get("event_time") or "")[:10]
        sort_key = (
            disclosed_date[:10], financial_text(payload, "disclosed_time") or "",
            str(row.get("available_at") or row.get("event_time") or ""),
            str(row.get("natural_key") or ""), self.parsed_rows,
        )
        observation = {
            "payload": MappingProxyType({key: value for key, value in payload.items()
                                         if key in _STATEMENT_FIELDS}),
            "available_at": str(row.get("available_at") or "") or None,
            "sort_key": sort_key,
        }
        comparable = _comparable_statement(payload)
        if comparable is not None:
            previous = self.comparable.get(comparable, [])
            # Keep an older correction only if it outranks the retained row.
            ranked = sorted([*previous, observation], key=lambda item: item["sort_key"], reverse=True)
            retained: list[dict[str, Any]] = []
            seen: set[str | None] = set()
            for candidate in ranked:
                candidate_period = financial_text(candidate["payload"], "period_end")
                if candidate_period not in seen:
                    retained.append(candidate)
                    seen.add(candidate_period)
            self.comparable[comparable] = retained[:2]
        changed = self.latest is None or sort_key > self.latest["sort_key"]
        if changed:
            self.latest = observation
            self.selected_natural_key = str(row.get("natural_key") or "") or None
        return changed

    def result(self) -> dict[str, Any] | None:
        if self.latest is None:
            return None
        return {key: value for key, value in self.latest.items() if key != "sort_key"}

    def prior(self) -> dict[str, Any] | None:
        if self.latest is None:
            return None
        payload = self.latest["payload"]
        comparable = _comparable_statement(payload)
        period = financial_text(payload, "period_end")
        if comparable is None or not period:
            return None
        for candidate in self.comparable.get(comparable, ()):
            if financial_text(candidate["payload"], "period_end") != period:
                return {key: value for key, value in candidate.items() if key != "sort_key"}
        return None


def statement_ratio_state(rows: Iterator[dict[str, Any]], *, code: str) -> FinancialCatalogState:
    """Pure selector for already PIT-visible fixtures; production uses the owned API."""
    accumulator = _StatementRatioAccumulator()
    count = 0
    for row in rows:
        count += 1
        accumulator.add(row)
    return FinancialCatalogState(
        dataset="fins_summary", code=code, initial_visible_state=STATEMENT_RATIO_STATE,
        visible_row_count=count, parsed_row_count=accumulator.parsed_rows,
        observation=accumulator.result(), prior_observation=accumulator.prior(),
        no_value_reason=None if accumulator.latest else "no PIT-visible financial statement",
    )


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
    prior_observation: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        for name in ("observation", "prior_observation"):
            observation = getattr(self, name)
            if observation is not None:
                frozen = dict(observation)
                if isinstance(frozen.get("payload"), Mapping):
                    frozen["payload"] = MappingProxyType(dict(frozen["payload"]))
                object.__setattr__(self, name, MappingProxyType(frozen))


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
    accumulator = (None if count_only else _StatementRatioAccumulator()
                   if initial_visible_state == STATEMENT_RATIO_STATE
                   else _PerShareObservationAccumulator())
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
        no_value_reason = ("no PIT-visible financial statement"
                           if initial_visible_state == STATEMENT_RATIO_STATE else "no BPS or EPS")
        selected_product_digest = None
        payload_column_evidence = last_column_evidence
    prior_observation = (accumulator.prior()
                         if isinstance(accumulator, _StatementRatioAccumulator) else None)
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
        prior_observation=prior_observation,
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
    "STATEMENT_RATIO_STATE",
    "FINS_ALIASES",
    "financial_number",
    "financial_value",
    "financial_text",
    "statement_ratio_state",
    "catalog_row_payload",
    "latest_fins_per_share_observation",
]
