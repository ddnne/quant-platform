"""Byte-exact tests for the generated Quant Ops routing authority."""

from __future__ import annotations

from pathlib import Path

from scripts.generate_governed_js import governed_contract, render_governed_js
from scripts.verify_governed_js_drift import drift_errors


def test_generated_governed_membership_and_canonical_routes_are_exact() -> None:
    ids, sources, *_ = governed_contract()
    assert set(ids) < set(sources)
    assert sources["equities_trades"] == "jquants"
    assert {
        dataset for dataset, source in sources.items() if source == "jsda"
    } == {
        "jsda_corporate_bond_transactions",
        "jsda_otc_bond_reference_prices",
        "jsda_tokyo_repo_rates",
    }
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


def test_generated_route_verifier_rejects_mapping_and_embedded_digest_drift(
    tmp_path: Path,
) -> None:
    _, _, _, source_digest = governed_contract()
    expected = render_governed_js()
    forged_digest = "sha256:" + "0" * 64
    corrupted = tmp_path / "governed-mapping-and-digest-drift.js"
    corrupted.write_text(
        expected.replace('"equities_master": "jquants"', '"equities_master": "jsda"')
        .replace(
            source_digest,
            forged_digest,
        ),
        encoding="utf-8",
    )
    assert any("byte-exact" in item for item in drift_errors(corrupted))


def test_generated_route_verifier_rejects_appended_executable_and_duplicates(
    tmp_path: Path,
) -> None:
    _, _, membership_digest, _ = governed_contract()
    expected = render_governed_js()
    variants = {
        "appended-executable": expected + "\nglobalThis.routingAuthorityBypass = true;\n",
        "duplicate-export": expected
        + "\nexport const GOVERNED_MEMBERSHIP_DIGEST = \"sha256:duplicate\";\n",
        "comment-export-mismatch": expected.replace(
            f"membership_digest={membership_digest}",
            "membership_digest=sha256:" + "f" * 64,
            1,
        ),
    }
    for name, body in variants.items():
        corrupted = tmp_path / f"{name}.js"
        corrupted.write_text(body, encoding="utf-8")
        assert any("byte-exact" in item for item in drift_errors(corrupted)), name
