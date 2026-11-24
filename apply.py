"""Stage 6: act on the user's exported decisions. DRY RUN unless --confirm is given.

    python apply.py --label                     dry run: what would get the Cleanup/Delete label
    python apply.py --label --confirm           tag them in Gmail (nothing leaves the inbox)
    python apply.py --trash --confirm           move them to Trash (Gmail keeps Trash 30 days)
    python apply.py --trash --only temu --confirm   just senders whose address contains "temu" (comma list allowed)
    python apply.py --biggest 10 ...            just the 10 biggest approved senders
    python apply.py --restore 2026-11-03T21:15  take one logged run back out of Trash

Never deletes permanently. Every run that changes Gmail is logged to applied.jsonl with its ids.
"""
import argparse
import json
from datetime import datetime
from pathlib import Path

import gmail

LABEL = "Cleanup/Delete"
BATCH = 1000  # batchModify limit


def approved_file(path):
    if path:
        return Path(path)
    dl = sorted((Path.home() / "Downloads").glob("gmail-cleanup-approved*.json"), key=lambda p: p.stat().st_mtime)
    if not dl:
        raise SystemExit("No gmail-cleanup-approved.json in Downloads. Export it from the review page first.")
    return dl[-1]


def label_id():
    for l in gmail.api("labels").get("labels", []):
        if l["name"] == LABEL:
            return l["id"]
    return gmail.api("labels", body={"name": LABEL, "labelListVisibility": "labelShow",
                                     "messageListVisibility": "show"})["id"]


def modify(ids, add=(), remove=()):
    for i in range(0, len(ids), BATCH):
        gmail.api("messages/batchModify", body={"ids": ids[i:i + BATCH], "addLabelIds": list(add),
                                                "removeLabelIds": list(remove)})


def restore(stamp):
    runs = [r for r in gmail.read_jsonl(gmail.data_path("applied.jsonl")) if r["ts"].startswith(stamp) and r["action"] == "trash"]
    if not runs:
        raise SystemExit(f"No trash run logged at {stamp}")
    for r in runs:
        for mid in r["ids"]:
            gmail.api(f"messages/{mid}/untrash", body={})
        print(f"Restored {len(r['ids'])} emails from run {r['ts']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", action="store_true")
    ap.add_argument("--trash", action="store_true")
    ap.add_argument("--confirm", action="store_true")
    ap.add_argument("--only")
    ap.add_argument("--biggest", type=int)
    ap.add_argument("--approved")
    ap.add_argument("--restore")
    a = ap.parse_args()
    if a.restore:
        return restore(a.restore)
    if a.label == a.trash:
        raise SystemExit("Pick one: --label or --trash")

    src = approved_file(a.approved)
    picks = {s["key"] for s in json.loads(src.read_text(encoding="utf-8"))["senders"] if s["user"] == "delete"}
    rows = [r for r in json.loads(gmail.data_path("decisions.json").read_text(encoding="utf-8"))
            if r["key"] in picks and any(o in r["key"] for o in (a.only or "").split(","))]
    rows.sort(key=lambda r: r["count"], reverse=True)
    rows = rows[:a.biggest]
    plan = [(r, r["delete_ids"] if r["decision"] in ("DELETE", "SPLIT") else r["old_ids"]) for r in rows]
    ids = [i for _, ii in plan for i in ii]

    print(f"From {src.name}: {len(rows)} senders, {len(ids)} emails")
    for r, ii in plan[:25]:
        print(f"  {len(ii):>6}  {r['key']}")
    if len(plan) > 25:
        print(f"  ... and {len(plan) - 25} more senders")
    action = "trash" if a.trash else "label"
    if not a.confirm:
        print(f"\nDRY RUN. Nothing changed. Add --confirm to {action} these {len(ids)} emails.")
        return
    if a.trash:
        modify(ids, add=["TRASH"])
    else:
        modify(ids, add=[label_id()])
    ts = datetime.now().isoformat(timespec="seconds")
    gmail.append_jsonl(gmail.data_path("applied.jsonl"), [{"ts": ts, "action": action, "senders": [r["key"] for r in rows], "ids": ids}])
    print(f"Done: {action} on {len(ids)} emails. Logged as run {ts}" + (f" (undo: python apply.py --restore {ts})" if a.trash else ""))


if __name__ == "__main__":
    main()
