"""Guard scripts/verify_all.sh as the pre-push entry (no live deploy)."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_all.sh"


def test_verify_all_script_exists_executable_and_bans_legacy_peer_deps() -> None:
    assert SCRIPT.is_file(), SCRIPT
    assert os.access(SCRIPT, os.X_OK), f"{SCRIPT} must be executable"
    src = SCRIPT.read_text(encoding="utf-8")
    assert "legacy-peer-deps" in src
    assert "VERIFY_NPM_CI" in src
    assert "VERIFY_NPM_TYPECHECK" in src
    assert "VERIFY_NPM_BUILD" in src
    for i, line in enumerate(src.splitlines(), start=1):
        code = line.split("#", 1)[0]
        assert "--legacy-peer-deps" not in code, (
            f"{SCRIPT}:{i} must not pass --legacy-peer-deps"
        )
