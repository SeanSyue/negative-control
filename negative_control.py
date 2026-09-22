"""Break one line, run the test that should catch it, then put it back.

    A green test is not evidence until you have seen it turn red.

This tool makes that rule cheap to follow. A *recipe* says: in this file,
replace this text with that text, then run this test. The tool applies the
change, runs the test, and restores the file from a copy - in a `finally`
block, with a check that the restore actually happened.

Every recipe ends in one of three verdicts:

* **red ✓**      - a test caught the break. This is what you want.
* **green ✗**    - no test turned red. **Deal with this one**: either the
                   assertion has a hole, the test case is too easy, or the
                   break never reached the code being measured.
* **broken ?**   - the tests did not run at all (syntax error, text not
                   found, test renamed, timeout). **This is not green and it
                   is not red - it is no result.**

Why the details below exist
---------------------------
Each of these was a real failure of an earlier version of this tool.

1. **Restore from a copy, never from git.** An early version restored with
   `git checkout -- <file>`. That restores *the last commit*, not *the file
   as it was a second ago* - and it threw away an uncommitted refactor in the
   same file. The file you are testing is usually the one with uncommitted
   work in it.

2. **Judge by pytest's exit code, not by searching the output.** An early
   version looked for the word "failed". A collection error prints "1 error",
   which does not contain "failed", so it was read as **green**. The tool then
   reported "this test has no teeth" about a run in which nothing was checked.
   Reading "the break didn't land" as "the test didn't catch it" leads people
   to delete tests that work. Exit code 1 = tests failed; any other non-zero
   = the run did not happen properly.

3. **No stale bytecode.** CPython decides whether a cached `.pyc` is still
   valid from the source file's mtime (in whole seconds) and its size. Two
   breaks applied within the same second that happen to produce files of the
   same size were run as *the first break* - and the second one was reported
   as "no teeth". This tool deletes the cache for the file on both sides and
   runs every child process with `PYTHONDONTWRITEBYTECODE=1`.

4. **One run at a time.** Two copies of this tool running on the same tree
   will each save the *other one's* broken file as "the original", and after
   restoring, the break stays in the tree for good. The tool takes a lock
   file and refuses to start if another run holds it.

Usage
-----
Run from the root of the project you want to check (or pass `--root`):

    # one break
    python negative_control.py --file src/pricing.py \\
        --replace "if total >= 100:" --with "if total > 100:" \\
        --test tests/test_pricing.py

    # a batch (a JSON array with the same fields)
    python negative_control.py --from mutations/mutations_pricing.json

    # every recipe under mutations/
    python negative_control.py --all

    # only check that every recipe still finds what it breaks (milliseconds)
    python negative_control.py --check

Note: `--replace` changes only the **first** match. If the text appears more
than once, make it longer; `--check` reports recipes whose text matches more
than one place.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

# The verdict marks are ✓ / ✗. A Windows console on a legacy code page cannot
# encode them and the whole run ends in a traceback - *after* every break has
# been run and restored, at the moment the summary is printed. The output is
# the only thing this tool produces, so it must not be lost.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# pytest exit codes. 1 means "tests ran and some failed"; any other non-zero
# code means the run itself did not happen properly.
PYTEST_ALL_PASSED = 0
PYTEST_TESTS_FAILED = 1

# A break can send the code under test into a prompt or dialog nobody answers.
# Wide enough not to kill a normal test file, short enough that nobody gets
# impatient and kills Python by hand - killing it skips the restore.
DEFAULT_TIMEOUT_SECONDS = 180

RECIPE_DIR_NAME = "mutations"
RECIPE_GLOB = "mutations_*.json"
LOCK_NAME = ".negative_control.lock"


@dataclass(frozen=True)
class Mutation:
    file: str
    replace: str
    with_: str
    test: str
    label: str = ""

    @property
    def name(self) -> str:
        return self.label or f"{self.file}: {self.replace[:40]}"


def _no_bytecode_env() -> dict[str, str]:
    """Environment for child processes: write no `.pyc` during this run.

    Without it, a `.pyc` left behind by one break can be read as valid by the
    next one, and the next break runs the previous break's code (see point 3
    in the module docstring). The cost is recompiling on every import.
    """
    return {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}


def _drop_stale_bytecode(path: Path) -> None:
    """Delete any `.pyc` cached for `path`, so the next run reads the source.

    Best effort: on Windows a `.pyc` held open by another process cannot be
    deleted. That is why `_no_bytecode_env()` exists as well - it stops new
    `.pyc` files from being written in the first place.
    """
    cache = path.parent / "__pycache__"
    if not cache.is_dir():
        return
    for compiled in cache.glob(f"{path.stem}.*.pyc"):
        try:
            compiled.unlink()
        except OSError:
            pass


def run_one(
    mutation: Mutation,
    *,
    root: Path,
    python: str,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> tuple[str, str]:
    """Apply, test, restore. Returns (verdict, detail).

    Verdict is "red" (a test caught it), "green" (nothing did), or "broken"
    (pytest could not run - the mutation is not a fair test of anything).

    The restore is in `finally` and is checked: a tool whose whole job is
    "put it back" must never leave the tree broken.
    """
    path = root / mutation.file
    if not path.is_file():
        return "broken", f"file not found: {mutation.file}"

    original = path.read_text(encoding="utf-8")
    if mutation.replace not in original:
        # Deliberately not "skip": the break was never applied, so this is
        # no result - not "the test has no teeth".
        return "broken", "text to replace not found (the break was not applied)"

    holding = Path(tempfile.mkdtemp(prefix="negative-control-")) / path.name
    shutil.copy2(path, holding)
    try:
        path.write_text(
            original.replace(mutation.replace, mutation.with_, 1),
            encoding="utf-8",
        )
        _drop_stale_bytecode(path)
        try:
            proc = subprocess.run(
                [python, "-m", "pytest", mutation.test, "-q", "--no-header"],
                cwd=root,
                env=_no_bytecode_env(),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            # A run that never finished measured nothing. Reading it as
            # "not caught" would lead someone to delete a working test.
            return "broken", (
                f"did not finish within {timeout} s - the break probably "
                "reached a prompt or dialog that nothing answers"
            )
        failures = [
            line for line in proc.stdout.splitlines() if line.startswith("FAILED")
        ]
        tail = proc.stdout.strip().splitlines()[-1:]
        detail = failures[0] if failures else " ".join(tail)

        # By exit code, not by searching for "failed" (point 2 above).
        if proc.returncode == PYTEST_TESTS_FAILED:
            return "red", detail
        if proc.returncode == PYTEST_ALL_PASSED:
            return "green", detail
        return "broken", f"exit {proc.returncode} | {detail}"
    finally:
        shutil.copy2(holding, path)
        _drop_stale_bytecode(path)
        if path.read_text(encoding="utf-8") != original:
            print(
                f"!!! RESTORE FAILED: {mutation.file} differs from before the "
                f"break. A copy of the original is at {holding} - fix this now.",
                file=sys.stderr,
            )
            raise SystemExit(2)


def recipe_dir(root: Path) -> Path:
    return root / RECIPE_DIR_NAME


def recipe_files(root: Path) -> list[Path]:
    """Every recipe file. Finding none is a problem, not an empty success."""
    return sorted(recipe_dir(root).glob(RECIPE_GLOB))


def stray_recipes(root: Path) -> list[Path]:
    """Recipe files that live outside `mutations/`. Should always be empty.

    Recipes scattered around a project have no owner, and recipes with no
    owner are the ones that quietly rot.
    """
    home = recipe_dir(root)
    return sorted(path for path in root.glob(RECIPE_GLOB) if path.parent != home)


def check_recipes(root: Path, paths: "list[Path] | None" = None) -> list[str]:
    """Has any recipe rotted? Returns a list of problems; empty means all good.

    Rot looks like this: the code was refactored (re-indented, a message
    changed, a line moved), and a recipe's `replace` text no longer matches
    anything. When run, that recipe comes back "broken ?" - true, but lost
    among a page of red ticks, and what it really means is "this check has
    guarded nothing since the refactor". So this is a rule that turns red,
    not a reminder to read carefully. Five things are checked:

    1. The target file still exists.
    2. `replace` appears in it **exactly once**. Zero means rot; more than
       one is also wrong, because only the first match is changed and the
       break lands somewhere nobody intended.
    3. `with` differs from `replace`. If they are equal the break changes
       nothing and is bound to be green - a green that means nothing.
    4. The test to run exists (the file, and the function if `::name` is
       given). A renamed test gives pytest a usage error: again "no result"
       that reads like "no teeth".
    5. All recipes live under `mutations/` (only when checking the whole
       project, not when the caller names specific files).
    """
    problems: list[str] = []

    for stray in stray_recipes(root) if paths is None else []:
        problems.append(
            f"{stray.relative_to(root).as_posix()}: recipe file is outside "
            f"{RECIPE_DIR_NAME}/ - recipes with no home are the ones that rot."
        )

    paths = recipe_files(root) if paths is None else list(paths)
    if not paths:
        problems.append(
            f"no recipes under {RECIPE_DIR_NAME}/ - "
            "a check that checks nothing is always green."
        )

    for recipe in paths:
        try:
            where = recipe.relative_to(root).as_posix()
        except ValueError:
            where = recipe.as_posix()
        try:
            items = json.loads(recipe.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            problems.append(f"{where}: cannot be read ({exc})")
            continue
        if not items:
            problems.append(f"{where}: empty recipe file")
            continue
        for index, item in enumerate(items):
            head = f"{where} / {item.get('label') or f'#{index}'}"
            missing = [key for key in ("file", "replace", "test") if key not in item]
            if missing:
                problems.append(f"{head}: missing fields {missing}")
                continue

            target = root / item["file"]
            if not target.is_file():
                problems.append(f"{head}: target file is gone ({item['file']})")
            else:
                found = target.read_text(encoding="utf-8").count(item["replace"])
                if found == 0:
                    problems.append(
                        f"{head}: the text to replace is no longer in "
                        f"{item['file']} - this check now guards nothing. "
                        "Update it to match the current code."
                    )
                elif found > 1:
                    problems.append(
                        f"{head}: the text to replace appears {found} times in "
                        f"{item['file']}, and only the first is changed - "
                        "make it longer so it matches one place."
                    )

            if item.get("with", "") == item["replace"]:
                problems.append(f"{head}: 'with' equals 'replace' - it changes nothing")

            test_file, _, node = item["test"].partition("::")
            test_path = root / test_file
            if not test_path.is_file():
                problems.append(f"{head}: test file is gone ({test_file})")
            elif node:
                bare = node.split("[")[0]
                pattern = r"^\s*(?:async\s+)?def\s+" + re.escape(bare) + r"\s*\("
                if re.search(pattern, test_path.read_text(encoding="utf-8"), re.M) is None:
                    problems.append(
                        f"{head}: {test_file} no longer has a test named {bare} "
                        "(renamed or deleted - pytest would only report a usage error)"
                    )

    return problems


def load_batch(path: Path) -> list[Mutation]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [
        Mutation(
            file=item["file"],
            replace=item["replace"],
            with_=item.get("with", ""),
            test=item["test"],
            label=item.get("label", ""),
        )
        for item in raw
    ]


class AnotherRunHasTheTree(RuntimeError):
    """Another copy of this tool is already working on this tree."""


@contextlib.contextmanager
def only_one_run(root: Path):
    """Refuse to start if another run holds the lock (point 4 above).

    It stops and says so rather than waiting: a queue would hide the problem,
    and "it's probably fine" is how a break ends up committed.
    """
    lock = root / LOCK_NAME
    try:
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            who = lock.read_text(encoding="utf-8").strip()
        except OSError:
            who = "(unreadable)"
        raise AnotherRunHasTheTree(
            f"Another negative-control run is working on this tree: {who}\n"
            "Two runs at once make one save the other's broken file as the "
            "original, and the break stays in the tree after restoring.\n\n"
            "Wait for it to finish. If it is gone (crash, closed window), "
            f"delete this file by hand:\n  {lock}"
        ) from None
    try:
        os.write(fd, f"pid {os.getpid()}".encode("utf-8"))
        os.close(fd)
        yield
    finally:
        try:
            lock.unlink()
        except OSError:
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Break one line, run the test, put it back. "
        "A green test is not evidence until you have seen it red."
    )
    parser.add_argument("--root", type=Path, default=Path.cwd(),
                        help="project root (default: current directory)")
    parser.add_argument("--python", default=sys.executable,
                        help="Python that runs pytest (default: this one)")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS,
                        help="seconds before a run counts as broken")
    parser.add_argument("--file", help="file to break (relative to --root)")
    parser.add_argument("--replace", help="text to replace")
    parser.add_argument("--with", dest="with_", default="", help="replacement text")
    parser.add_argument("--test", help="test to run (pytest path or node id)")
    parser.add_argument("--label", default="", help="a name for this break")
    parser.add_argument("--from", dest="batch", type=Path,
                        help="a JSON file with a batch of breaks")
    parser.add_argument("--all", action="store_true",
                        help=f"run every recipe under {RECIPE_DIR_NAME}/")
    parser.add_argument("--check", action="store_true",
                        help="only check that recipes still find their targets")
    args = parser.parse_args(argv)
    root = args.root.resolve()

    if args.check:
        # Before any test runs: this answers "will the verdicts mean anything?"
        problems = check_recipes(root)
        for problem in problems:
            print(f"rotted ✗  {problem}")
        if problems:
            print()
            print(
                f"{len(problems)} recipe(s) no longer find what they break. "
                "This is not red and not green - that check no longer exists. "
                "Update it to match the code; do not delete it."
            )
            return 1
        print(f"Recipes OK: {len(recipe_files(root))} file(s), every one still bites.")
        return 0

    if args.all:
        mutations = [m for path in recipe_files(root) for m in load_batch(path)]
    elif args.batch:
        mutations = load_batch(args.batch)
    elif args.file and args.replace and args.test:
        mutations = [Mutation(args.file, args.replace, args.with_, args.test, args.label)]
    else:
        parser.error("give --all / --from, or --file / --replace / --test")

    labels = {"red": "red ✓", "green": "green ✗ no teeth", "broken": "broken ? did not run"}
    tally = {"red": 0, "green": 0, "broken": 0}
    for mutation in mutations:
        verdict, detail = run_one(
            mutation, root=root, python=args.python, timeout=args.timeout
        )
        tally[verdict] += 1
        print(f"{labels[verdict]}  {mutation.name}")
        print(f"        {detail}")
        sys.stdout.flush()

    if tally["green"]:
        print()
        print(
            f"{tally['green']} break(s) turned no test red. Deal with these: "
            "the assertion has a hole, the case is too easy, or the break never "
            "reached the code being measured."
        )
    if tally["broken"]:
        print()
        print(
            f"{tally['broken']} break(s) did not run at all. This is not green and "
            "not red - it is no result. Treating it as green leads to deleting "
            "a test that works."
        )
    return 1 if tally["green"] or tally["broken"] else 0


if __name__ == "__main__":
    # --check is inside the lock too: it reads the source, and another run
    # may be halfway through breaking it.
    _argv = sys.argv[1:]
    _root = Path.cwd()
    if "--root" in _argv:
        _root = Path(_argv[_argv.index("--root") + 1])
    try:
        with only_one_run(_root.resolve()):
            raise SystemExit(main(_argv))
    except AnotherRunHasTheTree as clash:
        print(str(clash), file=sys.stderr)
        # 3, not 2: argparse uses 2 for "bad arguments", and "you typed it
        # wrong" must be distinguishable from "someone else is running".
        raise SystemExit(3) from None
