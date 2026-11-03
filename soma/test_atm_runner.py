"""Unit tests for the ATM clean-room isolation (TB-ATM-001).

Each test uses pytest's tmp_path as the room root so nothing touches the real
/tmp and every run is isolated.
"""
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))

from pipeline.atm_runner import (
    AGENT_TOOLSET,
    STRIPPED_TOOLS,
    CleanRoom,
    CleanRoomError,
)


def _room(tmp_path: Path, *args, **kwargs) -> CleanRoom:
    return CleanRoom(*args, root=tmp_path, **kwargs)


def test_read_write_roundtrip(tmp_path):
    with _room(tmp_path, "T-roundtrip") as room:
        room.write_file("out.py", "print('x')")
        assert room.read_file("out.py") == "print('x')"


def test_target_is_the_only_file_seeded(tmp_path):
    target = tmp_path / "target.py"
    target.write_text("original")

    with _room(tmp_path, "T-seed", target=target) as room:
        names = sorted(p.name for p in room.root.iterdir())
        assert names == ["target.py"]
        assert room.read_file("target.py") == "original"


def test_missing_target_seeds_empty_stub(tmp_path):
    missing = tmp_path / "does-not-exist.py"
    with _room(tmp_path, "T-stub", target=missing, stub="# stub") as room:
        assert room.read_file("does-not-exist.py") == "# stub"


def test_absolute_path_is_rejected(tmp_path):
    with _room(tmp_path, "T-abs") as room:
        with pytest.raises(CleanRoomError):
            room.read_file("/etc/passwd")
        with pytest.raises(CleanRoomError):
            room.write_file("/etc/passwd", "x")


def test_parent_traversal_is_rejected(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("do not read")

    with _room(tmp_path, "T-traverse") as room:
        with pytest.raises(CleanRoomError):
            room.read_file("../secret.txt")
        with pytest.raises(CleanRoomError):
            room.read_file("../../secret.txt")


def test_room_is_wiped_after_execution(tmp_path):
    room = _room(tmp_path, "T-wipe")
    with room:
        room.write_file("x.py", "x")
    assert not room.root.exists()


def test_stale_room_is_wiped_on_entry(tmp_path):
    room = _room(tmp_path, "T-stale")
    with room:
        room.write_file("leftover.py", "bleed")
    # Re-enter: any residue from the prior run must be gone.
    with room:
        assert not any(room.root.iterdir())


def test_scan_tools_are_stripped_from_toolset(tmp_path):
    with _room(tmp_path, "T-tools") as room:
        exposed = set(room.toolset())
        stripped = set(room.stripped())

    assert exposed == {"read_file", "write_file"}
    assert stripped == {"ls", "grep", "find", "explorer"}
    # No scanning tool is present in the exposed toolset.
    assert exposed.isdisjoint(stripped)
