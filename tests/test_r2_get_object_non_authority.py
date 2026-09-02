"""Exercise the bounded remote R2 read adapter through its public behavior."""

from pathlib import Path
from types import SimpleNamespace

import ops.r2_cli as r2_cli
from ops.r2_io import default_r2_get_object


def test_default_r2_get_object_uses_pinned_remote_read(
    tmp_path: Path, monkeypatch
) -> None:
    wrangler = tmp_path / "wrangler"
    wrangler.write_text("#!/bin/sh\n", encoding="utf-8")
    config = tmp_path / "wrangler.toml"
    config.write_text("name = 'test'\n", encoding="utf-8")
    seen: dict[str, object] = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = list(cmd)
        seen["kwargs"] = kwargs
        output_arg = next(part for part in cmd if part.startswith("--file="))
        Path(output_arg.removeprefix("--file=")).write_bytes(b"payload")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(r2_cli.subprocess, "run", fake_run)
    assert default_r2_get_object(
        "quant-structured",
        "research/eval/job=x/result.json",
        wrangler=wrangler,
        config=config,
    ) == b"payload"
    cmd = seen["cmd"]
    assert cmd[:4] == [
        str(wrangler),
        "r2",
        "object",
        "get",
    ]
    assert "quant-structured/research/eval/job=x/result.json" in cmd
    assert "--remote" in cmd
    assert f"--config={config}" in cmd
