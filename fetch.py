"""Stage 1: pull headers for every email (no bodies) into the private cache. Read-only.

    python fetch.py --limit 1000            newest 1,000 emails
    python fetch.py                         the whole mailbox (resumable: already-cached ids are skipped;
                                            emails gone from Gmail are dropped from the cache)
    python fetch.py --query "older_than:5y" any Gmail search

Writes .nexus-os/gmail-cleanup/messages.jsonl and sent_threads.json (threads the user replied in).
"""
import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from email.utils import parseaddr

import gmail

HEADERS = ["From", "Subject", "Date", "List-Unsubscribe", "List-Unsubscribe-Post"]


def unsub_links(h):
    """List-Unsubscribe is '<mailto:...>, <https://...>'. One-click means a plain POST does it (RFC 8058)."""
    parts = re.findall(r"<([^>]+)>", h.get("list-unsubscribe", ""))
    url = next((p for p in parts if p.startswith("https://")), None)
    return {"unsub_url": url, "unsub_mailto": next((p for p in parts if p.startswith("mailto:")), None),
            "unsub_one_click": bool(url) and "one-click" in h.get("list-unsubscribe-post", "").lower()}
WORKERS = 4  # Gmail allows ~50 metadata reads a second per user; 8 threads tripped it, 4 plus backoff holds


def one(mid):
    m = gmail.api(f"messages/{mid}", {"format": "metadata", "metadataHeaders": HEADERS})
    h = {x["name"].lower(): x["value"] for x in m.get("payload", {}).get("headers", [])}
    name, addr = parseaddr(h.get("from", ""))
    return {
        "id": m["id"], "threadId": m["threadId"], "labels": m.get("labelIds", []),
        "date_ms": int(m.get("internalDate", 0)), "size": m.get("sizeEstimate", 0),
        "from_name": name, "from_addr": addr.lower(), "subject": h.get("subject", ""),
        "snippet": m.get("snippet", ""), "unsub": "list-unsubscribe" in h, **unsub_links(h),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--query", default="-in:trash -in:spam -in:chats")
    a = ap.parse_args()

    cache = gmail.data_path("messages.jsonl")
    have = {r["id"] for r in gmail.read_jsonl(cache)}
    print(f"Listing ids for: {a.query} ...", flush=True)
    ids = gmail.list_ids(a.query, a.limit)
    todo = [i for i, _ in ids if i not in have]
    print(f"{len(ids)} match, {len(ids) - len(todo)} already cached, fetching {len(todo)}", flush=True)

    done = errors = 0
    with ThreadPoolExecutor(WORKERS) as pool:
        for start in range(0, len(todo), 400):  # save in chunks so a crash loses little
            rows = []
            for r in pool.map(lambda i: _safe(one, i), todo[start:start + 400]):
                if r is None:
                    errors += 1
                else:
                    rows.append(r)
            gmail.append_jsonl(cache, rows)
            done += len(rows)
            print(f"  {done}/{len(todo)} fetched", flush=True)

    if not a.limit and a.query == ap.get_default("query"):
        # whole-mailbox listing: drop cached emails that are gone (trashed or deleted since)
        live = {i for i, _ in ids}
        rows = [r for r in gmail.read_jsonl(cache) if r["id"] in live]
        gone = len(have) - (len(rows) - done)
        if gone:
            tmp = cache.with_suffix(".tmp")
            tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
            tmp.replace(cache)
            print(f"Dropped {gone} cached emails no longer in the mailbox", flush=True)

    print("Listing threads the user sent mail in ...", flush=True)
    sent = sorted({t for _, t in gmail.list_ids("in:sent")})
    gmail.data_path("sent_threads.json").write_text(json.dumps(sent), encoding="utf-8")
    print(f"Done. {done} new, {errors} errors, {len(sent)} sent threads. Cache: {cache}")


def _safe(fn, x):
    try:
        return fn(x)
    except Exception as e:
        print(f"  skip {x}: {e}", file=sys.stderr)
        return None


if __name__ == "__main__":
    main()
