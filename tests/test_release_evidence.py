from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "build_release_evidence.py"
SPEC = importlib.util.spec_from_file_location("build_release_evidence", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


def test_build_envelope_refuses_payload_without_writing() -> None:
    with pytest.raises(
        release.ReleaseObservationAuthorityUnavailable,
        match="release evidence publication is PENDING",
    ):
        release.build_envelope({"collector": "caller-self-claim"})


def test_write_envelope_creates_no_output(tmp_path: Path) -> None:
    output = tmp_path / "release"
    with pytest.raises(
        release.ReleaseObservationAuthorityUnavailable,
        match="authenticated collection/publication implementation is missing",
    ):
        release.write_envelope({"collector": "caller-self-claim"}, output)
    assert not output.exists()
