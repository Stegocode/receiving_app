"""Mutation gate: score killed/checked mutants and enforce the 78% threshold.

Exit codes:
  0 — gate passed (score >= threshold and all mutants were checked)
  1 — gate failed (score < threshold OR any mutant was not checked)
"""

import glob
import json
import sys


def main() -> None:
    threshold = 78

    killed = 0
    survived = 0
    not_checked = 0

    for path in glob.glob("mutants/**/*.meta", recursive=True):
        with open(path) as f:
            data = json.load(f)
        for code in data.get("exit_code_by_key", {}).values():
            if code is None:
                not_checked += 1
            elif code != 0:
                killed += 1
            else:
                survived += 1

    generated = killed + survived + not_checked
    checked = killed + survived

    print(f"Mutation results: {killed} killed / {survived} survived / {not_checked} not checked")
    print(f"Generated: {generated}  Checked: {checked}")

    if not_checked > 0:
        print(
            f"FAIL: {not_checked} mutant(s) were not checked "
            "(sandbox likely broken — all checked counts are unreliable)"
        )
        sys.exit(1)

    if checked == 0:
        print("FAIL: no mutants were checked at all")
        sys.exit(1)

    score = killed / checked * 100
    print(f"Mutation score: {killed}/{checked} = {score:.1f}% (threshold {threshold}%)")

    if score < threshold:
        print(f"FAIL: score {score:.1f}% is below threshold {threshold}%")
        sys.exit(1)

    print("PASS")


if __name__ == "__main__":
    main()
