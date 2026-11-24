"""Stage 2: group the cached emails by sender and work out the plain facts. No AI, no network.

Writes .nexus-os/gmail-cleanup/senders.json, biggest senders first.
"""
import json
import time
from collections import defaultdict

import os

import gmail

SAMPLES = 10  # newest distinct subjects shown to Jev per sender
# Your own addresses, comma-separated in the GMAIL_CLEANUP_OWN env var. Mail from these is always kept.
OWN = {a.strip().lower() for a in os.environ.get("GMAIL_CLEANUP_OWN", "").split(",") if a.strip()}


def sender_key(addr):
    """invoice+statements+acct_123@stripe.com -> invoice@stripe.com, so tagged addresses group together."""
    local, _, domain = addr.partition("@")
    return f"{local.split('+')[0]}@{domain}" if domain else addr


def is_protected(m, sent_threads):
    """Emails code always keeps, whatever Jev says: starred, filed under his own label, or a thread he replied in."""
    return (m["from_addr"] in OWN or "STARRED" in m["labels"] or any(l.startswith("Label_") for l in m["labels"])
            or "SENT" in m["labels"] or m["threadId"] in sent_threads)


def build():
    msgs = gmail.read_jsonl(gmail.data_path("messages.jsonl"))
    sent_threads = set(json.loads(gmail.data_path("sent_threads.json").read_text(encoding="utf-8")))
    groups = defaultdict(list)
    for m in msgs:
        if "SENT" in m["labels"] or m["from_addr"] in OWN:
            continue  # The user's own mail is never up for deletion
        groups[sender_key(m["from_addr"])].append(m)

    now = time.time() * 1000
    senders = []
    for key, ms in groups.items():
        ms.sort(key=lambda m: m["date_ms"], reverse=True)
        samples, seen = [], set()
        for m in ms:
            if m["subject"] not in seen:
                seen.add(m["subject"])
                samples.append({"subject": m["subject"], "preview": m["snippet"][:200]})
            if len(samples) == SAMPLES:
                break
        cats = defaultdict(int)
        for m in ms:
            for l in m["labels"]:
                if l.startswith("CATEGORY_"):
                    cats[l[9:].lower()] += 1
        senders.append({
            "key": key,
            "address": ms[0]["from_addr"],
            "name": next((m["from_name"] for m in ms if m["from_name"]), ""),
            "count": len(ms),
            "bytes": sum(m["size"] for m in ms),
            "first_ms": ms[-1]["date_ms"],
            "last_ms": ms[0]["date_ms"],
            "unread_share": round(sum("UNREAD" in m["labels"] for m in ms) / len(ms), 2),
            "unsub_share": round(sum(m["unsub"] for m in ms) / len(ms), 2),
            "gmail_tabs": dict(cats),
            "protected": sum(is_protected(m, sent_threads) for m in ms),
            "replied": any(m["threadId"] in sent_threads for m in ms),
            "age_days": round((now - ms[0]["date_ms"]) / 86_400_000),
            # newest unsubscribe link this sender gave, for the review page's Unsubscribe button
            "unsub": next(({k: m.get(k) for k in ("unsub_url", "unsub_mailto", "unsub_one_click")}
                           for m in ms if m.get("unsub_url") or m.get("unsub_mailto")), None),
            "latest_id": ms[0]["id"],
            "samples": samples,
        })
    senders.sort(key=lambda s: s["count"], reverse=True)
    out = gmail.data_path("senders.json")
    out.write_text(json.dumps(senders, ensure_ascii=False, indent=1), encoding="utf-8")
    return senders, out


if __name__ == "__main__":
    senders, out = build()
    print(f"{len(senders)} senders from {sum(s['count'] for s in senders)} emails -> {out}")
    for s in senders[:15]:
        print(f"  {s['count']:>5}  {s['bytes'] / 1e6:6.1f} MB  {s['key']}")
