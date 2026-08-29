from __future__ import annotations

import hashlib
import io
import json
import math
import time
from datetime import date, timedelta
from typing import Any

import pytest

from research.options_225_smile_features import SVIParameters, svi_total_variance

from test_cloud_personal_research_container import service
import personal_svi_2023_job as svi_job


def _canonical(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def _svi_spec(job_id: str, input_digest: str):
    prefix = f"research/personal/svi-2023/job={job_id}"
    body = {
        "cohort_id": "personal-svi-term-2023-v1",
        "feature_key": f"{prefix}/features.jsonl",
        "input_manifest_digest": input_digest,
        "input_manifest_key": f"{prefix}/input-manifest.json",
        "job_id": job_id,
        "manifest_key": f"{prefix}/manifest.json",
        "report_key": f"{prefix}/report.json",
        "request_digest": "sha256:" + "0" * 64,
        "runner_version": "personal-svi-cloud-runner/v4",
        "strategy_id": "svi-atm-term-ratio-momentum-switch",
    }
    provisional = svi_job.PersonalSvi2023JobSpec(**body)
    body["request_digest"] = provisional.derived_request_digest()
    return svi_job.PersonalSvi2023JobSpec.from_document(body)


class _Response(io.BytesIO):
    def __init__(self, data: bytes):
        super().__init__(data)
        self.headers = {"content-length": str(len(data))}
        self.status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()
        return False


def test_svi_job_manager_accepts_the_separate_spec_and_reaches_completed() -> None:
    spec = _svi_spec("svi-manager", "sha256:" + "a" * 64)
    seen = []

    def runner(job):
        seen.append(job)
        return {
            "job_id": job.job_id,
            "cohort_id": job.cohort_id,
            "cohort_digest": job.cohort_digest,
            "request_digest": job.request_digest,
            "status": "COMPLETED",
            "go": False,
        }

    manager = service.JobManager(runner)
    submitted = manager.submit(spec)
    assert submitted["cohort_id"] == "personal-svi-term-2023-v1"
    assert submitted["cohort_digest"].startswith("sha256:")
    for _ in range(100):
        if manager.status(spec.job_id)["status"] == "COMPLETED":
            break
        time.sleep(0.005)
    assert manager.status(spec.job_id)["status"] == "COMPLETED"
    assert seen == [spec]


def test_natural_key_and_payload_json_strings_are_unwrapped_and_deduplicated() -> None:
    day = "2023-09-01"
    key = (
        "structured/jsonl/derivatives_bars_daily_options_225/"
        "dt=2023-09-01/one.jsonl"
    )

    def record(iv: float, ingested: str, *, available: str | None = None):
        payload = {
            "Date": day,
            "Code": "130060018",
            "Strike": 40_000,
            "UnderPx": 40_000,
            "IV": iv,
        }
        return {
            "dataset": "derivatives_bars_daily_options_225",
            "natural_key": json.dumps(
                {"Code": payload["Code"], "Date": day}, separators=(",", ":")
            ),
            "event_time": f"{day}T15:00:00+09:00",
            "available_at": available or f"{day}T15:00:00+09:00",
            "ingested_at": ingested,
            "payload": json.dumps(payload, separators=(",", ":")),
        }

    raw = b"\n".join(
        _canonical(row)
        for row in (
            record(20.0, "2026-08-14T12:00:00+09:00"),
            record(21.0, "2026-08-14T12:01:00+09:00"),
            record(
                99.0,
                "2026-08-14T12:02:00+09:00",
                available="2023-09-02T00:00:00+09:00",
            ),
            record(
                98.0,
                "2026-08-14T12:03:00+09:00",
                available="2023-09-01T15:01:00+09:00",
            ),
        )
    ) + b"\n"
    digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    spec = _svi_spec("svi-dedupe", "sha256:" + "b" * 64)

    rows, audit = svi_job.load_one_options_day(
        spec,
        {
            "date": day,
            "objects": [
                {"key": key, "size": len(raw), "sha256": digest},
            ],
        },
        opener=lambda _spec, _key: _Response(raw),
    )

    assert len(rows) == 1
    assert rows[0]["IV"] == 21.0
    assert audit == {
        "source_rows": 2,
        "rejected_rows": 2,
        "deduplicated_rows": 1,
        "natural_keys": 1,
    }


def _panel_dates(count: int = 25) -> list[str]:
    start = date(2023, 3, 16)
    return [(start + timedelta(days=index)).isoformat() for index in range(count)]


def _beta_panel(count: int = 90) -> tuple[dict[str, Any], list[str]]:
    dates = [
        (date(2023, 1, 4) + timedelta(days=index)).isoformat()
        for index in range(count)
    ]
    prices = {"TOPIX": 2_000.0, "A": 100.0, "B": 100.0, "C": 100.0, "D": 100.0}
    series = {code: [[dates[0], value]] for code, value in prices.items()}
    models = {"A": (0.002, 6.0), "B": (0.0015, 5.0), "C": (-0.0015, -5.0), "D": (-0.002, -6.0)}
    for index, day in enumerate(dates[1:], start=1):
        topix_return = ((index % 7) - 3) * 0.0005
        prices["TOPIX"] *= 1.0 + topix_return
        series["TOPIX"].append([day, prices["TOPIX"]])
        for code, (drift, beta) in models.items():
            prices[code] *= 1.0 + drift + beta * topix_return
            series[code].append([day, prices[code]])
    return {
        "index_proxy": {"dataset": "indices_bars_daily_topix", "label": "TOPIX"},
        "bars": {**{code: series[code] for code in models}, "__NKY_PROXY__": series["TOPIX"]},
    }, dates


def test_fixed_strategy_has_one_session_signal_lag_ten_session_hold_and_cost() -> None:
    dates = _panel_dates()
    panel = {
        "bars": {
            "A": [[day, 100 + index * 3] for index, day in enumerate(dates)],
            "B": [[day, 100 + index * 2] for index, day in enumerate(dates)],
            "C": [[day, 100 + index] for index, day in enumerate(dates)],
            "D": [[day, 100 - index * 0.5] for index, day in enumerate(dates)],
        }
    }
    features = [
        {
            "date": day,
            "fit_success": True,
            "svi_atm_short_over_next_minus_one": -0.05,
        }
        for day in dates
    ]

    curve, trades, diagnostics, _trace = svi_job.evaluate_fixed_strategy(
        panel,
        features,
        dates,
    )
    by_day = {row["date"]: row for row in curve}

    assert by_day[dates[11]]["turnover_one_way"] == 0.0
    assert by_day[dates[12]]["signal_date"] == dates[10]
    assert by_day[dates[12]]["turnover_one_way"] == pytest.approx(1.0)
    assert by_day[dates[12]]["cost_return"] == pytest.approx(0.001)
    first_fill = next(trade for trade in trades if trade["signal_date"] is not None)
    assert first_fill["signal_date"] == dates[10]
    assert first_fill["fill_date"] == first_fill["date"] == dates[11]
    assert first_fill["pnl_date"] == dates[12]
    assert diagnostics["active_sessions"] > 0
    assert diagnostics["performance"]["annualized_sharpe"] is not None


def test_topix_beta_overlay_is_no_lookahead_capped_and_fail_closed() -> None:
    panel, dates = _beta_panel()
    features = [
        {"date": day, "fit_success": True, svi_job.FEATURE_FIELD: -0.05}
        for day in dates
    ]
    unhedged, _trades, _diagnostics, trace = svi_job.evaluate_fixed_strategy(
        panel, features, dates
    )
    comparison = svi_job.evaluate_topix_beta_hedged_comparison(
        panel, features, trace
    )
    assert comparison["status"] == "PARTIAL"
    assert comparison["performance"] is None
    assert comparison["performance_status"] == "UNAVAILABLE"
    assert comparison["hedge_tracking"]["calendar_sessions_dropped"] == 0
    estimated = next(
        row for row in comparison["daily_path"] if row["beta_status"] == "ESTIMATED"
    )
    current_index = dates.index(estimated["date"])
    assert estimated["signal_date"] == dates[current_index - 2]
    assert estimated["assumed_proxy_fill_date"] == dates[current_index - 1]
    assert estimated["beta_window_last_return_date"] <= estimated["signal_date"]
    assert abs(estimated["target_topix_proxy_hedge_weight"]) == 1.5
    assert comparison["signal_branch_coverage"]["contango_sessions"] == len(dates)
    assert comparison["signal_branch_coverage"]["front_inversion_sessions"] == 0

    stock = {day: value for day, value in panel["bars"]["A"]}
    topix = {day: value for day, value in panel["bars"]["__NKY_PROXY__"]}
    signal_day = dates[70]
    before = svi_job._estimate_beta_through(stock, topix, signal_day)
    mutated = {day: (value * 50 if day > signal_day else value) for day, value in stock.items()}
    mutated_topix = {
        day: (value / 50 if day > signal_day else value)
        for day, value in topix.items()
    }
    after = svi_job._estimate_beta_through(mutated, mutated_topix, signal_day)
    assert before == after
    assert before is not None and before[1] == 70

    unavailable = json.loads(json.dumps(panel))
    unavailable["bars"].pop("__NKY_PROXY__")
    with pytest.raises(RuntimeError, match="TOPIX index proxy series is unavailable"):
        svi_job.evaluate_topix_beta_hedged_comparison(
            unavailable, features, trace
        )

    incomplete = json.loads(json.dumps(panel))
    incomplete["bars"]["A"] = [pair for pair in incomplete["bars"]["A"] if pair[0] != dates[75]]
    incomplete_curve, _trades, incomplete_primary, incomplete_trace = (
        svi_job.evaluate_fixed_strategy(incomplete, features, dates)
    )
    incomplete_comparison = svi_job.evaluate_topix_beta_hedged_comparison(
        incomplete, features, incomplete_trace
    )
    tracking = incomplete_comparison["hedge_tracking"]
    assert incomplete_primary["status"] == "INCOMPLETE"
    assert incomplete_primary["performance"] is None
    assert incomplete_primary["performance_status"] == "UNAVAILABLE"
    assert incomplete_primary["calendar_sessions_dropped"] == 0
    assert incomplete_primary["incomplete_active_intervals"] == tracking[
        "incomplete_active_intervals"
    ]
    assert incomplete_comparison["status"] == "INCOMPLETE"
    assert incomplete_comparison["performance"] is None
    assert tracking["incomplete_active_interval_count"] > 0
    assert dates[75] in tracking["incomplete_active_intervals"]
    assert tracking["calendar_sessions_dropped"] == 0
    assert len(incomplete_comparison["daily_path"]) == len(unhedged)
    incomplete_row = next(
        row for row in incomplete_comparison["daily_path"] if row["date"] == dates[75]
    )
    primary_row_index = next(
        index for index, row in enumerate(incomplete_curve) if row["date"] == dates[75]
    )
    primary_row = incomplete_curve[primary_row_index]
    prior_equity = incomplete_curve[primary_row_index - 1]["equity"]
    assert primary_row["interval_status"] == "INCOMPLETE_TARGET_BOOK"
    assert primary_row["gross_return"] == 0.0
    assert primary_row["net_return"] == 0.0
    assert primary_row["cost_return"] == 0.0
    assert primary_row["turnover_one_way"] == 0.0
    assert primary_row["equity"] == prior_equity
    assert incomplete_row["interval_status"] == "INCOMPLETE_TARGET_BOOK"
    assert incomplete_row["equity"] is None


def test_topix_beta_overlay_requires_full_coverage_and_separates_proxy_costs() -> None:
    panel, dates = _beta_panel()
    features = [
        {"date": day, "fit_success": True, svi_job.FEATURE_FIELD: -0.05}
        for day in dates
    ]
    evaluation_dates = dates[70:]
    _unhedged, _trades, _diagnostics, trace = svi_job.evaluate_fixed_strategy(
        panel, features, evaluation_dates
    )
    comparison = svi_job.evaluate_topix_beta_hedged_comparison(
        panel, features, trace
    )

    assert comparison["status"] == "EVALUATED"
    assert comparison["performance_status"] == "AVAILABLE"
    assert comparison["performance"]["schema_version"] == "personal-performance/v1"
    tracking = comparison["hedge_tracking"]
    assert tracking["beta_coverage_complete"] is True
    assert tracking["beta_coverage_ratio_of_active_sessions"] == 1.0
    stock = comparison["comparison_stock_accounting"]
    proxy = comparison["hypothetical_topix_proxy_accounting"]
    combined = comparison["combined_comparison_accounting"]
    assert proxy["adjustment_count"] > 0
    assert proxy["included_in_performance_fill_count"] is False
    assert comparison["performance"]["fill_count"] == stock["adjustment_count"]
    assert combined["adjustment_count"] == (
        stock["adjustment_count"] + proxy["adjustment_count"]
    )
    assert combined["cost_amount"] == pytest.approx(
        stock["cost_amount"] + proxy["cost_amount"]
    )
    assert comparison["performance"]["cost_amount"] == pytest.approx(
        combined["cost_amount"]
    )
    equity_before = 1.0
    for row in comparison["daily_path"]:
        assert row["stock_adjustment_notional_amount"] == pytest.approx(
            row["stock_turnover_one_way"] * equity_before
        )
        assert row["topix_proxy_adjustment_notional_amount"] == pytest.approx(
            row["topix_proxy_turnover_one_way"] * equity_before
        )
        assert row["stock_cost_return"] == pytest.approx(
            row["stock_turnover_one_way"] * svi_job.ONE_WAY_COST
        )
        assert row["topix_hedge_cost_return"] == pytest.approx(
            row["topix_proxy_turnover_one_way"] * svi_job.ONE_WAY_COST
        )
        equity_before = row["equity"]


def _svi_chain(day: str, *, dte: int, cm: str, params: SVIParameters):
    under = 40_000.0
    expiry = (date.fromisoformat(day) + timedelta(days=dte)).isoformat()
    maturity = dte / 365.0
    ks = (-0.28, -0.23, -0.18, -0.14, -0.10, -0.05, 0.0, 0.05, 0.10, 0.14, 0.18, 0.23, 0.28)
    rows = []
    for index, log_moneyness in enumerate(ks):
        strike = under * math.exp(log_moneyness)
        iv = math.sqrt(svi_total_variance(log_moneyness, params) / maturity)
        for pc, offset in (("1", -0.001), ("2", 0.001)):
            code = f"{cm}-{index}-{pc}"
            payload = {
                "Date": day,
                "Code": code,
                "Strike": strike,
                "PCDiv": pc,
                "CM": cm,
                "SQD": expiry,
                "UnderPx": under,
                "IV": (iv + offset) * 100.0,
                "EmMrgnTrgDiv": "002",
            }
            rows.append(
                {
                    "dataset": "derivatives_bars_daily_options_225",
                    "natural_key": json.dumps(
                        {"Code": code, "Date": day}, separators=(",", ":")
                    ),
                    "event_time": f"{day}T15:00:00+09:00",
                    "available_at": f"{day}T15:00:00+09:00",
                    "ingested_at": "2026-08-14T12:00:00+09:00",
                    "payload": json.dumps(payload, separators=(",", ":")),
                }
            )
    return rows


def test_execute_svi_job_creates_feature_report_then_terminal_manifest() -> None:
    day = "2023-09-01"
    option_key = (
        "structured/jsonl/derivatives_bars_daily_options_225/"
        "dt=2023-09-01/synthetic.jsonl"
    )
    option_rows = _svi_chain(
        day,
        dte=30,
        cm="2023-10",
        params=SVIParameters(0.0075, 0.042, -0.42, 0.01, 0.16),
    ) + _svi_chain(
        day,
        dte=93,
        cm="2023-12",
        params=SVIParameters(0.014, 0.032, -0.28, 0.005, 0.20),
    )
    option_bytes = b"".join(_canonical(row) + b"\n" for row in option_rows)
    option_digest = "sha256:" + hashlib.sha256(option_bytes).hexdigest()
    dates = _panel_dates()
    panel = {
        "index_proxy": {
            "dataset": "indices_bars_daily_topix",
            "label": "TOPIX",
        },
        "bars": {
            code: [[observed, 100 + index + offset] for index, observed in enumerate(dates)]
            for offset, code in enumerate(("A", "B", "C", "D"))
        }
    }
    proxy_dates = _panel_dates(90)
    panel["bars"]["__NKY_PROXY__"] = [
        [observed, 2_000 + index] for index, observed in enumerate(proxy_dates)
    ]
    panel_bytes = _canonical(panel)
    manifest = {
        "schema_version": "personal-svi-2023-input/v2",
        "job_id": "svi-execute",
        "cohort_id": "personal-svi-term-2023-v1",
        "runner_version": "personal-svi-cloud-runner/v4",
        "authority": {
            "draft_only": True,
            "screening_only": True,
            "ready": False,
            "mass": False,
            "promotion": False,
            "live_orders": False,
            "go": False,
        },
        "panel": {
            "key": svi_job.PANEL_KEY,
            "size": len(panel_bytes),
            "etag": "p",
            "sha256": "sha256:" + hashlib.sha256(panel_bytes).hexdigest(),
        },
        "equity_universe": svi_job.EQUITY_UNIVERSE,
        "strategy": {
            "strategy_id": svi_job.STRATEGY_ID,
            "feature": svi_job.FEATURE_FIELD,
            "thesis": "fixed test thesis",
            "signal_lag_sessions": 1,
            "hold_sessions": svi_job.HOLD_SESSIONS,
            "one_way_cost": svi_job.ONE_WAY_COST,
        },
        "options": {
            "dataset": "derivatives_bars_daily_options_225",
            "natural_key": ["Date", "Code"],
            "days": [
                {
                    "date": day,
                    "objects": [
                        {
                            "key": option_key,
                            "size": len(option_bytes),
                            "sha256": option_digest,
                        }
                    ],
                }
            ],
            "object_count": 1,
            "total_bytes": len(option_bytes),
        },
        "sessions": {
            "warmup_sessions": 0,
            "warmup_dates": [],
            "evaluation_dates": [day],
        },
        "temporal_contract": {
            "source_decision_cutoff_jst": svi_job.DECISION_CUTOFF_JST,
            "signal_lag_sessions": 1,
            "fill_timing": "next_close",
            "first_pnl_interval": "fill_close_to_following_close",
        },
    }
    manifest_bytes = _canonical(manifest)
    manifest_digest = "sha256:" + hashlib.sha256(manifest_bytes).hexdigest()
    spec = _svi_spec("svi-execute", manifest_digest)
    objects = {
        spec.input_manifest_key: manifest_bytes,
        svi_job.PANEL_KEY: panel_bytes,
        option_key: option_bytes,
    }
    uploads: list[tuple[str, bytes, str]] = []

    def opener(_spec, key):
        return _Response(objects[key])

    def uploader(_spec, key, data):
        digest = "sha256:" + hashlib.sha256(data).hexdigest()
        uploads.append((key, data, digest))
        return digest

    terminal = svi_job.execute_svi_job(
        spec,
        input_opener=opener,
        uploader=uploader,
    )

    assert terminal["status"] == "COMPLETED"
    assert terminal["runner_version"] == "personal-svi-cloud-runner/v4"
    assert [key for key, _data, _digest in uploads] == [
        spec.feature_key,
        spec.report_key,
        spec.manifest_key,
    ]
    feature = json.loads(uploads[0][1].splitlines()[0])
    assert feature["fit_success"] is True
    assert feature["svi_atm_short_over_next_minus_one"] is not None
    report = json.loads(uploads[1][1])
    assert report["execution"]["signal_lag_sessions"] == 1
    assert report["execution"]["hold_sessions"] == 10
    assert report["execution"]["one_way_cost"] == 0.001
    assert report["schema_version"] == "personal-svi-2023-report/v4"
    assert report["runner_version"] == "personal-svi-cloud-runner/v4"
    assert report["candidate_status"] == report["evaluation"]["status"]
    assert report["candidate_status"] == "NOT_EVALUATED"
    assert report["evaluation"]["performance"] is None
    comparison = report["topix_beta_hedged_comparison"]
    assert comparison["status"] == "NOT_EVALUATED"
    assert comparison["performance"] is None
    assert comparison["performance_status"] == "UNAVAILABLE"
    instrument = report["topix_beta_hedged_comparison"]["instrument"]
    assert instrument["dataset"] == "indices_bars_daily_topix"
    assert instrument["etf_approximation"] == "1306_TOPIX_ETF_only"
    assert instrument["execution_claim"] is False
    assert report["draft_only"] is True
    assert report["screening_only"] is True
    assert report["go"] is False
