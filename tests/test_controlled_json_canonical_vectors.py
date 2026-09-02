from __future__ import annotations

import json
from pathlib import Path

import pytest

from paper_runtime.canonical_json import CanonicalJsonError, canonical_json_dumps


_VECTORS = (
    Path(__file__).resolve().parents[1]
    / "specs"
    / "ready"
    / "controlled_json_canonical_vectors.json"
)


def _runtime_number(name: str) -> float:
    return {
        "NaN": float("nan"),
        "Infinity": float("inf"),
        "-Infinity": float("-inf"),
    }[name]


def test_python_controlled_json_matches_shared_golden_vectors() -> None:
    document = json.loads(_VECTORS.read_text(encoding="utf-8"))
    assert document["schema_version"] == "controlled-json-canonical-v1"
    for vector in document["vectors"]:
        value = (
            json.loads(vector["input_json"])
            if "input_json" in vector
            else _runtime_number(vector["runtime_number"])
        )
        if "reject" in vector:
            with pytest.raises(CanonicalJsonError):
                canonical_json_dumps(value)
        else:
            assert canonical_json_dumps(value) == vector["canonical_json"]


@pytest.mark.parametrize("value", [{1: "non-string"}, {"x": object()}])
def test_python_controlled_json_rejects_values_outside_closed_json(value: object) -> None:
    with pytest.raises(CanonicalJsonError):
        canonical_json_dumps(value)
