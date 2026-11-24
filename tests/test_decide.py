"""Checks the Keep / Delete / Review truth table in decide.py. No network, no Gmail.
Run from the repo root: python -I tests/test_decide.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import questions as Q  # noqa: E402
from decide import verdict  # noqa: E402


def ans(cat, person=0.0, record=0.0):
    probs = {c: 0.0 for c in Q.CATEGORIES}
    probs[cat] = 1.0
    return {"category": probs, "written_by_person": person, "record_worth_keeping": record}


junk = "marketing_newsletter"
cases = [
    (None, "REVIEW", "no answer means a human decides"),
    (ans(junk, person=0.9), "KEEP", "a real person wrote it, whatever the category"),
    (ans(junk, record=0.8), "KEEP", "might be needed as a record"),
    (ans(junk), "DELETE", "clear junk with nothing worth keeping"),
    (ans(junk, record=0.5), "REVIEW", "junk category but unsure about records"),
    (ans("one_time_code", record=0.5), "DELETE", "old login codes go even when unsure (owner's rule)"),
    (ans("personal_from_a_person"), "REVIEW", "not a junk category, so never auto-deleted"),
]
fails = 0
for a, want, why in cases:
    got = verdict(a)[0]
    ok = got == want
    fails += not ok
    print(("ok   " if ok else "FAIL ") + f"{want:6} <- {why}" + ("" if ok else f" (got {got})"))
print("all passed" if not fails else f"{fails} failed")
sys.exit(1 if fails else 0)
