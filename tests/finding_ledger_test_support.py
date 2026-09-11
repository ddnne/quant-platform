"""Pure fixture-owned finding-ledger documents for tests."""

from __future__ import annotations

from copy import deepcopy


def controlled_ledger_document(
    document: dict, *, open_p0_ids: tuple[str, ...] = ()
) -> dict:
    value = deepcopy(document)
    value["merge_policy"]["independent_review_unresolved_p0"] = 0
    requested_open = frozenset(open_p0_ids)
    for finding in value["findings"]:
        finding["evidence"] = "test-owned-fixture-evidence"
        finding["closure"] = "test-owned-fixture-closure"
        if finding["severity"] == "P0":
            finding["status"] = "OPEN" if finding["id"] in requested_open else "FIXED"
    return value
