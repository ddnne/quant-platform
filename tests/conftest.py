"""Shared offline fixtures that mimic Cloudflare D1 export responses."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest


_REPO = Path(__file__).resolve().parents[1]
_SYNC = _REPO / "scripts" / "sync_d1_to_sqlite.py"
CF_TRADING_DAYS = ("2025-04-01", "2025-04-02", "2025-04-03", "2025-04-04")
CF_CODE = "8697"
# Secondary code so multi-code features (and the F6 smoke) exercise more than
# one issuer. Kept in lockstep with ``CF_CODE`` for symmetry.
CF_CODE_2 = "7203"
CF_CODES = (CF_CODE, CF_CODE_2)


def _json(value: dict) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _generic_row(dataset: str, payload: dict, available_at: str) -> dict:
    natural_key = {
        key: payload[key]
        for key in ("Code", "Date")
        if payload.get(key) not in (None, "")
    }
    return {
        "source": "jquants",
        "dataset": dataset,
        "natural_key": _json(natural_key),
        "event_time": f"{payload['Date']}T09:00:00+09:00",
        "available_at": available_at,
        "ingested_at": available_at,
        "payload": _json(payload),
        "raw_payload": json.dumps(payload, separators=(",", ":")),
    }


@pytest.fixture(scope="session")
def sync_module():
    spec = importlib.util.spec_from_file_location("sync_d1_to_sqlite", _SYNC)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def cf_d1_export_rows() -> dict[str, list[dict]]:
    """D1-shaped generic rows emitted by the premium Worker's export API.

    Multi-code (8697 + 7203) so feature smoke tests can exercise more than
    one issuer. 8697's price series matches the legacy single-code shape
    (100 → 102 → 101 → 104) so the assertions in
    ``test_phase35_sync_script.py`` and the existing F6 expected-value check
    stay valid; 7203 has its own ladder (8000 → 8050 → 7990 → 8120).
    """
    rows: list[dict] = []
    # Master: one snapshot per code on the same date.
    for code, name in ((CF_CODE, "Fixture Co"), (CF_CODE_2, "Fixture Motors")):
        rows.append(_generic_row(
            "equities_master",
            {
                "Code": code,
                "Date": "2025-03-31",
                "CompanyName": name,
                "MarketCode": "0111",
            },
            "2025-03-31T09:00:00+09:00",
        ))
    for day in CF_TRADING_DAYS:
        rows.append(
            _generic_row(
                "markets_calendar",
                {"Date": day, "HolidayDivision": "1"},
                "2025-01-01T00:00:00+09:00",
            )
        )
    # 8697 ladder (kept identical to the original single-code fixture).
    for day, close in zip(CF_TRADING_DAYS, (100.0, 102.0, 101.0, 104.0)):
        rows.append(
            _generic_row(
                "equities_bars_daily",
                {
                    "Code": CF_CODE,
                    "Date": day,
                    "Open": close,
                    "High": close,
                    "Low": close,
                    "Close": close,
                    "Volume": 1000.0,
                },
                f"{day}T15:30:00+09:00",
            )
        )
    # 7203 ladder.
    for day, close in zip(CF_TRADING_DAYS, (8000.0, 8050.0, 7990.0, 8120.0)):
        rows.append(
            _generic_row(
                "equities_bars_daily",
                {
                    "Code": CF_CODE_2,
                    "Date": day,
                    "Open": close,
                    "High": close,
                    "Low": close,
                    "Close": close,
                    "Volume": 2000.0,
                },
                f"{day}T15:30:00+09:00",
            )
        )
    return {"jquants_records": deepcopy(rows)}


@pytest.fixture
def synced_cf_d1_db(
    tmp_path, monkeypatch, sync_module, cf_d1_export_rows
) -> SimpleNamespace:
    """Run the real sync CLI against cursor-paginated in-memory D1 pages."""
    calls: list[str] = []

    def fake_export(client, url: str, token: str) -> dict:
        assert token == "fixture-token"
        calls.append(url)
        query = parse_qs(urlparse(url).query)
        table = query["table"][0]
        limit = int(query["limit"][0])
        cursor = int(query.get("cursor", ["0"])[0])
        source_rows = cf_d1_export_rows.get(table, [])
        page = deepcopy(source_rows[cursor : cursor + limit])
        next_cursor = cursor + len(page)
        has_more = next_cursor < len(source_rows)
        return {
            "table": table,
            "rows": page,
            "cursor": cursor,
            "next_cursor": next_cursor if has_more else None,
            "has_more": has_more,
            "limit": limit,
        }

    # ``_new_http_client`` returns the real httpx.Client in production. Stub
    # it with a sentinel so any accidental transport use inside a test fails
    # fast rather than touching the network.
    monkeypatch.setattr(sync_module, "_new_http_client", lambda: object())
    monkeypatch.setattr(sync_module, "_http_get_json", fake_export)
    db = tmp_path / "cf-export.sqlite"
    rc = sync_module.main(
        [
            "--db",
            str(db),
            "--url",
            "https://fixture.invalid",
            "--token",
            "fixture-token",
            "--table",
            "jquants_records",
            "--page-limit",
            "2",
        ]
    )
    # This fixture intentionally mirrors only one fact table and cannot pass
    # the governed READY publication gate. Mark it as an unmanaged unit-test
    # DB so PIT-shape tests can exercise rows; production sync never does this.
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE local_snapshot_policy SET require_manifest=0 "
            "WHERE singleton=1"
        )
    return SimpleNamespace(db=db, rc=rc, calls=calls, rows=cf_d1_export_rows)


@pytest.fixture(autouse=True)
def _disable_host_receipt_pem(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never load operator ~/.config receipt PEM during pytest."""
    monkeypatch.setenv("QUANT_RECEIPT_DISABLE_HOST_PEM", "1")
    monkeypatch.setenv("QUANT_READINESS_DISABLE_HOST_PEM", "1")


@pytest.fixture
def receipt_ed25519_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> SimpleNamespace:
    """Ephemeral Ed25519 pair; verifier reads tmp JSON, never the repo registry."""
    import base64

    import storage.receipt_crypto as rc
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    from storage.receipt_crypto import ReceiptSigningKey, generate_keypair

    priv_pem, pub, kid = generate_keypair(key_id="test-receipt-v1")
    keys_path = tmp_path / "receipt_verify_public_keys.json"
    keys_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "keys": [
                    {
                        "key_id": kid,
                        "public_key_b64": base64.b64encode(pub).decode("ascii"),
                        "algorithm": "Ed25519",
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(rc.VERIFY_KEYS_ENV, str(keys_path))
    monkeypatch.setattr(rc, "PUBLIC_KEYS_PATH", keys_path)
    priv = load_pem_private_key(priv_pem, password=None)
    assert isinstance(priv, Ed25519PrivateKey)
    return SimpleNamespace(
        path=keys_path,
        key_id=kid,
        signing_key=ReceiptSigningKey(key_id=kid, _private=priv),
    )
