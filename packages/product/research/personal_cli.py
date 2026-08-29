"""Command-line entry point for bounded personal DRAFT research."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Sequence

from execution.personal_paper_service import PersonalPaperExecutionRejected
from paper_runtime.personal_snapshot import PersonalSnapshotError
from research.dependency_closure import PlanDependencyClosureError
from research.personal_service import (
    DEFAULT_PERSONAL_UNIVERSE_ID,
    PERSONAL_EXECUTABLE_COHORT_IDS,
    PERSONAL_UNIVERSE_IDS,
    PersonalResearchInputError,
    PersonalResearchRequest,
    PersonalResearchService,
)
from selection.budget_ledger import MassResearchDisabledError
from strategies.spec import StrategySpec, StrategySpecError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="qp-research",
        description=(
            "Run deterministic DRAFT-only research against an immutable copy "
            "of one SQLite snapshot."
        ),
    )
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--end", required=True, help="inclusive ISO date")
    parser.add_argument("--start", help="inclusive ISO date; defaults to five years")
    parser.add_argument(
        "--universe",
        choices=PERSONAL_UNIVERSE_IDS,
        default=DEFAULT_PERSONAL_UNIVERSE_ID,
        help=(
            "closed PIT TOPIX selector (default: topix_all, each intersected "
            "with PIT-visible financials)"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/personal-research"),
        help="artifact directory (default: artifacts/personal-research)",
    )
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument(
        "--cohort",
        choices=PERSONAL_EXECUTABLE_COHORT_IDS,
        help="closed four-candidate factor cohort",
    )
    selection.add_argument(
        "--spec",
        action="append",
        type=Path,
        default=[],
        help="StrategySpec JSON file; repeat for 1-12 candidates",
    )
    return parser


def _load_specs(paths: Sequence[Path]) -> tuple[StrategySpec, ...] | None:
    if not paths:
        return None
    specs: list[StrategySpec] = []
    for path in paths:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PersonalResearchInputError(
                f"cannot read StrategySpec JSON: {path}"
            ) from exc
        documents = document if isinstance(document, list) else [document]
        for item in documents:
            specs.append(StrategySpec.from_dict(item))
    return tuple(specs)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        specs = _load_specs(args.spec)
        result = PersonalResearchService().run(
            PersonalResearchRequest(
                source_db=args.db,
                period_start=args.start,
                period_end=args.end,
                output_root=args.output,
                specs=specs,
                cohort_id=args.cohort,
                universe_id=args.universe,
            )
        )
    except (
        PersonalResearchInputError,
        PersonalSnapshotError,
        PersonalPaperExecutionRejected,
        PlanDependencyClosureError,
        MassResearchDisabledError,
        StrategySpecError,
        sqlite3.Error,
    ) as exc:
        print(f"qp-research: invalid input or data: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # pragma: no cover - terminal diagnostic
        print(
            f"qp-research: unexpected failure: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1

    print(
        json.dumps(
            {
                "report_id": result.report_id,
                "report_json": str(result.report_json_path),
                "report_markdown": str(result.report_markdown_path),
                "snapshot_id": result.snapshot.snapshot_id,
                "logical_data_snapshot_id": result.snapshot.logical_data_snapshot_id,
                "candidate_count": result.candidate_count,
                "evaluated_count": result.evaluated_count,
                "hold_count": result.hold_count,
                "unexpected_errors": result.unexpected_errors,
                "cohort_id": result.cohort_id,
                "cohort_digest": result.cohort_digest,
                "universe_id": result.universe_id,
                "universe_rule_digest": result.universe_rule_digest,
                "live_orders_enabled": False,
                "automatic_promotion": False,
                "model_calls": 0,
                "estimated_ai_cost_usd": 0.0,
                "go": False,
                "ready_snapshot_declared": False,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return result.exit_code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["main"]
