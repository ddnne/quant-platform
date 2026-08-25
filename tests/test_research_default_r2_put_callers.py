"""Glob research *.py: default_r2_put( callers stay in r2_io.py."""

from pathlib import Path

RESEARCH = Path(__file__).resolve().parents[1] / "packages" / "product" / "research"


def test_research_default_r2_put_callers_stay_in_r2_io() -> None:
    r2_io = RESEARCH / "r2_io.py"
    assert "def default_r2_put" in r2_io.read_text(encoding="utf-8")

    offenders: list[str] = []
    recon = ""
    for path in sorted(RESEARCH.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        src = path.read_text(encoding="utf-8")
        if path.relative_to(RESEARCH) == Path("r2_io.py"):
            continue
        if "default_r2_put(" in src:
            offenders.append(str(path.relative_to(RESEARCH)))
        if path.name == "reconstitution_evidence.py":
            recon = src
    assert not offenders, "default_r2_put( outside r2_io.py: " + ", ".join(offenders)
    assert recon
    assert "put_research_artifact" in recon
    assert "dry_run=True" in recon
