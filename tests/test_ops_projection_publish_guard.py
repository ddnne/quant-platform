"""Unit tests for enforce_complete_count_guard (fail-closed semantics)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from scripts.publish_ops_projection import enforce_complete_count_guard


class TestEnforceCompleteCountGuard:
    def test_refuse_when_remote_none(self) -> None:
        msg = enforce_complete_count_guard(
            local_complete=10, remote_complete=None
        )
        assert msg is not None
        assert "could not read remote COMPLETE" in msg
        assert "fail-closed" in msg

    def test_refuse_when_local_less_than_remote(self) -> None:
        msg = enforce_complete_count_guard(
            local_complete=5, remote_complete=6
        )
        assert msg is not None
        assert "local COMPLETE segments (5)" in msg
        assert "fewer than remote (6)" in msg

    def test_pass_when_local_equals_remote(self) -> None:
        assert (
            enforce_complete_count_guard(
                local_complete=7, remote_complete=7
            )
            is None
        )

    def test_pass_when_local_greater_than_remote(self) -> None:
        assert (
            enforce_complete_count_guard(
                local_complete=20, remote_complete=7
            )
            is None
        )

    def test_pass_when_remote_zero(self) -> None:
        # Fresh remote (no COMPLETE) must not block initial publish
        assert (
            enforce_complete_count_guard(
                local_complete=1, remote_complete=0
            )
            is None
        )

    def test_pass_when_both_zero(self) -> None:
        assert (
            enforce_complete_count_guard(
                local_complete=0, remote_complete=0
            )
            is None
        )

    def test_remote_zero_not_treated_as_unknown(self) -> None:
        # 0 is a valid probed value; only None triggers fail-closed
        msg_none = enforce_complete_count_guard(
            local_complete=0, remote_complete=None
        )
        msg_zero = enforce_complete_count_guard(
            local_complete=0, remote_complete=0
        )
        assert msg_none is not None
        assert msg_zero is None

    def test_negative_local_still_refused_when_remote_known(self) -> None:
        # Defensive: guard arithmetic must not silently pass bogus negatives
        msg = enforce_complete_count_guard(
            local_complete=-1, remote_complete=0
        )
        assert msg is not None

    def test_error_messages_expose_no_generic_override(self) -> None:
        for remote in (None, 100):
            msg = enforce_complete_count_guard(
                local_complete=1, remote_complete=remote
            )
            assert msg is not None
            assert "--force-apply-remote" not in msg

    def test_force_override_is_not_part_of_the_api(self) -> None:
        with pytest.raises(TypeError, match="unexpected keyword argument 'force'"):
            enforce_complete_count_guard(
                local_complete=1, remote_complete=100, force=True
            )
