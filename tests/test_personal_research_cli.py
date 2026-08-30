"""CLI contract for personal paper research."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from research import personal_cli


def test_cli_returns_two_for_missing_database(tmp_path: Path, capsys) -> None:
    code = personal_cli.main(
        ["--db", str(tmp_path / "missing.sqlite"), "--end", "2026-08-27"]
    )
    assert code == 2
    assert "database does not exist" in capsys.readouterr().err


def test_cli_prints_machine_readable_artifact_summary(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    database = tmp_path / "input.sqlite"
    database.touch()
    report_json = tmp_path / "report.json"
    report_markdown = tmp_path / "report.md"
    base_sleeve = tmp_path / "base-sleeve" / ("6" * 64 + ".json")

    class FakeService:
        def run(self, request):
            assert request.source_db == database
            assert request.period_end == "2026-08-27"
            assert request.cohort_id == "sector-relative-ls-v1"
            assert request.universe_id == "topix_all"
            return SimpleNamespace(
                report_id="sha256:" + "1" * 64,
                report_json_path=report_json,
                report_markdown_path=report_markdown,
                snapshot=SimpleNamespace(
                    snapshot_id="sha256:" + "2" * 64,
                    logical_data_snapshot_id="sha256:" + "3" * 64,
                ),
                candidate_count=4,
                evaluated_count=4,
                hold_count=0,
                unexpected_errors=0,
                cohort_id="sector-relative-ls-v1",
                cohort_digest="sha256:" + "4" * 64,
                universe_id="topix_all",
                universe_rule_digest="sha256:" + "5" * 64,
                base_sleeve_artifact_path=base_sleeve,
                base_sleeve_artifact_digest="sha256:" + "6" * 64,
                base_sleeve_archive_member=f"base-sleeve/{'6' * 64}.json",
                non_candidate_source_backtest_count=1,
                exit_code=0,
            )

    monkeypatch.setattr(personal_cli, "PersonalResearchService", FakeService)
    code = personal_cli.main(
        [
            "--db",
            str(database),
            "--end",
            "2026-08-27",
            "--output",
            str(tmp_path),
            "--cohort",
            "sector-relative-ls-v1",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["candidate_count"] == 4
    assert payload["evaluated_count"] == 4
    assert payload["hold_count"] == 0
    assert payload["cohort_id"] == "sector-relative-ls-v1"
    assert payload["cohort_digest"] == "sha256:" + "4" * 64
    assert payload["universe_id"] == "topix_all"
    assert payload["universe_rule_digest"] == "sha256:" + "5" * 64
    assert payload["base_sleeve_artifact"] == {
        "archive_member": f"base-sleeve/{'6' * 64}.json",
        "artifact_schema_version": "personal-base-sleeve-source/v1",
        "candidate_count_contribution": 0,
        "cohort_id": "sector-relative-ls-v1",
        "path": str(base_sleeve),
        "ranking_role": "NON_CANDIDATE_NOT_RANKED",
        "role": "INDEX_VOL_OVERLAY_BASE_SOURCE",
        "schema_version": "personal-base-sleeve-reference/v1",
        "sha256": "sha256:" + "6" * 64,
        "strategy_id": "personal_sector_balanced_four_factor_v1_ls",
        "universe_id": "topix_all",
    }
    assert payload["non_candidate_source_backtest_count"] == 1
    assert payload["live_orders_enabled"] is False
    assert payload["automatic_promotion"] is False
    assert payload["model_calls"] == 0
    assert payload["estimated_ai_cost_usd"] == 0.0
