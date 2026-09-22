"""The three verdicts, and the promise that the file is always put back."""
from __future__ import annotations

import sys
from pathlib import Path

import negative_control as nc


def _project(tmp_path: Path, test_body: str) -> Path:
    (tmp_path / "rule.py").write_text("def limit():\n    return 10\n", encoding="utf-8")
    (tmp_path / "pytest.ini").write_text("[pytest]\npythonpath = .\n", encoding="utf-8")
    (tmp_path / "test_rule.py").write_text(
        "from rule import limit\n\n\ndef test_limit():\n" + test_body, encoding="utf-8"
    )
    return tmp_path


def _break(**overrides) -> nc.Mutation:
    fields = dict(file="rule.py", replace="return 10", with_="return 11",
                  test="test_rule.py", label="limit changes")
    fields.update(overrides)
    return nc.Mutation(**fields)


def test_a_test_that_catches_the_break_is_red(tmp_path):
    root = _project(tmp_path, "    assert limit() == 10\n")
    verdict, _ = nc.run_one(_break(), root=root, python=sys.executable)
    assert verdict == "red"


def test_a_test_that_does_not_catch_it_is_green(tmp_path):
    # The weak test: passes before and after the break.
    root = _project(tmp_path, "    assert limit() > 0\n")
    verdict, _ = nc.run_one(_break(), root=root, python=sys.executable)
    assert verdict == "green"


def test_text_that_is_not_there_is_broken_not_green(tmp_path):
    """No break applied means no result. Calling it green would say the test
    has no teeth, when in fact nothing was measured."""
    root = _project(tmp_path, "    assert limit() == 10\n")
    verdict, _ = nc.run_one(_break(replace="return 99"), root=root, python=sys.executable)
    assert verdict == "broken"


def test_a_collection_error_is_broken_not_green(tmp_path):
    """The bug that made this tool judge by exit code: a collection error
    prints '1 error', with no 'failed' in it."""
    root = _project(tmp_path, "    assert limit() == 10\n")
    verdict, _ = nc.run_one(
        _break(with_="return (", label="syntax error"), root=root, python=sys.executable
    )
    assert verdict == "broken"


def test_the_file_is_restored_whatever_the_verdict(tmp_path):
    root = _project(tmp_path, "    assert limit() == 10\n")
    before = (root / "rule.py").read_text(encoding="utf-8")
    for mutation in (_break(), _break(with_="return ("), _break(replace="return 99")):
        nc.run_one(mutation, root=root, python=sys.executable)
        assert (root / "rule.py").read_text(encoding="utf-8") == before
