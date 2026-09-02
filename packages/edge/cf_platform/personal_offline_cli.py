"""Edge/ops composition for offline personal DRAFT research.

Filesystem and env parsing live here. Product receives only a typed
``OfflineFixtureDataView``. Persistent local SQLite is opt-in recovery only.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Sequence

from execution.personal_paper_service import PersonalPaperExecutionRejected
from paper_runtime.personal_snapshot import PersonalSnapshotError
from pit import PitError
from pit.personal_research_view import (
    OfflineFixtureDataView,
    PersonalResearchViewError,
)
from research.dependency_closure import PlanDependencyClosureError
from research.personal_base_sleeve import PERSONAL_BASE_SLEEVE_REFERENCE_SCHEMA
from research.factor_cohorts import (
    DEFAULT_FACTOR_COHORT_ID,
    LEGACY_PERSONAL_EXECUTABLE_COHORT_IDS,
)
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

LOCAL_MARKET_DATA_ENV = "QP_ALLOW_LOCAL_MARKET_DATA"
LOCAL_MARKET_DATA_DISABLED = (
    "local market data is disabled; persistent local SQLite is not the operator "
    "path. Use Cloudflare POST /v1/personal-snapshot-build, GET "
    "/v1/personal-snapshot-build/<job_id>, and POST /v1/personal-research-batch "
    "(R2 is authoritative; Container SQLite is ephemeral). Set "
    f"{LOCAL_MARKET_DATA_ENV}=1 only for developer/recovery compatibility."
)


def local_market_data_allowed() -> bool:
    """True only when ``QP_ALLOW_LOCAL_MARKET_DATA=1`` (exact).

    Any other value, including unset, denies opening or copying a market
    SQLite. Cloud Container composition binds an ephemeral snapshot through
    ``ContainerEphemeralDataView`` and does not set this env globally or
    launch ``qp-research``.
    """
    return os.environ.get(LOCAL_MARKET_DATA_ENV) == "1"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="qp-research",
        description=(
            "Developer/recovery compatibility for deterministic DRAFT-only "
            "research against an immutable copy of one SQLite snapshot. "
            "Persistent local market data is disabled unless "
            f"{LOCAL_MARKET_DATA_ENV}=1. The normal operator path is "
            "Cloudflare personal-snapshot-build/status and "
            "personal-research-batch. Default factor selection is "
            f"{DEFAULT_FACTOR_COHORT_ID} (AM-signal same-day PM-close). "
            "Explicit legacy *-v1 cohorts remain next-close replay."
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
        help=(
            "closed four-candidate factor cohort; omit with no --spec to use "
            f"{DEFAULT_FACTOR_COHORT_ID} (AM-signal same-day PM-close). "
            "Legacy *-v1 ids stay next-close replay"
        ),
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
        if not local_market_data_allowed():
            raise PersonalResearchInputError(LOCAL_MARKET_DATA_DISABLED)
        specs = _load_specs(args.spec)
        cohort_id = args.cohort
        if specs is None and cohort_id is None:
            cohort_id = DEFAULT_FACTOR_COHORT_ID
        cutoff = "morning_close"
        if cohort_id in LEGACY_PERSONAL_EXECUTABLE_COHORT_IDS or (
            specs is not None and cohort_id is None
        ):
            cutoff = "session_close"
        view = OfflineFixtureDataView.bind(
            args.db, artifact_root=args.output, decision_cutoff=cutoff
        )
        result = PersonalResearchService().run(
            PersonalResearchRequest(
                data_view=view,
                period_start=args.start,
                period_end=args.end,
                specs=specs,
                cohort_id=cohort_id,
                universe_id=args.universe,
            )
        )
    except (
        PersonalResearchInputError,
        PersonalResearchViewError,
        PersonalSnapshotError,
        PersonalPaperExecutionRejected,
        PlanDependencyClosureError,
        MassResearchDisabledError,
        StrategySpecError,
        PitError,
    ) as exc:
        print(f"qp-research: invalid input or data: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # pragma: no cover - terminal diagnostic
        print(
            f"qp-research: unexpected failure: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1

    returned_reference = getattr(result, "base_sleeve_artifact", None)
    if isinstance(returned_reference, dict):
        base_sleeve_artifact = dict(returned_reference)
        base_sleeve_artifact.pop("path", None)
        if base_sleeve_artifact.get("schema_version") != PERSONAL_BASE_SLEEVE_REFERENCE_SCHEMA:
            raise PersonalResearchInputError(
                "base sleeve reference schema mismatch"
            )
    elif returned_reference is not None:
        raise PersonalResearchInputError(
            "base sleeve artifact reference is invalid"
        )
    else:
        base_sleeve_artifact = None
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
                "execution_mode": getattr(
                    result, "execution_mode", "next_close"
                ),
                "execution_contract_digest": getattr(
                    result, "execution_contract_digest", None
                ),
                "base_sleeve_artifact": base_sleeve_artifact,
                "non_candidate_source_backtest_count": getattr(
                    result, "non_candidate_source_backtest_count", 0
                ),
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


__all__ = [
    "LOCAL_MARKET_DATA_DISABLED",
    "LOCAL_MARKET_DATA_ENV",
    "local_market_data_allowed",
    "main",
]
