"""Two runs on one tree would save each other's broken file as the original.

These tests run the tool as a real subprocess, so they run it on a **copy**
of the example. When this repository checks itself, a deliberately broken
tool runs here - and whatever it leaves behind (a lock it never released)
must land in a temporary folder, not in `example/`. An earlier version of
this file used `example/` directly, and the self-check left two lock files
there that blocked the next run.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[1] / "negative_control.py"
EXAMPLE = Path(__file__).resolve().parents[1] / "example"


@pytest.fixture
def project(tmp_path):
    copy = tmp_path / "example"
    shutil.copytree(EXAMPLE, copy)
    return copy


def _run(root, *args):
    return subprocess.run([sys.executable, str(TOOL), *args], cwd=root,
                          capture_output=True, text=True, encoding="utf-8")


def test_a_second_run_is_turned_away(project):
    lock = project / ".negative_control.lock"
    lock.write_text("pid 0 (placed by a test)", encoding="utf-8")
    proc = _run(project, "--check")
    assert proc.returncode == 3, "the second run went ahead"
    assert "Another negative-control run" in proc.stderr
    assert ".negative_control.lock" in proc.stderr, "it did not say where the lock is"


@pytest.mark.parametrize("form", ["--root=", "--root "])
def test_the_lock_is_on_the_root_being_changed_not_the_current_folder(project, tmp_path, form):
    """An earlier version found --root by scanning for the exact token, missed
    `--root=path`, and locked the current folder. Two runs from different
    folders then broke the same file, and one break stayed in it for good."""
    (project / ".negative_control.lock").write_text("pid 0 (placed by a test)", encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    args = [f"--root={project}"] if form == "--root=" else ["--root", str(project)]
    proc = _run(elsewhere, *args, "--check")
    assert proc.returncode == 3, f"a second run on the same root went ahead ({form})"
    assert not (elsewhere / ".negative_control.lock").exists()


def test_a_normal_run_releases_the_lock(project):
    proc = _run(project, "--check")
    assert proc.returncode != 3
    assert not (project / ".negative_control.lock").exists()


def test_the_example_itself_is_left_clean():
    """Nothing this suite does may leave a file in the real example."""
    leftovers = sorted(p.name for p in EXAMPLE.glob(".negative_control.lock*"))
    assert leftovers == [], f"left behind in example/: {leftovers}"
