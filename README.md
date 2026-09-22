# negative-control

**A green test is not evidence until you have seen it turn red.**

This is a small tool for checking your tests. You write a *recipe* — "in this file, change this line to that line, then run this test" — and the tool breaks your code on purpose, runs the test, and puts the code back. If the test turns red, it was guarding something. If it stays green, it wasn't, and now you know.

It is one Python file with no dependencies beyond pytest.

---

## Why green isn't evidence

A test can pass for the wrong reason. It can check the wrong value, check something that is always true, or never reach the code it is named after. All of these look exactly like a test that works: green.

The only way to tell them apart is to break the code the test claims to guard, and watch.

People do this by hand: edit a line, run the test, edit it back. The last step is where it goes wrong. This tool does all three steps, and it is careful about the third.

---

## Quick start

The `example/` folder is a tiny project with a shipping-fee rule and two tests. Both tests pass.

```python
# example/pricing.py
def shipping_fee(total: float) -> float:
    """Orders of 100 or more ship free. Anything smaller pays a flat fee."""
    if total >= FREE_SHIPPING_FROM:
        return 0.0
    return SHIPPING_FEE
```

```python
# example/tests/test_pricing.py
def test_an_order_of_exactly_100_ships_free():
    assert shipping_fee(100) == 0.0

def test_small_order_has_a_fee():
    assert shipping_fee(50) >= 0
```

`example/mutations/mutations_pricing.json` breaks the rule in two ways:

```json
[
  {
    "label": "orders of exactly 100 stop shipping free",
    "file": "pricing.py",
    "replace": "if total >= FREE_SHIPPING_FROM:",
    "with": "if total > FREE_SHIPPING_FROM:",
    "test": "tests/test_pricing.py::test_an_order_of_exactly_100_ships_free"
  },
  {
    "label": "small orders ship free by mistake",
    "file": "pricing.py",
    "replace": "    return SHIPPING_FEE",
    "with": "    return 0.0",
    "test": "tests/test_pricing.py::test_small_order_has_a_fee"
  }
]
```

Run it:

```
cd example
python ../negative_control.py --all
```

```
red ✓  orders of exactly 100 stop shipping free
        FAILED tests/test_pricing.py::test_an_order_of_exactly_100_ships_free - asser...
green ✗ no teeth  small orders ship free by mistake
        1 passed in 0.01s

1 break(s) turned no test red. Deal with these: the assertion has a hole,
the case is too easy, or the break never reached the code being measured.
```

The second test passed with the fee set to zero. `0 >= 0` is true. It was never checking the fee.

Fix the test, not the recipe:

```python
def test_small_order_has_a_fee():
    assert shipping_fee(50) == 8.0
```

Run it again and both are red. Now both tests are evidence.

---

## Writing a recipe

A recipe file is a JSON array in `mutations/`, named `mutations_<topic>.json`. Each entry:

| Field | Meaning |
|---|---|
| `file` | The file to break, relative to the project root |
| `replace` | The exact text to change. It must appear **exactly once** in the file |
| `with` | What to change it to. Must differ from `replace` |
| `test` | The test that should catch it: a file, or `file::test_name` |
| `label` | A short description of what the break means — written as the bug a user would see |

Good recipes:

- **Break the decision, not the wording.** If a test checks a message, change *which* message is chosen, not the text of the message. Otherwise the test that checks the text passes, and the choice goes unguarded.
- **Delete, don't comment out.** If a test searches the source for some text, a commented-out copy of that text still matches — and the break proves nothing.
- **Make the break match the failure.** Changing `>=` to `>` tests a boundary. Changing the whole function tests that the function is called at all. Pick the one your test claims to guard.
- **Point at one test.** `file::name` says which test is meant to catch it, so a green verdict points straight at the weak one.

---

## The three verdicts

| Verdict | Meaning | What to do |
|---|---|---|
| **red ✓** | A test failed. It caught the break. | Nothing. This is the goal. |
| **green ✗ no teeth** | Every test still passed. | Fix the test, or the case it uses. Do not change the recipe to make it red. |
| **broken ? did not run** | The tests did not run: the text wasn't found, the code no longer parses, the test was renamed, or it timed out. | This is **no result**. Do not read it as green. |

The third one matters most. A run that measured nothing looks, in a long list, like a run that found nothing — and the next step people take is to delete the test.

---

## Recipes rot

Code changes. A line is re-indented or reworded, and a recipe's `replace` text no longer matches anything. From that day the check guards nothing, and nothing says so.

```
python negative_control.py --check
```

checks every recipe in milliseconds, without running any tests:

- the target file exists;
- `replace` appears **exactly once** (more than once means the break lands somewhere unintended);
- `with` differs from `replace`;
- the named test still exists;
- every recipe file lives in `mutations/`.

Run it in your test suite (see `tests/test_recipes_still_bite.py`) so a rotted recipe turns red on its own.

---

## Why the details exist

Each of these was a real failure of an earlier version of this tool.

**1. It restores from a copy, never from git.**
An early version restored with `git checkout -- <file>`. That brings back the last *commit*, not the file as it was a second ago — and it threw away an uncommitted refactor in the same file. The file you are testing is usually the one you are working on.

**2. It reads pytest's exit code, not its output.**
An early version searched the output for "failed". A collection error prints `1 error`, which does not contain "failed", so it was read as green: "this test has no teeth", about a run in which nothing was checked. Exit code 1 means tests failed. Any other non-zero code means the run did not happen.

**3. It clears the bytecode cache.**
Python decides a cached `.pyc` is still valid from the source file's modification time — in whole seconds — and its size. Two breaks of the same size applied within one second ran as the *first* break, and the second was reported as having no teeth. The tool deletes the cache for the file before and after each break, and runs tests with `PYTHONDONTWRITEBYTECODE=1`.

**4. Only one run at a time.**
Two runs on the same project each save the other's broken file as "the original". After both restore, a break is left in your code. The tool takes a lock file (`.negative_control.lock`) and refuses to start if it is held, with exit code 3.

---

## Limits

- A recipe only covers the break someone thought of. Negative control tells you a test *can* fail; it cannot tell you what you forgot to test.
- It changes one text match at a time. It is not a mutation-testing framework that generates breaks for you — the point is that you choose the break that matches the claim your test makes.
- It runs your tests once per recipe, so a large recipe set on a slow suite takes a while. `--check` is instant.

---

## Usage

```
python negative_control.py --file src/rule.py --replace "a >= b" --with "a > b" --test tests/test_rule.py
python negative_control.py --from mutations/mutations_rule.json
python negative_control.py --all
python negative_control.py --check
```

Options: `--root` (project root, default: current directory), `--python` (interpreter that runs pytest, default: the one running this tool), `--timeout` (seconds, default 180).

Exit codes: `0` all red · `1` something green or broken · `2` bad arguments, or a restore failed · `3` another run holds the lock.

This repository checks itself: `mutations/mutations_the_tool_itself.json` breaks the tool seven ways, and each one turns its own tests red.

---

## License

MIT — see `LICENSE`.
