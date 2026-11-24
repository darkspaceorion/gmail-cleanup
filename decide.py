"""Stage 4: the truth table. Jev judged, this decides Keep / Delete / Review. No network.

Protected emails (starred, under the user's own label, or in a thread he replied in) are never
deleted, whatever the sender's verdict. Delete only ever covers emails older than OLD_DAYS.
Writes .nexus-os/gmail-cleanup/decisions.json.
"""
import json
import time

import gmail
import questions as Q
from classify import MIXED
from features import sender_key, is_protected

YES, NO = 0.7, 0.3
OLD_DAYS = 90
READ = 0.5  # The user opened over half of a sender's mail -> never auto-delete, send to Review


def top(probs):
    return max(probs, key=probs.get)


def verdict(ans):
    """One set of Jev answers -> (decision, reason). Same table for a sender or a single email."""
    if ans is None:
        return "REVIEW", "no answer from Jev"
    cat = top(ans["category"])
    if ans["written_by_person"] >= YES:
        return "KEEP", "written by a person"
    if ans["record_worth_keeping"] >= YES:
        return "KEEP", "record worth keeping"
    if cat in Q.DELETABLE and ans["record_worth_keeping"] < NO and ans["written_by_person"] < NO:
        return "DELETE", cat.replace("_", " ")
    if cat in Q.LOOSE_DELETE and ans["written_by_person"] < NO:
        return "DELETE", cat.replace("_", " ") + " (old alerts go)"
    return "REVIEW", "unsettled" if cat in Q.DELETABLE else f"{cat.replace('_', ' ')}, not clearly junk"


def build():
    senders = json.loads(gmail.data_path("senders.json").read_text(encoding="utf-8"))
    sent_threads = set(json.loads(gmail.data_path("sent_threads.json").read_text(encoding="utf-8")))
    jev_s = {r["key"]: r.get("answers") for r in gmail.read_jsonl(gmail.data_path("jev_senders.jsonl"))}
    jev_e = {r["id"]: r.get("answers") for r in gmail.read_jsonl(gmail.data_path("jev_emails.jsonl"))}
    picks_path = gmail.data_path("user_picks.json")  # his graded calls, saved by grade.py
    picks = json.loads(picks_path.read_text(encoding="utf-8")) if picks_path.exists() else {}
    msgs_by = {}
    for m in gmail.read_jsonl(gmail.data_path("messages.jsonl")):
        if "SENT" not in m["labels"]:
            msgs_by.setdefault(sender_key(m["from_addr"]), []).append(m)

    cutoff = time.time() * 1000 - OLD_DAYS * 86_400_000
    out = []
    for s in senders:
        ans = jev_s.get(s["key"])
        mixed = bool(ans) and ans.get("mixed_sender", 0) >= MIXED
        decision, reason = ("SPLIT", "mixed sender, judged email by email") if mixed else verdict(ans)
        if s["replied"] and decision == "DELETE":
            decision, reason = "REVIEW", "you've replied to this sender before"
        if decision == "DELETE" and s["unread_share"] < READ and ans and top(ans["category"]) not in Q.LOOSE_DELETE:
            decision, reason = "REVIEW", "you open most of these"
        source = "nexus"
        if s["key"] in picks:  # The user already decided this sender: his call wins, never asked again
            decision = "DELETE" if picks[s["key"]] == "delete" else "KEEP"
            reason, source = "your call", "user"
            # ...except a "bin" picked from a few weeks of mail must not sweep away years of records
            # (Robinhood 2026-11-03: picked on adverts, 178 of 848 were tax forms and statements).
            if decision == "DELETE" and ans and mixed:
                decision, reason = "SPLIT", "your earlier call, but older mail is mixed: judged email by email"
            elif decision == "DELETE" and ans and ans["record_worth_keeping"] >= YES:
                decision, reason, source = "REVIEW", "you said bin, but older mail looks like records", "nexus"
        # old_ids: everything the user could choose to bin (old, unprotected). delete_ids: what we recommend.
        old_ids, delete_ids, delete_bytes = [], [], 0
        for m in msgs_by.get(s["key"], []):
            if m["date_ms"] >= cutoff or is_protected(m, sent_threads):
                continue
            old_ids.append(m["id"])
            if (verdict(jev_e.get(m["id"]))[0] if mixed else decision) == "DELETE":
                delete_ids.append(m["id"])
                delete_bytes += m["size"]
        out.append({
            "key": s["key"], "name": s["name"], "count": s["count"], "bytes": s["bytes"],
            "first_ms": s["first_ms"], "last_ms": s["last_ms"], "unread_share": s["unread_share"],
            "protected": s["protected"], "samples": s["samples"][:5],
            "unsub": s.get("unsub"), "latest_id": s.get("latest_id"),
            "category": top(ans["category"]) if ans else None,
            "probs": {k: v for k, v in (ans or {}).items() if k != "category"},
            "decision": decision, "reason": reason, "source": source,
            "old_ids": old_ids, "delete_ids": delete_ids, "delete_bytes": delete_bytes,
        })
    path = gmail.data_path("decisions.json")
    path.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out, path


if __name__ == "__main__":
    out, path = build()
    tally = {}
    for r in out:
        t = tally.setdefault(r["decision"], [0, 0])
        t[0] += 1
        t[1] += r["count"]
    for d, (n, c) in sorted(tally.items()):
        print(f"  {d:7} {n:>5} senders  {c:>7} emails")
    print(f"  Would trash {sum(len(r['delete_ids']) for r in out)} emails, "
          f"{sum(r['delete_bytes'] for r in out) / 1e6:.1f} MB -> {path}")
