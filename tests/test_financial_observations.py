"""DataPlane latest per-share financial observation selector."""

from __future__ import annotations

from types import MappingProxyType

from features.complete21_min_parsers import (
    _as_float_or_none,
    _latest_fins_per_share_observation,
    _row_payload,
)
from pit.financial_observations import (
    _as_float_or_none as dataplane_as_float_or_none,
    catalog_row_payload,
    latest_fins_per_share_observation,
)


def test_latest_per_share_observation_prefers_older_bps_and_counts_payloads() -> None:
    rows = [
        {
            "payload": {
                "DiscDate": "2025-01-15",
                "CurPerEn": "2024-12-31",
                "BPS": 80.0,
            }
        },
        {
            "payload": {
                "DiscDate": "2025-04-15",
                "CurPerEn": "2025-03-31",
                "EPS": 12.0,
            }
        },
        {"payload": {"NetSales": 1.0, "CurPerEn": "2025-06-30"}},
        {
            "payload": {},
            "raw_payload": {
                "BPS": 999.0,
                "CurPerEn": "2025-09-30",
                "DiscDate": "2025-10-01",
            },
        },
        {
            "payload": "not-json",
            "raw_payload": {"EPS": 3.0, "DiscDate": "2025-07-01"},
        },
        {
            "payload": MappingProxyType(
                {"BPS": 50.0, "CurPerEn": "2024-01-01"}
            ),
            "raw_payload": {"NetSales": 2.0},
        },
    ]

    selected = latest_fins_per_share_observation(rows)
    compat = _latest_fins_per_share_observation(rows)

    assert latest_fins_per_share_observation is _latest_fins_per_share_observation
    assert catalog_row_payload is _row_payload
    assert dataplane_as_float_or_none is _as_float_or_none
    assert selected == compat
    assert selected is not None
    assert selected == {
        "statement_period_end": "2024-12-31",
        "disclosure_date": "2025-01-15",
        "split_safety_anchor": "2024-12-31",
        "split_safety_anchor_source": "statement_period_end",
        "fins_rows": 5,
        "mode": "bps_over_price",
        "bps": 80.0,
    }

    fallback_only = latest_fins_per_share_observation(
        [
            {
                "payload": "not-json",
                "raw_payload": {
                    "BPS": 40.0,
                    "CurPerEn": "2024-03-31",
                    "DiscDate": "2024-04-15",
                },
            }
        ]
    )
    assert fallback_only == _latest_fins_per_share_observation(
        [
            {
                "payload": "not-json",
                "raw_payload": {
                    "BPS": 40.0,
                    "CurPerEn": "2024-03-31",
                    "DiscDate": "2024-04-15",
                },
            }
        ]
    )
    assert fallback_only is not None
    assert fallback_only["mode"] == "bps_over_price"
    assert fallback_only["bps"] == 40.0
    assert fallback_only["split_safety_anchor"] == "2024-03-31"
    assert fallback_only["fins_rows"] == 1

    mapping_only = latest_fins_per_share_observation(
        [
            {
                "payload": MappingProxyType(
                    {"BPS": 50.0, "CurPerEn": "2024-01-01"}
                )
            }
        ]
    )
    assert mapping_only is None
    assert catalog_row_payload({"payload": {}}) == {}
    assert catalog_row_payload(
        {"payload": {}, "raw_payload": {"BPS": 1.0}}
    ) == {}
