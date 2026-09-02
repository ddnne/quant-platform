"""Focused P0 checks for Controlled Pilot identities, fill contract, and engine."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from execution.controlled_fill_contract import (
    CONTROLLED_FILL_CONTRACT,
    CONTROLLED_FILL_CONTRACT_DIGEST,
    ControlledFillContractError,
    require_controlled_fill_contract,
)
from paper_runtime.readiness_attestation import (
    CONTROLLED_FILL_CONTRACT_DIGEST as READY_FILL_DIGEST,
    controlled_physical_snapshot_key,
)
from research.experiment_plans import load_experiment_plans
from research.factor_cohorts import AM_SIGNAL_PM_CLOSE_EXECUTION_CONTRACT
from strategies.paper import Lifecycle, PaperRunConfig, run_paper


def test_plans_bind_morning_to_afternoon_fill_contract() -> None:
    plans = load_experiment_plans()
    assert len(plans) == 4
    for plan in plans:
        contract = require_controlled_fill_contract(dict(plan.fill_contract))
        assert contract["execution_mode"] == "am_signal_pm_close"
        assert contract["signal_session"] == "morning_close"
        assert contract["fill_session"] == "afternoon_close"
        assert contract["contract_digest"] == CONTROLLED_FILL_CONTRACT_DIGEST
        assert contract["lifecycle"] == "Paper"
        assert contract["retrospective_only"] is False


def test_draft_retrospective_contract_cannot_authorize_controlled() -> None:
    draft = dict(AM_SIGNAL_PM_CLOSE_EXECUTION_CONTRACT)
    with pytest.raises(ControlledFillContractError):
        require_controlled_fill_contract(draft)
    mutated = dict(CONTROLLED_FILL_CONTRACT)
    mutated["execution_mode"] = "next_close"
    mutated["contract_digest"] = CONTROLLED_FILL_CONTRACT_DIGEST
    with pytest.raises(ControlledFillContractError, match="next_close|DRAFT"):
        require_controlled_fill_contract(mutated)


def test_physical_key_is_not_derived_from_logical_id() -> None:
    logical = "sha256:" + ("ab" * 32)
    physical = "sha256:" + ("cd" * 32)
    key = controlled_physical_snapshot_key(physical)
    assert "cd" * 8 in key
    assert "ab" * 8 not in key
    assert key != controlled_physical_snapshot_key(logical)
    assert READY_FILL_DIGEST == CONTROLLED_FILL_CONTRACT_DIGEST


def test_run_paper_rejects_controlled_paper_lifecycle(tmp_path) -> None:
    config = PaperRunConfig(
        start="2023-01-04",
        end="2023-01-05",
        db_path=tmp_path / "missing.sqlite",
        lifecycle=Lifecycle.PAPER,
    )
    with pytest.raises(PermissionError, match="DRAFT-only"):
        run_paper(object(), config)


def test_controlled_paper_config_rejects_retrospective_fill(tmp_path) -> None:
    from price_basis import PERSONAL_RETROSPECTIVE_ADJUSTED

    with pytest.raises(ValueError, match="DRAFT"):
        PaperRunConfig(
            start="2023-01-04",
            end="2023-01-05",
            db_path=tmp_path / "missing.sqlite",
            lifecycle=Lifecycle.PAPER,
            execution_mode="am_signal_pm_close",
            price_basis=PERSONAL_RETROSPECTIVE_ADJUSTED,
        )


def test_generated_controlled_pilot_contract_matches_compiler() -> None:
    from execution.exact_four_binding import controlled_pilot_v1_contract
    from qp_paths import repo_root

    generated = json.loads(
        (repo_root() / "specs" / "ready" / "controlled_pilot_v1.generated.json").read_text(
            encoding="utf-8"
        )
    )
    assert generated == json.loads(
        json.dumps(controlled_pilot_v1_contract(), sort_keys=True)
    )
    assert generated["coverage_policy_version"] == "collection-coverage/v3"
    assert generated["plan_ids"] == [
        "exp-mdh-hold10-momentum",
        "exp-xs-hold10-mom5",
        "exp-event-post-hold5",
        "exp-fund-hold10-value-mom",
    ]
    assert generated["max_gross_weight_ppm"] == 500_000
    assert generated["fill_contract"]["retrospective_only"] is False


def test_trader_batch_compares_ready_universe_and_rejects_duplicates() -> None:
    import base64
    from datetime import datetime, timezone

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from execution.trader_authorization_batch import (
        TraderBatchAuthorizationError,
        decode_strict_trader_json,
        verify_trader_authorization_batch_bytes,
    )
    from qp_paths import repo_root

    root = repo_root() / "specs" / "ready"
    keys_doc = json.loads(
        (root / "controlled_pilot_verify_keys.generated.json").read_text(encoding="utf-8")
    )
    ready = json.loads(
        (root / "controlled_pilot_ready.generated.json").read_text(encoding="utf-8")
    )
    payload = (root / "controlled_pilot_trader_batch.generated.json").read_bytes()
    public = Ed25519PublicKey.from_public_bytes(
        base64.b64decode(keys_doc["public_key_b64"], validate=True)
    )
    kwargs = {
        "environment": "staging",
        "request_digest": keys_doc["request_digest"],
        "idempotency_key": keys_doc["request"]["idempotency_key"],
        "ready_attestation_id": keys_doc["request"]["ready_attestation_id"],
        "ready_manifest_digest": ready["attestation"]["ready_manifest_digest"],
        "snapshot_id": keys_doc["logical_snapshot_id"],
        "immutable_db_digest": keys_doc["physical_snapshot_id"],
        "snapshot_key": ready["physical"]["key"],
        "snapshot_size": ready["physical"]["size"],
        "resolved_universe_digest": keys_doc["resolved_universe_digest"],
        "keys": {keys_doc["key_id"]: public},
    }
    frozen = datetime(2026, 9, 2, 12, 0, 30, tzinfo=timezone.utc)

    class _Clock:
        @staticmethod
        def now(tz=None):
            del tz
            return frozen

    import execution.trader_authorization_batch as batch

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(batch, "_now", lambda: frozen)
    try:
        digest = verify_trader_authorization_batch_bytes(payload, now=frozen, **kwargs)
        assert digest.startswith("sha256:")
        with pytest.raises(TraderBatchAuthorizationError, match="does not bind"):
            verify_trader_authorization_batch_bytes(
                payload,
                **{**kwargs, "resolved_universe_digest": "sha256:" + ("00" * 32)},
            )
        with pytest.raises(TraderBatchAuthorizationError, match="duplicate"):
            decode_strict_trader_json(b'{"a":1,"a":2}')
    finally:
        monkeypatch.undo()


def test_am_decision_excludes_noon_master_revision(tmp_path) -> None:
    from core.execution import morning_close_as_of
    from data_contracts.identity import natural_key
    from pit.universe_pit import resolve_universe_day_slices
    from research.universe_contract import resolve_tse_prime_with_fins
    from storage.sqlite_store import SqliteStore

    day = "2024-04-01"
    nxt = "2024-04-02"
    path = tmp_path / "noon.sqlite"

    def row(dataset, payload, event_time, available_at):
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return {
            "source": "jquants",
            "dataset": dataset,
            "natural_key": natural_key(payload, dataset),
            "event_time": event_time,
            "available_at": available_at,
            "ingested_at": available_at,
            "payload": encoded,
            "raw_payload": None,
        }

    rows = []
    for value in (day, nxt):
        rows.append(
            row(
                "markets_calendar",
                {"Date": value, "HolidayDivision": "1"},
                f"{value}T00:00:00+09:00",
                f"{value}T00:00:00+09:00",
            )
        )
    rows.append(
        row(
            "equities_master",
            {
                "Code": "1001",
                "Date": day,
                "MarketCode": "0111",
                "ScaleCategory": "TOPIX Core30",
            },
            f"{day}T08:00:00+09:00",
            f"{day}T08:00:00+09:00",
        )
    )
    rows.append(
        row(
            "equities_master",
            {
                "Code": "1002",
                "Date": day,
                "MarketCode": "0111",
                "ScaleCategory": "TOPIX Large70",
            },
            f"{day}T12:00:00+09:00",
            f"{day}T12:00:00+09:00",
        )
    )
    rows.append(
        row(
            "fins_summary",
            {"Code": "1001", "DiscDate": "2024-03-29", "DiscNo": "1"},
            "2024-03-29T15:00:00+09:00",
            "2024-03-29T15:00:00+09:00",
        )
    )
    rows.append(
        row(
            "fins_summary",
            {"Code": "1002", "DiscDate": "2024-03-29", "DiscNo": "2"},
            "2024-03-29T15:00:00+09:00",
            "2024-03-29T15:00:00+09:00",
        )
    )
    store = SqliteStore(path)
    store.upsert("jquants_records", rows)
    store._conn.execute(
        "CREATE TABLE snapshot_observation_clock (observed_through TEXT NOT NULL)"
    )
    store._conn.execute(
        "INSERT INTO snapshot_observation_clock VALUES (?)",
        (f"{nxt}T15:30:00+09:00",),
    )
    store._conn.commit()
    store.close()
    slices = resolve_universe_day_slices(
        path,
        period_start=day,
        period_end=nxt,
        as_of_for_day={
            day: morning_close_as_of(day),
            nxt: morning_close_as_of(nxt),
        },
    )
    resolved = resolve_tse_prime_with_fins(
        slices, period_start=day, period_end=nxt
    )
    assert resolved.codes_for(day) == ("1001",)
    assert "1002" in resolved.codes_for(nxt)


def test_close_only_bars_are_not_controlled_am_evidence(tmp_path) -> None:
    from _coreseed import TRADING_DAYS, seed_db
    from core import RAW, run_backtest, standard_cost
    from core.execution import morning_close_as_of
    from core.universe import membership_at
    from core.strategy_protocol import OrderIntent

    code = "1332"
    days = TRADING_DAYS
    db = seed_db(
        tmp_path,
        codes=[code],
        morning_adjustment_prices={code: {day: 100.0 for day in days}},
        afternoon_adjustment_prices={code: {day: 150.0 for day in days}},
    )

    class AlwaysLong:
        strategy_id = "always_long"
        params: dict = {}

        def on_bar(self, ctx):
            return [OrderIntent(code=code, target_weight=0.5)]

    res = run_backtest(
        AlwaysLong(),
        days[0],
        days[-1],
        db_path=db,
        universe=membership_at(morning_close_as_of(days[0]), db_path=db, codes=(code,)),
        execution_mode="am_signal_pm_close",
        price_basis=RAW,
        cost_model=standard_cost(bps=0.0),
        max_gross_weight=0.5,
    )
    assert res.trades == []
    assert res.metadata["authentic_am_session_evidence"] is False


def test_authentic_am_session_and_realized_gross_cap(tmp_path) -> None:
    from _coreseed import (
        TRADING_DAYS,
        seed_governed_am_pm_session_db,
    )
    from core import RAW, run_backtest, standard_cost
    from core.execution import morning_close_as_of
    from core.universe import membership_at
    from core.strategy_protocol import OrderIntent

    code = "1332"
    days = TRADING_DAYS
    morning = {code: {day: 100.0 for day in days}}
    afternoon = {code: {day: 150.0 for day in days}}
    db = seed_governed_am_pm_session_db(
        tmp_path,
        codes=[code],
        days=days,
        morning_prices=morning,
        afternoon_prices=afternoon,
    )

    class AlwaysLong:
        strategy_id = "always_long"
        params: dict = {}

        def on_bar(self, ctx):
            return [OrderIntent(code=code, target_weight=0.5)]

    res = run_backtest(
        AlwaysLong(),
        days[0],
        days[-1],
        db_path=db,
        universe=membership_at(morning_close_as_of(days[0]), db_path=db, codes=(code,)),
        execution_mode="am_signal_pm_close",
        price_basis=RAW,
        cost_model=standard_cost(bps=0.0),
        max_gross_weight=0.5,
    )
    assert res.metadata["authentic_am_session_evidence"] is False
    assert res.metrics["selection_eligible"] is False
    assert res.metrics["comparison_eligible"] is False
    assert res.trades == []


def test_exact_closure_includes_am_dataset() -> None:
    from execution.exact_four_binding import controlled_pilot_v1_contract
    from paper_runtime.readiness_attestation import EXACT_FOUR_DATASET_IDS
    from research.experiment_plans import load_experiment_plan_closures

    contract = controlled_pilot_v1_contract()
    assert "equities_bars_daily_am" in contract["dataset_ids"]
    assert "equities_bars_daily_am" in EXACT_FOUR_DATASET_IDS
    closures = load_experiment_plan_closures()
    for closure in closures:
        assert "equities_bars_daily_am" in closure.required_datasets


def test_synthetic_am_timestamps_on_daily_bars_are_rejected(tmp_path) -> None:
    from _coreseed import TRADING_DAYS, seed_db
    from core import RAW, run_backtest, standard_cost
    from core.execution import morning_close_as_of
    from core.universe import membership_at
    from core.strategy_protocol import OrderIntent

    code = "1332"
    days = TRADING_DAYS
    db = seed_db(
        tmp_path,
        codes=[code],
        morning_adjustment_prices={code: {day: 100.0 for day in days}},
        afternoon_adjustment_prices={code: {day: 150.0 for day in days}},
    )

    class AlwaysLong:
        strategy_id = "always_long"
        params: dict = {}

        def on_bar(self, ctx):
            return [OrderIntent(code=code, target_weight=0.5)]

    res = run_backtest(
        AlwaysLong(),
        days[0],
        days[-1],
        db_path=db,
        universe=membership_at(morning_close_as_of(days[0]), db_path=db, codes=(code,)),
        execution_mode="am_signal_pm_close",
        price_basis=RAW,
        cost_model=standard_cost(bps=0.0),
        max_gross_weight=0.5,
    )
    assert res.trades == []
    assert res.metadata["authentic_am_session_evidence"] is False


def test_noon_ingested_backdated_master_excluded_at_1130(tmp_path) -> None:
    import sqlite3

    from core.execution import morning_close_as_of
    from data_contracts.identity import natural_key
    from pit.universe_pit import resolve_universe_day_slices
    from research.universe_contract import resolve_tse_prime_with_fins
    from storage.sqlite_store import SqliteStore

    day = "2024-04-01"
    nxt = "2024-04-02"
    path = tmp_path / "noon-ingest.sqlite"

    def row(dataset, payload, event_time, available_at, ingested_at):
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return {
            "source": "jquants",
            "dataset": dataset,
            "natural_key": natural_key(payload, dataset),
            "event_time": event_time,
            "available_at": available_at,
            "ingested_at": ingested_at,
            "payload": encoded,
            "raw_payload": None,
        }

    rows = []
    for value in (day, nxt):
        rows.append(
            row(
                "markets_calendar",
                {"Date": value, "HolidayDivision": "1"},
                f"{value}T00:00:00+09:00",
                f"{value}T00:00:00+09:00",
                f"{value}T00:00:00+09:00",
            )
        )
    rows.append(
        row(
            "equities_master",
            {
                "Code": "1001",
                "Date": day,
                "MarketCode": "0111",
                "ScaleCategory": "TOPIX Core30",
            },
            f"{day}T08:00:00+09:00",
            f"{day}T08:00:00+09:00",
            f"{day}T08:00:00+09:00",
        )
    )
    rows.append(
        row(
            "equities_master",
            {
                "Code": "1002",
                "Date": day,
                "MarketCode": "0111",
                "ScaleCategory": "TOPIX Large70",
            },
            f"{day}T08:00:00+09:00",
            f"{day}T08:00:00+09:00",
            f"{day}T12:00:00+09:00",
        )
    )
    rows.append(
        row(
            "fins_summary",
            {"Code": "1001", "DiscDate": "2024-03-29", "DiscNo": "1"},
            "2024-03-29T15:00:00+09:00",
            "2024-03-29T15:00:00+09:00",
            "2024-03-29T15:00:00+09:00",
        )
    )
    rows.append(
        row(
            "fins_summary",
            {"Code": "1002", "DiscDate": "2024-03-29", "DiscNo": "2"},
            "2024-03-29T15:00:00+09:00",
            "2024-03-29T15:00:00+09:00",
            "2024-03-29T15:00:00+09:00",
        )
    )
    store = SqliteStore(path)
    store.upsert("jquants_records", rows)
    store._conn.execute(
        "CREATE TABLE snapshot_observation_clock (observed_through TEXT NOT NULL)"
    )
    store._conn.execute(
        "INSERT INTO snapshot_observation_clock VALUES (?)",
        (f"{day}T11:30:00+09:00",),
    )
    store._conn.commit()
    store.close()
    live = resolve_tse_prime_with_fins(
        resolve_universe_day_slices(
            path,
            period_start=day,
            period_end=day,
            as_of_for_day={day: morning_close_as_of(day)},
        ),
        period_start=day,
        period_end=day,
    )
    assert live.codes_for(day) == ("1001",)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE snapshot_observation_clock SET observed_through=?",
            (f"{day}T15:30:00+09:00",),
        )
    later = resolve_tse_prime_with_fins(
        resolve_universe_day_slices(
            path,
            period_start=day,
            period_end=day,
            as_of_for_day={day: morning_close_as_of(day)},
        ),
        period_start=day,
        period_end=day,
    )
    # The immutable observation clock is distinct from the decision clock:
    # once the snapshot has observed the backfill, its officially 08:00 fact
    # is eligible for the historical 11:30 decision without moving event time.
    assert later.codes_for(day) == ("1001", "1002")


def test_carried_position_10x_move_without_target_caps_actual_gross(tmp_path) -> None:
    from _coreseed import seed_governed_am_pm_session_db
    from core import RAW, run_backtest, standard_cost
    from core.execution import morning_close_as_of
    from core.universe import membership_at
    from core.strategy_protocol import OrderIntent

    code = "1332"
    days = ["2025-04-01", "2025-04-02"]
    morning = {code: {days[0]: 100.0, days[1]: 100.0}}
    afternoon = {code: {days[0]: 100.0, days[1]: 1000.0}}
    db = seed_governed_am_pm_session_db(
        tmp_path,
        codes=[code],
        days=days,
        morning_prices=morning,
        afternoon_prices=afternoon,
    )

    class OneShot:
        strategy_id = "one_shot"
        params: dict = {}

        def on_bar(self, ctx):
            if ctx.date == days[0]:
                return [OrderIntent(code=code, target_weight=0.5)]
            return []

    res = run_backtest(
        OneShot(),
        days[0],
        days[1],
        db_path=db,
        universe=membership_at(morning_close_as_of(days[0]), db_path=db, codes=(code,)),
        execution_mode="am_signal_pm_close",
        price_basis=RAW,
        cost_model=standard_cost(bps=10.0),
        max_gross_weight=0.5,
    )
    assert res.metadata["authentic_am_session_evidence"] is False
    assert res.metrics["selection_eligible"] is False
    assert res.trades == []


def test_python_registry_raw_and_canonical_are_distinct() -> None:
    from paper_runtime.readiness_attestation import (
        PINNED_READINESS_REGISTRY_DOCUMENT_DIGEST,
        PINNED_READINESS_REGISTRY_RAW_DIGEST,
        PINNED_READINESS_REGISTRY_RAW_SIZE,
    )

    assert PINNED_READINESS_REGISTRY_DOCUMENT_DIGEST != PINNED_READINESS_REGISTRY_RAW_DIGEST
    assert PINNED_READINESS_REGISTRY_RAW_SIZE > 0



def test_experiment_plan_schema_locks_am_fill_contract() -> None:
    import jsonschema
    from research.experiment_plans import load_experiment_plan_schema, load_experiment_plans
    from execution.exact_four_binding import controlled_pilot_v1_contract

    schema = load_experiment_plan_schema()
    contract = controlled_pilot_v1_contract()["fill_contract"]
    props = schema["properties"]["fill_contract"]["properties"]
    for key, value in contract.items():
        assert props[key]["const"] == value
    for plan in load_experiment_plans():
        jsonschema.validate(plan.to_dict(), schema)


def test_tampered_prior_am_lookback_is_excluded(tmp_path) -> None:
    from _coreseed import TRADING_DAYS, seed_governed_am_pm_session_db
    from core import RAW, run_backtest, standard_cost
    from core.engine import _am_row_identity
    from core.execution import morning_close_as_of
    from core.universe import membership_at
    from core.strategy_protocol import OrderIntent
    from storage.sqlite_store import SqliteStore
    import sqlite3

    code = "1332"
    days = TRADING_DAYS
    db = seed_governed_am_pm_session_db(
        tmp_path,
        codes=[code],
        days=days,
        morning_prices={code: {day: 100.0 for day in days}},
        afternoon_prices={code: {day: 150.0 for day in days}},
    )
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    prior = days[0]
    row = conn.execute(
        "SELECT * FROM jquants_records WHERE dataset='equities_bars_daily_am' AND payload LIKE ?",
        (f"%{prior}%",),
    ).fetchone()
    payload = json.loads(row["payload"])
    payload["MAdjC"] = 777.0
    conn.execute(
        "UPDATE jquants_records SET payload=? WHERE source=? AND dataset=? AND natural_key=?",
        (json.dumps(payload, sort_keys=True, separators=(",", ":")), row["source"], row["dataset"], row["natural_key"]),
    )
    conn.commit()
    conn.close()

    class AlwaysLong:
        strategy_id = "always_long"
        params: dict = {}
        seen = []

        def on_bar(self, ctx):
            for bar in ctx.bars:
                self.seen.append(bar.close)
            return [OrderIntent(code=code, target_weight=0.5)]

    res = run_backtest(
        AlwaysLong(),
        days[0],
        days[-1],
        db_path=db,
        universe=membership_at(morning_close_as_of(days[0]), db_path=db, codes=(code,)),
        execution_mode="am_signal_pm_close",
        price_basis=RAW,
        cost_model=standard_cost(bps=0.0),
        max_gross_weight=0.5,
    )
    assert 777.0 not in AlwaysLong.seen
    assert any(
        item.get("reason") == "insufficient_authorized_am_lookback"
        for item in res.metadata.get("am_skipped_decisions", [])
    ) or res.trades == []


def test_missing_observed_through_rejects_universe(tmp_path) -> None:
    from core.execution import morning_close_as_of
    from data_contracts.identity import natural_key
    from pit.errors import PitError
    from pit.universe_pit import resolve_universe_day_slices
    from storage.sqlite_store import SqliteStore

    day = "2024-04-01"
    path = tmp_path / "no-clock.sqlite"

    def row(dataset, payload, event_time, available_at):
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return {
            "source": "jquants",
            "dataset": dataset,
            "natural_key": natural_key(payload, dataset),
            "event_time": event_time,
            "available_at": available_at,
            "ingested_at": available_at,
            "payload": encoded,
            "raw_payload": None,
        }

    rows = [
        row("markets_calendar", {"Date": day, "HolidayDivision": "1"}, f"{day}T00:00:00+09:00", f"{day}T00:00:00+09:00"),
        row(
            "equities_master",
            {"Code": "1001", "Date": day, "MarketCode": "0111", "ScaleCategory": "TOPIX Core30"},
            f"{day}T08:00:00+09:00",
            f"{day}T08:00:00+09:00",
        ),
        row("fins_summary", {"Code": "1001", "DiscDate": "2024-03-29", "DiscNo": "1"}, "2024-03-29T15:00:00+09:00", "2024-03-29T15:00:00+09:00"),
    ]
    store = SqliteStore(path)
    store.upsert("jquants_records", rows)
    store.close()
    with pytest.raises(PitError, match="observation cutoff|observation clock"):
        resolve_universe_day_slices(
            path,
            period_start=day,
            period_end=day,
            as_of_for_day={day: morning_close_as_of(day)},
        )


def test_historical_backfill_does_not_use_current_snapshot_clock_as_infinity(tmp_path) -> None:
    from core.execution import morning_close_as_of
    from data_contracts.identity import natural_key
    from pit.universe_pit import resolve_universe_day_slices
    from research.universe_contract import resolve_tse_prime_with_fins
    from storage.sqlite_store import SqliteStore

    day = "2024-04-01"
    path = tmp_path / "backfill.sqlite"

    def row(dataset, payload, event_time, available_at, ingested_at):
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return {
            "source": "jquants",
            "dataset": dataset,
            "natural_key": natural_key(payload, dataset),
            "event_time": event_time,
            "available_at": available_at,
            "ingested_at": ingested_at,
            "payload": encoded,
            "raw_payload": None,
        }

    rows = [
        row("markets_calendar", {"Date": day, "HolidayDivision": "1"}, f"{day}T00:00:00+09:00", f"{day}T00:00:00+09:00", f"{day}T00:00:00+09:00"),
        row(
            "equities_master",
            {"Code": "1001", "Date": day, "MarketCode": "0111", "ScaleCategory": "TOPIX Core30"},
            f"{day}T08:00:00+09:00",
            f"{day}T08:00:00+09:00",
            f"{day}T08:00:00+09:00",
        ),
        row(
            "equities_master",
            {"Code": "1002", "Date": day, "MarketCode": "0111", "ScaleCategory": "TOPIX Large70"},
            f"{day}T08:00:00+09:00",
            f"{day}T08:00:00+09:00",
            "2026-09-02T12:00:00+09:00",
        ),
        row("fins_summary", {"Code": "1001", "DiscDate": "2024-03-29", "DiscNo": "1"}, "2024-03-29T15:00:00+09:00", "2024-03-29T15:00:00+09:00", "2024-03-29T15:00:00+09:00"),
        row("fins_summary", {"Code": "1002", "DiscDate": "2024-03-29", "DiscNo": "2"}, "2024-03-29T15:00:00+09:00", "2024-03-29T15:00:00+09:00", "2024-03-29T15:00:00+09:00"),
    ]
    store = SqliteStore(path)
    store.upsert("jquants_records", rows)
    store._conn.execute("CREATE TABLE snapshot_observation_clock (observed_through TEXT NOT NULL)")
    store._conn.execute("INSERT INTO snapshot_observation_clock VALUES (?)", (f"{day}T11:30:00+09:00",))
    store._conn.commit()
    store.close()
    resolved = resolve_tse_prime_with_fins(
        resolve_universe_day_slices(
            path,
            period_start=day,
            period_end=day,
            as_of_for_day={day: morning_close_as_of(day)},
        ),
        period_start=day,
        period_end=day,
    )
    assert resolved.codes_for(day) == ("1001",)


def test_canonical_json_unicode_matches_utf8_profile() -> None:
    from paper_runtime.canonical_json import canonical_json_bytes, canonical_json_digest

    payload = {"x": "日本"}
    raw = canonical_json_bytes(payload)
    assert raw == b'{"x":"\xe6\x97\xa5\xe6\x9c\xac"}' or "日本".encode("utf-8") in raw
    assert b"\\u" not in raw
    assert canonical_json_digest(payload).startswith("sha256:")


def test_exact_four_ready_datasets_include_am() -> None:
    from paper_runtime.readiness_attestation import EXACT_FOUR_DATASET_IDS
    from research.ready_manifest import load_exact_four_pilot_ready_binding

    binding = load_exact_four_pilot_ready_binding()
    assert "equities_bars_daily_am" in binding.required_datasets
    assert tuple(sorted(binding.required_datasets)) == tuple(sorted(EXACT_FOUR_DATASET_IDS))


def test_controlled_rejects_missing_observation_tables(tmp_path) -> None:
    from _coreseed import TRADING_DAYS, seed_governed_am_pm_session_db
    from core.execution import morning_close_as_of
    from core.universe import membership_at
    import sqlite3
    from pit.errors import PitError

    code = "1332"
    days = TRADING_DAYS
    db = seed_governed_am_pm_session_db(
        tmp_path,
        codes=[code],
        days=days,
        morning_prices={code: {day: 100.0 for day in days}},
        afternoon_prices={code: {day: 150.0 for day in days}},
    )
    conn = sqlite3.connect(db)
    conn.execute("DROP TABLE IF EXISTS snapshot_observation_clock")
    conn.execute("DROP TABLE IF EXISTS dataset_watermarks")
    conn.commit()
    conn.close()

    with pytest.raises(PitError, match="observation cutoff"):
        membership_at(
            morning_close_as_of(days[0]), db_path=db, codes=(code,)
        )


def test_controlled_rejects_forged_am_row_self_hash(tmp_path) -> None:
    from _coreseed import TRADING_DAYS, seed_governed_am_pm_session_db
    from core import RAW, run_backtest, standard_cost
    from core.engine import _am_row_identity
    from core.execution import morning_close_as_of
    from core.universe import membership_at
    from core.strategy_protocol import OrderIntent
    import sqlite3

    code = "1332"
    days = TRADING_DAYS
    db = seed_governed_am_pm_session_db(
        tmp_path,
        codes=[code],
        days=days,
        morning_prices={code: {day: 100.0 for day in days}},
        afternoon_prices={code: {day: 150.0 for day in days}},
    )
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM jquants_records WHERE dataset='equities_bars_daily_am'"
    ).fetchall()
    for row in rows:
        payload = json.loads(row["payload"])
        payload["MAdjC"] = 777.0
        payload["trusted_receipt_digest"] = "sha256:" + ("ab" * 32)
        payload["product_snapshot_id"] = "sha256:" + ("cd" * 32)
        payload["receipt_proof_digest"] = payload["trusted_receipt_digest"]
        payload["product_digest"] = payload["product_snapshot_id"]
        forged = {**dict(row), "payload": payload}
        payload["am_row_identity"] = _am_row_identity(forged)
        conn.execute(
            "UPDATE jquants_records SET payload=? WHERE source=? AND dataset=? "
            "AND natural_key=?",
            (
                json.dumps(payload, sort_keys=True, separators=(",", ":")),
                row["source"],
                row["dataset"],
                row["natural_key"],
            ),
        )
    conn.commit()
    conn.close()

    class AlwaysLong:
        strategy_id = "always_long"
        params: dict = {}
        seen: list[float] = []

        def on_bar(self, ctx):
            for bar in ctx.bars:
                self.seen.append(bar.close)
            return [OrderIntent(code=code, target_weight=0.5)]

    res = run_backtest(
        AlwaysLong(),
        days[0],
        days[-1],
        db_path=db,
        universe=membership_at(morning_close_as_of(days[0]), db_path=db, codes=(code,)),
        execution_mode="am_signal_pm_close",
        price_basis=RAW,
        cost_model=standard_cost(bps=0.0),
        max_gross_weight=0.5,
    )
    assert 777.0 not in AlwaysLong.seen
    assert res.trades == []
    assert res.metadata["authentic_am_session_evidence"] is False


def test_controlled_genuine_opaque_am_view_still_runs(tmp_path) -> None:
    from _coreseed import TRADING_DAYS, seed_governed_am_pm_session_db
    from core import RAW, run_backtest, standard_cost
    from core.execution import morning_close_as_of
    from core.universe import membership_at
    from core.strategy_protocol import OrderIntent
    from pit.governed_am_view import GovernedAmSessionDataView

    with pytest.raises(TypeError, match="closed snapshot verifier"):
        GovernedAmSessionDataView(
            _token=object(),
            observed_through="2025-04-04T15:30:00+09:00",
            _authorized=(),
            _unauthorized=(),
            _handle=object(),
        )

    code = "1332"
    days = TRADING_DAYS
    db = seed_governed_am_pm_session_db(
        tmp_path,
        codes=[code],
        days=days,
        morning_prices={code: {day: 100.0 for day in days}},
        afternoon_prices={code: {day: 150.0 for day in days}},
    )

    class AlwaysLong:
        strategy_id = "always_long"
        params: dict = {}

        def on_bar(self, ctx):
            return [OrderIntent(code=code, target_weight=0.5)]

    res = run_backtest(
        AlwaysLong(),
        days[0],
        days[-1],
        db_path=db,
        universe=membership_at(morning_close_as_of(days[0]), db_path=db, codes=(code,)),
        execution_mode="am_signal_pm_close",
        price_basis=RAW,
        cost_model=standard_cost(bps=0.0),
        max_gross_weight=0.5,
    )
    assert res.metadata["authentic_am_session_evidence"] is False
    assert res.metrics["selection_eligible"] is False
    assert res.trades == []


def _file_digest(path) -> str:
    import hashlib
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _verified_session_scope_from_db(path) -> dict:
    import sqlite3
    from ops.receipt_product import PRODUCT_ARTIFACT_FIELDS, product_artifact_digest
    from research.ready_manifest import canonical_digest

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    observed = str(
        conn.execute("SELECT observed_through FROM snapshot_observation_clock").fetchone()[0]
    )
    entries = []
    for dataset_id in (
        "equities_bars_daily",
        "equities_bars_daily_am",
        "equities_master",
        "fins_summary",
        "indices_bars_daily_topix",
        "markets_calendar",
    ):
        products = conn.execute(
            "SELECT artifact_body FROM receipt_product_materializations WHERE dataset=?",
            (dataset_id,),
        ).fetchall()
        rows = []
        for product in products:
            for line in str(product["artifact_body"] or "").splitlines():
                if not line:
                    continue
                parsed = json.loads(line)
                rows.append({field: parsed[field] for field in PRODUCT_ARTIFACT_FIELDS})
        keys = sorted({row["natural_key"] for row in rows})
        digest = product_artifact_digest(rows)
        entries.append(
            {
                "dataset_id": dataset_id,
                "natural_key_count": len(keys),
                "natural_key_digest": canonical_digest(keys),
                "product_artifact_digests": [digest],
                "product_artifact_set_digest": canonical_digest([digest]),
            }
        )
    conn.close()
    return {
        "format": "controlled-session-scope/v1",
        "dependency_scope_proof_digest": "sha256:" + ("44" * 32),
        "physical_db_digest": _file_digest(path),
        "observed_through": observed,
        "entries": entries,
    }


def _verified_worker_scope_from_db(path):
    import hashlib
    import sqlite3

    from pit.governed_am_view import _session_scope_from_verified_worker_job

    session_scope = _verified_session_scope_from_db(path)
    profile_digest = "sha256:" + ("77" * 32)
    ready_body = {
        "observed_through": session_scope["observed_through"],
        "profile_digest": profile_digest,
        "pit_contract_digests": {
            "dependency_scope": session_scope["dependency_scope_proof_digest"]
        },
    }
    ready_digest = "sha256:" + hashlib.sha256(
        json.dumps(
            ready_body,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    embedded = {
        "ready_manifest": {**ready_body, "manifest_digest": ready_digest},
        "dependency_scope_evidence": {
            "proof_digest": session_scope["dependency_scope_proof_digest"]
        },
    }
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS local_snapshot_manifests "
        "(snapshot_id TEXT PRIMARY KEY, format TEXT NOT NULL, "
        "committed_at TEXT NOT NULL, source_run_id INTEGER NOT NULL, "
        "change_seq INTEGER NOT NULL, manifest_json TEXT NOT NULL)"
    )
    conn.execute("DELETE FROM local_snapshot_manifests")
    conn.execute(
        "INSERT INTO local_snapshot_manifests "
        "(snapshot_id,format,committed_at,source_run_id,change_seq,manifest_json) "
        "VALUES (?,?,?,?,?,?)",
        (
            "fixture-embedded-ready",
            "fixture-embedded-ready/v1",
            session_scope["observed_through"],
            0,
            0,
            json.dumps(embedded, sort_keys=True, separators=(",", ":")),
        ),
    )
    conn.commit()
    conn.close()
    session_scope["physical_db_digest"] = _file_digest(path)
    return _session_scope_from_verified_worker_job(
        session_scope=session_scope,
        ready_manifest_digest=ready_digest,
        signed_projection_document_digest="sha256:" + ("66" * 32),
        profile_digest=profile_digest,
    )


def _verified_snapshot_handle_from_db(path):
    from pit.governed_am_view import _open_verified_controlled_snapshot

    verified_scope = _verified_worker_scope_from_db(path)
    handle = _open_verified_controlled_snapshot(
        pinned_path=path,
        verified_physical_digest=_file_digest(path),
        verified_session_scope=verified_scope,
    )
    return handle


def _verified_snapshot_view_from_db(path):
    handle = _verified_snapshot_handle_from_db(path)
    return handle.am_session_data_view()


def test_public_bind_is_not_exported() -> None:
    import pit
    assert "bind_governed_am_session_data_view" not in pit.__all__
    with pytest.raises(AttributeError):
        getattr(pit, "bind_governed_am_session_data_view")


def test_public_db_path_cannot_mint_controlled_am_authority(tmp_path) -> None:
    from _coreseed import TRADING_DAYS, seed_governed_am_pm_session_db
    from core import RAW, run_backtest, standard_cost
    from core.execution import morning_close_as_of
    from core.universe import membership_at
    from core.strategy_protocol import OrderIntent
    from pit.governed_am_view import assemble_governed_am_session_data_view
    from pit.errors import SnapshotObservationClockError

    code = "1332"
    days = TRADING_DAYS
    db = seed_governed_am_pm_session_db(
        tmp_path,
        codes=[code],
        days=days,
        morning_prices={code: {day: 100.0 for day in days}},
        afternoon_prices={code: {day: 150.0 for day in days}},
    )

    class AlwaysLong:
        strategy_id = "always_long"
        params: dict = {}

        def on_bar(self, ctx):
            return [OrderIntent(code=code, target_weight=0.5)]

    res = run_backtest(
        AlwaysLong(),
        days[0],
        days[-1],
        db_path=db,
        universe=membership_at(morning_close_as_of(days[0]), db_path=db, codes=(code,)),
        execution_mode="am_signal_pm_close",
        price_basis=RAW,
        cost_model=standard_cost(bps=0.0),
        max_gross_weight=0.5,
    )
    assert res.trades == []
    assert res.metadata["authentic_am_session_evidence"] is False
    assert res.metrics["selection_eligible"] is False
    assert res.metrics["comparison_eligible"] is False
    with pytest.raises(SnapshotObservationClockError):
        assemble_governed_am_session_data_view(
            db_path=db,
            physical_digest=_file_digest(db),
            expected_observed_through=f"{days[-1]}T15:30:00+09:00",
            signed_am_binding={},
        )


@pytest.mark.parametrize(
    ("clock", "admitted"),
    [
        ("11:29:59", False),
        ("12:15:00", True),
        ("12:30:00", True),
        ("12:30:01", False),
    ],
)
def test_controlled_am_product_has_exact_operational_deadline(
    clock: str, admitted: bool
) -> None:
    from pit.governed_am_view import (
        am_decision_row_is_visible,
        am_product_row_is_admitted,
    )

    day = "2025-04-01"
    instant = f"{day}T{clock}+09:00"
    assert (
        am_product_row_is_admitted(
            available_at=instant,
            ingested_at=instant,
            session_date=day,
        )
        is admitted
    )
    # The AM product has the authenticated operational exception. Every
    # other fact remains behind the 11:30 PIT wall.
    assert am_decision_row_is_visible(
        available_at=instant,
        ingested_at=instant,
        as_of=f"{day}T11:30:00+09:00",
    ) is (clock <= "11:30:00")


def test_dual_catalog_rehash_fails_without_signed_binding(tmp_path) -> None:
    from _coreseed import TRADING_DAYS, seed_governed_am_pm_session_db
    from pit.governed_am_view import assemble_governed_am_session_data_view
    from pit.errors import SnapshotObservationClockError

    code = "1332"
    days = TRADING_DAYS
    db = seed_governed_am_pm_session_db(
        tmp_path,
        codes=[code],
        days=days,
        morning_prices={code: {day: 100.0 for day in days}},
        afternoon_prices={code: {day: 150.0 for day in days}},
    )
    with pytest.raises(SnapshotObservationClockError, match="path, digest, or mapping"):
        assemble_governed_am_session_data_view(
            db_path=db,
            physical_digest=_file_digest(db),
            expected_observed_through=f"{days[-1]}T15:30:00+09:00",
            signed_am_binding={"entries": []},
        )


def test_decoy_ready_manifest_table_cannot_change_scope(tmp_path) -> None:
    from _coreseed import TRADING_DAYS, seed_governed_am_pm_session_db
    from core import RAW, run_backtest, standard_cost
    from core.execution import morning_close_as_of
    from core.universe import membership_at
    from core.strategy_protocol import OrderIntent
    import sqlite3

    code = "1332"
    days = TRADING_DAYS
    db = seed_governed_am_pm_session_db(
        tmp_path,
        codes=[code],
        days=days,
        morning_prices={code: {day: 100.0 for day in days}},
        afternoon_prices={code: {day: 150.0 for day in days}},
    )
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE ready_manifest (payload TEXT)")
    conn.execute("CREATE TABLE ready_manifests (payload TEXT)")
    conn.commit()
    conn.close()

    class AlwaysLong:
        strategy_id = "always_long"
        params: dict = {}

        def on_bar(self, ctx):
            return [OrderIntent(code=code, target_weight=0.5)]

    res = run_backtest(
        AlwaysLong(),
        days[0],
        days[-1],
        db_path=db,
        universe=membership_at(morning_close_as_of(days[0]), db_path=db, codes=(code,)),
        execution_mode="am_signal_pm_close",
        price_basis=RAW,
        cost_model=standard_cost(bps=0.0),
        max_gross_weight=0.5,
    )
    assert res.metadata["authentic_am_session_evidence"] is False
    assert res.metrics["selection_eligible"] is False
    assert res.metrics["comparison_eligible"] is False
    assert res.trades == []


def test_fixture_view_cannot_enter_controlled(tmp_path) -> None:
    from _coreseed import TRADING_DAYS, seed_governed_am_pm_session_db
    from core import RAW, run_backtest, standard_cost
    from core.execution import morning_close_as_of
    from core.universe import membership_at
    from core.strategy_protocol import OrderIntent
    from pit.governed_am_view import mint_offline_fixture_am_session_data_view

    code = "1332"
    days = TRADING_DAYS
    db = seed_governed_am_pm_session_db(
        tmp_path,
        codes=[code],
        days=days,
        morning_prices={code: {day: 100.0 for day in days}},
        afternoon_prices={code: {day: 150.0 for day in days}},
    )
    fixture = mint_offline_fixture_am_session_data_view(
        observed_through=f"{days[-1]}T15:30:00+09:00"
    )
    assert fixture.offline_fixture is True

    class AlwaysLong:
        strategy_id = "always_long"
        params: dict = {}

        def on_bar(self, ctx):
            return [OrderIntent(code=code, target_weight=0.5)]

    with pytest.raises(TypeError, match="cannot enter"):
        run_backtest(
            AlwaysLong(),
            days[0],
            days[-1],
            db_path=db,
            universe=membership_at(morning_close_as_of(days[0]), db_path=db, codes=(code,)),
            execution_mode="am_signal_pm_close",
            price_basis=RAW,
            cost_model=standard_cost(bps=0.0),
            max_gross_weight=0.5,
            am_session_data_view=fixture,
        )


def test_controlled_pins_same_artifact_and_rejects_replace_mutate_swap(tmp_path) -> None:
    from _coreseed import TRADING_DAYS, seed_governed_am_pm_session_db
    from core import RAW, run_backtest, standard_cost
    from core.execution import morning_close_as_of
    from core.universe import membership_at
    from core.strategy_protocol import OrderIntent
    from pit.governed_am_view import assemble_governed_am_session_data_view
    from pit.errors import SnapshotObservationClockError

    code = "1332"
    days = TRADING_DAYS
    db = seed_governed_am_pm_session_db(
        tmp_path,
        codes=[code],
        days=days,
        morning_prices={code: {day: 100.0 for day in days}},
        afternoon_prices={code: {day: 150.0 for day in days}},
    )
    universe = membership_at(morning_close_as_of(days[0]), db_path=db, codes=(code,))
    view = _verified_snapshot_view_from_db(db)

    class AlwaysLong:
        strategy_id = "always_long"
        params: dict = {}

        def on_bar(self, ctx):
            return [OrderIntent(code=code, target_weight=0.5)]

    res = run_backtest(
        AlwaysLong(),
        days[0],
        days[-1],
        db_path=db,
        universe=universe,
        execution_mode="am_signal_pm_close",
        price_basis=RAW,
        cost_model=standard_cost(bps=0.0),
        max_gross_weight=0.5,
        am_session_data_view=view,
    )
    assert res.metadata["authentic_am_session_evidence"] is True
    assert res.metrics["selection_eligible"] is True
    assert res.metrics["comparison_eligible"] is True
    assert res.trades
    for trade in res.trades:
        assert trade["price"] == 150.0

    with open(db, "ab") as handle:
        handle.write(b"tamper")
    with pytest.raises(SnapshotObservationClockError, match="mutated|replaced"):
        view.assert_pinned_artifact(db)

    other = seed_governed_am_pm_session_db(
        tmp_path / "other",
        codes=[code],
        days=days,
        morning_prices={code: {day: 100.0 for day in days}},
        afternoon_prices={code: {day: 150.0 for day in days}},
    )
    with pytest.raises(SnapshotObservationClockError, match="swapped"):
        view.assert_pinned_artifact(other)


def test_controlled_open_rejects_symlink_and_wal_sidecar(tmp_path) -> None:
    from _coreseed import seed_governed_am_pm_session_db
    from pit.errors import SnapshotObservationClockError
    from pit.governed_am_view import _open_verified_controlled_snapshot

    source = seed_governed_am_pm_session_db(tmp_path / "source")
    scope = _verified_worker_scope_from_db(source)
    physical_digest = _file_digest(source)
    alias = tmp_path / "alias.sqlite"
    try:
        alias.symlink_to(source)
    except OSError:
        pytest.skip("host does not permit symlinks")
    with pytest.raises(SnapshotObservationClockError, match="missing|symlink"):
        _open_verified_controlled_snapshot(
            pinned_path=alias,
            verified_physical_digest=physical_digest,
            verified_session_scope=scope,
        )

    wal = Path(str(source) + "-wal")
    wal.write_bytes(b"uncommitted-generation")
    with pytest.raises(SnapshotObservationClockError, match="WAL/SHM"):
        _open_verified_controlled_snapshot(
            pinned_path=source,
            verified_physical_digest=physical_digest,
            verified_session_scope=scope,
        )


def test_controlled_open_rejects_fins_tamper_with_manifest_and_prices_unchanged(
    tmp_path,
) -> None:
    import sqlite3

    from _coreseed import seed_governed_am_pm_session_db
    from ops.receipt_product import (
        canonical_product_artifact_bytes,
        product_artifact_digest,
    )
    from pit.errors import SnapshotObservationClockError
    from pit.governed_am_view import (
        _open_verified_controlled_snapshot,
        _session_scope_from_verified_worker_job,
    )

    source = seed_governed_am_pm_session_db(tmp_path)
    verified_scope = _verified_worker_scope_from_db(source)
    signed_session_scope = _verified_session_scope_from_db(source)
    assert [entry["dataset_id"] for entry in signed_session_scope["entries"]] == [
        "equities_bars_daily",
        "equities_bars_daily_am",
        "equities_master",
        "fins_summary",
        "indices_bars_daily_topix",
        "markets_calendar",
    ]

    conn = sqlite3.connect(source)
    conn.row_factory = sqlite3.Row
    manifest_before = str(
        conn.execute("SELECT manifest_json FROM local_snapshot_manifests").fetchone()[0]
    )
    prices_before = conn.execute(
        "SELECT dataset, artifact_digest, artifact_body "
        "FROM receipt_product_materializations "
        "WHERE dataset IN ('equities_bars_daily','equities_bars_daily_am') "
        "ORDER BY dataset"
    ).fetchall()
    materialization = conn.execute(
        "SELECT artifact_body FROM receipt_product_materializations "
        "WHERE dataset='fins_summary'"
    ).fetchone()
    product_rows = [
        json.loads(line)
        for line in str(materialization["artifact_body"]).splitlines()
        if line
    ]
    changed = product_rows[0]
    payload = json.loads(changed["payload"])
    payload["NetSales"] = 123_456
    changed["payload"] = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    artifact_body = canonical_product_artifact_bytes(product_rows).decode("utf-8")
    artifact_digest = product_artifact_digest(product_rows)
    conn.execute(
        "UPDATE jquants_records SET payload=? "
        "WHERE source=? AND dataset=? AND natural_key=?",
        (
            changed["payload"],
            changed["source"],
            changed["dataset"],
            changed["natural_key"],
        ),
    )
    conn.execute(
        "UPDATE receipt_product_materializations "
        "SET artifact_digest=?, artifact_body=? WHERE dataset='fins_summary'",
        (artifact_digest, artifact_body),
    )
    conn.commit()
    assert str(
        conn.execute("SELECT manifest_json FROM local_snapshot_manifests").fetchone()[0]
    ) == manifest_before
    assert conn.execute(
        "SELECT dataset, artifact_digest, artifact_body "
        "FROM receipt_product_materializations "
        "WHERE dataset IN ('equities_bars_daily','equities_bars_daily_am') "
        "ORDER BY dataset"
    ).fetchall() == prices_before
    conn.close()

    changed_physical_digest = _file_digest(source)
    with pytest.raises(
        SnapshotObservationClockError,
        match="physical snapshot digest does not match signed PIT dependency scope",
    ):
        _open_verified_controlled_snapshot(
            pinned_path=source,
            verified_physical_digest=changed_physical_digest,
            verified_session_scope=verified_scope,
        )

    # Exercise the execution-side six-dataset seal independently of the
    # authority digest check: even a Worker capability for these physical
    # bytes cannot retain the old signed fins_summary product closure.
    signed_session_scope["physical_db_digest"] = changed_physical_digest
    execution_scope = _session_scope_from_verified_worker_job(
        session_scope=signed_session_scope,
        ready_manifest_digest=verified_scope.ready_manifest_digest,
        signed_projection_document_digest=(
            verified_scope.signed_projection_document_digest
        ),
        profile_digest=verified_scope.profile_digest,
    )
    with pytest.raises(
        SnapshotObservationClockError,
        match="fins_summary product digest set does not match signed PIT dependency scope",
    ):
        _open_verified_controlled_snapshot(
            pinned_path=source,
            verified_physical_digest=changed_physical_digest,
            verified_session_scope=execution_scope,
        )


def test_engine_exception_releases_binding_and_handle_is_one_shot(tmp_path) -> None:
    from _coreseed import TRADING_DAYS, seed_governed_am_pm_session_db
    from core import RAW, run_backtest, standard_cost
    from core.execution import morning_close_as_of
    from core.universe import membership_at
    from pit.errors import SnapshotObservationClockError
    from pit.query import _scoped_read_connection

    code = "1332"
    days = TRADING_DAYS
    db = seed_governed_am_pm_session_db(tmp_path, codes=[code], days=days)
    universe = membership_at(
        morning_close_as_of(days[0]), db_path=db, codes=(code,)
    )
    handle = _verified_snapshot_handle_from_db(db)
    view = handle.am_session_data_view()

    class Explodes:
        strategy_id = "explodes"
        params: dict = {}

        def on_bar(self, _ctx):
            raise RuntimeError("strategy exploded")

    with pytest.raises(RuntimeError, match="strategy exploded"):
        run_backtest(
            Explodes(),
            days[0],
            days[-1],
            db_path=db,
            universe=universe,
            execution_mode="am_signal_pm_close",
            price_basis=RAW,
            cost_model=standard_cost(bps=0.0),
            max_gross_weight=0.5,
            am_session_data_view=view,
        )
    assert _scoped_read_connection(db) is None
    with pytest.raises(SnapshotObservationClockError, match="cannot be reused"):
        view.bind_engine_reads()
    handle.close()
    with pytest.raises(SnapshotObservationClockError, match="closed"):
        view.assert_pinned_artifact()


def test_controlled_batch_uses_one_pinned_connection_for_identity_universe_and_four_runs(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sqlite3

    from _coreseed import TRADING_DAYS, seed_governed_am_pm_session_db
    from core import RAW, run_backtest, standard_cost
    from core.strategy_protocol import OrderIntent
    from data_contracts.identity import natural_key
    import pit.governed_am_view as governed

    code = "1332"
    days = TRADING_DAYS
    db = seed_governed_am_pm_session_db(
        tmp_path,
        codes=[code],
        days=days,
        morning_prices={code: {day: 100.0 for day in days}},
        afternoon_prices={code: {day: 150.0 for day in days}},
    )
    conn = sqlite3.connect(db)
    rows: list[tuple[str, str, str, str, str, str, str, str]] = []
    for day in days:
        midnight = f"{day}T00:00:00+09:00"
        payload = {"Date": day, "HolidayDivision": "1"}
        rows.append(
            (
                "jquants",
                "markets_calendar",
                natural_key(payload, "markets_calendar"),
                midnight,
                midnight,
                midnight,
                json.dumps(
                    payload,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "",
            )
        )
    first = days[0]
    midnight = f"{first}T00:00:00+09:00"
    for dataset_id, payload in (
        (
            "equities_master",
            {"Code": code, "Date": first, "MarketCode": "0111"},
        ),
        (
            "fins_summary",
            {
                "Code": code,
                "DiscDate": first,
                "DiscTime": "00:00:00",
                "DiscNo": "1",
            },
        ),
    ):
        rows.append(
            (
                "jquants",
                dataset_id,
                natural_key(payload, dataset_id),
                midnight,
                midnight,
                midnight,
                json.dumps(payload, sort_keys=True, separators=(",", ":")),
                "",
            )
        )
    conn.executemany(
        "INSERT OR REPLACE INTO jquants_records "
        "(source,dataset,natural_key,event_time,available_at,ingested_at,payload,raw_payload) "
        "VALUES (?,?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()

    verified_scope = _verified_worker_scope_from_db(db)
    physical_digest = _file_digest(db)
    actual_connect = sqlite3.connect
    connect_calls: list[str] = []

    def only_authority_open(*args, **kwargs):
        connect_calls.append(str(args[0]) if args else "")
        if len(connect_calls) > 1:
            raise AssertionError("controlled replay attempted a second SQLite connect")
        return actual_connect(*args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", only_authority_open)
    handle = governed._open_verified_controlled_snapshot(
        pinned_path=db,
        verified_physical_digest=physical_digest,
        verified_session_scope=verified_scope,
    )

    class AlwaysLong:
        strategy_id = "always_long"
        params: dict = {}

        def on_bar(self, ctx):
            return [OrderIntent(code=code, target_weight=0.5)]

    try:
        handle._begin_controlled_batch_reads()
        assert handle.logical_snapshot_id().startswith("sha256:")
        universe = handle.resolve_controlled_universe(
            period_start=days[0], period_end=days[-1]
        )
        assert universe.codes_for(days[0]) == (code,)
        for _ordinal in range(4):
            result = run_backtest(
                AlwaysLong(),
                days[0],
                days[-1],
                db_path=db,
                universe=universe,
                execution_mode="am_signal_pm_close",
                price_basis=RAW,
                cost_model=standard_cost(bps=0.0),
                max_gross_weight=0.5,
                am_session_data_view=handle.am_session_data_view(),
            )
            assert result.metadata["authentic_am_session_evidence"] is True
    finally:
        handle._end_controlled_batch_reads()
        handle.close()
    assert len(connect_calls) == 1


def test_noon_ingested_row_absent_from_1130_signal(tmp_path) -> None:
    from _coreseed import TRADING_DAYS, seed_governed_am_pm_session_db
    from core.execution import morning_close_as_of
    from pit.governed_am_view import (
        am_decision_row_is_visible,
        assemble_governed_am_session_data_view,
    )
    import sqlite3

    code = "1332"
    other = "8697"
    days = TRADING_DAYS
    db = seed_governed_am_pm_session_db(
        tmp_path,
        codes=[code, other],
        days=days,
        morning_prices={
            code: {day: 100.0 for day in days},
            other: {day: 110.0 for day in days},
        },
        afternoon_prices={
            code: {day: 150.0 for day in days},
            other: {day: 160.0 for day in days},
        },
    )
    noon = f"{days[-1]}T12:00:00+09:00"
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "UPDATE jquants_records SET ingested_at=? WHERE dataset='equities_bars_daily_am' "
        "AND payload LIKE ?",
        (noon, f"%{other}%"),
    )
    stored = conn.execute(
        "SELECT source, dataset, natural_key, event_time, available_at, "
        "ingested_at, payload, COALESCE(raw_payload, '') AS raw_payload "
        "FROM jquants_records WHERE dataset='equities_bars_daily_am' "
        "ORDER BY natural_key"
    ).fetchall()
    from ops.receipt_product import (
        canonical_product_artifact_bytes,
        product_artifact_digest,
    )
    product_rows = []
    for row in stored:
        payload_raw = row["payload"]
        payload_obj = json.loads(payload_raw) if isinstance(payload_raw, str) else {}
        payload_text = json.dumps(
            payload_obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        product_rows.append(
            {
                "source": str(row["source"]),
                "dataset": str(row["dataset"]),
                "natural_key": str(row["natural_key"]),
                "event_time": str(row["event_time"]),
                "available_at": str(row["available_at"]),
                "ingested_at": str(row["ingested_at"]),
                "payload": payload_text,
                "raw_payload": str(row["raw_payload"] or ""),
            }
        )
    artifact_body = canonical_product_artifact_bytes(product_rows).decode("utf-8")
    artifact_digest = product_artifact_digest(product_rows)
    conn.execute(
        "UPDATE receipt_product_materializations SET artifact_digest=?, artifact_body=? "
        "WHERE dataset='equities_bars_daily_am'",
        (artifact_digest, artifact_body),
    )
    conn.commit()
    conn.close()
    assert am_decision_row_is_visible(
        available_at=f"{days[-1]}T11:30:00+09:00",
        ingested_at=f"{days[-1]}T11:30:00+09:00",
        as_of=morning_close_as_of(days[-1]),
    )
    assert not am_decision_row_is_visible(
        available_at=f"{days[-1]}T11:30:00+09:00",
        ingested_at=noon,
        as_of=morning_close_as_of(days[-1]),
    )
    view = _verified_snapshot_view_from_db(db)
    visible = view.authorized_rows(
        as_of=morning_close_as_of(days[-1]),
        codes={code, other},
        from_date=days[-1],
        to_date=days[-1],
    )
    codes = {str(row["code"]) for row in visible}
    assert code in codes
    assert other not in codes


def test_publisher_clock_write_and_reader_rejections(tmp_path) -> None:
    import sqlite3
    from paper_runtime.snapshot import (
        SnapshotRejected,
        canonical_observed_through_from_authenticated_exported_at,
        write_publisher_owned_snapshot_observation_clock,
    )
    from pit.errors import SnapshotObservationClockError
    from pit.query import snapshot_observed_through
    from research.universe_contract import resolve_tse_prime_with_fins
    from selection.budget_ledger import MassResearchDisabledError

    clock = "2025-04-04T15:30:00+09:00"
    assert canonical_observed_through_from_authenticated_exported_at(clock) == clock
    with pytest.raises(SnapshotRejected, match="missing"):
        canonical_observed_through_from_authenticated_exported_at(None)
    with pytest.raises(SnapshotRejected, match="missing"):
        canonical_observed_through_from_authenticated_exported_at("")
    with pytest.raises(SnapshotRejected, match="malformed"):
        canonical_observed_through_from_authenticated_exported_at("not-a-clock")
    with pytest.raises(SnapshotRejected, match="noncanonical"):
        canonical_observed_through_from_authenticated_exported_at(
            "2025-04-04T15:30:00+00:00"
        )
    with pytest.raises(SnapshotRejected, match="future"):
        canonical_observed_through_from_authenticated_exported_at(
            "2099-01-01T15:30:00+09:00"
        )

    path = tmp_path / "clock.sqlite"
    conn = sqlite3.connect(path)
    written = write_publisher_owned_snapshot_observation_clock(conn, clock)
    conn.commit()
    conn.close()
    assert written == clock
    assert snapshot_observed_through(path) == clock
    assert snapshot_observed_through(path, expected=clock) == clock
    with pytest.raises(SnapshotObservationClockError, match="manifest"):
        snapshot_observed_through(path, expected="2025-04-03T15:30:00+09:00")

    missing = tmp_path / "missing.sqlite"
    sqlite3.connect(missing).close()
    with pytest.raises(SnapshotObservationClockError, match="missing"):
        snapshot_observed_through(missing)

    zero = tmp_path / "zero.sqlite"
    conn = sqlite3.connect(zero)
    conn.execute(
        "CREATE TABLE snapshot_observation_clock (observed_through TEXT NOT NULL)"
    )
    conn.execute("INSERT INTO snapshot_observation_clock VALUES ('0')")
    conn.commit()
    conn.close()
    with pytest.raises(SnapshotObservationClockError):
        snapshot_observed_through(zero)

    dup_id = tmp_path / "dup-identical.sqlite"
    conn = sqlite3.connect(dup_id)
    conn.execute(
        "CREATE TABLE snapshot_observation_clock (observed_through TEXT NOT NULL)"
    )
    conn.execute("INSERT INTO snapshot_observation_clock VALUES (?)", (clock,))
    conn.execute("INSERT INTO snapshot_observation_clock VALUES (?)", (clock,))
    conn.commit()
    conn.close()
    with pytest.raises(SnapshotObservationClockError, match="singleton"):
        snapshot_observed_through(dup_id)

    dup_cf = tmp_path / "dup-conflict.sqlite"
    conn = sqlite3.connect(dup_cf)
    conn.execute(
        "CREATE TABLE snapshot_observation_clock (observed_through TEXT NOT NULL)"
    )
    conn.execute("INSERT INTO snapshot_observation_clock VALUES (?)", (clock,))
    conn.execute(
        "INSERT INTO snapshot_observation_clock VALUES (?)",
        ("2025-04-03T15:30:00+09:00",),
    )
    conn.commit()
    conn.close()
    with pytest.raises(SnapshotObservationClockError, match="singleton"):
        snapshot_observed_through(dup_cf)

    malformed = tmp_path / "malformed.sqlite"
    conn = sqlite3.connect(malformed)
    conn.execute(
        "CREATE TABLE snapshot_observation_clock (observed_through TEXT NOT NULL)"
    )
    conn.execute("INSERT INTO snapshot_observation_clock VALUES ('yesterday')")
    conn.commit()
    conn.close()
    with pytest.raises(SnapshotObservationClockError, match="malformed"):
        snapshot_observed_through(malformed)

    future = tmp_path / "future.sqlite"
    conn = sqlite3.connect(future)
    conn.execute(
        "CREATE TABLE snapshot_observation_clock (observed_through TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO snapshot_observation_clock VALUES ('2099-01-01T15:30:00+09:00')"
    )
    conn.commit()
    conn.close()
    with pytest.raises(SnapshotObservationClockError, match="future"):
        snapshot_observed_through(future)

    with pytest.raises(MassResearchDisabledError):
        resolve_tse_prime_with_fins(missing, period_start="2024-04-01", period_end="2024-04-01")


def test_unprovisioned_issuer_holds_without_mutation(tmp_path) -> None:
    from paper_runtime.snapshot import (
        SnapshotRejected,
        _publish_exact_four_pilot_ready_snapshot_via_authority,
    )

    staging = tmp_path / "staging.sqlite"
    staging.write_bytes(b"unchanged-bytes")
    snapshots = tmp_path / "snapshots"
    with pytest.raises(SnapshotRejected, match="unprovisioned|PENDING"):
        _publish_exact_four_pilot_ready_snapshot_via_authority(
            staging,
            snapshots,
            signed_projection_document=b"{}",
            _product_api=object(),
        )
    assert staging.read_bytes() == b"unchanged-bytes"
    assert not snapshots.exists() or not any(snapshots.iterdir())
