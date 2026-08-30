from __future__ import annotations

import hashlib
import io
import json
from typing import Any

import pytest

from test_cloud_personal_research_container import service as _service  # noqa: F401
import personal_option_sidecar_job as job


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


class _Response(io.BytesIO):
    def __init__(self, data: bytes, status: int = 200):
        super().__init__(data)
        self.headers = {"content-length": str(len(data))}
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()
        return False


def _spec() -> job.PersonalOptionSidecarJobSpec:
    return job.PersonalOptionSidecarJobSpec.from_document(
        {
            "cohort_id": job.COHORT_ID,
            "input_manifest_digest": "sha256:" + "b" * 64,
            "input_manifest_key": "research/personal/option-sidecar/job=sidecar-py/input-manifest.json",
            "job_id": "sidecar-py",
            "manifest_key": "research/personal/option-sidecar/job=sidecar-py/manifest.json",
            "producer_id": job.PRODUCER_ID,
            "request_digest": "sha256:" + "c" * 64,
            "runner_version": job.RUNNER_VERSION,
        }
    )


def _options_ref(key: str, body: bytes, day: str, run_id: str) -> dict[str, Any]:
    return {
        "key": key,
        "etag": f"etag-{run_id}",
        "size": len(body),
        "bytes": len(body),
        "sha256": "sha256:" + hashlib.sha256(body).hexdigest(),
        "dataset": job.DATASET,
        "run_id": run_id,
        "date": day,
        "schema": job.RECORDS_SCHEMA,
        "count": sum(1 for line in body.splitlines() if line.strip()),
    }


def _record(day: str, code: str, ingested: str, strike: float) -> dict[str, Any]:
    payload = {
        "Date": day,
        "Code": code,
        "Strike": strike,
        "UnderPx": 40_000,
        "BaseVol": 20.0,
        "IV": 21.0,
        "PCDiv": "2",
        "CM": "2021-02",
        "LTD": "2021-02-12",
        "SQD": "2021-02-12",
        "EmMrgnTrgDiv": "002",
    }
    return {
        "dataset": job.DATASET,
        "natural_key": {"Date": day, "Code": code},
        "event_time": f"{day}T15:00:00+09:00",
        "available_at": f"{day}T15:00:00+09:00",
        "ingested_at": ingested,
        "payload": payload,
    }


def test_duplicate_date_code_keeps_lexicographic_max_rank() -> None:
    day = "2021-01-04"
    early_key = (
        "structured/jsonl/derivatives_bars_daily_options_225/dt=2021-01-04/a.jsonl"
    )
    late_key = (
        "structured/jsonl/derivatives_bars_daily_options_225/dt=2021-01-04/b.jsonl"
    )
    first = _canonical(_record(day, "130060018", "2026-08-14T12:00:00+09:00", 1.0)) + b"\n"
    second = _canonical(_record(day, "130060018", "2026-08-14T12:01:00+09:00", 2.0)) + b"\n"
    third = _canonical(_record(day, "130060018", "2026-08-14T12:01:00+09:00", 3.0)) + b"\n"
    bodies = {early_key: first, late_key: second + third}
    spec = _spec()

    def opener(_spec: job.PersonalOptionSidecarJobSpec, key: str) -> _Response:
        return _Response(bodies[key])

    rows, audit = job.load_one_options_day(
        spec,
        {
            "date": day,
            "objects": [
                _options_ref(early_key, first, day, "a"),
                _options_ref(late_key, second + third, day, "b"),
            ],
        },
        opener=opener,
    )
    assert len(rows) == 1
    assert rows[0]["Strike"] == 3.0
    assert audit["deduplicated_rows"] == 2
    assert audit["rejected_rows"] == 0
    assert job.DUPLICATE_RESOLUTION["winner"] == "lexicographic_max"
    assert job.DUPLICATE_RESOLUTION["natural_key"] == ["Date", "Code"]


def test_malformed_count_and_missing_natural_key_fail_closed() -> None:
    day = "2021-01-04"
    key = "structured/jsonl/derivatives_bars_daily_options_225/dt=2021-01-04/a.jsonl"
    spec = _spec()
    valid = _canonical(_record(day, "130060018", "2026-08-14T12:00:00+09:00", 1.0)) + b"\n"

    def opener_for(body: bytes):
        def opener(_spec: job.PersonalOptionSidecarJobSpec, _key: str) -> _Response:
            return _Response(body)

        return opener

    bad_count = _options_ref(key, valid, day, "a")
    bad_count["count"] = 2
    with pytest.raises(RuntimeError, match="count mismatch"):
        job.load_one_options_day(
            spec, {"date": day, "objects": [bad_count]}, opener=opener_for(valid)
        )
    malformed = b"{not-json}\n"
    with pytest.raises(RuntimeError, match="malformed JSON"):
        job.load_one_options_day(
            spec,
            {"date": day, "objects": [_options_ref(key, malformed, day, "a")]},
            opener=opener_for(malformed),
        )
    missing = dict(_record(day, "130060018", "2026-08-14T12:00:00+09:00", 1.0))
    del missing["natural_key"]
    missing_body = _canonical(missing) + b"\n"
    with pytest.raises(RuntimeError, match="natural_key"):
        job.load_one_options_day(
            spec,
            {"date": day, "objects": [_options_ref(key, missing_body, day, "a")]},
            opener=opener_for(missing_body),
        )


def test_streaming_daily_outputs_match_all_rows_bundle() -> None:
    days = ["2021-01-04", "2021-01-05", "2021-01-06"]
    all_rows: list[dict[str, Any]] = []
    daily: dict[str, list[dict[str, Any]]] = {
        "base_vol_series": [],
        "atm_iv_series": [],
        "skew_series": [],
        "cm_term_series": [],
    }
    for day in days:
        rows = [
            _record(day, "P_ATM", f"{day}T15:00:00+09:00", 40000.0)["payload"]
            | {"PCDiv": "1", "IV": 20.5, "CM": "2021-02", "LTD": "2021-02-12", "SQD": "2021-02-12", "EmMrgnTrgDiv": "002", "UnderPx": 40000.0, "BaseVol": 20.0 + days.index(day)},
            _record(day, "C_ATM", f"{day}T15:00:00+09:00", 40000.0)["payload"]
            | {"PCDiv": "2", "IV": 19.5, "CM": "2021-02", "LTD": "2021-02-12", "SQD": "2021-02-12", "EmMrgnTrgDiv": "002", "UnderPx": 40000.0, "BaseVol": 20.0 + days.index(day)},
            _record(day, "P_OTM", f"{day}T15:00:00+09:00", 38000.0)["payload"]
            | {"PCDiv": "1", "IV": 22.0, "CM": "2021-02", "LTD": "2021-02-12", "SQD": "2021-02-12", "EmMrgnTrgDiv": "002", "UnderPx": 40000.0, "BaseVol": 20.0 + days.index(day)},
        ]
        all_rows.extend(rows)
        outputs = job.daily_outputs_from_rows(rows)
        for field, values in outputs.items():
            daily[field].extend(values)
    streamed = job.assemble_series_bundle(daily)
    full = job.build_series_bundle_from_rows(all_rows)
    for field in (
        "base_vol_series",
        "atm_iv_series",
        "spread_series",
        "skew_series",
        "cm_term_series",
        "cm_term_ratio_series",
        "basevol_delta_series",
        "stats",
        "version",
        "dataset",
    ):
        assert streamed[field] == full[field]
