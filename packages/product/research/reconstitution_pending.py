"""Print HUMAN_RECONSTITUTION_PENDING pack. Detect-only. Does not apply. Not GO."""
from __future__ import annotations

import json
from typing import Any, Mapping

from research.eval_flags import RECONSTITUTION_APPLY


def pending_reconstitution_pack(
    occupancy_by_track: Mapping[str, Mapping[str, float]] | None = None,
) -> dict[str, Any]:
    """Pending sleeves from reconstitution_occupancy_preview.

    Does not choose drop_parents vs drop_children. Does not restitch 24ek.
    Does not flip RECONSTITUTION_APPLY.
    """
    from research.combo_basket_catalog import (
        FLOW_FIFTH_BLEND_THINNER_JOB,
        HUMAN_RECONSTITUTION_PENDING,
        KEEP_BOTH_SLEEVES_JOB,
        reconstitution_occupancy_preview,
    )

    preview = reconstitution_occupancy_preview(occupancy_by_track)
    ids = list(preview.get("human_pending") or HUMAN_RECONSTITUTION_PENDING)
    wanted = set(ids)
    return {
        "version": "reconstitution-pending/v1",
        "preview_exists": True,
        "human_pending": ids,
        "keep_sleeves_job": preview.get("keep_sleeves_job") or KEEP_BOTH_SLEEVES_JOB,
        "flow_fifth_blend_thinner_job": (
            preview.get("flow_fifth_blend_thinner_job") or FLOW_FIFTH_BLEND_THINNER_JOB
        ),
        "do_not_restitch_blend": True,
        "human_choice_required": True,
        "human_only_drop_parents_vs_drop_children": True,
        "do_not_auto_choose": True,
        "apply": bool(preview.get("apply")) and bool(RECONSTITUTION_APPLY),
        "sleeves": [
            s
            for s in (preview.get("sleeves") or [])
            if str(s.get("basket_id") or "") in wanted
        ],
        "go": False,
        "not_a_pass": True,
    }


def main() -> int:
    pack = pending_reconstitution_pack()
    print(json.dumps(pack, ensure_ascii=True, indent=2, default=str))
    return 0 if pack.get("apply") is False and pack.get("go") is False else 2


if __name__ == "__main__":
    raise SystemExit(main())
