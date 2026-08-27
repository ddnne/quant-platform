"""Byte-exact tests for the generated Quant Ops routing authority."""

from __future__ import annotations

from pathlib import Path

from scripts.generate_governed_js import governed_contract, render_governed_js
from scripts.verify_governed_js_drift import (
    GOVERNED_JS,
    drift_errors,
)


def test_generated_governed_membership_and_canonical_routes_are_exact() -> None:
    ids, sources, membership_digest, source_digest = governed_contract()
    assert len(ids) == 26
    assert len(sources) == 31
    assert set(ids) < set(sources)
    assert sources["equities_trades"] == "jquants"
    assert {
        dataset for dataset, source in sources.items() if source == "jsda"
    } == {
        "jsda_corporate_bond_transactions",
        "jsda_otc_bond_reference_prices",
        "jsda_tokyo_repo_rates",
    }
    assert membership_digest == (
        "sha256:1ae6eae118d6c5a2340b8834ec020cd46072800837aac10c1c8f68fc19b5b343"
    )
    assert source_digest == (
        "sha256:1f72a99e049e9519827fb045db50c56863835c0b0183f52989f42d7c378b9f92"
    )
    assert GOVERNED_JS.read_text(encoding="utf-8") == render_governed_js()
    assert drift_errors() == []


def test_generated_route_verifier_rejects_mapping_drift(tmp_path: Path) -> None:
    corrupted = tmp_path / "governed.js"
    corrupted.write_text(
        render_governed_js().replace(
            '"equities_master": "jquants"',
            '"equities_master": "jsda"',
            1,
        ),
        encoding="utf-8",
    )
    assert any("byte-exact" in item for item in drift_errors(corrupted))


def test_generated_route_verifier_rejects_self_consistent_embedded_digest_drift(
    tmp_path: Path,
) -> None:
    expected = render_governed_js()
    forged_digest = "sha256:" + "0" * 64
    corrupted = tmp_path / "governed-self-consistent-forgery.js"
    corrupted.write_text(
        expected.replace('"equities_master": "jquants"', '"equities_master": "jsda"')
        .replace(
            "sha256:1f72a99e049e9519827fb045db50c56863835c0b0183f52989f42d7c378b9f92",
            forged_digest,
        ),
        encoding="utf-8",
    )
    assert any("byte-exact" in item for item in drift_errors(corrupted))


def test_generated_route_verifier_rejects_appended_executable_and_duplicates(
    tmp_path: Path,
) -> None:
    expected = render_governed_js()
    variants = {
        "appended-executable": expected + "\nglobalThis.routingAuthorityBypass = true;\n",
        "duplicate-export": expected
        + "\nexport const GOVERNED_MEMBERSHIP_DIGEST = \"sha256:duplicate\";\n",
        "comment-export-mismatch": expected.replace(
            "membership_digest=sha256:1ae6eae118d6c5a2340b8834ec020cd46072800837aac10c1c8f68fc19b5b343",
            "membership_digest=sha256:" + "f" * 64,
            1,
        ),
    }
    for name, body in variants.items():
        corrupted = tmp_path / f"{name}.js"
        corrupted.write_text(body, encoding="utf-8")
        assert any("byte-exact" in item for item in drift_errors(corrupted)), name
