"""Local publisher CLI is not a production authority."""

from __future__ import annotations

from scripts.publish_ops_projection import main


def test_local_publisher_refuses_remote_and_offline_apply() -> None:
    assert main(["--apply-remote"]) == 7
    assert main(["--dry-run"]) == 7
