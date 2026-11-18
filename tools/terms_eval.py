"""Does the name suggester know the trade words? Scores it against fixed test cases.

Developer tool. Run from the repo root (plain Python, no venv needed):
    python tools/terms_eval.py
    python tools/terms_eval.py --model @cf/meta/llama-3.3-70b-instruct-fp8-fast

A case passes when any expected word appears in any suggested term
(case-insensitive). Don't edit the Worker's prompt to fit these cases one by
one: that measures memorisation, not whether it will work for your viewers.
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import terms  # noqa: E402

# (what an artist might type, words that mean it found the right thing)
CASES = [
    ("wall trim in a commercial office interior", ["cove base", "wall base", "rubber base", "vinyl base", "resilient base"]),
    ("metal strip on the edge of stairs so you don't slip", ["nosing"]),
    ("the ceiling in offices with the white tiles in a metal grid",
     ["suspended ceiling", "drop ceiling", "acoustic ceiling tile", "t-bar", "ceiling grid"]),
    ("the bar you push to open an emergency exit door", ["panic bar", "crash bar", "exit device", "push bar"]),
    ("the u-shaped pipe under a sink", ["p-trap", "p trap", "trap"]),
    ("rubber strip at the bottom of a door that blocks drafts", ["door sweep", "door bottom"]),
    ("plastic channel that hides cables running along a wall", ["raceway", "cable cover", "trunking"]),
    ("decorative block under a shelf or countertop that holds it up", ["corbel", "bracket"]),
]
# Control: already the right words. Should come back (nearly) unchanged first.
CONTROL = ("black mesh office chair", ["office chair"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=None, help="Workers AI model id (must be on the Worker's allowlist)")
    parser.add_argument("--url", default=terms.SUGGEST_URL)
    args = parser.parse_args()

    passed, times = 0, []
    for text, expected in CASES + [CONTROL]:
        start = time.perf_counter()
        try:
            got = terms.suggest(text, url=args.url, model=args.model)
        except Exception as exc:
            got, error = [], f"{type(exc).__name__}: {exc}"
        else:
            error = None
        times.append(time.perf_counter() - start)

        names = [t["term"].lower() for t in got]
        hit = any(e in n for e in expected for n in names)
        if (text, expected) == CONTROL:
            hit = bool(names) and expected[0] in names[0]
            label = "CONTROL"
        else:
            passed += hit
            label = "PASS" if hit else "MISS"
        print(f"{label:<8}{text}  ({times[-1]:.1f} s)")
        if error:
            print(f"        error: {error}")
        for t in got:
            print(f"        - {t['term']:<34} {t['gloss']}")

    times.sort()
    print(f"\n{passed}/{len(CASES)} found the trade term   (bar for shipping: 6/{len(CASES)})")
    print(f"median {times[len(times) // 2]:.1f} s, slowest {times[-1]:.1f} s   (bar: median under 3 s)")


if __name__ == "__main__":
    main()
