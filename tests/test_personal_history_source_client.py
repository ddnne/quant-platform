from __future__ import annotations

from datetime import date, timedelta
import importlib.util
import io
import json
from pathlib import Path
import sys

import pytest

from ingestion.personal_history import PERSONAL_HISTORY_DATASETS, PersonalHistoryError

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = (
    ROOT
    / "platform"
    / "workers"
    / "research-mass-eval"
    / "container"
    / "personal_history_source_client.py"
)
SPEC = importlib.util.spec_from_file_location(
    "personal_history_source_client", MODULE_PATH
)
assert SPEC is not None and SPEC.loader is not None
client_mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = client_mod
SPEC.loader.exec_module(client_mod)


class _Response(io.BytesIO):
    def __init__(self, payload: dict, headers: dict[str, str], status: int = 200):
        body = json.dumps(payload, separators=(",", ":")).encode()
        super().__init__(body)
        self.status = status
        self.headers = headers

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()
        return False


def _calendar_month(month: str) -> list[dict]:
    start = date.fromisoformat(f"{month}-01")
    rows = []
    current = start
    while current.month == start.month:
        rows.append(
            {
                "Date": current.isoformat(),
                "HolidayDivision": "1" if current.weekday() < 5 else "0",
            }
        )
        current += timedelta(days=1)
    return rows


def test_adapter_preserves_page_evidence_and_rejects_other_datasets() -> None:
    posted: list[dict] = []

    class Opener:
        def urlopen(self, request, timeout=120):
            payload = json.loads(request.data.decode())
            posted.append(payload)
            assert payload["dataset_id"] in PERSONAL_HISTORY_DATASETS
            assert "api_key" not in json.dumps(payload)
            month = payload["segment_id"]
            body = {"data": _calendar_month(month)}
            headers = {
                "x-quant-acquisition-evidence-state": "RAW_PAGE",
                "x-quant-acquisition-pagination-state": "EXHAUSTED",
                "x-quant-acquisition-continuation": "NONE",
                "x-quant-acquisition-slice-date": "NONE",
            }
            return _Response(body, headers)

    client = client_mod.PersonalHistorySourceClient(
        environment="production",
        period_end="2024-03-31",
        opener=Opener(),
    )
    fetched = client.fetch_dataset_evidenced(
        "markets_calendar", **{"from": "2024-03-10", "to": "2024-03-12"}
    )
    assert [row["Date"] for row in fetched.rows] == [
        "2024-03-10",
        "2024-03-11",
        "2024-03-12",
    ]
    assert fetched.pages[0].request_params["from"] == "2024-03-10"
    assert json.loads(fetched.pages[0].response_body)["data"] == list(fetched.rows)
    assert posted[0]["operation"] == "fetch_governed_page"
    with pytest.raises(PersonalHistoryError, match="not a personal history dataset"):
        client.fetch_dataset_evidenced("fins_details", date="2024-03-01")
