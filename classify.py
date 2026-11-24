"""Stage 3: ask Jev about each sender, then about each email from mixed senders.

Sends only sender name/address, subjects and Gmail's short preview. Never full bodies.
Every call's exact request and the answers go to .nexus-os/gmail-cleanup/jev_senders.jsonl and
jev_emails.jsonl, so any result can be rerun. Already-answered senders are skipped.

    python classify.py --limit 30        first 30 unanswered senders (biggest first)
    python classify.py --only amazon.com senders whose address contains this
    python classify.py                   everything left
"""
import argparse
import json
import os
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import gmail
import questions as Q
from features import sender_key

API = "https://api.typesafe.ai/v1/systemone"
MIXED = 0.7      # mixed_sender above this -> judge each email on its own
WORKERS = 4


def ask(state, qs, key):
    body = {"model": "jev-latest", "state": state, "questions": qs}
    rec = {"request": body}
    try:
        req = urllib.request.Request(API, data=json.dumps(body).encode(), method="POST", headers={
            "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            out = json.load(r)
        rec["answers"] = {k: (a.get("probabilities") if a["type"] == "choice" else round(a["noul"], 3))
                          for k, a in out["answers"].items()}
        rec.update(model=out.get("model"), usage=out.get("usage", {}))
    except Exception as e:  # logged as an error, never treated as an answer
        rec["error"] = f"{type(e).__name__}: {e}"[:300]
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--only")
    ap.add_argument("--keys", help="comma-separated sender keys, for a hand-picked probe")
    ap.add_argument("--retry-errors", action="store_true", help="re-ask senders whose last call failed")
    a = ap.parse_args()
    key = os.environ.get("TYPESAFE_API_KEY")
    if not key:
        raise SystemExit("TYPESAFE_API_KEY is not set")

    senders = json.loads(gmail.data_path("senders.json").read_text(encoding="utf-8"))
    log_s = gmail.data_path("jev_senders.jsonl")
    done = {r["key"]: r for r in gmail.read_jsonl(log_s)}
    keys = set(a.keys.split(",")) if a.keys else None
    picked = lambda k: (a.only or "") in k and (keys is None or k in keys)
    todo = [s for s in senders if picked(s["key"])
            and (s["key"] not in done or (a.retry_errors and "error" in done[s["key"]]))][:a.limit]
    print(f"Asking Jev about {len(todo)} senders ...", flush=True)

    t0, tokens, errs = time.time(), 0, 0
    with ThreadPoolExecutor(WORKERS) as pool:
        recs = list(pool.map(lambda s: {"key": s["key"], **ask(Q.sender_state(s), Q.SENDER_QUESTIONS, key)}, todo))
    gmail.append_jsonl(log_s, recs)
    for r in recs:
        done[r["key"]] = r
        tokens += r.get("usage", {}).get("input_tokens", 0)
        errs += "error" in r

    # Mixed senders: judge each of their emails on its own.
    mixed = {k for k, r in done.items() if r.get("answers", {}).get("mixed_sender", 0) >= MIXED}
    log_e = gmail.data_path("jev_emails.jsonl")
    have = {r["id"] for r in gmail.read_jsonl(log_e) if "error" not in r}
    by_key = {s["key"]: s for s in senders}
    msgs = [m for m in gmail.read_jsonl(gmail.data_path("messages.jsonl"))
            if sender_key(m["from_addr"]) in mixed and "SENT" not in m["labels"] and m["id"] not in have
            and picked(sender_key(m["from_addr"]))]
    if msgs:
        print(f"{len(mixed)} mixed senders, asking about {len(msgs)} of their emails one by one ...", flush=True)
        with ThreadPoolExecutor(WORKERS) as pool:
            erecs = list(pool.map(lambda m: {"id": m["id"], "key": sender_key(m["from_addr"]),
                                             **ask(Q.email_state(by_key[sender_key(m["from_addr"])], m), Q.EMAIL_QUESTIONS, key)}, msgs))
        gmail.append_jsonl(log_e, erecs)
        tokens += sum(r.get("usage", {}).get("input_tokens", 0) for r in erecs)
        errs += sum("error" in r for r in erecs)

    cost = tokens / 1e6 * 0.042
    print(f"Done in {time.time() - t0:.0f}s. {tokens:,} input tokens (~${cost:.4f}), {errs} errors.")


if __name__ == "__main__":
    main()
