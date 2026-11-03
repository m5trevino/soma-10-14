"""Integration tests for the ATM clean-room wiring in the active Drafter.

Verifies the code-generation stage writes exclusively inside a CleanRoom: the
payload lands in the workspace, the sterile /tmp room is wiped afterward, an
escaping path is refused, and no directory-scanning tool is part of the
agent's surface.
"""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from store import Soma
from drafter_dendrite import DrafterDendrite
from pipeline import atm_runner
from pipeline.atm_runner import AGENT_TOOLSET, STRIPPED_TOOLS


@pytest.fixture
def drafter():
    # _write_draft_file does not touch Soma or the LLM client, so an empty
    # in-memory store and a null client are enough to construct a real
    # DrafterDendrite.
    return DrafterDendrite(Soma(), None)


def _patch_roots(tmp_path, monkeypatch):
    """Point the workspace and the ATM root at pytest's temp dir."""
    monkeypatch.setattr(
        DrafterDendrite, "_get_workspace_path",
        lambda self, sid: tmp_path / "workspace" / sid,
    )
    monkeypatch.setattr(atm_runner, "ATM_ROOT", tmp_path / "atm")


def test_draft_write_stages_through_cleanroom(tmp_path, monkeypatch, drafter):
    _patch_roots(tmp_path, monkeypatch)

    out = drafter._write_draft_file("sess-1", "app/main.py", "print('hi')")

    assert out is not None
    written = Path(out)
    assert written.is_file()
    assert written.read_text() == "print('hi')"

    # The clean room must be completely wiped after the write.
    atm_root = tmp_path / "atm"
    assert not list(atm_root.glob("dendritic_atm_*")), \
        "clean room residue left behind"


def test_draft_escape_is_refused(tmp_path, monkeypatch, drafter):
    _patch_roots(tmp_path, monkeypatch)
    out = drafter._write_draft_file("sess-1", "../../etc/passwd", "evil")
    assert out is None


def test_agent_toolset_has_no_scan_tools():
    assert set(AGENT_TOOLSET) == {"read_file", "write_file"}
    assert set(STRIPPED_TOOLS) == {"ls", "grep", "find", "explorer"}
    assert set(AGENT_TOOLSET).isdisjoint(STRIPPED_TOOLS)
