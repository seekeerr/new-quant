"""
Localhost tracker for the frozen strategy.

    py -m strategy_live.server            -> http://127.0.0.1:8765
    py -m strategy_live.server --port 9000

Stdlib only - no Flask, no build step. The page reads the latest snapshot and
renders it; "Recompute" reruns the model in a background thread and the page
picks up the new snapshot when it lands.

Binds to 127.0.0.1 deliberately: this shows a live trading book and should not
be reachable from the network.
"""
import sys
import os
import json
import argparse
import threading
import traceback
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

SNAP_DIR = os.path.join(ROOT, 'strategy_live', 'snapshots')
LATEST = os.path.join(SNAP_DIR, 'latest.json')

_job = {'running': False, 'started': None, 'error': None, 'finished': None}


def _recompute():
    _job.update(running=True, started=datetime.now().isoformat(timespec='seconds'),
                error=None)
    try:
        from strategy_live.compute import build
        build(with_backtest=True)
        _job['finished'] = datetime.now().isoformat(timespec='seconds')
    except Exception:
        _job['error'] = traceback.format_exc()[-1500:]
    finally:
        _job['running'] = False


def load_latest():
    if not os.path.exists(LATEST):
        return None
    with open(LATEST, encoding='utf-8') as f:
        return json.load(f)


def snapshot_list():
    if not os.path.isdir(SNAP_DIR):
        return []
    xs = [f[:-5] for f in os.listdir(SNAP_DIR)
          if f.endswith('.json') and f != 'latest.json']
    return sorted(xs, reverse=True)


PAGE = r"""<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Strategy Tracker</title>
<style>
:root{
 --bg:#F4F6F9;--card:#ffffff;--c2:#EBEFF5;--ink:#14171E;--ink2:#3B4350;
 --mut:#6A7484;--line:#D9DFE8;--acc:#1F46C8;--accs:#E4E9FA;
 --pos:#0B7355;--poss:#DCF0E8;--neg:#B63A33;--negs:#FAE3E1;--hold:#8A6A1F;--holds:#F7EDD6;
}
@media(prefers-color-scheme:dark){:root:not([data-theme=light]){
 --bg:#0E1117;--card:#161A22;--c2:#1E232D;--ink:#E9ECF2;--ink2:#C3CAD6;
 --mut:#8C96A6;--line:#2A303B;--acc:#7E9DFF;--accs:#1B2542;
 --pos:#4CC79B;--poss:#13302A;--neg:#F0776C;--negs:#35201E;--hold:#D6AC5A;--holds:#2E2718;}}
:root[data-theme=dark]{
 --bg:#0E1117;--card:#161A22;--c2:#1E232D;--ink:#E9ECF2;--ink2:#C3CAD6;
 --mut:#8C96A6;--line:#2A303B;--acc:#7E9DFF;--accs:#1B2542;
 --pos:#4CC79B;--poss:#13302A;--neg:#F0776C;--negs:#35201E;--hold:#D6AC5A;--holds:#2E2718;}
*{box-sizing:border-box}
body{margin:0;padding:0 18px 60px;background:var(--bg);color:var(--ink);
 font:14px/1.55 ui-sans-serif,system-ui,"Segoe UI",Roboto,sans-serif}
.w{max-width:1180px;margin:0 auto}
.mono{font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace;font-variant-numeric:tabular-nums}
h1{font-size:1.32rem;margin:0;letter-spacing:-.02em}
h2{font-size:.96rem;margin:0 0 12px;letter-spacing:-.01em}
.eb{font:600 .63rem/1 ui-monospace,monospace;letter-spacing:.14em;text-transform:uppercase;color:var(--mut)}
header{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;
 flex-wrap:wrap;padding:22px 0 16px;border-bottom:2px solid var(--ink)}
.hl{display:flex;flex-direction:column;gap:6px}
.meta{font:.72rem/1.5 ui-monospace,monospace;color:var(--mut)}
.hr{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
button{font:600 .76rem ui-sans-serif,system-ui;padding:8px 14px;border-radius:5px;
 border:1px solid var(--line);background:var(--card);color:var(--ink);cursor:pointer}
button.p{background:var(--acc);color:#fff;border-color:transparent}
button:disabled{opacity:.5;cursor:not-allowed}
button:focus-visible{outline:2px solid var(--acc);outline-offset:2px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(112px,1fr));gap:1px;
 background:var(--line);border:1px solid var(--line);border-radius:6px;overflow:hidden;margin:18px 0}
.st{background:var(--card);padding:13px 15px}
/* money tiles lead and are visually weighted above the ratio tiles */
.st.money-kpi{background:var(--accs)}
.st.money-kpi .v{font-size:1.5rem}
.st.money-kpi .k{color:var(--acc);font-weight:600}
.st .v{font:700 1.4rem/1.1 ui-sans-serif,system-ui;letter-spacing:-.025em;font-variant-numeric:tabular-nums}
.st .k{font:500 .6rem/1 ui-monospace,monospace;letter-spacing:.12em;text-transform:uppercase;
 color:var(--mut);margin-top:5px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin:18px 0}
@media(max-width:820px){.grid{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--line);border-radius:7px;padding:16px 18px}
.act{display:flex;flex-direction:column;gap:6px}
.arow{display:grid;grid-template-columns:58px 1fr auto;gap:10px;align-items:center;
 padding:8px 11px;border-radius:5px;background:var(--c2)}
.arow.b{background:var(--poss)} .arow.s{background:var(--negs)} .arow.h{background:transparent;
 border:1px solid var(--line)}
.pill{font:700 .62rem/1 ui-monospace,monospace;letter-spacing:.09em;padding:5px 7px;
 border-radius:3px;text-align:center}
.arow.b .pill{background:var(--pos);color:#fff} .arow.s .pill{background:var(--neg);color:#fff}
.arow.h .pill{background:var(--c2);color:var(--mut)}
.sym{font:600 .85rem ui-monospace,monospace}
.why{font:.7rem ui-monospace,monospace;color:var(--mut)}
table{width:100%;border-collapse:collapse;font-size:.8rem}
th{font:600 .6rem ui-monospace,monospace;letter-spacing:.1em;text-transform:uppercase;
 color:var(--mut);text-align:left;padding:0 9px 8px 0;border-bottom:1px solid var(--line);white-space:nowrap}
td{padding:6px 9px 6px 0;border-bottom:1px solid var(--line);white-space:nowrap}
tr:last-child td{border-bottom:0}
.r{text-align:right}
tr.zbuy td:first-child{box-shadow:inset 3px 0 0 var(--pos)}
tr.zhold td:first-child{box-shadow:inset 3px 0 0 var(--hold)}
tr.own{background:var(--accs)}
.tag{font:600 .58rem ui-monospace,monospace;padding:2px 5px;border-radius:3px;
 background:var(--acc);color:#fff;margin-left:6px}
.scroll{overflow-x:auto}
.bars{display:flex;gap:3px;align-items:flex-end;height:76px;margin-top:4px}
.bcol{flex:1;display:flex;flex-direction:column;justify-content:flex-end;min-width:0}
.bar{border-radius:2px 2px 0 0;background:var(--pos)}
.bar.n{background:var(--neg);border-radius:0 0 2px 2px}
.blabs{display:flex;gap:3px;margin-top:5px}
.blab{flex:1;font:.54rem ui-monospace,monospace;color:var(--mut);text-align:center;
 overflow:hidden;min-width:0}
.note{font-size:.78rem;color:var(--mut);margin-top:10px;line-height:1.5}
.money{background:var(--card);border:1px solid var(--line);border-radius:7px;
 padding:20px 22px;margin:18px 0}
.mtop{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap}
.mbig{font:700 2.5rem/1 ui-sans-serif,system-ui;letter-spacing:-.035em;
 font-variant-numeric:tabular-nums}
.marrow{font:400 1.5rem ui-sans-serif;color:var(--mut)}
.mprofit{font:600 1rem ui-sans-serif;padding:5px 11px;border-radius:5px;
 background:var(--poss);color:var(--pos)}
.mprofit.dn{background:var(--negs);color:var(--neg)}
.msub{font:.8rem/1.6 ui-sans-serif;color:var(--mut);margin-top:10px}
.yrs{display:grid;grid-template-columns:repeat(auto-fit,minmax(112px,1fr));
 gap:9px;margin-top:18px}
.yr{background:var(--c2);border-radius:5px;padding:11px 13px}
.yr .y{font:600 .62rem ui-monospace,monospace;letter-spacing:.1em;color:var(--mut)}
.yr .v{font:600 .98rem/1.3 ui-sans-serif;font-variant-numeric:tabular-nums;margin-top:3px}
.yr .g{font:600 .74rem ui-monospace,monospace;margin-top:2px}
.spark{display:flex;gap:1px;align-items:flex-end;height:44px;margin-top:16px}
.spark i{flex:1;background:var(--acc);opacity:.55;border-radius:1px 1px 0 0;min-width:0}
.spark i.last{opacity:1}
.lad{margin-top:18px}
.ladrow{display:grid;grid-template-columns:96px 1fr 74px;gap:12px;align-items:center;
 padding:6px 0;border-bottom:1px solid var(--line)}
.ladrow:last-child{border-bottom:0}
.ladrow.you{background:var(--accs);border-radius:5px;padding:7px 9px;
 margin:0 -9px;border-bottom:0}
.ladcap{font:600 .76rem ui-monospace,monospace}
.ladtrack{height:16px;background:var(--c2);border-radius:3px;overflow:hidden}
.ladfill{height:100%;background:var(--acc);opacity:.75;border-radius:3px}
.ladrow.you .ladfill{opacity:1}
.ladval{font:600 .78rem ui-monospace,monospace;text-align:right;font-variant-numeric:tabular-nums}
.help{background:var(--accs);border-radius:7px;padding:15px 18px;margin:16px 0;
 font:.82rem/1.65 ui-sans-serif;color:var(--ink2)}
.help b{color:var(--ink)}
.help .hq{display:block;margin-bottom:7px}
.help .hq:last-child{margin-bottom:0}
.banner{padding:11px 15px;border-radius:6px;background:var(--holds);color:var(--hold);
 font:600 .78rem ui-sans-serif,system-ui;margin:14px 0}
.err{background:var(--negs);color:var(--neg);white-space:pre-wrap;font:.7rem ui-monospace,monospace;
 padding:12px;border-radius:6px;margin:12px 0;max-height:220px;overflow:auto}
.dot{display:inline-block;width:7px;height:7px;border-radius:50%;background:var(--pos);margin-right:6px}
.dot.busy{background:var(--hold);animation:p 1s infinite}
@keyframes p{50%{opacity:.3}}
@media(prefers-reduced-motion:reduce){.dot.busy{animation:none}}
footer{margin-top:26px;padding-top:16px;border-top:1px solid var(--line);
 font:.7rem/1.7 ui-monospace,monospace;color:var(--mut)}
</style></head><body><div class="w" id="app">loading…</div>
<script>
const $=(h)=>{const d=document.createElement('div');d.innerHTML=h;return d};
const fmt=(n,d=2)=>n==null?'—':Number(n).toFixed(d);
const sgn=(n)=>n==null?'—':(n>0?'+':'')+Number(n).toFixed(2)+'%';
// Indian money formatting - lakh/crore, because that is how the book is read
const rup=(n)=>{if(n==null)return '—';const a=Math.abs(n),s=n<0?'-':'';
  if(a>=1e7)return s+'₹'+(a/1e7).toFixed(2)+' cr';
  if(a>=1e5)return s+'₹'+(a/1e5).toFixed(2)+' L';
  return s+'₹'+Math.round(a).toLocaleString('en-IN')};
let S=null,busy=false;

async function load(){
  const r=await fetch('/api/snapshot'); S=await r.json(); render();
}
async function poll(){
  const r=await fetch('/api/job'); const j=await r.json();
  const b=document.getElementById('rb');
  if(j.running){busy=true; if(b){b.disabled=true;b.textContent='Computing…'} setTimeout(poll,1500);}
  else if(busy){busy=false; await load();}
}
async function recompute(){
  const b=document.getElementById('rb'); b.disabled=true; b.textContent='Computing…';
  await fetch('/api/recompute',{method:'POST'}); busy=true; setTimeout(poll,1200);
}

function render(){
  if(!S||S.error){document.getElementById('app').innerHTML=
    '<div class="err">No snapshot yet. Run: py -m strategy_live.compute</div>';return}
  const p=S.performance||{}, a=S.actions||{}, held=new Set(S.holdings||[]);
  const q=(p.quarters||[]).slice(-12);
  const mx=Math.max(1,...q.map(x=>Math.abs(x.r)));

  let h=`<header>
    <div class="hl"><h1>${S.strategy}</h1>
      <div class="meta">v${S.version} · hash ${S.param_hash} · frozen ${S.params.frozen_on||'—'}<br>
      data as of <b>${S.asof}</b> · universe ${S.universe_size} · computed ${S.generated}</div></div>
    <div class="hr">
      <button id="rb" class="p" onclick="recompute()">Recompute</button>
      <button onclick="location.reload()">Reload</button>
    </div></header>`;

  const M=S.money;
  if(M){
    const up=M.profit>=0, sp=(M.curve||[]).filter((_,i)=>i%2===0);
    const lo=Math.min(...sp.map(x=>x.v)), hi=Math.max(...sp.map(x=>x.v));
    h+=`<div class="money"><div class="eb">Paise — kitne ke kitne bane</div>
      <div class="mtop" style="margin-top:10px">
        <span class="mbig" style="color:var(--mut)">${rup(M.invested)}</span>
        <span class="marrow">&rarr;</span>
        <span class="mbig">${rup(M.now)}</span>
        <span class="mprofit ${up?'':'dn'}">${M.multiple}x</span>
      </div>
      <div class="msub">${M.start_date} se ${M.end_date} tak — ${M.years} saal.
        Beech mein sabse bada gira: <b>${M.worst_dip}%</b> (${rup(M.worst_dip_rupees)}).
        ${M.is_real_money?'':'<b>Ye backtest ka paisa hai — asli nahi.</b>'}</div>
      <div class="spark">`;
    sp.forEach((x,i)=>{const ht=hi>lo?Math.max(2,(x.v-lo)/(hi-lo)*42):2;
      h+=`<i class="${i===sp.length-1?'last':''}" style="height:${ht}px"></i>`});
    h+=`</div><div class="yrs">`;
    (M.per_year||[]).forEach(y=>{const g=y.pct>=0;
      h+=`<div class="yr"><div class="y">${y.year}</div>
        <div class="v">${rup(y.value)}</div>
        <div class="g" style="color:${g?'var(--pos)':'var(--neg)'}">${g?'+':''}${y.pct}%</div></div>`});
    h+=`</div><div class="note">Capital strategy_live/capital.json mein badal sakte hain.</div></div>`;
  }

  const L=S.ladder;
  if(L&&L.length){
    const mx=Math.max(...L.map(x=>x.cagr)), mine=(S.money||{}).invested;
    h+=`<div class="card lad"><div class="eb">Size ka asar</div>
      <h2 style="margin-top:8px">Kitne paise par kitna return</h2>`;
    L.forEach(x=>{
      const isMine=mine&&Math.abs(x.capital-mine)<1;
      h+=`<div class="ladrow ${isMine?'you':''}">
        <span class="ladcap">${rup(x.capital)}${isMine?' ←':''}</span>
        <span class="ladtrack"><span class="ladfill" style="width:${x.cagr/mx*100}%;display:block"></span></span>
        <span class="ladval">${x.cagr}%</span></div>`});
    h+=`<div class="note">Chhoti raqam par har order ka fixed ₹20 brokerage aur
      poore share khareedne ki majboori return kha jaati hai. Ye scaled numbers
      nahi hain — har line ka alag backtest chala hai.</div></div>`;
  }

  h+=`<div class="help">
    <span class="hq"><b>asof ${S.asof}</b> — is date tak ka market data use hua hai.
      Aaj se purana dikhe to matlab naya bhavcopy download nahi hua.</span>
    <span class="hq"><b>Ye page kya karta hai</b> — roz ke bhaav se 500 stocks ko score karke
      batata hai ki top 10 kaunse hain, aur aapke portfolio se kya badalna chahiye.</span>
    <span class="hq"><b>Agla update</b> — tracker har 6 ghante khud chalta hai; ya
      "Recompute" dabaiye. Par asli trade mahine mein ek baar —
      agle rebalance par.</span></div>`;

  h+=`<div class="stats">`;
  if(M){
    const up=M.profit>=0;
    h+=`<div class="st money-kpi"><div class="v">${rup(M.now)}</div>
        <div class="k">Value now</div></div>
      <div class="st money-kpi"><div class="v" style="color:${up?'var(--pos)':'var(--neg)'}">${up?'+':''}${rup(M.profit)}</div>
        <div class="k">Profit</div></div>
      <div class="st money-kpi"><div class="v" style="color:${up?'var(--pos)':'var(--neg)'}">${up?'+':''}${M.pct}%</div>
        <div class="k">Total return</div></div>`;
  }
  h+=`<div class="st"><div class="v">${fmt(p.cagr,2)}%</div><div class="k">CAGR</div></div>
    <div class="st"><div class="v">${fmt(p.sharpe,2)}</div><div class="k">Sharpe</div></div>
    <div class="st"><div class="v" style="color:var(--neg)">${fmt(p.maxdd,1)}%</div><div class="k">Max DD</div></div>
    <div class="st"><div class="v">${a.hold?.length??0}/${S.params.n_stocks}</div><div class="k">Held</div></div>
    <div class="st"><div class="v">${(a.buy?.length??0)+(a.sell?.length??0)}</div><div class="k">Pending trades</div></div>
    <div class="st"><div class="v">${p.n_trades??'—'}</div><div class="k">Trades to date</div></div>
  </div>`;

  const nAct=(a.buy?.length??0)+(a.sell?.length??0);
  if(nAct) h+=`<div class="banner">${nAct} trade${nAct>1?'s':''} pending at the next monthly rebalance — ${a.buy.length} buy, ${a.sell.length} sell.</div>`;

  h+=`<div class="grid"><div class="card"><div class="eb">Next rebalance</div>
    <h2 style="margin-top:8px">What to trade</h2><div class="act">`;
  (a.sell||[]).forEach(x=>h+=`<div class="arow s"><span class="pill">SELL</span>
    <span class="sym">${x.symbol}</span><span class="why">${x.reason||''}</span></div>`);
  (a.buy||[]).forEach(x=>h+=`<div class="arow b"><span class="pill">BUY</span>
    <span class="sym">${x.symbol}</span><span class="why">rank ${x.rank}</span></div>`);
  (a.hold||[]).forEach(x=>h+=`<div class="arow h"><span class="pill">HOLD</span>
    <span class="sym">${x.symbol}</span><span class="why">rank ${x.rank}</span></div>`);
  h+=`</div><div class="note">Buy at rank ≤ ${S.params.n_stocks}; keep until rank &gt; ${S.params.buffer}.
    Equal weight, ${S.params.rebalance} rebalance.</div></div>`;

  h+=`<div class="card"><div class="eb">Out of sample</div>
    <h2 style="margin-top:8px">Quarterly returns</h2><div class="bars">`;
  q.forEach(x=>{const pos=x.r>=0,ht=Math.max(2,Math.abs(x.r)/mx*70);
    h+=`<div class="bcol">${pos?`<div class="bar" style="height:${ht}px"></div>`:''}
        ${!pos?`<div class="bar n" style="height:${ht}px"></div>`:''}</div>`});
  h+=`</div><div class="blabs">`;
  q.forEach(x=>h+=`<div class="blab">${x.q.slice(2)}</div>`);
  h+=`</div><div class="note">${p.start} → ${p.end} · ₹1 cr book → ₹${((p.final||0)/1e7).toFixed(2)} cr.
    Backtested, not live-traded.</div></div></div>`;

  h+=`<div class="card"><div class="eb">Ranking</div>
   <h2 style="margin-top:8px">Top 30 today</h2><div class="scroll"><table>
   <thead><tr><th>#</th><th>Symbol</th><th class="r">Price</th><th class="r">20d</th>
   <th class="r">Mom %ile</th><th class="r">LowVol %ile</th><th class="r">Amihud %ile</th>
   <th class="r">Turnover</th></tr></thead><tbody>`;
  (S.ranks||[]).slice(0,30).forEach(r=>{
    const z=r.rank<=S.params.n_stocks?'zbuy':(r.rank<=S.params.buffer?'zhold':'');
    h+=`<tr class="${z} ${held.has(r.symbol)?'own':''}">
      <td class="mono">${r.rank}</td>
      <td class="mono" style="font-weight:600">${r.symbol}${held.has(r.symbol)?'<span class="tag">HELD</span>':''}</td>
      <td class="mono r">${fmt(r.price,1)}</td>
      <td class="mono r" style="color:${r.ret20d>=0?'var(--pos)':'var(--neg)'}">${sgn(r.ret20d)}</td>
      <td class="mono r">${fmt(r.mom_pct,0)}</td><td class="mono r">${fmt(r.lowvol_pct,0)}</td>
      <td class="mono r">${fmt(r.amihud_pct,0)}</td>
      <td class="mono r">₹${fmt(r.turnover_lakh,0)}L</td></tr>`});
  h+=`</tbody></table></div>
   <div class="note"><span style="color:var(--pos)">▌</span> ranks 1–${S.params.n_stocks} buy zone ·
   <span style="color:var(--hold)">▌</span> ${S.params.n_stocks+1}–${S.params.buffer} buffer (hold, don't buy) ·
   highlighted rows are currently held.</div></div>`;

  h+=`<footer>Frozen ${S.params.frozen_on} · momentum ${S.params.w_momentum} /
   lowvol ${S.params.w_lowvol} / amihud ${S.params.w_amihud} ·
   top-${S.params.rank_band[1]} by turnover · no stop loss.<br>
   Snapshots: strategy_live/snapshots/ · edit parameters only in strategy_live/frozen.py.<br>
   Backtested figures. Not investment advice.</footer>`;

  document.getElementById('app').innerHTML=h;
}
load(); poll();
</script></body></html>"""


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype='application/json'):
        b = body.encode('utf-8') if isinstance(body, str) else body
        self.send_response(code)
        self.send_header('Content-Type', ctype + '; charset=utf-8')
        self.send_header('Content-Length', str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path in ('/', '/index.html'):
            return self._send(200, PAGE, 'text/html')
        if self.path == '/api/snapshot':
            s = load_latest()
            return self._send(200, json.dumps(s or {'error': 'no snapshot'}))
        if self.path == '/api/job':
            return self._send(200, json.dumps(_job))
        if self.path == '/api/snapshots':
            return self._send(200, json.dumps(snapshot_list()))
        if self.path.startswith('/api/snapshot/'):
            d = self.path.rsplit('/', 1)[-1]
            p = os.path.join(SNAP_DIR, f'{d}.json')
            if not os.path.exists(p):
                return self._send(404, json.dumps({'error': 'not found'}))
            with open(p, encoding='utf-8') as f:
                return self._send(200, f.read())
        self._send(404, json.dumps({'error': 'not found'}))

    def do_POST(self):
        if self.path == '/api/recompute':
            if _job['running']:
                return self._send(409, json.dumps({'error': 'already running'}))
            threading.Thread(target=_recompute, daemon=True).start()
            return self._send(202, json.dumps({'started': True}))
        self._send(404, json.dumps({'error': 'not found'}))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=8765)
    ap.add_argument('--host', default='127.0.0.1')
    a = ap.parse_args()

    if not os.path.exists(LATEST):
        print('no snapshot yet - computing one first (about 20s)...')
        from strategy_live.compute import build
        build(with_backtest=True)

    srv = ThreadingHTTPServer((a.host, a.port), H)
    print(f'\n  strategy tracker  ->  http://{a.host}:{a.port}\n'
          f'  snapshots: {SNAP_DIR}\n  Ctrl+C to stop\n')
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print('stopped')


if __name__ == '__main__':
    main()
