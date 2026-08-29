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
        "--output",
        type=Path,
        default=Path("artifacts/personal-research"),
        help="artifact directory (default: artifacts/personal-research)",
    )
    parser.add_argument(
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
                "live_orders_enabled": False,
                "automatic_promotion": False,
                "model_calls": 0,
                "estimated_ai_cost_usd": 0.0,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return result.exit_code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["main"]
