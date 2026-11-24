"""Grade a trial: compare NEXUS's recommendations with the user's picks from the exported review.

    python grade.py trial-2a

Saves trials/<name>.json with counts only (sender addresses, no subjects), safe to commit.
The number that matters most is wrong deletes: senders NEXUS said DELETE that the user kept.
Senders the user had already decided in an earlier round are left out of the grade (no credit for
repeating his own answer). His picks are merged into .nexus-os/gmail-cleanup/user_picks.json,
which decide.py treats as final.
"""
import json
import sys
from datetime import date
from pathlib import Path

import gmail
from apply import approved_file

name = sys.argv[1] if len(sys.argv) > 1 else f"trial-{date.today()}"
already = {r["key"] for r in json.loads(gmail.data_path("decisions.json").read_text(encoding="utf-8"))
           if r.get("source") == "user"}
all_picks = json.loads(approved_file(None).read_text(encoding="utf-8"))["senders"]
picks = [p for p in all_picks if p["key"] not in already]
wrong_delete = [p["key"] for p in picks if p["recommended"] == "DELETE" and p["user"] == "keep"]
missed = [p["key"] for p in picks if p["recommended"] == "KEEP" and p["user"] == "delete"]
settled = [p for p in picks if p["recommended"] in ("DELETE", "KEEP")]
agree = sum((p["recommended"] == "DELETE") == (p["user"] == "delete") for p in settled)
review = sum(p["recommended"] in ("REVIEW", "SPLIT") for p in picks)
res = {
    "trial": name, "graded_senders": len(picks), "carried_forward": len(already),
    "agreement": round(agree / len(settled), 3) if settled else None,
    "review_share": round(review / len(picks), 3) if picks else None,
    "wrong_deletes": wrong_delete, "missed_deletes": missed,
}
out = Path(__file__).parent / "trials" / f"{name}.json"
out.parent.mkdir(exist_ok=True)
out.write_text(json.dumps(res, indent=1), encoding="utf-8")

store = gmail.data_path("user_picks.json")
saved = json.loads(store.read_text(encoding="utf-8")) if store.exists() else {}
saved.update({p["key"]: p["user"] for p in all_picks})
store.write_text(json.dumps(saved, indent=1), encoding="utf-8")

print(json.dumps({k: (len(v) if isinstance(v, list) else v) for k, v in res.items()}, indent=1))
print(f"Saved {out}; {len(saved)} of the user's picks stored")
