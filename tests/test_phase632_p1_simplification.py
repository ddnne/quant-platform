"""Phase 6.3.2 P1/integration simplifications. Not GO."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from data_contracts.identity import natural_key
from personal_history_compact_support import stamp_compact_manifest
from pit.personal_research_view import (
    OPTION_SIDECAR_MANIFEST_SCHEMA,
    OPTION_SIDECAR_OBJECT_SCHEMA,
    OfflineFixtureDataView,
)
from research.offline.factory import MassFactoryConfig
from research.offline.factory_eval_data import load_batch_data_context
from research.personal_universe import PersonalResolvedUniverseMembership
from selection.budget_ledger import MassResearchDisabledError


def _catalog_db(path: Path, *, observed: str = "2099-01-01T00:00:00+09:00") -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE jquants_records ("
        "source TEXT NOT NULL, dataset TEXT NOT NULL, natural_key TEXT NOT NULL, "
        "event_time TEXT NOT NULL, available_at TEXT NOT NULL, ingested_at TEXT NOT NULL, "
        "payload TEXT, raw_payload TEXT, "
        "PRIMARY KEY (source, dataset, natural_key))"
    )
    con.execute(
        "CREATE TABLE jquants_records_revisions AS SELECT * FROM jquants_records WHERE 0"
    )
    stamp_compact_manifest(
        con, format_name="unmanaged-catalog", observed_through=observed
    )
    return con


def _insert_record(
    con: sqlite3.Connection,
    *,
    dataset: str,
    payload: dict,
    event_time: str,
    available_at: str | None = None,
    ingested_at: str | None = None,
) -> None:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    available = available_at or event_time
    con.execute(
        "INSERT INTO jquants_records "
        "(source, dataset, natural_key, event_time, available_at, ingested_at, "
        "payload, raw_payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "jquants",
            dataset,
            natural_key(payload, dataset),
            event_time,
            available,
            ingested_at or available,
            encoded,
            encoded,
        ),
    )


def _universe(*days: str, codes: tuple[str, ...] = ("1301",)) -> PersonalResolvedUniverseMembership:
    return PersonalResolvedUniverseMembership(
        period_start=days[0],
        period_end=days[-1],
        decision_memberships=tuple((day, codes) for day in days),
        rule_id="topix_all_with_fins",
        rule_version="personal-topix-scale-with-fins/v1",
        rule_digest="sha256:" + "11" * 32,
    )


def test_morning_cutoff_with_only_pm_rows_is_unknown(tmp_path: Path) -> None:
    path = tmp_path / "pm-only.sqlite"
    con = _catalog_db(path)
    con.execute(
        "CREATE TABLE jquants_daily_bars ("
        "source TEXT, code TEXT, date TEXT, event_time TEXT, available_at TEXT, "
        "ingested_at TEXT, close REAL, adjustment_close REAL, volume REAL, "
        "adjustment_volume REAL)"
    )
    for day, close, adj in (("2024-01-04", 100.0, 100.0), ("2024-01-05", 150.0, 150.0)):
        stamp = f"{day}T15:30:00+09:00"
        con.execute(
            "INSERT INTO jquants_daily_bars("
            "source,code,date,event_time,available_at,ingested_at,"
            "close,adjustment_close,volume,adjustment_volume) "
            "VALUES ('jquants','1301',?,?,?,?,?,?,?,?)",
            (day, stamp, stamp, stamp, close, adj, 1000.0, 1000.0),
        )
        payload = {
            "Code": "1301",
            "Date": day,
            "Close": close,
            "AdjustmentClose": adj,
            "Volume": 1000.0,
            "AdjustmentVolume": 1000.0,
        }
        _insert_record(
            con,
            dataset="equities_bars_daily",
            payload=payload,
            event_time=stamp,
        )
    con.commit()
    con.close()
    view = OfflineFixtureDataView.bind(
        path, artifact_root=tmp_path / "art", decision_cutoff="morning_close"
    )
    evidence = view.corporate_action_check(
        universe=_universe("2024-01-04", "2024-01-05"), lookback_days=0
    )
    assert evidence["status"] == "UNKNOWN"
    assert evidence["reason"] == "morning_corporate_action_evidence_unavailable"
    assert evidence["extreme_price_move_events"] == []
    assert evidence["supported_factor_events"] == []


def test_morning_cutoff_uses_governed_am_adjustment_evidence(tmp_path: Path) -> None:
    path = tmp_path / "am-bars.sqlite"
    con = _catalog_db(path)
    rows = (
        ("2024-01-04", 100.0, 100.0, 1000.0, 1000.0),
        ("2024-01-05", 50.0, 100.0, 2000.0, 1000.0),
    )
    for day, close, adj, vol, adj_vol in rows:
        stamp = f"{day}T11:30:00+09:00"
        payload = {
            "Code": "1301",
            "Date": day,
            "MC": close,
            "MAdjC": adj,
            "MVo": vol,
            "MAdjVo": adj_vol,
        }
        _insert_record(
            con,
            dataset="equities_bars_daily_am",
            payload=payload,
            event_time=stamp,
        )
    con.commit()
    con.close()
    view = OfflineFixtureDataView.bind(
        path, artifact_root=tmp_path / "art", decision_cutoff="morning_close"
    )
    evidence = view.corporate_action_check(
        universe=_universe("2024-01-04", "2024-01-05"), lookback_days=0
    )
    assert evidence["status"] == "OBSERVED"
    assert evidence["affected_codes"] == ["1301"]
    assert evidence["supported_factor_events"]
    assert evidence["extreme_price_move_events"] == []
    assert evidence["bar_dataset"] == "equities_bars_daily_am"


def test_am_dual_clock_is_exact_and_dataset_scoped(tmp_path: Path) -> None:
    path = tmp_path / "am-dual-clock.sqlite"
    con = _catalog_db(path)
    for code, acquired in (
        ("1300", "2024-01-05T11:29:59+09:00"),
        ("1301", "2024-01-05T12:15:00+09:00"),
        ("1302", "2024-01-05T12:30:00+09:00"),
        ("1303", "2024-01-05T12:30:01+09:00"),
    ):
        _insert_record(
            con,
            dataset="equities_bars_daily_am",
            payload={
                "Code": code,
                "Date": "2024-01-05",
                "MC": 100.0,
                "MAdjC": 100.0,
                "MVa": 1000.0,
                "MAdjVo": 10.0,
                "Close": 777.0,
                "C": 777.0,
                "AdjC": 888.0,
                "AdjustmentClose": 888.0,
                "Volume": 7777.0,
                "TurnoverValue": 8888.0,
                "AAdjC": 999.0,
            },
            event_time="2024-01-05T11:30:00+09:00",
            available_at=acquired,
            ingested_at=acquired,
        )
    _insert_record(
        con,
        dataset="equities_bars_daily_am",
        payload={"Code": "1304", "Date": "2024-01-05", "MAdjC": 100.0},
        event_time="2024-01-05T11:30:00+09:00",
        available_at="2024-01-05T12:15:00+09:00",
        ingested_at="2024-01-06T09:00:00+09:00",
    )
    late_revision = {
        "Code": "1305",
        "Date": "2024-01-05",
        "MC": 100.0,
        "MAdjC": 200.0,
    }
    _insert_record(
        con,
        dataset="equities_bars_daily_am",
        payload=late_revision,
        event_time="2024-01-05T11:30:00+09:00",
        available_at="2024-01-05T12:15:00+09:00",
        ingested_at="2024-01-06T09:00:00+09:00",
    )
    timely_revision = dict(late_revision, MAdjC=100.0)
    encoded = json.dumps(timely_revision, sort_keys=True, separators=(",", ":"))
    con.execute(
        "INSERT INTO jquants_records_revisions "
        "(source,dataset,natural_key,event_time,available_at,ingested_at,"
        "payload,raw_payload) VALUES (?,?,?,?,?,?,?,?)",
        (
            "jquants",
            "equities_bars_daily_am",
            natural_key(timely_revision, "equities_bars_daily_am"),
            "2024-01-05T11:30:00+09:00",
            "2024-01-05T12:15:00+09:00",
            "2024-01-05T12:15:00+09:00",
            encoded,
            encoded,
        ),
    )
    _insert_record(
        con,
        dataset="fins_summary",
        payload={"Code": "1301", "DiscDate": "2024-01-05", "DiscNo": "1"},
        event_time="2024-01-05T11:00:00+09:00",
        available_at="2024-01-05T11:30:01+09:00",
        ingested_at="2024-01-05T11:30:01+09:00",
    )
    con.commit()
    con.close()
    view = OfflineFixtureDataView.bind(
        path, artifact_root=tmp_path / "dual-art", decision_cutoff="morning_close"
    )

    am_rows = [
        row
        for page in view.iter_decision_pages(
            decision_date="2024-01-05",
            dataset="equities_bars_daily_am",
            codes=("1300", "1301", "1302", "1303", "1304", "1305"),
            start="2024-01-05",
            end="2024-01-05",
        )
        for row in page
    ]
    assert {
        str(row["payload"]["Code"])
        for row in am_rows
    } == {"1301", "1302", "1305"}
    by_code = {str(row["payload"]["Code"]): row for row in am_rows}
    assert all(
        set(by_code[code]["payload"])
        == {"Code", "Date", "MC", "MAdjC", "MVa", "MAdjVo"}
        for code in ("1301", "1302")
    )
    assert set(by_code["1305"]["payload"]) == {"Code", "Date", "MC", "MAdjC"}
    assert all(row["raw_payload"] == row["payload"] for row in am_rows)
    assert next(
        row["payload"]["MAdjC"]
        for row in am_rows
        if row["payload"]["Code"] == "1305"
    ) == 100.0
    non_am = [
        row
        for page in view.iter_decision_pages(
            decision_date="2024-01-05",
            dataset="fins_summary",
            codes=("1301",),
            start="2024-01-05",
            end="2024-01-05",
        )
        for row in page
    ]
    assert non_am == []
    coverage = view.observed_bar_coverage(
        _universe("2024-01-05", codes=("1301", "1302", "1305")),
        minimum_ratio=1.0,
    )
    assert coverage["status"] == "PASS"
    assert coverage["observed_rows"] == 3
    late_coverage = view.observed_bar_coverage(
        _universe("2024-01-05", codes=("1304",)), minimum_ratio=1.0
    )
    assert late_coverage["status"] == "FAIL"
    assert late_coverage["observed_rows"] == 0
    pre_window_coverage = view.observed_bar_coverage(
        _universe("2024-01-05", codes=("1300",)), minimum_ratio=1.0
    )
    assert pre_window_coverage["status"] == "FAIL"
    assert pre_window_coverage["observed_rows"] == 0


def test_morning_corporate_action_requires_end_day_every_code(tmp_path: Path) -> None:
    path = tmp_path / "am-end-day-completeness.sqlite"
    con = _catalog_db(path)
    for day, codes in (
        ("2024-01-04", ("1301", "1302")),
        ("2024-01-05", ("1301",)),
    ):
        for code in codes:
            acquired = f"{day}T12:15:00+09:00"
            _insert_record(
                con,
                dataset="equities_bars_daily_am",
                payload={
                    "Code": code,
                    "Date": day,
                    "MC": 100.0,
                    "MAdjC": 100.0,
                },
                event_time=f"{day}T11:30:00+09:00",
                available_at=acquired,
                ingested_at=acquired,
            )
    con.commit()
    con.close()
    view = OfflineFixtureDataView.bind(
        path, artifact_root=tmp_path / "complete-art", decision_cutoff="morning_close"
    )
    evidence = view.corporate_action_check(
        universe=_universe(
            "2024-01-04", "2024-01-05", codes=("1301", "1302")
        ),
        lookback_days=0,
    )
    assert evidence["status"] == "UNKNOWN"
    assert evidence["reason"] == "morning_decision_date_evidence_incomplete"
    assert evidence["missing_codes"] == ["1302"]


def test_morning_long_names_and_madjc_only_factor_proof_are_explicit(
    tmp_path: Path,
) -> None:
    path = tmp_path / "am-native-evidence.sqlite"
    con = _catalog_db(path)
    for day, adjusted in (("2024-01-04", 100.0), ("2024-01-05", 110.0)):
        acquired = f"{day}T12:15:00+09:00"
        _insert_record(
            con,
            dataset="equities_bars_daily_am",
            payload={
                "Code": "1301",
                "Date": day,
                "MorningClose": 100.0,
                "MorningAdjustmentClose": adjusted,
                "MorningTurnoverValue": 1000.0,
                "MorningAdjustmentVolume": 10.0,
                "AfternoonAdjustmentClose": 999.0,
                "AdjustmentClose": 888.0,
            },
            event_time=f"{day}T11:30:00+09:00",
            available_at=acquired,
            ingested_at=acquired,
        )
    con.commit()
    con.close()
    view = OfflineFixtureDataView.bind(
        path, artifact_root=tmp_path / "long-art", decision_cutoff="morning_close"
    )
    rows = [
        row
        for page in view.iter_decision_pages(
            decision_date="2024-01-05",
            dataset="equities_bars_daily_am",
            codes=("1301",),
            start="2024-01-04",
            end="2024-01-05",
        )
        for row in page
    ]
    assert all("AdjustmentClose" not in row["payload"] for row in rows)
    assert all("AfternoonAdjustmentClose" not in row["payload"] for row in rows)
    evidence = view.corporate_action_check(
        universe=_universe("2024-01-04", "2024-01-05"), lookback_days=0
    )
    assert evidence["status"] == "OBSERVED"
    assert evidence["adjustment_factor_proof"] == "COMPLETE"
    assert evidence["factor_unproven_codes"] == []

    only_path = tmp_path / "am-madjc-only.sqlite"
    con = _catalog_db(only_path)
    for day, adjusted in (("2024-01-04", 100.0), ("2024-01-05", 200.0)):
        acquired = f"{day}T12:15:00+09:00"
        _insert_record(
            con,
            dataset="equities_bars_daily_am",
            payload={"Code": "1301", "Date": day, "MAdjC": adjusted},
            event_time=f"{day}T11:30:00+09:00",
            available_at=acquired,
            ingested_at=acquired,
        )
    con.commit()
    con.close()
    only_view = OfflineFixtureDataView.bind(
        only_path,
        artifact_root=tmp_path / "madjc-only-art",
        decision_cutoff="morning_close",
    )
    advisory = only_view.corporate_action_check(
        universe=_universe("2024-01-04", "2024-01-05"), lookback_days=0
    )
    assert advisory["status"] == "WARN"
    assert advisory["reason"] == (
        "morning_adjustment_factor_unproven_with_extreme_adjusted_move"
    )
    assert advisory["adjustment_factor_proof"] == "INCOMPLETE"
    assert advisory["factor_unproven_codes"] == ["1301"]
    assert advisory["supported_factor_events"] == []
    assert advisory["extreme_price_move_events"]


def test_am_coverage_rejects_pm_only_payload_in_am_dataset(tmp_path: Path) -> None:
    path = tmp_path / "am-pm-poison.sqlite"
    con = _catalog_db(path)
    _insert_record(
        con,
        dataset="equities_bars_daily_am",
        payload={"Code": "1301", "Date": "2024-01-05", "AAdjC": 999.0},
        event_time="2024-01-05T11:30:00+09:00",
        available_at="2024-01-05T12:15:00+09:00",
        ingested_at="2024-01-05T12:15:00+09:00",
    )
    con.commit()
    con.close()
    view = OfflineFixtureDataView.bind(
        path, artifact_root=tmp_path / "poison-art", decision_cutoff="morning_close"
    )
    coverage = view.observed_bar_coverage(
        _universe("2024-01-05"), minimum_ratio=1.0
    )
    assert coverage["status"] == "FAIL"
    assert coverage["observed_rows"] == 0


def test_option_eval_ignores_arbitrary_temp_log_dir(tmp_path: Path) -> None:
    from research.eval_loaders import load_opt225_regime_bundle_for_eval
    from research.options_225_vol_series import (
        DATASET_ID,
        OPTIONS_225_VOL_SERIES_VERSION,
    )

    path = tmp_path / "opt.sqlite"
    con = _catalog_db(path)
    con.commit()
    con.close()
    poison = tmp_path / "poison-log"
    poison.mkdir()
    (poison / "base_vol_series.ndjson").write_text(
        '{"date":"2021-01-04","base_vol":99.0}\n'
    )
    (poison / "atm_iv_series.ndjson").write_text(
        '{"date":"2021-01-04","atm_iv":99.0}\n'
    )
    view = OfflineFixtureDataView.bind(
        path, artifact_root=tmp_path / "art", decision_cutoff="morning_close"
    )
    assert load_opt225_regime_bundle_for_eval(view) is None
    assert view.read_option_sidecar() is None
    assert not hasattr(view, "option_sidecar_ref")

    obj = {
        "schema_version": OPTION_SIDECAR_OBJECT_SCHEMA,
        "dataset": DATASET_ID,
        "version": OPTIONS_225_VOL_SERIES_VERSION,
        "opt225_regime": {
            "dataset": DATASET_ID,
            "version": OPTIONS_225_VOL_SERIES_VERSION,
            "source": {
                "dataset": DATASET_ID,
                "version": OPTIONS_225_VOL_SERIES_VERSION,
            },
            "basevol": {"rv_abs_by_date": {"2021-01-04": 20.0}},
        },
    }
    from pit.personal_research_view import _canonical_sidecar_bytes, _sidecar_digest

    object_digest = _sidecar_digest(_canonical_sidecar_bytes(obj))
    manifest = {
        "schema_version": OPTION_SIDECAR_MANIFEST_SCHEMA,
        "object_digest": object_digest,
        "cutoff": "morning_close",
        "pit_cutoff": "2021-01-04T11:30:00+09:00",
        "dataset": DATASET_ID,
        "version": OPTIONS_225_VOL_SERIES_VERSION,
    }
    digest = view.seal_option_sidecar(manifest=manifest, obj=obj)
    obj["opt225_regime"]["basevol"]["rv_abs_by_date"]["2021-01-04"] = 99.0
    loaded = load_opt225_regime_bundle_for_eval(view)
    assert loaded is not None
    assert loaded["source"]["dataset"] == DATASET_ID
    assert digest == object_digest
    assert loaded["basevol"]["rv_abs_by_date"]["2021-01-04"] == 20.0
    first_read = view.read_option_sidecar()
    assert first_read is not None
    first_read["opt225_regime"]["basevol"]["rv_abs_by_date"]["2021-01-04"] = 88.0
    second_read = view.read_option_sidecar()
    assert second_read is not None
    assert (
        second_read["opt225_regime"]["basevol"]["rv_abs_by_date"]["2021-01-04"]
        == 20.0
    )
    with pytest.raises(TypeError):
        view.read_option_sidecar(object())


def test_fins_empty_long_period_is_one_revision_stream(tmp_path: Path) -> None:
    from research.eval_loaders import load_fins_events_from_sqlite

    path = tmp_path / "empty-fins.sqlite"
    con = _catalog_db(path)
    con.commit()
    con.close()
    view = OfflineFixtureDataView.bind(
        path, artifact_root=tmp_path / "art", decision_cutoff="morning_close"
    )
    before = view.typed_query_count
    events = load_fins_events_from_sqlite(
        view, start="2014-01-01", end="2026-12-31"
    )
    after = view.typed_query_count
    assert events == {}
    assert after - before == 1


def test_fins_revision_as_of_keeps_later_correction(tmp_path: Path) -> None:
    from research.eval_loaders import (
        fins_asof,
        load_fins_events_from_sqlite,
        load_fins_latest_asof_map,
    )

    path = tmp_path / "fins-rev.sqlite"
    con = _catalog_db(path)
    payload_v1 = {
        "Code": "33210",
        "DiscDate": "2008-05-15",
        "DiscNo": "2",
        "TA": 100.0,
        "EqAR": 0.4,
        "EPS": 1.0,
    }
    payload_v2 = dict(payload_v1)
    payload_v2["TA"] = 200.0
    payload_v2["EPS"] = 2.0
    key = natural_key(payload_v1, "fins_summary")
    v1_time = "2008-05-15T12:00:00+09:00"
    v2_time = "2008-08-01T12:00:00+09:00"
    encoded_v1 = json.dumps(payload_v1, sort_keys=True, separators=(",", ":"))
    encoded_v2 = json.dumps(payload_v2, sort_keys=True, separators=(",", ":"))
    con.execute(
        "INSERT INTO jquants_records "
        "(source, dataset, natural_key, event_time, available_at, ingested_at, "
        "payload, raw_payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "jquants",
            "fins_summary",
            key,
            "2008-05-15T12:00:00+09:00",
            v2_time,
            v2_time,
            encoded_v2,
            encoded_v2,
        ),
    )
    con.execute(
        "INSERT INTO jquants_records_revisions "
        "(source, dataset, natural_key, event_time, available_at, ingested_at, "
        "payload, raw_payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "jquants",
            "fins_summary",
            key,
            "2008-05-15T12:00:00+09:00",
            v1_time,
            v1_time,
            encoded_v1,
            encoded_v1,
        ),
    )
    con.commit()
    con.close()
    view = OfflineFixtureDataView.bind(
        path, artifact_root=tmp_path / "art", decision_cutoff="session_close"
    )
    early = load_fins_events_from_sqlite(
        view, codes=["33210"], start="2008-01-01", end="2008-06-01"
    )
    late = load_fins_events_from_sqlite(
        view, codes=["33210"], start="2008-01-01", end="2008-09-01"
    )
    assert early["33210"][0]["ta"] == 100.0
    assert early["33210"][0]["eps"] == 1.0
    assert late["33210"][0]["ta"] == 200.0
    assert late["33210"][0]["eps"] == 2.0
    assert late["33210"][0]["source_disc_date"] == "2008-05-15"
    assert late["33210"][0]["disc_date"] == "2008-08-01"
    stream = load_fins_latest_asof_map(late)["33210"]
    assert fins_asof(stream, "2008-06-01")["eps"] == 1.0
    assert fins_asof(stream, "2008-08-02")["eps"] == 2.0
    assert view.typed_query_count == 2


def test_disabled_mass_and_factory_fail_before_local_paths(tmp_path: Path) -> None:
    from research.cf_daily_path_job import run_cf_daily_path_fanout
    from research.cf_mass_eval_job import resolve_or_stage_panels
    from research.cf_mass_eval_run import run_cf_mass_eval_job
    from research.cf_mass_eval_stage import (
        build_real_period_panel,
        stage_real_panels_to_r2,
    )
    from research.offline.factory import run_mass_factory

    db = tmp_path / "must-not-open.sqlite"
    db.write_text("not a database")
    with pytest.raises(MassResearchDisabledError, match="run_cf_mass_eval_job"):
        run_cf_mass_eval_job(job_id="x", staging_dir=tmp_path)
    with pytest.raises(MassResearchDisabledError, match="resolve_or_stage_panels"):
        resolve_or_stage_panels(job_id="x", staging_dir=tmp_path)
    with pytest.raises(MassResearchDisabledError, match="stage_real_panels_to_r2"):
        stage_real_panels_to_r2("x", staging_dir=tmp_path, view=db)
    with pytest.raises(MassResearchDisabledError, match="build_real_period_panel"):
        build_real_period_panel(
            {"period_id": "p", "period_start": "2024-01-01", "period_end": "2024-01-02"},
            view=db,
        )
    with pytest.raises(MassResearchDisabledError, match="run_cf_daily_path_fanout"):
        run_cf_daily_path_fanout(job_id="x", skip_stage=True, staging_dir=tmp_path)
    with pytest.raises(MassResearchDisabledError, match="load_batch_data_context"):
        load_batch_data_context(
            MassFactoryConfig(),
            view=db,
            sqlite_path=db,
            mirror_dir=tmp_path,
        )
    with pytest.raises(MassResearchDisabledError, match="run_mass_factory"):
        run_mass_factory(synthetic=False, out_dir=tmp_path)
    assert db.read_text() == "not a database"


def test_option_module_has_no_raw_log_dir_loader() -> None:
    import research.options_225_vol_series as series

    assert not hasattr(series, "load_opt225_series_cache")
    assert not hasattr(series, "_DEFAULT_LOG_DIR")
    assert not hasattr(series, "_W94_LOG_DIR")
