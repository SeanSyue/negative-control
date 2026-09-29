"""A test that already fails turns red whatever the break does.

An earlier version counted that red as "caught the break". The tool now runs
each test once on the untouched code; if it does not pass, there is no result.
"""
from __future__ import annotations

import sys

import negative_control as nc


def _project(tmp_path, test_body: str):
    (tmp_path / "rule.py").write_text("def limit():\n    return 10\n", encoding="utf-8")
    (tmp_path / "pytest.ini").write_text("[pytest]\npythonpath = .\n", encoding="utf-8")
    (tmp_path / "test_rule.py").write_text(
        "from rule import limit\n\n\ndef test_limit():\n" + test_body, encoding="utf-8"
    )
    return tmp_path


BREAK = nc.Mutation(file="rule.py", replace="return 10", with_="return 11",
                    test="test_rule.py", label="limit changes")


def test_a_test_that_fails_before_the_break_is_broken_not_red(tmp_path):
    root = _project(tmp_path, "    assert False\n")
    verdict, detail = nc.run_one(BREAK, root=root, python=sys.executable)
    assert verdict == "broken", detail
    assert "before anything is broken" in detail


def test_a_test_that_passes_first_can_still_be_red(tmp_path):
    root = _project(tmp_path, "    assert limit() == 10\n")
    verdict, _ = nc.run_one(BREAK, root=root, python=sys.executable)
    assert verdict == "red"


def test_the_first_run_happens_on_the_untouched_file(tmp_path):
    """The file must still hold the original text after a broken baseline."""
    root = _project(tmp_path, "    assert False\n")
    before = (root / "rule.py").read_bytes()
    nc.run_one(BREAK, root=root, python=sys.executable)
    assert (root / "rule.py").read_bytes() == before
