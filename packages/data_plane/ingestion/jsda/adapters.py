"""Formal JSDA adapter surface. Staging parse never writes COMPLETE receipts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol


@dataclass(frozen=True)
class JsdaAdapterSpec:
    dataset_id: str
    official_index_url: str
    fact_table: str
    segment_granularity: str
    history_target_start: str
    event_date_fields: tuple[str, ...]
    publication_label_fields: tuple[str, ...]
    natural_key_fields: tuple[str, ...]
    allows_correction_revisions: bool


class JsdaSourceAdapter(Protocol):
    spec: JsdaAdapterSpec

    def canonical_segment_id(self, *, artifact_name: str, meta: Mapping[str, Any]) -> str:
        ...

    def available_at_policy(self) -> str:
        ...


class OtcBondReferenceAdapter:
    spec = JsdaAdapterSpec(
        dataset_id="jsda_otc_bond_reference_prices",
        official_index_url=(
            "https://market.jsda.or.jp/shijyo/saiken/baibai/baisanchi/index.html"
        ),
        fact_table="jsda_otc_bond_reference_prices",
        segment_granularity="official_archive_day",
        history_target_start="2002-08-02",
        event_date_fields=("quote_effective_date",),
        publication_label_fields=("publication_label_date",),
        natural_key_fields=("isin", "quote_effective_date"),
        allows_correction_revisions=True,
    )

    def canonical_segment_id(self, *, artifact_name: str, meta: Mapping[str, Any]) -> str:
        day = str(meta.get("publication_label_date") or meta.get("segment_id") or "")
        if len(day) >= 10 and day[4] == "-":
            return day[:10]
        return f"file_{artifact_name}"

    def available_at_policy(self) -> str:
        return "publication_label_conservative"


class TokyoRepoAdapter:
    spec = JsdaAdapterSpec(
        dataset_id="jsda_tokyo_repo_rates",
        official_index_url="https://www.jsda.or.jp/shiryoshitsu/toukei/trr/",
        fact_table="jsda_repo_rates",
        segment_granularity="source_time_series_file",
        history_target_start="2012-10-29",
        event_date_fields=("observation_date",),
        publication_label_fields=("publication_date",),
        natural_key_fields=("tenor", "observation_date"),
        allows_correction_revisions=False,
    )

    def canonical_segment_id(self, *, artifact_name: str, meta: Mapping[str, Any]) -> str:
        return f"timeseries_{artifact_name}"

    def available_at_policy(self) -> str:
        return "publication_date_or_ingest_conservative"


class CorporateBondTransactionsAdapter:
    spec = JsdaAdapterSpec(
        dataset_id="jsda_corporate_bond_transactions",
        official_index_url=(
            "https://www.jsda.or.jp/shiryoshitsu/toukei/saiken_torihiki/"
        ),
        fact_table="jsda_corporate_bond_transactions",
        segment_granularity="official_archive_year",
        history_target_start="2015-11-04",
        event_date_fields=("trade_date",),
        publication_label_fields=("file_label_date",),
        natural_key_fields=("trade_id", "trade_date"),
        allows_correction_revisions=False,
    )

    def canonical_segment_id(self, *, artifact_name: str, meta: Mapping[str, Any]) -> str:
        year = meta.get("archive_year")
        if year:
            return f"year_{year}"
        return f"file_{artifact_name}"

    def available_at_policy(self) -> str:
        return "file_publication_conservative"


ADAPTERS: dict[str, JsdaSourceAdapter] = {
    "jsda_otc_bond_reference_prices": OtcBondReferenceAdapter(),
    "jsda_tokyo_repo_rates": TokyoRepoAdapter(),
    "jsda_corporate_bond_transactions": CorporateBondTransactionsAdapter(),
}


def adapter_for(dataset_id: str) -> JsdaSourceAdapter:
    try:
        return ADAPTERS[dataset_id]
    except KeyError as exc:
        raise KeyError(f"no JSDA adapter for {dataset_id!r}") from exc


__all__ = [
    "ADAPTERS",
    "CorporateBondTransactionsAdapter",
    "JsdaAdapterSpec",
    "JsdaSourceAdapter",
    "OtcBondReferenceAdapter",
    "TokyoRepoAdapter",
    "adapter_for",
]
