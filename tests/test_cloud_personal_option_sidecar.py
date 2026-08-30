from __future__ import annotations

import hashlib
import io
import json
from typing import Any

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


def test_duplicate_date_code_keeps_lexicographic_max_rank() -> None:
    day = "2021-01-04"
    early_key = (
        "structured/jsonl/derivatives_bars_daily_options_225/dt=2021-01-04/a.jsonl"
    )
    late_key = (
        "structured/jsonl/derivatives_bars_daily_options_225/dt=2021-01-04/b.jsonl"
    )

    def record(code: str, ingested: str, strike: float) -> dict[str, Any]:
        payload = {
            "Date": day,
            "Code": code,
            "Strike": strike,
            "UnderPx": 40_000,
            "BaseVol": 20.0,
            "IV": 21.0,
        }
        return {
            "dataset": job.DATASET,
            "natural_key": {"Date": day, "Code": code},
            "event_time": f"{day}T15:00:00+09:00",
            "ingested_at": ingested,
            "payload": payload,
        }

    first = _canonical(record("130060018", "2026-08-14T12:00:00+09:00", 1.0)) + b"\n"
    second = _canonical(record("130060018", "2026-08-14T12:01:00+09:00", 2.0)) + b"\n"
    third = _canonical(record("130060018", "2026-08-14T12:01:00+09:00", 3.0)) + b"\n"
    bodies = {
        early_key: first,
        late_key: second + third,
    }
    spec = _spec()

    def opener(_spec: job.PersonalOptionSidecarJobSpec, key: str) -> _Response:
        return _Response(bodies[key])

    rows, audit = job.load_one_options_day(
        spec,
        {
            "date": day,
            "objects": [
                {
                    "key": early_key,
                    "size": len(first),
                    "sha256": "sha256:" + hashlib.sha256(first).hexdigest(),
                },
                {
                    "key": late_key,
                    "size": len(second + third),
                    "sha256": "sha256:" + hashlib.sha256(second + third).hexdigest(),
                },
            ],
        },
        opener=opener,
    )
    assert len(rows) == 1
    assert rows[0]["Strike"] == 3.0
    assert audit["deduplicated_rows"] == 2
    assert job.DUPLICATE_RESOLUTION["winner"] == "lexicographic_max"
    assert job.DUPLICATE_RESOLUTION["natural_key"] == ["Date", "Code"]
