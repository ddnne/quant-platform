"""Behavior tests for the small personal DRAFT research loop."""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import multiprocessing.synchronize
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import paper_runtime.personal_prepared_frame as prepared_frame_module
import pit
import pit.api as pit_api_module
import pytest

from core import run_backtest
from core.engine import _make_feature_accessor
from data_contracts.identity import natural_key
from execution.personal_paper_service import PersonalPaperExecutionService
from paper_runtime.snapshot_identity import data_snapshot_id
from paper_runtime.personal_snapshot import PersonalSnapshot
from paper_runtime.personal_prepared_frame import (
    _feature_cache_key_document,
    _personal_prepared_frame_scope,
)
from price_basis import PERSONAL_RETROSPECTIVE_ADJUSTED
from research.paper_candidate_specs import (
    build_factor_rank_strategy_spec,
    build_multi_day_hold_strategy_spec,
)
from research.personal_service import (
    PERSONAL_DECISION_POLICY,
    PERSONAL_EXACT_FOUR_MAX_BACKTESTS,
    PERSONAL_RESEARCH_REPORT_VERSION,
    PERSONAL_SHORT_FINANCING_ANNUAL_RATES,
    PERSONAL_SHORT_FINANCING_BASELINE_ANNUAL_RATE,
    PERSONAL_SHORT_FINANCING_SESSIONS_PER_YEAR,
    PersonalResearchInputError,
    PersonalResearchPolicy,
    PersonalResearchRequest,
    PersonalResearchService,
    _CandidateProcessTask,
    _candidate_process_domain,
    _canonical_bytes,
    _calendar_lookback_days,
    _closures,
    _evaluate_candidates_concurrently,
    _fixed_position_short_financing_evidence,
    _md_short_financing,
    _periods,
    _run_one,
    _short_financing_sensitivity_document,
    _validated_specs,
    _write_continuous_base_sleeve_artifact,
    default_personal_specs,
    get_research_cohort,
    personal_specs_for_cohort,
)
from research.personal_base_sleeve import (
    BASE_SLEEVE_ID,
    PERSONAL_BASE_SLEEVE_ARTIFACT_SCHEMA,
    validate_personal_base_sleeve_artifact,
)
from research.personal_universe import (
    PersonalResolvedUniverseMembership,
    personal_universe_selector,
)
from storage.sqlite_store import SqliteStore
from strategies.spec import (
    FactorLeg,
    FeatureRef,
    interpret_strategy_spec,
    iter_feature_refs,
    strategy_spec_digest,
)


def _spawn_candidate_document(
    task: _CandidateProcessTask,
) -> tuple[int, dict[str, object]]:
    spec, closure = _candidate_process_domain(task)
    return (
        task.ordinal,
        {
            "strategy_id": spec.strategy_id,
            "strategy_spec_version": spec.version,
            "strategy_spec_digest": strategy_spec_digest(spec),
            "dependency_closure_digest": closure.closure_digest,
            "decision": "REJECT",
        },
    )


def _dates(start: date, end: date) -> list[str]:
    values: list[str] = []
    cursor = start
    while cursor <= end:
        values.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return values


def _generic(dataset: str, payload: dict, *, event: str, available: str) -> dict:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return {
        "source": "jquants",
        "dataset": dataset,
        "natural_key": natural_key(payload, dataset),
        "event_time": event,
        "available_at": available,
        "ingested_at": available,
        "payload": encoded,
        "raw_payload": encoded,
    }


@pytest.fixture
def personal_db(tmp_path: Path) -> tuple[Path, str, str]:
    start = date(2024, 1, 1)
    end = date(2024, 5, 31)
    all_days = _dates(start, end)
    sessions = [day for day in all_days if date.fromisoformat(day).weekday() < 5]
    codes = ("1301", "1302", "1303", "1304")
    source = tmp_path / "personal.sqlite"
    store = SqliteStore(source)
    store.upsert(
        "jquants_market_calendar",
        [
            {
                "source": "jquants",
                "date": day,
                "event_time": f"{day}T09:00:00+09:00",
                "available_at": "2023-01-01T00:00:00+09:00",
                "ingested_at": "2023-01-01T00:00:00+09:00",
                "holiday_division": (
                    "1" if date.fromisoformat(day).weekday() < 5 else "0"
                ),
            }
            for day in all_days
        ],
    )
    store.upsert(
        "jquants_listed_info",
        [
            {
                "source": "jquants",
                "code": code,
                "snapshot_date": "2023-12-29",
                "event_time": "2023-12-29T09:00:00+09:00",
                "available_at": "2023-12-29T09:00:00+09:00",
                "ingested_at": "2023-12-29T09:00:00+09:00",
                "company_name": f"Fixture {code}",
                "sector_17_code": "1",
                "sector_33_code": "10" if code in {"1301", "1302"} else "20",
                "market_code": "0112" if code == "1304" else "0111",
                "scale_category": (
                    "TOPIX Core30" if code == "1301" else "TOPIX Large70"
                ),
            }
            for code in codes
        ],
    )
    bars: list[dict] = []
    generic: list[dict] = []
    for day in all_days:
        holiday = "1" if date.fromisoformat(day).weekday() < 5 else "0"
        generic.append(
            _generic(
                "markets_calendar",
                {"Date": day, "HolidayDivision": holiday},
                event=f"{day}T09:00:00+09:00",
                available="2023-01-01T00:00:00+09:00",
            )
        )
    for code_index, code in enumerate(codes):
        master = {
            "Code": code,
            "Date": "2023-12-29",
            "CompanyName": f"Fixture {code}",
            "MarketCode": "0112" if code == "1304" else "0111",
            "ScaleCategory": (
                "TOPIX Core30" if code == "1301" else "TOPIX Large70"
            ),
            "Sector33Code": "10" if code in {"1301", "1302"} else "20",
        }
        generic.append(
            _generic(
                "equities_master",
                master,
                event="2023-12-29T09:00:00+09:00",
                available="2023-12-29T09:00:00+09:00",
            )
        )
        fins = {
            "Code": code,
            "DiscDate": "2023-12-29",
            "DiscNo": str(code_index + 1),
            "EPS": 8.0 + code_index,
            "BPS": 80.0 + 10.0 * code_index,
            "ROE": 0.08 + code_index * 0.01,
            "Sales": 1_000.0 + code_index * 100.0,
            "NP": 80.0 + code_index * 10.0,
            "TA": 2_000.0 + code_index * 100.0,
            "Eq": 1_000.0 + code_index * 50.0,
            "CurPerType": "FY",
            "CurPerEn": "2023-12-31",
            "DocType": "FYFinancialStatements_Consolidated_JP",
        }
        generic.append(
            _generic(
                "fins_summary",
                fins,
                event="2023-12-29T15:00:00+09:00",
                available="2023-12-29T15:00:00+09:00",
            )
        )
        for session_index, day in enumerate(sessions):
            close = 100.0 + code_index * 5.0 + session_index * (0.2 + code_index * 0.05)
            available = f"{day}T15:00:00+09:00"
            bars.append(
                {
                    "source": "jquants",
                    "code": code,
                    "date": day,
                    "event_time": available,
                    "available_at": available,
                    "ingested_at": available,
                    "open": close,
                    "high": close,
                    "low": close,
                    "close": close,
                    "adjustment_close": close,
                    "volume": 1000.0,
                }
            )
    store.upsert("jquants_daily_bars", bars)
    store.upsert("jquants_records", generic)
    store.close()
    return source, start.isoformat(), end.isoformat()


def _policy(**changes) -> PersonalResearchPolicy:
    values = {
        "validation_folds": 2,
        "min_fold_sessions": 20,
        "holdout_months": 1,
        "min_holdout_sessions": 20,
        "base_cost_bps": 0.0,
        "stress_cost_bps": 0.0,
        "min_positive_folds": 2,
        "min_validation_sharpe": -100.0,
        "max_drawdown": 1.0,
        "min_fills": 0,
        "max_candidates": 12,
        "max_parallel": 1,
    }
    values.update(changes)
    return PersonalResearchPolicy(**values)


def _candidate_test_wave(
    output_root: Path,
) -> tuple[
    tuple[_CandidateProcessTask, ...],
    tuple[object, ...],
    tuple[object, ...],
]:
    policy = _policy(max_parallel=4)
    specs = personal_specs_for_cohort("diverse-core-v1")
    closures = _closures(
        specs,
        start="2022-01-01",
        end="2026-01-01",
        policy=policy,
        universe_selector=personal_universe_selector("topix_all"),
    )
    tasks = tuple(
        _CandidateProcessTask(
            ordinal=ordinal,
            strategy_spec_document=_canonical_bytes(spec.to_dict()),
            dependency_closure_document=_canonical_bytes(closure.to_dict()),
            snapshot=SimpleNamespace(),
            universe=SimpleNamespace(),
            fold_periods=(("2022-01-01", "2022-12-31"),),
            holdout_period=("2025-01-01", "2026-01-01"),
            output_root=output_root,
            policy=policy,
            short_financing_required=False,
        )
        for ordinal, (spec, closure) in enumerate(zip(specs, closures, strict=True))
    )
    return tasks, specs, closures


def _request(
    source: Path, start: str, end: str, output: Path
) -> PersonalResearchRequest:
    return PersonalResearchRequest(
        source_db=source,
        period_start=start,
        period_end=end,
        output_root=output,
        specs=(
            build_multi_day_hold_strategy_spec(
                hold_days=3,
                momentum_n=3,
                top_k=2,
                momentum_feature_id=(
                    "retrospective_split_adjusted_momentum_n"
                ),
                strategy_id="personal_test_momentum",
            ),
        ),
    )


def _prepared_frame_spec(case: str):
    price = FactorLeg(
        feature=FeatureRef(
            id="retrospective_price_ratio",
            version="1.0.0",
            params={"mode": "return_ratio", "short_n": 2, "long_n": 3},
        ),
        weight=1.0,
        direction="high_good",
    )
    fundamental = FactorLeg(
        feature=FeatureRef(
            id="pit_fundamental_ratio",
            version="1.0.0",
            params={"mode": "roe"},
        ),
        weight=1.0,
        direction="high_good",
    )
    legs = {
        "price": (price,),
        "fundamental": (fundamental,),
        "long_short": (price, fundamental),
    }[case]
    return build_factor_rank_strategy_spec(
        strategy_id=f"personal_prepared_frame_{case}",
        legs=legs,
        hold_days=1,
        group="sector33",
        long_frac=0.25,
        short_frac=0.25,
        allow_short=case == "long_short",
        min_eligible_ratio=1.0,
        min_eligible_count=4,
        min_group_count=2,
        rationale=f"Prepared-frame {case} behavioral parity fixture.",
    )


def _prepared_frame_case(
    source: Path, start: str, end: str
) -> tuple[PersonalResolvedUniverseMembership, tuple[str, str]]:
    selector = personal_universe_selector("topix_all")
    sessions = tuple(
        day
        for day in _dates(date.fromisoformat(start), date.fromisoformat(end))
        if date.fromisoformat(day).weekday() < 5
    )[:30]
    universe = PersonalResolvedUniverseMembership(
        period_start=sessions[0],
        period_end=sessions[-1],
        decision_memberships=tuple(
            (day, ("1301", "1302", "1303", "1304")) for day in sessions
        ),
        rule_id=selector.rule_id,
        rule_version=selector.rule_version,
        rule_digest=selector.rule_digest,
    )
    return universe, (sessions[0], sessions[-1])


def test_prepared_feature_key_binds_exact_snapshot_scope_and_definition() -> None:
    document = _feature_cache_key_document(
        snapshot_id="sha256:" + "1" * 64,
        as_of="2024-01-05T15:30:00+09:00",
        code="1301",
        feature_id="retrospective_price_ratio",
        feature_version="1.0.0",
        definition_digest="sha256:" + "2" * 64,
        params={"mode": "return_ratio", "short_n": 20, "long_n": 252},
    )

    assert document == {
        "schema_version": "personal-prepared-feature-key/v1",
        "snapshot_id": "sha256:" + "1" * 64,
        "as_of": "2024-01-05T15:30:00+09:00",
        "code_present": True,
        "code": "1301",
        "feature_id": "retrospective_price_ratio",
        "feature_version": "1.0.0",
        "feature_definition_digest": "sha256:" + "2" * 64,
        "params": {"mode": "return_ratio", "short_n": 20, "long_n": 252},
    }
    assert document != _feature_cache_key_document(
        snapshot_id="sha256:" + "1" * 64,
        as_of="2024-01-05T15:30:00+09:00",
        code=1301,
        feature_id="retrospective_price_ratio",
        feature_version="1.0.0",
        definition_digest="sha256:" + "2" * 64,
        params={"mode": "return_ratio", "short_n": 20, "long_n": 252},
    )
    for changed in (
        {**document, "snapshot_id": "sha256:" + "3" * 64},
        {**document, "as_of": "2024-01-08T15:30:00+09:00"},
        {**document, "feature_version": "1.0.1"},
        {**document, "feature_definition_digest": "sha256:" + "4" * 64},
        {**document, "params": {**document["params"], "long_n": 120}},
    ):
        assert changed != document


def test_prepared_frame_temp_sqlite_is_removed_after_exception(
    personal_db: tuple[Path, str, str],
) -> None:
    source, _start, _end = personal_db
    cache_path: Path | None = None
    with pytest.raises(RuntimeError, match="test abort"):
        with _personal_prepared_frame_scope(
            db_path=source,
            snapshot_id=data_snapshot_id(source),
        ) as frame:
            cache_path = frame.cache_path
            assert cache_path.is_file()
            raise RuntimeError("test abort")
    assert cache_path is not None
    assert not cache_path.exists()


def test_prepared_frame_rejects_saturated_and_oversized_entries_before_json(
    personal_db: tuple[Path, str, str],
    monkeypatch,
) -> None:
    source, _start, _end = personal_db

    def forbidden_json(_value):
        raise AssertionError("saturated or oversized entry reached JSON encoding")

    def forbidden_compress(_value, **_kwargs):
        raise AssertionError("saturated or oversized entry reached compression")

    with _personal_prepared_frame_scope(
        db_path=source,
        snapshot_id=data_snapshot_id(source),
    ) as frame:
        monkeypatch.setattr(prepared_frame_module, "_canonical_json", forbidden_json)
        monkeypatch.setattr(
            prepared_frame_module.zlib,
            "compress",
            forbidden_compress,
        )
        frame._stats["cache_saturated"] = 1
        frame.store_feature(
            as_of="2024-01-05T15:30:00+09:00",
            feature_id="example",
            feature_version="1.0.0",
            definition_digest="sha256:" + "1" * 64,
            inputs={"code": "1301"},
            value=1.0,
            metadata={},
        )
        frame.store_price_rows(
            as_of="2024-01-05T15:30:00+09:00",
            from_event="2024-01-05",
            to_event="2024-01-05",
            codes=("1301",),
            rows=({"code": "1301", "date": "2024-01-05"},),
        )

        frame._stats["cache_saturated"] = 0
        monkeypatch.setattr(
            prepared_frame_module,
            "PERSONAL_PREPARED_FRAME_MAX_ENTRY_BYTES",
            64,
        )
        frame.store_feature(
            as_of="2024-01-05T15:30:00+09:00",
            feature_id="example",
            feature_version="1.0.0",
            definition_digest="sha256:" + "1" * 64,
            inputs={"code": "1301"},
            value="x" * 256,
            metadata={},
        )
        frame.store_price_rows(
            as_of="2024-01-05T15:30:00+09:00",
            from_event="2024-01-05",
            to_event="2024-01-05",
            codes=("1301",),
            rows=({"code": "1301", "payload": "x" * 256},),
        )
        stats = frame.stats()

    assert int(stats["feature_writes"]) == 0
    assert int(stats["price_window_writes"]) == 0
    assert int(stats["feature_uncacheable"]) == 1
    assert int(stats["price_window_uncacheable"]) == 1


@pytest.mark.parametrize("case", ("price", "fundamental", "long_short"))
def test_personal_prepared_frame_matches_uncached_price_fundamental_and_ls(
    personal_db: tuple[Path, str, str],
    tmp_path: Path,
    case: str,
) -> None:
    source, start, end = personal_db
    universe, period = _prepared_frame_case(source, start, end)
    spec = _prepared_frame_spec(case)
    snapshot_id = data_snapshot_id(source)
    common = {
        "db_path": source,
        "snapshot_id": snapshot_id,
        "universe": universe,
        "period": period,
        "cost_bps": 10.0,
        "lookback_days": 3,
        "max_drawdown": 1.0,
        "short_financing_annual_rate": (
            PERSONAL_SHORT_FINANCING_BASELINE_ANNUAL_RATE
            if case == "long_short"
            else None
        ),
    }
    baseline = _run_one(
        PersonalPaperExecutionService(),
        spec,
        output_root=tmp_path / f"{case}-uncached",
        **common,
    )[3]

    with _personal_prepared_frame_scope(
        db_path=source,
        snapshot_id=snapshot_id,
    ) as frame:
        cache_path = frame.cache_path
        first = _run_one(
            PersonalPaperExecutionService(),
            spec,
            output_root=tmp_path / f"{case}-cached",
            **common,
        )[3]
        replay = _run_one(
            PersonalPaperExecutionService(),
            spec,
            output_root=tmp_path / f"{case}-replay",
            **common,
        )[3]
        stats = frame.stats()

    assert first == baseline
    assert replay == baseline
    assert int(stats["feature_hits"]) > 0
    assert int(stats["price_window_hits"]) > 0
    assert not cache_path.exists()


def test_prepared_first_pass_stores_only_exact_session_bar_rows(
    personal_db: tuple[Path, str, str],
    tmp_path: Path,
    monkeypatch,
) -> None:
    source, start, end = personal_db
    universe, period = _prepared_frame_case(source, start, end)
    spec = _prepared_frame_spec("price")
    snapshot_id = data_snapshot_id(source)
    real_get_bars = pit.get_equity_bars_daily
    engine_reads: list[tuple[str, str, int]] = []

    def tracked_get_bars(*args, **kwargs):
        result = real_get_bars(*args, **kwargs)
        codes = tuple(kwargs.get("codes") or ())
        if len(codes) == 4:
            engine_reads.append(
                (
                    str(kwargs.get("from_event")),
                    str(kwargs.get("to_event")),
                    len(result.rows),
                )
            )
        return result

    monkeypatch.setattr(pit, "get_equity_bars_daily", tracked_get_bars)
    common = {
        "db_path": source,
        "snapshot_id": snapshot_id,
        "universe": universe,
        "period": period,
        "cost_bps": 10.0,
        "lookback_days": 536,
        "max_drawdown": 1.0,
    }
    uncached = _run_one(
        PersonalPaperExecutionService(),
        spec,
        output_root=tmp_path / "bar-shape-uncached",
        **common,
    )[3]
    uncached_reads = tuple(engine_reads)
    engine_reads.clear()

    with _personal_prepared_frame_scope(
        db_path=source,
        snapshot_id=snapshot_id,
    ) as frame:
        prepared = _run_one(
            PersonalPaperExecutionService(),
            spec,
            output_root=tmp_path / "bar-shape-prepared",
            **common,
        )[3]
        prepared_reads = tuple(engine_reads)
        stats = frame.stats()

    assert prepared == uncached
    assert uncached_reads
    assert prepared_reads
    assert any(from_event != to_event for from_event, to_event, _ in uncached_reads)
    assert any(from_event == to_event for from_event, to_event, _ in prepared_reads)
    # Each successful SQL validity probe stores one empty decision-window
    # marker; only exact-session price rows are persisted in the cache.
    assert int(stats["price_rows_written"]) * 5 < sum(
        rows for _, _, rows in uncached_reads
    )
    assert int(stats["price_rows_written"]) == 4 * len(
        universe.decision_memberships
    )
    assert int(stats["price_window_writes"]) == (
        len(prepared_reads) + len(universe.decision_memberships)
    )


def test_prepared_frame_preserves_missing_reason_and_halves_pit_queries(
    personal_db: tuple[Path, str, str],
    tmp_path: Path,
    monkeypatch,
) -> None:
    source, start, end = personal_db
    universe, period = _prepared_frame_case(source, start, end)
    spec = _prepared_frame_spec("price")
    snapshot_id = data_snapshot_id(source)
    real_run_query = pit_api_module.run_query
    query_count = 0

    def counted_run_query(*args, **kwargs):
        nonlocal query_count
        query_count += 1
        return real_run_query(*args, **kwargs)

    monkeypatch.setattr(pit_api_module, "run_query", counted_run_query)
    with _personal_prepared_frame_scope(
        db_path=source,
        snapshot_id=snapshot_id,
    ) as frame:
        feature = _make_feature_accessor(
            f"{period[1]}T15:30:00+09:00",
            source,
        )
        missing_first = feature(
            "pit_fundamental_ratio",
            version="1.0.0",
            code="1301",
            mode="sales_growth",
        )
        missing_first.metadata["datasets"].append("caller-mutation")
        missing_replay = feature(
            "pit_fundamental_ratio",
            version="1.0.0",
            code="1301",
            mode="sales_growth",
        )
        assert missing_first.value is None
        assert missing_replay.value is None
        assert "caller-mutation" not in missing_replay.metadata["datasets"]
        assert missing_replay.metadata["reason"] == "no prior comparable statement"

        before_first = query_count
        _run_one(
            PersonalPaperExecutionService(),
            spec,
            db_path=source,
            snapshot_id=snapshot_id,
            universe=universe,
            period=period,
            cost_bps=10.0,
            lookback_days=3,
            output_root=tmp_path / "query-count-first",
            max_drawdown=1.0,
        )
        first_queries = query_count - before_first
        before_replay = query_count
        _run_one(
            PersonalPaperExecutionService(),
            spec,
            db_path=source,
            snapshot_id=snapshot_id,
            universe=universe,
            period=period,
            cost_bps=10.0,
            lookback_days=3,
            output_root=tmp_path / "query-count-replay",
            max_drawdown=1.0,
        )
        replay_queries = query_count - before_replay
        stats = frame.stats()

    assert replay_queries * 2 < first_queries
    assert int(stats["source_feature_computations_avoided"]) > 0
    assert int(stats["source_price_queries_avoided"]) > 0


def test_prepared_frame_preserves_late_revision_fallback_and_departed_holding(
    personal_db: tuple[Path, str, str],
    tmp_path: Path,
) -> None:
    source, start, end = personal_db
    universe, period = _prepared_frame_case(source, start, end)
    sessions = tuple(day for day, _codes in universe.decision_memberships)
    connection = sqlite3.connect(source)
    connection.row_factory = sqlite3.Row
    try:
        # Current-session absence must retain the same prior-bar fallback.
        connection.execute(
            "DELETE FROM jquants_daily_bars WHERE code=? AND date=?",
            ("1301", sessions[10]),
        )
        # A D bar disclosed only on D+1 is not visible at D's close.
        late_available = f"{sessions[12]}T15:00:00+09:00"
        connection.execute(
            "UPDATE jquants_daily_bars SET available_at=?,ingested_at=? "
            "WHERE code=? AND date=?",
            (late_available, late_available, "1302", sessions[11]),
        )
        # Preserve the old D-visible version and add a later-visible revision.
        original = connection.execute(
            "SELECT * FROM jquants_daily_bars WHERE code=? AND date=?",
            ("1303", sessions[5]),
        ).fetchone()
        assert original is not None
        revised = dict(original)
        revised_available = f"{sessions[13]}T15:00:00+09:00"
        revised["available_at"] = revised_available
        revised["ingested_at"] = revised_available
        for field in ("open", "high", "low", "close", "adjustment_close"):
            revised[field] = float(revised[field]) * 1.25
        columns = tuple(revised)
        connection.execute(
            "INSERT INTO jquants_daily_bars_revisions ("
            + ",".join(columns)
            + ") VALUES ("
            + ",".join("?" for _ in columns)
            + ")",
            tuple(revised[column] for column in columns),
        )
        connection.commit()
    finally:
        connection.close()

    departed_universe = PersonalResolvedUniverseMembership(
        period_start=period[0],
        period_end=period[1],
        decision_memberships=tuple(
            (
                day,
                codes if day <= sessions[15] else tuple(c for c in codes if c != "1304"),
            )
            for day, codes in universe.decision_memberships
        ),
        rule_id=universe.rule_id,
        rule_version=universe.rule_version,
        rule_digest=universe.rule_digest,
    )
    snapshot_id = data_snapshot_id(source)
    spec = build_multi_day_hold_strategy_spec(
        strategy_id="personal_prepared_frame_departed_holding",
        hold_days=1,
        top_k=1,
        min_score=-1.0,
        momentum_n=3,
        momentum_feature_id="retrospective_split_adjusted_momentum_n",
        sticky=False,
    )
    common = {
        "db_path": source,
        "snapshot_id": snapshot_id,
        "universe": departed_universe,
        "period": period,
        "cost_bps": 10.0,
        "lookback_days": 3,
        "max_drawdown": 1.0,
        "short_financing_annual_rate": None,
    }
    baseline = _run_one(
        PersonalPaperExecutionService(),
        spec,
        output_root=tmp_path / "adversarial-uncached",
        **common,
    )[3]
    with _personal_prepared_frame_scope(
        db_path=source,
        snapshot_id=snapshot_id,
    ) as frame:
        prepared = _run_one(
            PersonalPaperExecutionService(),
            spec,
            output_root=tmp_path / "adversarial-cached",
            **common,
        )[3]
        replay = _run_one(
            PersonalPaperExecutionService(),
            spec,
            output_root=tmp_path / "adversarial-replay",
            **common,
        )[3]
        stats = frame.stats()

    assert prepared == baseline
    assert replay == baseline
    assert int(stats["price_window_writes"]) > 0
    assert int(stats["price_window_hits"]) > 0
    assert any(
        trade["code"] == "1304" and trade["side"] == "buy"
        for trade in baseline.trades
    )
    assert baseline.equity_curve[-1]["positions_value"] > 0.0


@pytest.mark.parametrize("bad_adjustment_close", (None, -1.0))
def test_compact_path_matches_historical_adjustment_failure(
    personal_db: tuple[Path, str, str],
    tmp_path: Path,
    bad_adjustment_close: float | None,
) -> None:
    source, start, end = personal_db
    universe, _period = _prepared_frame_case(source, start, end)
    sessions = tuple(day for day, _codes in universe.decision_memberships)
    bad_day = sessions[2]
    run_days = sessions[8:14]
    connection = sqlite3.connect(source)
    try:
        connection.execute(
            "UPDATE jquants_daily_bars SET adjustment_close=? "
            "WHERE code=? AND date=?",
            (bad_adjustment_close, "1301", bad_day),
        )
        connection.commit()
    finally:
        connection.close()

    bounded_universe = PersonalResolvedUniverseMembership(
        period_start=run_days[0],
        period_end=run_days[-1],
        decision_memberships=tuple(
            (day, codes)
            for day, codes in universe.decision_memberships
            if day in run_days
        ),
        rule_id=universe.rule_id,
        rule_version=universe.rule_version,
        rule_digest=universe.rule_digest,
    )
    snapshot_id = data_snapshot_id(source)
    common = {
        "db_path": source,
        "snapshot_id": snapshot_id,
        "universe": bounded_universe,
        "period": (run_days[0], run_days[-1]),
        "cost_bps": 10.0,
        "lookback_days": 536,
        "max_drawdown": 1.0,
    }
    spec = _prepared_frame_spec("fundamental")
    with pytest.raises(ValueError) as uncached_error:
        _run_one(
            PersonalPaperExecutionService(),
            spec,
            output_root=tmp_path / "invalid-adjustment-uncached",
            **common,
        )
    with _personal_prepared_frame_scope(
        db_path=source,
        snapshot_id=snapshot_id,
    ):
        with pytest.raises(ValueError) as prepared_error:
            _run_one(
                PersonalPaperExecutionService(),
                spec,
                output_root=tmp_path / "invalid-adjustment-prepared",
                **common,
            )

    assert str(prepared_error.value) == str(uncached_error.value)
    assert bad_day in str(prepared_error.value)


def test_compact_price_path_excludes_custom_and_same_day_strategies(
    personal_db: tuple[Path, str, str],
) -> None:
    source, start, end = personal_db
    universe, period = _prepared_frame_case(source, start, end)
    snapshot_id = data_snapshot_id(source)

    class InspectBars:
        strategy_id = "inspect_full_bars"
        params: dict = {}

        def __init__(self) -> None:
            self.observed: list[tuple[int, ...]] = []

        def on_bar(self, ctx):
            self.observed.append(
                tuple(len(ctx.bars[code]) for code in sorted(ctx.universe))
            )
            return []

    baseline_strategy = InspectBars()
    baseline = run_backtest(
        baseline_strategy,
        period[0],
        period[1],
        db_path=source,
        execution_mode="next_close",
        universe=universe,
        lookback_days=14,
    )
    prepared_strategy = InspectBars()
    with _personal_prepared_frame_scope(
        db_path=source,
        snapshot_id=snapshot_id,
    ) as frame:
        prepared = run_backtest(
            prepared_strategy,
            period[0],
            period[1],
            db_path=source,
            execution_mode="next_close",
            universe=universe,
            lookback_days=14,
        )
        custom_stats = frame.stats()
    assert prepared == baseline
    assert prepared_strategy.observed == baseline_strategy.observed
    assert int(custom_stats["price_window_requests"]) == 0
    assert max(max(counts) for counts in prepared_strategy.observed) > 1

    spec = _prepared_frame_spec("price")
    same_day_baseline = run_backtest(
        interpret_strategy_spec(spec),
        period[0],
        period[1],
        db_path=source,
        execution_mode="same_day_close",
        universe=universe,
        lookback_days=14,
        price_basis=PERSONAL_RETROSPECTIVE_ADJUSTED,
    )
    with _personal_prepared_frame_scope(
        db_path=source,
        snapshot_id=snapshot_id,
    ) as frame:
        same_day_prepared = run_backtest(
            interpret_strategy_spec(spec),
            period[0],
            period[1],
            db_path=source,
            execution_mode="same_day_close",
            universe=universe,
            lookback_days=14,
            price_basis=PERSONAL_RETROSPECTIVE_ADJUSTED,
        )
        same_day_stats = frame.stats()
    assert same_day_prepared == same_day_baseline
    assert int(same_day_stats["price_window_requests"]) == 0


def _install_managed_sync_evidence(source: Path, *, failing: str | None = None) -> None:
    datasets = (
        "equities_bars_daily",
        "equities_master",
        "fins_summary",
        "markets_calendar",
    )
    connection = sqlite3.connect(source)
    try:
        connection.execute(
            "INSERT INTO local_snapshot_policy "
            "(singleton,require_manifest,snapshot_ready,publication_state,last_error) "
            "VALUES (1,1,0,'REJECTED','READY not published') "
            "ON CONFLICT(singleton) DO UPDATE SET require_manifest=1,"
            "snapshot_ready=0,publication_state='REJECTED',"
            "last_error='READY not published'"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS ingestion_validation ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT,dataset TEXT,status TEXT,"
            "rows_seen INTEGER)"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS ingestion_watermarks ("
            "dataset TEXT PRIMARY KEY,last_ingested_at TEXT NOT NULL)"
        )
        for dataset in datasets:
            connection.execute(
                "INSERT INTO ingestion_validation(dataset,status,rows_seen) "
                "VALUES (?,?,1)",
                (dataset, "fail" if dataset == failing else "pass"),
            )
            connection.execute(
                "INSERT INTO ingestion_watermarks(dataset,last_ingested_at) "
                "VALUES (?,?)",
                (dataset, "2024-06-01T00:00:00+09:00"),
            )
        connection.commit()
    finally:
        connection.close()


def test_personal_research_runs_real_paper_and_is_idempotent(
    personal_db: tuple[Path, str, str], tmp_path: Path
) -> None:
    source, start, end = personal_db
    service = PersonalResearchService(policy=_policy())
    request = _request(source, start, end, tmp_path / "artifacts")

    first = service.run(request)
    second = service.run(request)

    assert first.exit_code == 0
    assert first.report_id == second.report_id
    assert first.report_json_path == second.report_json_path
    assert first.snapshot == second.snapshot
    report = json.loads(first.report_json_path.read_text(encoding="utf-8"))
    assert report["version"] == PERSONAL_RESEARCH_REPORT_VERSION
    assert report["decision_policy"] == PERSONAL_DECISION_POLICY
    assert report["candidate_execution"] == {
        "model": "serial",
        "worker_processes": 1,
        "max_parallel": 1,
        "shared_snapshot_and_quality_preparation": True,
        "base_sleeve_before_fanout": False,
    }
    assert report["summary"] == {
        "analysis_status": "COMPLETED",
        "candidate_count": 1,
        "evaluated_count": 1,
        "hold_count": 1,
        "unexpected_errors": 0,
        "non_candidate_source_backtest_count": 0,
    }
    assert report["candidates"][0]["decision"] == "HOLD"
    assert report["candidates"][0]["stress"] is not None
    assert report["candidates"][0]["holdout"] is not None
    assert report["candidates"][0]["holdout"]["selection_use"] is False
    candidate = report["candidates"][0]
    assert candidate["strategy"]["thesis"]
    assert candidate["strategy"]["mechanics_summary"]
    assert candidate["strategy"]["return_source"]
    assert candidate["strategy"]["works_when"]
    assert candidate["strategy"]["fails_when"]
    assert candidate["validation"]["performance"]["schema_version"] == (
        "personal-fold-stability/v1"
    )
    assert candidate["validation"]["performance"]["stitched_performance"][
        "schema_version"
    ] == "personal-performance/v1"
    assert report["comparison"]["schema_version"] == (
        "personal-performance-comparison/v2"
    )
    comparison_row = report["comparison"]["rows"][0]
    assert comparison_row["return_source"]
    assert comparison_row["works_when"]
    assert comparison_row["fails_when"]
    assert comparison_row["evidence_assessment"]
    assert report["comparison"]["rows"][0]["strategy_id"] == (
        candidate["strategy_id"]
    )
    assert first.universe_id == "topix_all"
    assert report["universe"]["rule_id"] == "topix_all_with_fins"
    assert report["universe"]["controlled_live_eligibility"] == "FORBIDDEN"
    assert report["dependency_closures"][0]["universe_dependencies"][0][
        "id"
    ] == "topix_all_with_fins"
    markdown = first.report_markdown_path.read_text(encoding="utf-8")
    assert "## Comparable performance" in markdown
    assert "Return source" in markdown
    assert "Works when" in markdown
    assert "Fails when" in markdown
    assert "Evidence" in markdown
    assert report["data_quality"]["market_bar_coverage"]["status"] == "PASS"
    assert report["price_basis"] == {
        "id": "PERSONAL_RETROSPECTIVE_ADJUSTED",
        "source": "vendor_adjusted_ohlcv",
        "time_semantics": "retrospective_not_point_in_time",
        "position_units": "synthetic_split_adjusted_units",
        "supported_actions": "vendor_splits_and_reverse_splits",
        "unexplained_action_policy": (
            "extreme_adjusted_moves_advisory; missing_adjusted_"
            "evidence_fail_closed"
        ),
        "lifecycle": "DRAFT_only",
        "live_trading_eligible": False,
    }
    assert report["live_orders_enabled"] is False
    assert report["automatic_promotion"] is False
    assert report["go"] is False
    assert report["ready_snapshot_declared"] is False
    assert report["model_calls"] == 0
    assert report["estimated_ai_cost_usd"] == 0.0


def test_zero_passes_is_completed_not_an_error(
    personal_db: tuple[Path, str, str], tmp_path: Path
) -> None:
    source, start, end = personal_db
    result = PersonalResearchService(policy=_policy(min_fills=1_000_000)).run(
        _request(source, start, end, tmp_path / "rejected")
    )

    assert result.exit_code == 0
    assert result.hold_count == 0
    report = json.loads(result.report_json_path.read_text(encoding="utf-8"))
    assert report["candidates"][0]["decision"] == "REJECT"
    assert "fills" in report["candidates"][0]["reasons"]
    assert report["candidates"][0]["stress"] is None
    assert report["candidates"][0]["holdout"] is None


def test_default_candidates_are_long_only_where_applicable() -> None:
    specs = default_personal_specs()
    assert len(specs) == 4
    assert all(
        "retrospective_split_adjusted_momentum_n"
        in {ref.id for ref in iter_feature_refs(spec)}
        for spec in specs
    )
    assert specs[2].rule.allow_short is False
    assert specs[3].rule.allow_short is False


def test_closed_cohort_selection_and_explicit_specs_are_mutually_exclusive() -> None:
    specs, cohort = _validated_specs(
        None,
        _policy(),
        "diverse-core-v1",
    )
    assert cohort is not None
    assert cohort.cohort_id == "diverse-core-v1"
    assert len(specs) == 4

    with pytest.raises(PersonalResearchInputError, match="mutually exclusive"):
        _validated_specs((specs[0],), _policy(), "diverse-core-v1")
    long_short, long_short_cohort = _validated_specs(
        None,
        _policy(),
        "sector-relative-ls-v1",
        "topix_all",
    )
    assert long_short_cohort is not None
    assert long_short_cohort.short_financing_required is True
    assert len(long_short) == 4
    assert all(spec.rule.allow_short for spec in long_short)
    with pytest.raises(PersonalResearchInputError, match="closed.*cohort"):
        _validated_specs((long_short[0],), _policy())
    with pytest.raises(PersonalResearchInputError, match="compact-market"):
        _validated_specs(
            None,
            _policy(),
            "sector-relative-ls-v1",
            "topix_core30",
        )


def test_fixed_short_financing_monotonically_lowers_return(
    personal_db: tuple[Path, str, str], tmp_path: Path
) -> None:
    source, start, end = personal_db
    selector = personal_universe_selector("topix_all")
    sessions = tuple(
        day
        for day in _dates(date.fromisoformat(start), date.fromisoformat(end))
        if date.fromisoformat(day).weekday() < 5
    )
    universe = PersonalResolvedUniverseMembership(
        period_start=start,
        period_end=end,
        decision_memberships=tuple(
            (day, ("1301", "1302", "1303", "1304")) for day in sessions
        ),
        rule_id=selector.rule_id,
        rule_version=selector.rule_version,
        rule_digest=selector.rule_digest,
    )
    spec = build_factor_rank_strategy_spec(
        strategy_id="personal_test_fixed_short_financing",
        legs=(
            FactorLeg(
                feature=FeatureRef(
                    id="retrospective_price_ratio",
                    version="1.0.0",
                    params={
                        "mode": "return_ratio",
                        "short_n": 2,
                        "long_n": 3,
                    },
                ),
                weight=1.0,
                direction="high_good",
            ),
        ),
        hold_days=1,
        group="market",
        long_frac=0.25,
        short_frac=0.25,
        allow_short=True,
        min_eligible_ratio=1.0,
        min_eligible_count=4,
        min_group_count=2,
        rationale="Deterministic fixture long-short financing sensitivity.",
    )
    output_root = tmp_path / "short-financing"
    evidence, _daily, _dates_used, paper_result = _run_one(
        PersonalPaperExecutionService(),
        spec,
        db_path=source,
        snapshot_id=data_snapshot_id(source),
        universe=universe,
        period=(start, end),
        cost_bps=10.0,
        lookback_days=3,
        output_root=output_root,
        max_drawdown=1.0,
        short_financing_annual_rate=(
            PERSONAL_SHORT_FINANCING_BASELINE_ANNUAL_RATE
        ),
    )
    financing = evidence["short_financing"]
    assert financing["formula_version"]
    assert financing["modelled_assumption"] is True
    assert financing["borrow_evidence"] is False
    assert financing["gap_sessions"] == 0
    assert evidence["cost_bps"] == 10.0
    assert PERSONAL_SHORT_FINANCING_SESSIONS_PER_YEAR == 245
    financing_trades = [
        trade
        for trade in paper_result.trades
        if trade.get("side") == "short_financing"
    ]
    assert financing_trades
    assert financing_trades[0]["cost"] == pytest.approx(
        financing_trades[0]["short_notional"]
        * PERSONAL_SHORT_FINANCING_BASELINE_ANNUAL_RATE
        / 245
    )

    runs_by_rate: dict[float, list[dict]] = {}
    daily_by_rate: dict[float, list[float]] = {}
    dates_by_rate: dict[float, list[str]] = {}
    for rate in PERSONAL_SHORT_FINANCING_ANNUAL_RATES:
        derived, daily, dates_used = _fixed_position_short_financing_evidence(
            paper_result,
            period=(start, end),
            starting_capital=1_000_000.0,
            annual_rate=rate,
        )
        assert derived["formula_version"]
        assert derived["sessions_per_year"] == 245
        assert derived["baseline_run_id"] == paper_result.run_id
        assert derived["position_trace"] == "fixed_to_observed_3pct_baseline"
        assert derived["execution"] == "derived_non_executable"
        assert derived["lifecycle"] == "DRAFT"
        assert derived["derived_artifacts_emitted"] is False
        assert derived["short_financing_cost_amount"] == pytest.approx(
            sum(float(trade["short_notional"]) for trade in financing_trades)
            * rate
            / 245
        )
        if rate == PERSONAL_SHORT_FINANCING_BASELINE_ANNUAL_RATE:
            assert derived["performance"] == evidence["performance"]
        runs_by_rate[rate] = [derived]
        daily_by_rate[rate] = daily
        dates_by_rate[rate] = dates_used

    assert PERSONAL_SHORT_FINANCING_BASELINE_ANNUAL_RATE == 0.03
    trace_digests = {
        runs_by_rate[rate][0]["trace_digest"]
        for rate in PERSONAL_SHORT_FINANCING_ANNUAL_RATES
    }
    assert trace_digests == {financing["trace_digest"]}
    returns = [
        runs_by_rate[rate][0]["performance"]["total_return_net"]
        for rate in PERSONAL_SHORT_FINANCING_ANNUAL_RATES
    ]
    financing_costs = [
        runs_by_rate[rate][0]["short_financing_cost_amount"]
        for rate in PERSONAL_SHORT_FINANCING_ANNUAL_RATES
    ]
    assert returns[0] > returns[1] > returns[2]
    assert financing_costs[0] == 0.0
    assert financing_costs[0] < financing_costs[1] < financing_costs[2]
    assert len(tuple((output_root / "paper").glob("*.json"))) == 1
    assert len(tuple((output_root / "risk").glob("*.json"))) == 1
    sensitivity = _short_financing_sensitivity_document(
        runs_by_rate,
        daily_by_rate,
        dates_by_rate,
    )
    assert sensitivity["caller_tunable"] is False
    assert sensitivity["higher_rate_net_return_nonincreasing"] is True
    assert [result["annual_rate"] for result in sensitivity["results"]] == [
        0.0,
        0.03,
        0.10,
    ]
    assert all(
        result["performance"]["stitched_performance"]["schema_version"]
        == "personal-performance/v1"
        for result in sensitivity["results"]
    )
    assert all(
        result["performance"]["stitched_performance"]["fill_count"] > 0
        for result in sensitivity["results"]
    )


def test_continuous_base_sleeve_is_content_addressed_and_not_a_candidate(
    personal_db: tuple[Path, str, str], tmp_path: Path
) -> None:
    source, start, end = personal_db
    universe, period = _prepared_frame_case(source, start, end)
    selector = personal_universe_selector("topix_all")
    cohort = get_research_cohort("sector-relative-ls-v1")
    cohort_document = cohort.to_dict()
    cohort_ref = {
        "registry_version": cohort_document["version"],
        "cohort_id": cohort.cohort_id,
        "cohort_digest": cohort_document["cohort_digest"],
    }
    specs = tuple(
        personal_specs_for_cohort("sector-relative-ls-v1", universe_id="topix_all")
    )
    closures = _closures(
        specs,
        start=period[0],
        end=period[1],
        policy=_policy(),
        universe_selector=selector,
        cohort_ref=cohort_ref,
    )
    spec, closure = next(
        (candidate, dependency)
        for candidate, dependency in zip(specs, closures, strict=True)
        if candidate.strategy_id == BASE_SLEEVE_ID
    )
    snapshot_digest = data_snapshot_id(source)
    output_root = tmp_path / "continuous-base-sleeve"
    output_root.mkdir()
    source_period = (universe.decision_memberships[5][0], period[1])
    source_membership = PersonalResolvedUniverseMembership(
        period_start=source_period[0],
        period_end=source_period[1],
        decision_memberships=tuple(
            (day, codes)
            for day, codes in universe.decision_memberships
            if source_period[0] <= day <= source_period[1]
        ),
        rule_id=universe.rule_id,
        rule_version=universe.rule_version,
        rule_digest=universe.rule_digest,
    )

    reference, artifact_path, artifact_digest = (
        _write_continuous_base_sleeve_artifact(
            PersonalPaperExecutionService(),
            spec,
            closure,
            snapshot=SimpleNamespace(
                db_path=source,
                snapshot_id=snapshot_digest,
                logical_data_snapshot_id=snapshot_digest,
            ),
            universe=universe,
            source_period=source_period,
            output_root=output_root,
            cohort_digest=str(cohort_document["cohort_digest"]),
        )
    )

    assert artifact_path.is_file()
    assert artifact_digest == "sha256:" + hashlib.sha256(
        artifact_path.read_bytes()
    ).hexdigest()
    assert artifact_path.name == f"{artifact_digest[7:]}.json"
    assert reference["archive_member"] == artifact_path.relative_to(
        output_root
    ).as_posix()
    assert reference["candidate_count_contribution"] == 0
    assert reference["ranking_role"] == "NON_CANDIDATE_NOT_RANKED"
    document = json.loads(artifact_path.read_text(encoding="utf-8"))
    validate_personal_base_sleeve_artifact(document)
    assert document["schema_version"] == PERSONAL_BASE_SLEEVE_ARTIFACT_SCHEMA
    assert document["source_run"]["execution_mode"] == "next_close"
    assert document["source_run"]["stock_one_way_cost_bps"] == 10.0
    assert document["source_run"]["short_financing_annual_rate"] == 0.03
    assert document["source_run"]["terminal_positions"] == (
        "NOT_FORCE_LIQUIDATED_BY_SOURCE_RUN"
    )
    assert document["wrapper_entry_cost_applied_to_source"] is False
    assert document["wrapper_liquidation_cost_applied_to_source"] is False
    assert document["universe"]["resolved_membership_digest"] == (
        source_membership.resolved_membership_digest
    )
    assert document["universe"]["resolved_membership_digest"] != (
        universe.resolved_membership_digest
    )
    assert document["lifecycle"] == "DRAFT"
    assert document["go"] is False
    assert document["automatic_promotion"] is False
    assert document["live_orders_enabled"] is False
    assert len(document["daily_path"]) == len(source_membership.decision_memberships)
    inconsistent = json.loads(json.dumps(document))
    inconsistent["daily_path"][0]["base_sleeve_return"] += 0.01
    with pytest.raises(ValueError, match="NAV and return are inconsistent"):
        validate_personal_base_sleeve_artifact(inconsistent)
    outside_period = json.loads(json.dumps(document))
    outside_period["daily_path"][0]["date"] = "2000-01-01"
    with pytest.raises(ValueError, match="outside its period"):
        validate_personal_base_sleeve_artifact(outside_period)
    truncated = json.loads(json.dumps(document))
    truncated["daily_path"].pop(len(truncated["daily_path"]) // 2)
    with pytest.raises(ValueError, match="source session count"):
        validate_personal_base_sleeve_artifact(truncated)


def test_exact_four_backtest_budget_adds_only_one_base_source_run(
    personal_db: tuple[Path, str, str], tmp_path: Path
) -> None:
    source, start, end = personal_db
    assert PersonalResearchPolicy().validation_folds == 4
    assert PersonalResearchPolicy().max_parallel == 4
    assert 4 * (PersonalResearchPolicy().validation_folds + 2) == 24
    assert PERSONAL_EXACT_FOUR_MAX_BACKTESTS == 25
    request = PersonalResearchRequest(
        source_db=source,
        period_start=start,
        period_end=end,
        output_root=tmp_path / "too-many-backtests",
        cohort_id="diverse-core-v1",
    )

    with pytest.raises(PersonalResearchInputError, match="25-backtest budget"):
        PersonalResearchService(policy=_policy(validation_folds=5)).run(request)


def test_candidate_process_fanout_uses_four_workers_restores_order_and_bounds_failure(
    tmp_path: Path,
) -> None:
    policy = _policy(max_parallel=4)
    specs = personal_specs_for_cohort("diverse-core-v1")
    closures = _closures(
        specs,
        start="2022-01-01",
        end="2026-01-01",
        policy=policy,
        universe_selector=personal_universe_selector("topix_all"),
    )
    tasks = tuple(
        _CandidateProcessTask(
            ordinal=ordinal,
            strategy_spec_document=_canonical_bytes(spec.to_dict()),
            dependency_closure_document=_canonical_bytes(closure.to_dict()),
            snapshot=SimpleNamespace(),
            universe=SimpleNamespace(),
            fold_periods=(("2022-01-01", "2022-12-31"),),
            holdout_period=("2025-01-01", "2026-01-01"),
            output_root=tmp_path,
            policy=policy,
            short_financing_required=False,
        )
        for ordinal, (spec, closure) in enumerate(zip(specs, closures, strict=True))
    )
    started: list[int] = []
    joined: list[int] = []
    closed: list[int] = []

    def bounded_worker(task: _CandidateProcessTask):
        if task.ordinal == 2:
            raise RuntimeError("bounded child failure")
        return _spawn_candidate_document(task)

    class FakeProcess:
        def __init__(self, *, target, args, name, daemon):
            assert name == f"qp-candidate-{args[0].ordinal}"
            assert daemon is False
            self.target = target
            self.args = args
            self.ordinal = args[0].ordinal
            self.exitcode = None
            self.alive = False

        def start(self):
            self.alive = True
            started.append(self.ordinal)

        def join(self, _timeout=None):
            assert started == [0, 1, 2, 3]
            if self.exitcode is None:
                self.target(*self.args)
                self.exitcode = 0
                self.alive = False
                joined.append(self.ordinal)

        def is_alive(self):
            return self.alive

        def terminate(self):
            self.alive = False
            self.exitcode = -15

        def kill(self):
            self.alive = False
            self.exitcode = -9

        def close(self):
            assert not self.alive
            closed.append(self.ordinal)

    class FakeContext:
        def Process(self, **kwargs):
            return FakeProcess(**kwargs)

    candidates, unexpected_errors = _evaluate_candidates_concurrently(
        tasks,
        max_workers=4,
        process_context=FakeContext(),
        candidate_worker=bounded_worker,
    )

    assert started == [0, 1, 2, 3]
    assert joined == [0, 1, 2, 3]
    assert closed == [0, 1, 2, 3]
    assert [candidate["strategy_id"] for candidate in candidates] == [
        spec.strategy_id for spec in specs
    ]
    assert unexpected_errors == 1
    assert candidates[2]["error"] == {
        "type": "RuntimeError",
        "detail": "bounded child failure",
    }


def test_candidate_process_start_failure_reaps_every_started_child(
    tmp_path: Path,
) -> None:
    tasks, _specs, _closures = _candidate_test_wave(tmp_path)
    processes: list[object] = []
    started: list[int] = []
    terminated: list[int] = []
    joined: list[tuple[int, float | None]] = []
    closed: list[int] = []

    class FakeProcess:
        def __init__(self, *, target, args, name, daemon):
            self.ordinal = args[0].ordinal
            self.exitcode = None
            self.alive = False
            processes.append(self)

        def start(self):
            if self.ordinal == 2:
                raise FileNotFoundError(2, "spawn unavailable")
            self.alive = True
            started.append(self.ordinal)

        def join(self, timeout=None):
            joined.append((self.ordinal, timeout))
            if self.exitcode is None and not self.alive:
                self.exitcode = -15

        def is_alive(self):
            return self.alive

        def terminate(self):
            terminated.append(self.ordinal)
            self.alive = False
            self.exitcode = -15

        def kill(self):
            raise AssertionError("terminated fake child must not require kill")

        def close(self):
            assert not self.alive
            closed.append(self.ordinal)

    class FakeContext:
        def Process(self, **kwargs):
            return FakeProcess(**kwargs)

    with pytest.raises(FileNotFoundError, match="spawn unavailable"):
        _evaluate_candidates_concurrently(
            tasks,
            max_workers=4,
            process_context=FakeContext(),
            candidate_worker=_spawn_candidate_document,
        )

    assert started == [0, 1]
    assert terminated == [0, 1]
    assert joined == [(0, 5.0), (1, 5.0), (0, None), (1, None)]
    assert closed == [0, 1, 2, 3]
    assert not list(tmp_path.glob(".candidate-process-results-*"))


def test_candidate_process_fan_in_fails_closed_for_nonzero_missing_and_malformed(
    tmp_path: Path,
) -> None:
    tasks, specs, _closures = _candidate_test_wave(tmp_path)
    started: list[int] = []
    closed: list[int] = []

    class FakeProcess:
        def __init__(self, *, target, args, name, daemon):
            self.target = target
            self.args = args
            self.ordinal = args[0].ordinal
            self.exitcode = None
            self.alive = False

        def start(self):
            self.alive = True
            started.append(self.ordinal)

        def join(self, _timeout=None):
            assert started == [0, 1, 2, 3]
            if self.exitcode is not None:
                return
            if self.ordinal == 0:
                self.target(*self.args)
                self.exitcode = 0
            elif self.ordinal == 1:
                self.exitcode = 0
            elif self.ordinal == 2:
                self.args[1].write_bytes(b"{malformed")
                self.exitcode = 0
            else:
                self.exitcode = 17
            self.alive = False

        def is_alive(self):
            return self.alive

        def terminate(self):
            self.alive = False
            self.exitcode = -15

        def kill(self):
            self.alive = False
            self.exitcode = -9

        def close(self):
            assert not self.alive
            closed.append(self.ordinal)

    class FakeContext:
        def Process(self, **kwargs):
            return FakeProcess(**kwargs)

    candidates, unexpected_errors = _evaluate_candidates_concurrently(
        tasks,
        max_workers=4,
        process_context=FakeContext(),
        candidate_worker=_spawn_candidate_document,
    )

    assert unexpected_errors == 3
    assert closed == [0, 1, 2, 3]
    assert [candidate["strategy_id"] for candidate in candidates] == [
        spec.strategy_id for spec in specs
    ]
    assert candidates[0].get("error") is None
    assert [candidate["error"]["detail"] for candidate in candidates[1:]] == [
        "candidate process result file is missing",
        "candidate process result file is malformed",
        "candidate process exited nonzero (17)",
    ]
    assert not list(tmp_path.glob(".candidate-process-results-*"))


def test_candidate_process_fan_in_rejects_candidate_identity_mismatch(
    tmp_path: Path,
) -> None:
    tasks, specs, _closures = _candidate_test_wave(tmp_path)

    def mismatched_worker(task: _CandidateProcessTask):
        ordinal, candidate = _spawn_candidate_document(task)
        if ordinal == 1:
            candidate["strategy_spec_digest"] = "sha256:" + "0" * 64
        return ordinal, candidate

    class InlineProcess:
        def __init__(self, *, target, args, name, daemon):
            self.target = target
            self.args = args
            self.ordinal = args[0].ordinal
            self.exitcode = None
            self.alive = False

        def start(self):
            self.alive = True

        def join(self, _timeout=None):
            if self.exitcode is None:
                self.target(*self.args)
                if self.ordinal == 2:
                    result_path = self.args[1]
                    envelope = json.loads(result_path.read_bytes())
                    envelope["ordinal"] = 99
                    result_path.write_bytes(_canonical_bytes(envelope))
                self.exitcode = 0
                self.alive = False

        def is_alive(self):
            return self.alive

        def terminate(self):
            self.alive = False
            self.exitcode = -15

        def kill(self):
            self.alive = False
            self.exitcode = -9

        def close(self):
            assert not self.alive

    class InlineContext:
        def Process(self, **kwargs):
            return InlineProcess(**kwargs)

    candidates, unexpected_errors = _evaluate_candidates_concurrently(
        tasks,
        max_workers=4,
        process_context=InlineContext(),
        candidate_worker=mismatched_worker,
    )

    assert unexpected_errors == 2
    assert [candidate["strategy_id"] for candidate in candidates] == [
        spec.strategy_id for spec in specs
    ]
    assert candidates[1]["error"] == {
        "type": "RuntimeError",
        "detail": "candidate process result identity mismatch",
    }
    assert candidates[2]["error"] == {
        "type": "RuntimeError",
        "detail": "candidate process result envelope identity mismatch",
    }


def test_diverse_core_candidate_documents_cross_a_real_spawn_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = _policy(max_parallel=4)
    selector = personal_universe_selector("topix_all")
    specs = personal_specs_for_cohort("diverse-core-v1")
    closures = _closures(
        specs,
        start="2022-01-01",
        end="2026-01-01",
        policy=policy,
        universe_selector=selector,
    )
    closure_digests = tuple(sorted(closure.closure_digest for closure in closures))
    snapshot = PersonalSnapshot(
        snapshot_id="sha256:" + "1" * 64,
        db_path=tmp_path / "snapshot.sqlite",
        manifest_path=tmp_path / "snapshot.json",
        database_sha256="sha256:" + "2" * 64,
        logical_data_snapshot_id="sha256:" + "3" * 64,
        required_datasets=tuple(
            sorted(
                {
                    dataset
                    for closure in closures
                    for dataset in closure.required_datasets
                }
            )
        ),
        period_start="2022-01-01",
        period_end="2026-01-01",
        closure_digests=closure_digests,
    )
    universe = PersonalResolvedUniverseMembership(
        period_start="2022-01-01",
        period_end="2026-01-01",
        decision_memberships=(("2022-01-03", ("1301",)),),
        rule_id=selector.rule_id,
        rule_version=selector.rule_version,
        rule_digest=selector.rule_digest,
    )
    tasks = tuple(
        _CandidateProcessTask(
            ordinal=ordinal,
            strategy_spec_document=_canonical_bytes(spec.to_dict()),
            dependency_closure_document=_canonical_bytes(closure.to_dict()),
            snapshot=snapshot,
            universe=universe,
            fold_periods=(("2022-01-01", "2022-12-31"),),
            holdout_period=("2025-01-01", "2026-01-01"),
            output_root=tmp_path,
            policy=policy,
            short_financing_required=False,
        )
        for ordinal, (spec, closure) in enumerate(zip(specs, closures, strict=True))
    )

    def semlock_unavailable(*_args, **_kwargs):
        raise FileNotFoundError(2, "No such file or directory")

    monkeypatch.setattr(
        multiprocessing.synchronize.SemLock,
        "__init__",
        semlock_unavailable,
    )
    candidates, unexpected_errors = _evaluate_candidates_concurrently(
        tasks,
        max_workers=4,
        candidate_worker=_spawn_candidate_document,
    )

    assert unexpected_errors == 0
    assert [
        (
            candidate["strategy_id"],
            candidate["strategy_spec_digest"],
            candidate["dependency_closure_digest"],
        )
        for candidate in candidates
    ] == [
        (spec.strategy_id, strategy_spec_digest(spec), closure.closure_digest)
        for spec, closure in zip(specs, closures, strict=True)
    ]


@pytest.mark.parametrize("max_parallel", (0, 5))
def test_personal_research_parallelism_is_capped_at_four(max_parallel: int) -> None:
    with pytest.raises(ValueError, match="parallelism"):
        PersonalResearchPolicy(max_parallel=max_parallel)


def test_short_financing_markdown_exposes_monotonicity_failure() -> None:
    text = _md_short_financing(
        {
            "higher_rate_net_return_nonincreasing": False,
            "results": [],
        }
    )

    assert "monotonicity FAIL (validation REJECT)" in text


def test_selected_cohort_id_and_digest_are_bound_to_report(
    personal_db: tuple[Path, str, str], tmp_path: Path
) -> None:
    source, start, end = personal_db
    result = PersonalResearchService(policy=_policy()).run(
        PersonalResearchRequest(
            source_db=source,
            period_start=start,
            period_end=end,
            output_root=tmp_path / "cohort-report",
            cohort_id="diverse-core-v1",
        )
    )
    report = json.loads(result.report_json_path.read_text(encoding="utf-8"))

    assert result.cohort_id == "diverse-core-v1"
    assert result.cohort_digest == report["strategy_cohort"]["cohort_digest"]
    assert report["strategy_cohort"]["registry_version"] == (
        "personal-factor-cohorts/v2"
    )
    assert report["summary"]["candidate_count"] == 4
    assert report["summary"]["analysis_status"] == "NO_ANALYSIS"
    assert report["period"] == {
        "start": start,
        "data_start": start,
        "evaluation_start": None,
        "end": end,
        "warmup_sessions": 253,
    }
    assert all(
        candidate["reasons"] == ["insufficient_post_warmup_sessions"]
        for candidate in report["candidates"]
    )
    assert all(
        closure["plan_digest"].startswith("sha256:")
        for closure in report["dependency_closures"]
    )
    assert "Cohort: `diverse-core-v1`" in result.report_markdown_path.read_text(
        encoding="utf-8"
    )


def test_cohort_history_floor_is_enforced_before_materialization(
    personal_db: tuple[Path, str, str], tmp_path: Path
) -> None:
    source, _start, end = personal_db

    with pytest.raises(PersonalResearchInputError, match="history floor 2008-07-07"):
        PersonalResearchService(policy=_policy()).run(
            PersonalResearchRequest(
                source_db=source,
                period_start="2008-07-06",
                period_end=end,
                output_root=tmp_path / "must-not-materialize",
                cohort_id="price-relative-v1",
            )
        )
    assert not (tmp_path / "must-not-materialize").exists()


def test_cohort_warmup_sessions_are_excluded_from_analysis_periods() -> None:
    days = _dates(date(2024, 1, 1), date(2024, 4, 30))
    universe = PersonalResolvedUniverseMembership(
        period_start=days[0],
        period_end=days[-1],
        decision_memberships=tuple((day, ("1301",)) for day in days),
        rule_id="topix_all_with_fins",
        rule_version="personal-topix-scale-with-fins/v1",
        rule_digest=(
            "sha256:1111111111111111111111111111111111111111111111111111111111111111"
        ),
    )
    policy = _policy(
        validation_folds=1,
        min_fold_sessions=10,
        holdout_months=1,
        min_holdout_sessions=10,
        min_positive_folds=1,
    )

    periods = _periods(
        universe,
        end=date.fromisoformat(days[-1]),
        policy=policy,
        warmup_sessions=5,
    )

    assert periods is not None
    validation, _holdout = periods
    assert validation[0][0] == days[5]
    assert (
        _periods(
            universe,
            end=date.fromisoformat(days[-1]),
            policy=policy,
            warmup_sessions=len(days),
        )
        is None
    )


def test_large_trading_lookback_is_expanded_to_calendar_days() -> None:
    assert _calendar_lookback_days(252) == 534


def test_report_identity_is_independent_of_output_directory(
    personal_db: tuple[Path, str, str], tmp_path: Path
) -> None:
    source, start, end = personal_db
    service = PersonalResearchService(policy=_policy())

    first = service.run(_request(source, start, end, tmp_path / "out-a"))
    second = service.run(_request(source, start, end, tmp_path / "out-b"))

    assert first.snapshot.snapshot_id == second.snapshot.snapshot_id
    assert first.report_id == second.report_id
    first_report = json.loads(first.report_json_path.read_text(encoding="utf-8"))
    paper_path = tmp_path / "out-a" / first_report["candidates"][0]["validation"][
        "runs"
    ][0]["paper_artifact"]
    paper = json.loads(paper_path.read_text(encoding="utf-8"))
    assert "db_path" not in paper["reproducibility"]
    assert "db_path" not in paper["backtest"]["metadata"]


def test_incomplete_observed_bar_breadth_is_no_analysis(
    personal_db: tuple[Path, str, str], tmp_path: Path
) -> None:
    source, start, end = personal_db
    connection = sqlite3.connect(source)
    try:
        connection.execute(
            "DELETE FROM jquants_daily_bars WHERE code='1304' AND date=?", (start,)
        )
        connection.execute(
            "DELETE FROM jquants_records WHERE dataset='equities_bars_daily' "
            "AND substr(event_time,1,10)=? AND json_extract(payload,'$.Code')='1304'",
            (start,),
        )
        connection.commit()
    finally:
        connection.close()

    result = PersonalResearchService(policy=_policy()).run(
        _request(source, start, end, tmp_path / "incomplete")
    )

    assert result.exit_code == 2
    assert result.evaluated_count == 0
    report = json.loads(result.report_json_path.read_text(encoding="utf-8"))
    assert report["summary"]["analysis_status"] == "NO_ANALYSIS"
    assert report["data_quality"]["market_bar_coverage"]["status"] == "FAIL"
    assert report["candidates"][0]["decision"] == "SKIPPED"


def test_partial_financials_cannot_silently_shrink_the_universe(
    personal_db: tuple[Path, str, str], tmp_path: Path
) -> None:
    source, start, end = personal_db
    connection = sqlite3.connect(source)
    try:
        connection.execute(
            "DELETE FROM jquants_records WHERE dataset='fins_summary' "
            "AND json_extract(payload,'$.Code')='1304'"
        )
        connection.commit()
    finally:
        connection.close()

    result = PersonalResearchService(policy=_policy()).run(
        _request(source, start, end, tmp_path / "partial-fins")
    )

    assert result.exit_code == 2
    report = json.loads(result.report_json_path.read_text(encoding="utf-8"))
    breadth = report["data_quality"]["universe_breadth"]
    assert breadth["status"] == "FAIL"
    assert breadth["minimum_daily_ratio"] == 0.75
    assert report["candidates"][0]["reasons"] == [
        "universe_fins_breadth_below_threshold"
    ]


def test_factor_change_is_handled_and_extreme_move_is_advisory(
    personal_db: tuple[Path, str, str], tmp_path: Path
) -> None:
    source, start, end = personal_db
    connection = sqlite3.connect(source)
    try:
        connection.execute(
            "UPDATE jquants_daily_bars SET adjustment_close=close/2 "
            "WHERE code='1304' AND date>='2024-03-01'"
        )
        connection.execute(
            "UPDATE jquants_records SET "
            "payload=json_set(payload,'$.AdjustmentClose',"
            "json_extract(payload,'$.Close')/2),"
            "raw_payload=json_set(raw_payload,'$.AdjustmentClose',"
            "json_extract(raw_payload,'$.Close')/2) "
            "WHERE dataset='equities_bars_daily' "
            "AND json_extract(payload,'$.Code')='1304' "
            "AND json_extract(payload,'$.Date')>='2024-03-01'"
        )
        connection.commit()
    finally:
        connection.close()

    result = PersonalResearchService(policy=_policy()).run(
        _request(source, start, end, tmp_path / "split")
    )

    assert result.exit_code == 0
    report = json.loads(result.report_json_path.read_text(encoding="utf-8"))
    candidate = report["candidates"][0]
    assert "corporate_action_trades" not in candidate["reasons"]
    assert report["data_quality"]["corporate_actions"]["status"] == "WARN"
    assert "1304" in report["data_quality"]["corporate_actions"][
        "affected_codes"
    ]
    corporate_actions = report["data_quality"]["corporate_actions"]
    assert "1304" in corporate_actions["suspicious_jump_codes"]
    assert corporate_actions["extreme_price_move_events"]


def test_large_adjusted_market_move_is_not_a_corporate_action_rejection(
    personal_db: tuple[Path, str, str], tmp_path: Path
) -> None:
    source, start, end = personal_db
    connection = sqlite3.connect(source)
    try:
        connection.execute(
            "UPDATE jquants_daily_bars SET open=open*1.4,high=high*1.4,"
            "low=low*1.4,close=close*1.4,adjustment_close=adjustment_close*1.4 "
            "WHERE code='1304' AND date='2024-03-11'"
        )
        connection.commit()
    finally:
        connection.close()

    result = PersonalResearchService(policy=_policy()).run(
        _request(source, start, end, tmp_path / "large-market-move")
    )

    assert result.exit_code == 0
    report = json.loads(result.report_json_path.read_text(encoding="utf-8"))
    corporate_actions = report["data_quality"]["corporate_actions"]
    candidate = report["candidates"][0]
    assert corporate_actions["status"] == "WARN"
    assert corporate_actions["affected_codes"] == []
    assert "1304" in corporate_actions["suspicious_jump_codes"]
    assert corporate_actions["extreme_price_move_events"]
    assert "corporate_action_trades" not in candidate["reasons"]


def test_constant_back_adjustment_factor_is_not_a_false_split_boundary(
    personal_db: tuple[Path, str, str], tmp_path: Path
) -> None:
    source, start, end = personal_db
    connection = sqlite3.connect(source)
    try:
        connection.execute(
            "UPDATE jquants_daily_bars SET adjustment_close=ROUND(close/3,1) "
            "WHERE code='1304'"
        )
        connection.execute(
            "UPDATE jquants_records SET "
            "payload=json_set(payload,'$.AdjustmentClose',"
            "ROUND(json_extract(payload,'$.Close')/3,1)),"
            "raw_payload=json_set(raw_payload,'$.AdjustmentClose',"
            "ROUND(json_extract(raw_payload,'$.Close')/3,1)) "
            "WHERE dataset='equities_bars_daily' "
            "AND json_extract(payload,'$.Code')='1304'"
        )
        connection.commit()
    finally:
        connection.close()

    result = PersonalResearchService(policy=_policy()).run(
        _request(source, start, end, tmp_path / "constant-adjustment")
    )

    assert result.exit_code == 0
    report = json.loads(result.report_json_path.read_text(encoding="utf-8"))
    assert report["data_quality"]["corporate_actions"]["status"] == "PASS"
    assert report["data_quality"]["corporate_actions"]["affected_codes"] == []


def test_recent_holdout_metrics_are_exploratory_not_a_selection_gate(
    personal_db: tuple[Path, str, str], tmp_path: Path, monkeypatch
) -> None:
    source, start, end = personal_db
    import research.personal_service as module

    calls = 0

    def fake_run_one(*args, **kwargs):
        nonlocal calls
        calls += 1
        recent = calls == 4
        evidence = {
            "total_return_post_cost": -0.1 if recent else 0.1,
            "annualized_sharpe": -1.0 if recent else 1.0,
            "max_drawdown": 0.1,
            "fills": 100,
            "risk_status": "pass",
        }
        returns = (
            [-0.015, -0.005] * 10
            if recent
            else [0.005, 0.015] * 10
        )
        dates = [f"2024-01-{index + 1:02d}" for index in range(len(returns))]
        return evidence, returns, dates, None

    monkeypatch.setattr(module, "_run_one", fake_run_one)
    result = PersonalResearchService(policy=_policy()).run(
        _request(source, start, end, tmp_path / "exploratory")
    )

    report = json.loads(result.report_json_path.read_text(encoding="utf-8"))
    candidate = report["candidates"][0]
    assert candidate["decision"] == "HOLD"
    assert candidate["holdout"]["checks"]["positive_return"] is False
    assert candidate["holdout"]["selection_use"] is False


def test_rejected_ready_state_does_not_block_valid_personal_sync_evidence(
    personal_db: tuple[Path, str, str], tmp_path: Path
) -> None:
    source, start, end = personal_db
    _install_managed_sync_evidence(source)

    result = PersonalResearchService(policy=_policy()).run(
        _request(source, start, end, tmp_path / "managed-valid")
    )

    assert result.exit_code == 0
    report = json.loads(result.report_json_path.read_text(encoding="utf-8"))
    assert report["data_quality"]["source_sync"]["status"] == "PASS"
    assert report["data_quality"]["source_sync"][
        "source_publication_state"
    ] == "REJECTED"


def test_failed_latest_dataset_validation_is_no_analysis(
    personal_db: tuple[Path, str, str], tmp_path: Path
) -> None:
    source, start, end = personal_db
    _install_managed_sync_evidence(source, failing="fins_summary")

    result = PersonalResearchService(policy=_policy()).run(
        _request(source, start, end, tmp_path / "managed-failed")
    )

    assert result.exit_code == 2
    report = json.loads(result.report_json_path.read_text(encoding="utf-8"))
    assert report["summary"]["analysis_status"] == "NO_ANALYSIS"
    assert report["data_quality"]["source_sync"]["status"] == "FAIL"
    assert report["candidates"][0]["reasons"] == [
        "source_sync_evidence_unusable"
    ]


def test_unexpected_candidate_error_keeps_bounded_diagnostic(
    personal_db: tuple[Path, str, str], tmp_path: Path, monkeypatch
) -> None:
    source, start, end = personal_db
    import research.personal_service as module

    def explode(*args, **kwargs):
        raise RuntimeError("useful bounded diagnostic")

    monkeypatch.setattr(module, "_candidate_evaluation", explode)
    result = PersonalResearchService(policy=_policy()).run(
        _request(source, start, end, tmp_path / "unexpected")
    )

    assert result.exit_code == 1
    report = json.loads(result.report_json_path.read_text(encoding="utf-8"))
    error = report["candidates"][0]["error"]
    assert error == {
        "type": "RuntimeError",
        "detail": "useful bounded diagnostic",
    }
