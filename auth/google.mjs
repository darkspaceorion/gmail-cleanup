/**
 * Google sign-in and read-only reader (calendar + Gmail, READ-ONLY).
 * Zero dependencies: plain HTTPS calls with Node's built-in fetch, so nothing
 * heavy gets installed into the project.
 *
 * Secrets live OUTSIDE the repo, in %USERPROFILE%\.nexus-os\ :
 *   google-client.json   the OAuth client file downloaded from Google Cloud (Clients > Download JSON)
 *   google-token.json    written by `auth` - the sign-in. Delete it to sign out.
 *
 * Usage:
 *   node tools/google.mjs auth       one-time sign-in (opens the browser)
 *   node tools/google.mjs calendar   JSON: upcoming events across every ticked calendar
 *   node tools/google.mjs mail       JSON: last 3 days of inbox threads (headers only)
 *   node tools/google.mjs search "q" read-only list of threads matching a Gmail query, for tuning
 */
import { createServer } from 'http';
import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'fs';
import { exec } from 'child_process';
import { join } from 'path';
import { homedir } from 'os';

const DIR = process.env.NEXUS_OS_SECRETS || join(homedir(), '.nexus-os');
const CLIENT_PATH = join(DIR, 'google-client.json');
const TOKEN_PATH = join(DIR, 'google-token.json');
const SCOPES = [
  'https://www.googleapis.com/auth/calendar.readonly',
  /* modify = read + labels + Trash (never permanent delete). Needed by Projects/gmail-cleanup;
     everything in this file still only reads. */
  'https://www.googleapis.com/auth/gmail.modify',
];
/* must match the redirect URI on the OAuth client in Google Cloud */
const REDIRECT_PORT = 3847;
const REDIRECT_URI = `http://localhost:${REDIRECT_PORT}/oauth2callback`;
const TOKEN_URL = 'https://oauth2.googleapis.com/token';

function clientCreds() {
  if (!existsSync(CLIENT_PATH)) {
    console.error(`Missing ${CLIENT_PATH} - download the OAuth client JSON from Google Cloud and save it there`);
    process.exit(1);
  }
  const raw = JSON.parse(readFileSync(CLIENT_PATH, 'utf8'));
  return raw.web || raw.installed || raw;               /* Google's download wraps it in "web" */
}

async function tokenCall(params) {
  const r = await fetch(TOKEN_URL, { method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams(params) });
  const j = await r.json();
  if (!r.ok) throw new Error('token: ' + (j.error_description || j.error || r.status));
  return j;
}

/* a valid access token, refreshing (and saving) it when it is about to expire */
async function accessToken() {
  if (!existsSync(TOKEN_PATH)) { console.error('Not signed in yet. Run: node tools/google.mjs auth'); process.exit(1); }
  const tok = JSON.parse(readFileSync(TOKEN_PATH, 'utf8'));
  if (tok.access_token && tok.expiry_date && Date.now() < tok.expiry_date - 60000) return tok.access_token;
  const c = clientCreds();
  const fresh = await tokenCall({ client_id: c.client_id, client_secret: c.client_secret,
    refresh_token: tok.refresh_token, grant_type: 'refresh_token' });
  const saved = { ...tok, access_token: fresh.access_token, expiry_date: Date.now() + fresh.expires_in * 1000 };
  writeFileSync(TOKEN_PATH, JSON.stringify(saved, null, 2));
  return saved.access_token;
}

async function api(url) {
  const r = await fetch(url, { headers: { Authorization: 'Bearer ' + await accessToken() } });
  const j = await r.json();
  if (!r.ok) throw new Error((j.error && j.error.message) || 'HTTP ' + r.status);
  return j;
}

async function auth() {
  mkdirSync(DIR, { recursive: true });
  const c = clientCreds();
  const url = 'https://accounts.google.com/o/oauth2/v2/auth?' + new URLSearchParams({
    client_id: c.client_id, redirect_uri: REDIRECT_URI, response_type: 'code',
    scope: SCOPES.join(' '), access_type: 'offline', prompt: 'consent',
    ...(process.env.GMAIL_LOGIN_HINT ? { login_hint: process.env.GMAIL_LOGIN_HINT } : {}) });  /* pick the right Google account */
  console.log('\nOpening the browser - sign in to the Google account to clean and click Allow\n');
  exec(`start "" "${url}"`);
  await new Promise((resolve, reject) => {
    const srv = createServer(async (req, res) => {
      if (!req.url.startsWith('/oauth2callback')) { res.writeHead(404); return res.end(); }
      const q = new URL(req.url, REDIRECT_URI).searchParams;
      if (!q.get('code')) { res.writeHead(400); res.end('Sign-in cancelled: ' + (q.get('error') || 'no code')); srv.close(); return reject(new Error(q.get('error') || 'no code')); }
      try {
        const t = await tokenCall({ code: q.get('code'), client_id: c.client_id, client_secret: c.client_secret,
          redirect_uri: REDIRECT_URI, grant_type: 'authorization_code' });
        writeFileSync(TOKEN_PATH, JSON.stringify({ ...t, expiry_date: Date.now() + t.expires_in * 1000 }, null, 2));
        res.writeHead(200, { 'Content-Type': 'text/html' });
        res.end('<body style="background:#1d2024;color:#e8eaed;font:16px sans-serif;padding:40px">' +
                '<h2 style="color:#ff6a00">Connected.</h2>You can close this tab.</body>');
        console.log('\nSigned in. Token saved to ' + TOKEN_PATH);
        srv.close(); resolve();
      } catch (e) { res.writeHead(500); res.end(e.message); srv.close(); reject(e); }
    }).listen(REDIRECT_PORT, '127.0.0.1');
  });
}

/* every calendar ticked in the Google Calendar sidebar, merged, soonest first */
async function calendar() {
  const CAL = 'https://www.googleapis.com/calendar/v3';
  const list = await api(CAL + '/users/me/calendarList?maxResults=50');
  const picked = (list.items || []).filter(c => c.selected);
  const timeMin = new Date().toISOString();
  const results = await Promise.all(picked.map(c =>
    api(`${CAL}/calendars/${encodeURIComponent(c.id)}/events?` + new URLSearchParams({
      timeMin, singleEvents: 'true', orderBy: 'startTime', maxResults: '10' }))
      .then(r => (r.items || []).map(e => ({
        title: e.summary || '(no title)',
        start: e.start?.dateTime || e.start?.date,
        allDay: !e.start?.dateTime,
        cal: c.summaryOverride || c.summary,
        link: e.htmlLink,
        meet: e.conferenceData?.entryPoints?.[0]?.uri || e.hangoutLink || null,
      }))).catch(() => [])));
  const events = results.flat().sort((a, b) => new Date(a.start) - new Date(b.start)).slice(0, 8);
  console.log(JSON.stringify({ source: 'google-calendar', fetched: new Date().toISOString(),
    calendars: picked.map(c => c.summaryOverride || c.summary), events }));
}

/* last 3 days of inbox THREADS, headers only (never bodies). Promotions, Social and
   Forums tabs are dropped by the query itself. Updates stays in, because Upwork client
   messages land there. One row per thread, describing its latest message, plus whether
   The user wrote anywhere in it - that is how a reply to him gets spotted.
   bulk = the latest message carries List-Unsubscribe or Precedence: bulk/list. */
const MAIL_Q = 'in:inbox newer_than:3d -category:promotions -category:social -category:forums';
const GM = 'https://gmail.googleapis.com/gmail/v1/users/me';
const HDRS = ['Subject', 'From', 'List-Unsubscribe', 'Precedence'].map(h => 'metadataHeaders=' + h).join('&');

function threadRow(t) {
  const msgs = t.messages || [];
  const last = msgs[msgs.length - 1] || {};
  const head = m => { const h = {}; (m.payload?.headers || []).forEach(x => h[x.name.toLowerCase()] = x.value); return h; };
  const h = head(last), first = head(msgs[0] || {});
  const labels = last.labelIds || [];
  return {
    id: t.id, subject: h.subject || first.subject || '(no subject)', from: h.from || '',
    ts: +(last.internalDate || 0), n: msgs.length,
    unread: msgs.some(m => (m.labelIds || []).includes('UNREAD')),
    fromMe: labels.includes('SENT'),
    iWrote: msgs.some(m => (m.labelIds || []).includes('SENT')),
    bulk: !!h['list-unsubscribe'] || /bulk|list/i.test(h.precedence || ''),
    cat: (labels.find(l => l.startsWith('CATEGORY_')) || '').replace('CATEGORY_', '').toLowerCase(),
    /* the user's own labels on any message in the thread, as ids (mail() swaps in the names) */
    labels: [...new Set(msgs.flatMap(m => (m.labelIds || []).filter(l => l.startsWith('Label_'))))]
  };
}

/* Thread rows are cached outside the repo, keyed by Gmail's historyId, so a refresh
   only re-reads threads that changed. Keeps us far under Gmail's per-minute quota.
   Each query gets its own cache file, because a save keeps only that query's threads. */
const CACHE_PATH = join(DIR, 'mail-cache.json');
const STAR_CACHE_PATH = join(DIR, 'mail-starred-cache.json');
async function threads(q, max, cachePath = null) {
  const list = await api(`${GM}/threads?` + new URLSearchParams({ q, maxResults: String(max) }));
  const items = list.threads || [];
  let cache = {};
  if (cachePath) try { cache = JSON.parse(readFileSync(cachePath, 'utf8')); } catch (_) {}
  const fresh = {}, todo = [];
  /* rows cached before labels were read have no labels field, so read those again */
  items.forEach(t => cache[t.id]?.h === t.historyId && cache[t.id].row?.labels ? fresh[t.id] = cache[t.id] : todo.push(t));
  for (let i = 0; i < todo.length; i += 10)          /* 10 at a time keeps well inside Gmail's rate limit */
    await Promise.all(todo.slice(i, i + 10).map(t =>
      api(`${GM}/threads/${t.id}?format=metadata&${HDRS}`)
        .then(x => { fresh[t.id] = { h: t.historyId, row: threadRow(x) }; }).catch(() => {})));
  if (cachePath) try { writeFileSync(cachePath, JSON.stringify(fresh)); } catch (_) {}
  return { total: items.length, rows: items.map(t => fresh[t.id]?.row).filter(Boolean) };
}

/* inbox rows for triage, plus every starred thread (any age) for the widget's Starred tab */
const STAR_Q = 'is:starred';
async function mail() {
  const [{ total, rows }, star, lab] = await Promise.all([threads(MAIL_Q, 100, CACHE_PATH),
    threads(STAR_Q, 25, STAR_CACHE_PATH), api(`${GM}/labels`).catch(() => ({}))]);
  const names = Object.fromEntries((lab.labels || []).map(l => [l.id, l.name]));
  const named = r => ({ ...r, labels: (r.labels || []).map(id => names[id] || id) });
  console.log(JSON.stringify({ query: MAIL_Q, total, rows: rows.map(named), starred: star.rows.map(named) }));
}

/* read-only helper for tuning the rules:  node tools/google.mjs search "from:upwork.com newer_than:30d" */
async function search() {
  const { rows } = await threads(process.argv[3] || MAIL_Q, +process.argv[4] || 30);
  rows.forEach(r => console.log([r.unread ? 'U' : ' ', r.fromMe ? 'ME' : r.iWrote ? 'RE' : '  ',
    r.bulk ? 'BULK' : '    ', (r.cat || '').padEnd(8), r.from.slice(0, 38).padEnd(38), '|', r.subject.slice(0, 70)].join(' ')));
}

const cmd = process.argv[2];
const run = { auth, calendar, mail, search }[cmd];
if (!run) console.log('Usage: node tools/google.mjs auth | calendar | mail | search "<gmail query>" [max]');
else run().catch(e => { console.error(e.message); process.exit(1); });
