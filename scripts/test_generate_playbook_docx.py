"""Smoke tests for scripts/generate_playbook_docx.py.

Skips entirely when python-docx is not installed (it lives in the local
.venv-docx managed by `make playbook-docx`, not in CI or the system
interpreter) — same optional-dependency posture as iterate_cross_docx.
"""

import os
import sys

import pytest

docx = pytest.importorskip("docx")

sys.path.insert(0, os.path.dirname(__file__))

import generate_playbook_docx as gen  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _generate(tmp_path):
    out = tmp_path / "playbook.docx"
    argv = sys.argv
    sys.argv = ["generate_playbook_docx.py", "--repo", REPO, "--out", str(out)]
    try:
        gen.main()
    finally:
        sys.argv = argv
    return out


def test_generates_openable_docx(tmp_path):
    out = _generate(tmp_path)
    assert out.exists() and out.stat().st_size > 10000
    doc = docx.Document(str(out))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "Google Ads Playbook" in text


def test_all_three_sections_render_as_banners(tmp_path):
    out = _generate(tmp_path)
    doc = docx.Document(str(out))
    cells = [c.text for t in doc.tables for r in t.rows for c in r.cells]
    for banner_title in (
        "Phase 1 Playbook",
        "Phase 2 Playbook (Value Screen)",
        "Appendix — Cost Model (lead-facing economics)",
    ):
        assert any(banner_title == c.strip() for c in cells), banner_title


def test_body_carries_current_playbook_content(tmp_path):
    out = _generate(tmp_path)
    doc = docx.Document(str(out))
    everything = "\n".join(p.text for p in doc.paragraphs) + "\n".join(
        c.text for t in doc.tables for r in t.rows for c in r.cells
    )
    # One marker per hardening batch: probe field (PR #2015), utm suffix
    # (#1728), stalled detection (#1912) — proves the docx tracks the md.
    for marker in (
        "dayzero_probe_passed_at",
        "utm_source=google&utm_medium=cpc",
        "bid-capped shortfall",
    ):
        assert marker in everything, marker


def test_slice_section_unknown_heading_exits():
    with pytest.raises(SystemExit):
        gen.slice_section("# nope\n", "Missing Section")
