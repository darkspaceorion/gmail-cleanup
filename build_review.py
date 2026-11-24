"""Stage 5: build the review page from decisions.json and open it in the browser.

The page holds email subjects, so it lives in .nexus-os/gmail-cleanup/review.html, never in the repo.
The user sets each sender to Delete or Keep, then clicks Export. That downloads
gmail-cleanup-approved.json to Downloads, which apply.py reads. The export also records what NEXUS
recommended next to what the user chose, so each trial can be graded (grade.py).
"""
import argparse
import json
import os
from pathlib import Path

import gmail

PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Gmail Cleanup Review</title>
<style>
:root{--bg:#f6f6f4;--card:#fff;--ink:#1d2024;--mute:#6b6f76;--line:#e2e2de;--acc:#d45500;--del:#c0392b;--keep:#2e7d4f;--rev:#a07000}
@media (prefers-color-scheme:dark){:root{--bg:#1d2024;--card:#26292e;--ink:#e8eaed;--mute:#9aa0a6;--line:#363a40;--acc:#ff6a00;--del:#ff6b5e;--keep:#5cc98a;--rev:#e0b040}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,sans-serif}
header{position:sticky;top:0;background:var(--bg);border-bottom:1px solid var(--line);padding:14px 16px;z-index:2}
h1{margin:0 0 6px;font-size:18px}h1 b{color:var(--acc)}
.tot{display:flex;gap:18px;flex-wrap:wrap;color:var(--mute)}.tot b{color:var(--ink);font-size:16px}
.bar{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}
button,select{font:inherit;border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:6px;padding:5px 10px;cursor:pointer}
button.go{background:var(--acc);border-color:var(--acc);color:#fff;font-weight:600}
main{padding:12px 16px;max-width:1100px;margin:auto}
.row{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--line);border-radius:8px;padding:10px 12px;margin-bottom:8px}
.row.d{border-left-color:var(--del)}.row.k{border-left-color:var(--keep)}
.top{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap}.who{font-weight:600;word-break:break-all}
.meta{color:var(--mute);font-size:12.5px}.tag{font-size:11.5px;padding:1px 7px;border-radius:10px;border:1px solid currentColor}
.DELETE{color:var(--del)}.KEEP{color:var(--keep)}.REVIEW,.SPLIT{color:var(--rev)}
.pick{margin-left:auto;display:flex;gap:4px}.pick button.on.dl{background:var(--del);color:#fff;border-color:var(--del)}
.pick button.on.kp{background:var(--keep);color:#fff;border-color:var(--keep)}
.pick button.us{border-style:dashed}.pick button.us.done{border-style:solid;opacity:.6;cursor:default}
.sug{color:var(--acc)}
ul{margin:6px 0 0;padding-left:18px;color:var(--mute);font-size:12.5px}li{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
</style></head><body>
<header><h1>Gmail Cleanup <b>Review</b></h1>
<div class="tot"><span>To trash: <b id="n">0</b> emails</span><span><b id="mb">0</b> MB</span><span><b id="dec">0</b> of <b id="all">0</b> senders decided</span></div>
<p class="meta" style="margin:8px 0 0"><b>Bin / Keep</b> is only about emails <b>already in your inbox</b> older than 90 days: would you miss them? &nbsp;Whether you still want <b>new</b> mail from a sender is the separate <b>Unsubscribe</b> button.</p>
<div class="bar"><select id="f"><option value="">All</option><option>DELETE</option><option>REVIEW</option><option>SPLIT</option><option>KEEP</option><option value="todo">Undecided</option><option value="unsub">Suggest unsubscribe</option><option value="recheck">Recheck</option></select>
<select id="s"><option value="count">Most emails</option><option value="bytes">Most MB</option></select>
<button id="acc">Accept all DELETE suggestions</button><button class="go" id="exp">Export decisions</button></div></header>
<main id="list"></main>
<script>
const D=__DATA__;const KEY='gmail-cleanup-picks';let picks={};
const RECHECK=__RECHECK__,RECHECK_ID='__RECHECK_ID__';
try{picks=JSON.parse(localStorage.getItem(KEY)||'{}')}catch(e){}
// Rows to redo after a grading round: clear their old pick once, then show them under "Recheck".
try{if(RECHECK.length&&localStorage.getItem(KEY+'-reset')!==RECHECK_ID){for(const k of RECHECK)delete picks[k];
 localStorage.setItem(KEY,JSON.stringify(picks));localStorage.setItem(KEY+'-reset',RECHECK_ID)}}catch(e){}
let unsubbed={};try{unsubbed=JSON.parse(localStorage.getItem(KEY+'-unsub')||'{}')}catch(e){}
const save=()=>{try{localStorage.setItem(KEY,JSON.stringify(picks));localStorage.setItem(KEY+'-unsub',JSON.stringify(unsubbed))}catch(e){}};
// Suggest unsubscribing from bulk senders we'd bin, or that the user mostly never opens.
const suggest=r=>r.decision!=='KEEP'&&(r.decision==='DELETE'||r.unread_share>=0.8);
const unsubLabel=r=>unsubbed[r.key]?unsubbed[r.key]:!r.unsub?'Find unsubscribe':r.unsub.unsub_one_click?'Unsubscribe (1 click)':'Unsubscribe';
function unsubscribe(r){if(unsubbed[r.key])return;const u=r.unsub||{};
 if(u.unsub_one_click){fetch(u.unsub_url,{method:'POST',mode:'no-cors',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'List-Unsubscribe=One-Click'})
  .then(()=>{unsubbed[r.key]='Unsubscribed';save();draw()}).catch(()=>{window.open(u.unsub_url,'_blank')});return}
 if(u.unsub_url){window.open(u.unsub_url,'_blank');unsubbed[r.key]='Opened link'}
 else if(u.unsub_mailto){location.href=u.unsub_mailto;unsubbed[r.key]='Email drafted'}
 else{window.open('https://mail.google.com/mail/u/0/#all/'+r.latest_id,'_blank');return}
 save();draw()}
const ids=r=>picks[r.key]!=='delete'?[]:(r.decision==='DELETE'||r.decision==='SPLIT')?r.delete_ids:r.old_ids;
const fmt=ms=>new Date(ms).toISOString().slice(0,7);
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function totals(){let n=0,b=0,dec=0;for(const r of D){const i=ids(r);n+=i.length;if(i.length)b+=r.decision==='DELETE'||r.decision==='SPLIT'?r.delete_bytes:r.bytes;if(picks[r.key])dec++}
 document.getElementById('n').textContent=n.toLocaleString();document.getElementById('mb').textContent=(b/1e6).toFixed(1);
 document.getElementById('dec').textContent=dec;document.getElementById('all').textContent=D.length}
function draw(){const f=document.getElementById('f').value,s=document.getElementById('s').value;
 const rows=D.filter(r=>!f||(f==='todo'?!picks[r.key]:f==='unsub'?suggest(r):f==='recheck'?RECHECK.includes(r.key):r.decision===f)).sort((a,b)=>b[s]-a[s]);
 document.getElementById('list').innerHTML=rows.map(r=>{const p=picks[r.key];const old=(r.decision==='DELETE'||r.decision==='SPLIT')?r.delete_ids.length:r.old_ids.length;
  return `<div class="row ${p==='delete'?'d':p==='keep'?'k':''}" data-k="${esc(r.key)}"><div class="top">
  <span class="who">${esc(r.name||r.key)}</span><span class="meta">${esc(r.key)}</span>
  <span class="tag ${r.decision}">${r.decision}</span><span class="meta">${esc(r.reason)}${r.category?' · '+r.category.replace(/_/g,' '):''}</span>
  ${suggest(r)?'<span class="meta sug">suggest unsubscribe</span>':''}
  <span class="pick"><button class="us ${unsubbed[r.key]?'done':''}" data-a="unsub">${unsubLabel(r)}</button><button class="dl ${p==='delete'?'on':''}" data-a="delete">Bin old emails${old?' ('+old+')':''}</button><button class="kp ${p==='keep'?'on':''}" data-a="keep">Keep old emails</button></span></div>
  <div class="meta">${r.count} emails · ${(r.bytes/1e6).toFixed(1)} MB · ${fmt(r.first_ms)} to ${fmt(r.last_ms)} · ${Math.round(r.unread_share*100)}% unread${r.protected?' · '+r.protected+' protected (starred, labelled or replied)':''}</div>
  <ul>${r.samples.map(e=>`<li>${esc(e.subject||'(no subject)')}</li>`).join('')}</ul></div>`}).join('');totals()}
document.getElementById('list').onclick=e=>{const b=e.target.closest('button');if(!b)return;const k=b.closest('.row').dataset.k;
 if(b.dataset.a==='unsub')return unsubscribe(D.find(r=>r.key===k));
 picks[k]=picks[k]===b.dataset.a?undefined:b.dataset.a;if(!picks[k])delete picks[k];save();draw()};
document.getElementById('f').onchange=draw;document.getElementById('s').onchange=draw;
document.getElementById('acc').onclick=()=>{for(const r of D)if(r.decision==='DELETE'&&!picks[r.key])picks[r.key]='delete';save();draw()};
document.getElementById('exp').onclick=()=>{const out={exported:new Date().toISOString(),
 senders:D.filter(r=>picks[r.key]).map(r=>({key:r.key,recommended:r.decision,user:picks[r.key],count:r.count})),
 unsubscribed:Object.keys(unsubbed)};
 const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(out,null,1)],{type:'application/json'}));
 a.download='gmail-cleanup-approved.json';a.click()};
draw();
</script></body></html>"""


def build(recheck_trial=None):
    rows = json.loads(gmail.data_path("decisions.json").read_text(encoding="utf-8"))
    recheck = []
    if recheck_trial:  # the wrong deletes from a graded trial, to be picked again
        recheck = json.loads((Path(__file__).parent / "trials" / f"{recheck_trial}.json").read_text(encoding="utf-8"))["wrong_deletes"]
    path = gmail.data_path("review.html")
    data = json.dumps(rows, ensure_ascii=False).replace("</", "<\\/")
    page = PAGE.replace("__RECHECK__", json.dumps(recheck)).replace("__RECHECK_ID__", recheck_trial or "")
    path.write_text(page.replace("__DATA__", data), encoding="utf-8")
    return path


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--recheck", help="graded trial name, e.g. trial-2a: its wrong deletes get re-asked")
    p = build(ap.parse_args().recheck)
    print(f"Review page: {p}")
    os.startfile(p)
