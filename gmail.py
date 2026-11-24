"""Shared helpers: Gmail API calls on the shared Google sign-in, plus the private data folder.

The sign-in comes from (auth/google.mjs), stored outside
the repo in %USERPROFILE%\\.nexus-os\\. Everything this tool saves about the user's mail (message cache,
Jev answers, review page) goes in .nexus-os\\gmail-cleanup\\, never in the repo or a synced folder.
Standard library only.
"""
import http.client
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SECRETS = Path(os.environ.get("NEXUS_OS_SECRETS") or Path.home() / ".nexus-os")
CLIENT_PATH = SECRETS / "google-client.json"
TOKEN_PATH = SECRETS / "google-token.json"
DATA = SECRETS / "gmail-cleanup"
GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
TOKEN_URL = "https://oauth2.googleapis.com/token"


def data_path(name):
    DATA.mkdir(parents=True, exist_ok=True)
    return DATA / name


def read_jsonl(path):
    if not Path(path).exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def append_jsonl(path, rows):
    with open(path, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _post_form(url, params):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(params).encode(), method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


_cached = {}


def access_token():
    """A valid access token, refreshed (and saved back, same format as google.mjs) near expiry."""
    if _cached.get("exp", 0) > time.time() * 1000 + 60_000:
        return _cached["tok"]
    if not TOKEN_PATH.exists():
        raise SystemExit(f"Not signed in. Run: node auth/google.mjs auth")
    tok = json.loads(TOKEN_PATH.read_text(encoding="utf-8"))
    if not (tok.get("access_token") and tok.get("expiry_date", 0) > time.time() * 1000 + 60_000):
        raw = json.loads(CLIENT_PATH.read_text(encoding="utf-8"))
        c = raw.get("web") or raw.get("installed") or raw
        fresh = _post_form(TOKEN_URL, {"client_id": c["client_id"], "client_secret": c["client_secret"],
                                       "refresh_token": tok["refresh_token"], "grant_type": "refresh_token"})
        tok.update(access_token=fresh["access_token"], expiry_date=int(time.time() * 1000 + fresh["expires_in"] * 1000))
        TOKEN_PATH.write_text(json.dumps(tok, indent=2), encoding="utf-8")
    _cached.update(tok=tok["access_token"], exp=tok["expiry_date"])
    return _cached["tok"]


def api(path, params=None, body=None, method=None, tries=6):
    """One Gmail API call. Backs off and retries on rate limits (429) and server errors."""
    url = f"{GMAIL}/{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True)
    data = json.dumps(body).encode() if body is not None else None
    for attempt in range(tries):
        req = urllib.request.Request(url, data=data, method=method or ("POST" if data else "GET"), headers={
            "Authorization": f"Bearer {access_token()}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "ignore")
            # Gmail sends rate limits as 429, or as 403 with "quota" / "rateLimitExceeded" in the body
            limited = e.code == 429 or (e.code == 403 and ("uota" in msg or "ateLimit" in msg))
            if (limited or e.code >= 500) and attempt < tries - 1:
                time.sleep(min(2 ** (attempt + 1), 60))
                continue
            raise RuntimeError(f"Gmail {e.code} on {path}: {msg[:300]}")
        except (urllib.error.URLError, TimeoutError, http.client.HTTPException, ConnectionError):
            if attempt < tries - 1:
                time.sleep(min(2 ** attempt, 30))
                continue
            raise


def list_ids(query, limit=None):
    """Message ids (newest first) matching a Gmail search, as (id, threadId) pairs."""
    out, page = [], None
    while True:
        params = {"q": query, "maxResults": 500}
        if page:
            params["pageToken"] = page
        res = api("messages", params)
        out += [(m["id"], m["threadId"]) for m in res.get("messages", [])]
        page = res.get("nextPageToken")
        if not page or (limit and len(out) >= limit):
            return out[:limit] if limit else out
