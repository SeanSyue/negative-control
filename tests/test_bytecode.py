"""The second break must not run as the first one.

CPython treats a cached .pyc as valid when the source's mtime (whole seconds)
and size match. Two breaks of the same size in the same second used to run
the first break's code - and the second was reported as 'no teeth'.
"""
from __future__ import annotations

import importlib.util
import os
import sys

import negative_control as nc


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.ANSWER


def test_the_second_break_is_not_run_as_the_first(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "dont_write_bytecode", False)
    victim = tmp_path / "victim.py"
    same_second = (1_700_000_000, 1_700_000_000)

    victim.write_text("ANSWER = 'first'\n", encoding="utf-8")
    os.utime(victim, same_second)
    assert _load(victim, "_v1") == "first"
    assert list((tmp_path / "__pycache__").glob("victim.*.pyc")), (
        "no .pyc was written, so this test cannot show what it is meant to show"
    )

    victim.write_text("ANSWER = 'secnd'\n", encoding="utf-8")  # same size
    os.utime(victim, same_second)
    assert _load(victim, "_v2") == "first", "the stale-cache danger did not reproduce"

    nc._drop_stale_bytecode(victim)
    assert _load(victim, "_v3") == "secnd"
