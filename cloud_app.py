"""Protected StockAlgo dashboard, JSON API, and database-backed strategy builder."""
import os, re, secrets, time, threading
from pathlib import Path
from datetime import datetime, timedelta, time as clock_time, timezone
from zoneinfo import ZoneInfo
from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import HTMLResponse, FileResponse
import indicators as I
import builder_api as Builder
import cloud_store as DB
import stock_screener as Screener



SCREENER_HTML = r"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>StockAlgo Screener</title>
<style>
:root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;padding:18px;background:#0c1422;color:#e7eef9;font:14px system-ui}a,button{background:#2563eb;color:white;border:0;border-radius:8px;padding:9px 12px;text-decoration:none;cursor:pointer}button.secondary{background:#26364e}input,select,textarea{background:#0b1320;color:#e7eef9;border:1px solid #354862;border-radius:8px;padding:9px;max-width:100%}.wrap{max-width:1400px;margin:auto}.card{background:#152238;border:1px solid #2b3d57;border-radius:13px;padding:15px;margin:12px 0}.muted{color:#9cafc8}.row{display:flex;gap:9px;align-items:center;flex-wrap:wrap}.conditions{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:8px}.condition{display:grid;grid-template-columns:1fr 75px 90px 34px;gap:5px}.condition select,.condition input{width:100%;min-width:0}.tabs{display:flex;gap:6px;flex-wrap:wrap}.tabs button{background:#26364e}.tabs button.active{background:#2563eb}.tablewrap{overflow:auto}table{border-collapse:collapse;width:100%;min-width:760px}td,th{text-align:left;padding:9px;border-bottom:1px solid #2b3d57;white-space:nowrap}.pill{background:#123b32;color:#81e2bb;border-radius:30px;padding:5px 9px;font-size:12px}.hint{font-size:12px;color:#9cafc8}@media(max-width:600px){body{padding:10px}.condition{grid-template-columns:1fr 68px 78px 30px}.card{padding:12px}}
</style></head><body><main class="wrap">
<header class="row"><div style="flex:1"><h1 style="margin:0">Market Intelligence &amp; Stock Screener</h1><div class="muted">Find and compare companies using fundamental and market-derived technical conditions.</div></div><a href="/">Dashboard</a><a href="/market-data">Groww Market Data</a><a href="/builder">Strategy Builder</a></header>
<section class="card"><h3>How to use this screener</h3><div class="hint">1. Choose a filter category and add conditions. 2. AND means every condition must match; OR means at least one must match. 3. Run screen to see companies in your imported fundamental universe. 4. Save a screen to reuse it. Technical filters need stored 5-minute candles; fundamental filters need imported company financials.</div><div class="row" style="margin-top:10px"><span class="pill">Fundamentals: imported data</span><span class="pill">Technicals: Groww candles</span><span class="pill">Missing data never passes a filter</span></div></section>
<section class="card"><div class="row"><h3 style="margin-right:auto">1. Build your filters</h3><label>Category <select id="filterCategory"><option value="all">All categories</option><option value="fundamental">Fundamental</option><option value="technical">Technical</option><option value="market">Market data</option></select></label><label>Exchange <select id="exchange"><option>NSE</option><option>BSE</option></select></label><label>Logic <select id="logic"><option>AND</option><option>OR</option></select></label><button class="secondary" onclick="addCondition()">+ Add filter</button><button onclick="runScreen()">Run screen</button></div><div id="conditions" class="conditions"></div><p class="hint">Missing fundamental/technical values are excluded from a condition match. Use reporting period and source timestamps when interpreting results.</p><div class="row"><input id="screenName" placeholder="Name this screen"><button class="secondary" onclick="saveScreen()">Save screen</button><select id="savedScreens" onchange="loadScreen()"><option value="">Load saved screen…</option></select><span id="screenStatus" class="hint"></span></div></section>
<section class="card"><div class="row"><h3 style="margin-right:auto">2. Load fundamental data</h3><span class="pill">CSV/JSON-ready</span></div><p class="hint">Import only data you are authorized to use. CSV headers: symbol,company_name,sector,period_end,market_cap_cr,pe,pb,roe,roce,debt_equity,sales_growth_3y,profit_growth_3y,opm,dividend_yield,promoter_holding,pledged_percent,current_ratio,interest_coverage,free_cash_flow_cr. Percentage fields should be numeric percentages (e.g. 18.5), not fractions.</p><textarea id="importJson" rows="4" style="width:100%" placeholder='[{"symbol":"RACLGEAR","company_name":"RACL Geartech","pe":35.2,"roce":16.6,"roe":16.1}]'></textarea><div class="row"><button class="secondary" onclick="importData()">Import JSON data</button><span id="importStatus" class="muted"></span></div></section>
<section class="card"><div class="row"><h3 style="margin-right:auto">3. Matching companies</h3><span id="resultMeta" class="muted">Run a screen to see matching companies.</span></div><div class="tablewrap"><table id="results"><thead><tr><th>Symbol</th><th>Company</th><th>Market cap ₹Cr</th><th>CMP ₹</th><th>P/E</th><th>ROE %</th><th>ROCE %</th><th>Sales growth 3Y %</th><th>Debt/Equity</th><th>RSI 14</th><th>20-bar return %</th></tr></thead><tbody></tbody></table></div><p id="screenNote" class="hint"></p></section>
</main><script>
let filters=[],rows=[];
const $=id=>document.getElementById(id);
async function api(url,opts={}){let r=await fetch(url,{headers:{'Content-Type':'application/json'},...opts});let d=await r.json();if(!r.ok)throw Error(d.detail||'Request failed');return d}
function addCondition(field='roce',op='>',value='20'){let category=$('filterCategory').value;let available=filters.filter(f=>category==='all'||f.category===category);let box=document.createElement('div');box.className='condition';box.innerHTML='<select class="field"></select><select class="op"><option>></option><option><</option><option>>=</option><option><=</option><option>==</option><option>!=</option></select><input class="value" type="number" step="any"><button class="secondary" title="Remove">×</button>';let sel=box.querySelector('.field');available.forEach(f=>{let o=document.createElement('option');o.value=f.field;o.textContent=f.label+' · '+f.category;sel.append(o)});if(available.some(f=>f.field===field))sel.value=field;box.querySelector('.op').value=op;box.querySelector('.value').value=value;box.querySelector('button').onclick=()=>box.remove();$('conditions').append(box)}
function getConditions(){return [...document.querySelectorAll('.condition')].map(x=>({field:x.querySelector('.field').value,op:x.querySelector('.op').value,value:x.querySelector('.value').value}))}
async function runScreen(){try{let d=await api('/api/screener/run',{method:'POST',body:JSON.stringify({conditions:getConditions(),logic:$('logic').value,exchange:$('exchange').value})});$('resultMeta').textContent=d.count+' matches · '+d.fundamental_universe_count+' companies in fundamental database';$('screenNote').textContent=d.note;let tb=$('results').querySelector('tbody');tb.innerHTML='';d.results.forEach(r=>{let tr=document.createElement('tr');let vals=[r.symbol,r.company_name||'—',r.market_cap_cr,r.last_price,r.pe,r.roe,r.roce,r.sales_growth_3y,r.debt_equity,r.rsi_14,r.return_20bar];vals.forEach(v=>{let td=document.createElement('td');td.textContent=v==null?'—':typeof v==='number'?v.toFixed(2):v;tr.append(td)});tb.append(tr)})$('screenStatus').textContent='';}catch(e){$('screenStatus').textContent='Screen failed: '+e.message;}}
async function importData(){try{let data=JSON.parse($('importJson').value);let d=await api('/api/screener/import',{method:'POST',body:JSON.stringify({rows:data,source:'user_import'})});$('importStatus').textContent='Imported '+d.imported+' companies'}catch(e){$('importStatus').textContent=e.message}}
async function saveScreen(){try{let name=$('screenName').value.trim();let d=await api('/api/screener/screens',{method:'POST',body:JSON.stringify({name,conditions:getConditions(),logic:$('logic').value,exchange:$('exchange').value})});await loadScreens();$('screenStatus').textContent='Saved screen: '+d.saved}catch(e){$('screenStatus').textContent=e.message}}
async function loadScreens(){let d=await api('/api/screener/screens');$('savedScreens').innerHTML='<option value="">Load saved screen…</option>';d.screens.forEach(s=>{let o=document.createElement('option');o.value=s.name;o.textContent=s.name;o.dataset.definition=JSON.stringify(s.definition);$('savedScreens').append(o)})}
function loadScreen(){let o=$('savedScreens').selectedOptions[0];if(!o||!o.dataset.definition)return;let d=JSON.parse(o.dataset.definition);$('conditions').innerHTML='';$('logic').value=d.logic;$('exchange').value=d.exchange;(d.conditions||[]).forEach(c=>addCondition(c.field,c.op,c.value))}
$('filterCategory').addEventListener('change',()=>{let boxes=[...document.querySelectorAll('.condition')];boxes.forEach(b=>b.remove());addCondition()});
(async()=>{filters=(await api('/api/screener/filters')).filters;addCondition('roce','>','20');addCondition('sales_growth_3y','>','15');addCondition('debt_equity','<','0.5');await loadScreens()})().catch(e=>alert(e.message));
</script></body></html>"""


MARKET_DATA_HTML = r"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Groww Market Data · StockAlgo</title>
<style>*{box-sizing:border-box}body{margin:0;padding:16px;background:#0b1220;color:#e5edf7;font:14px/1.5 system-ui}.wrap{max-width:1100px;margin:auto}.card{background:#152238;border:1px solid #2b3d57;border-radius:14px;padding:15px;margin:12px 0}.muted{color:#9cafc8}.row{display:flex;gap:9px;align-items:center;flex-wrap:wrap}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px}button,a,select,input{padding:10px;border-radius:9px;border:1px solid #354862}button,a{background:#2563eb;color:white;text-decoration:none;cursor:pointer}input,select{background:#0b1320;color:#e7eef9}.pill{display:inline-block;border-radius:20px;background:#123b32;color:#81e2bb;padding:5px 9px}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;min-width:500px}td,th{text-align:left;padding:9px;border-bottom:1px solid #2b3d57}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#0b1320;padding:10px;border-radius:9px}.steps{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:8px}.step{background:#101c30;padding:11px;border-radius:10px}.step b{display:block;margin-bottom:4px}@media(max-width:600px){body{padding:10px}}</style></head><body><main class="wrap">
<header class="row"><div style="flex:1"><h1>Groww Market Data</h1><div class="muted">Read-only integration · StockAlgo</div></div><a href="/">Dashboard</a><a href="/screener">Stock Screener</a><a href="/builder">Strategy Builder</a></header>
<section class="card"><h2>1. Connection status</h2><div class="row"><span id="config" class="pill">Checking environment…</span><button onclick="status()">Refresh status</button><button onclick="profile()">Test Groww account</button></div><p class="muted">Configured means the API key and secret are present and the SDK is installed. Test Groww account verifies actual authentication and any daily approval.</p><pre id="connection">No connection test run yet.</pre></section>
<section class="card"><h2>2. Fetch market data</h2><div class="grid"><label>Symbol<br><input id="symbol" value="RELIANCE" maxlength="40" style="width:100%;margin-top:5px"></label><label>Exchange<br><select id="exchange" style="width:100%;margin-top:5px"><option>NSE</option><option>BSE</option></select></label><label>Auto quote polling<br><input value="Every 5 seconds" disabled style="width:100%;margin-top:5px"></label><label>Historical candle refresh<br><input value="Every 60 seconds · 5-minute candles" disabled style="width:100%;margin-top:5px"></label></div><p class="row"><button onclick="quote()">Fetch quote now</button><button onclick="manual()">Refresh quote + candles</button><button onclick="holdings()">View holdings</button><button onclick="orders()">View order history</button></p><div class="row"><span id="market" class="pill">Market status loading…</span><span id="source" class="muted">No data fetched</span></div><div class="scroll"><table id="quotes"><thead><tr><th>Symbol</th><th>Exchange</th><th>Last price / quote payload</th><th>Fetched at</th><th>Source</th></tr></thead><tbody></tbody></table></div><h3>Latest stored 5-minute candles</h3><div class="scroll"><table id="candles"><thead><tr><th>Time</th><th>Open</th><th>High</th><th>Low</th><th>Close</th><th>Volume</th></tr></thead><tbody></tbody></table></div><pre id="output">Market data responses will appear here.</pre></section>
<section class="card"><h2>3. How the collector works</h2><div class="steps"><div class="step"><b>Quote polling</b>Every 5 seconds while this page is open during market hours.</div><div class="step"><b>Historical candles</b>5-minute OHLCV candles; refresh no more than once per minute per symbol.</div><div class="step"><b>Persistent storage</b>Latest quotes and candles are saved to PostgreSQL.</div><div class="step"><b>Outside market hours</b>Automatic polling pauses. Manual refresh is available, subject to Groww API availability.</div></div><p class="muted">NSE/BSE cash session is treated as weekdays 09:15–15:30 IST. Prices outside the live session may be stale; the source and fetch time are shown.</p></section>
<section class="card"><h2>4. Safety</h2><span class="pill">Paper only · Live orders disabled</span><p class="muted">This workspace only reads profile, quotes, holdings, positions and order history. It does not place, modify or cancel broker orders.</p></section>
</main><script>
const $=id=>document.getElementById(id);async function req(url,opts={}){let r=await fetch(url,{headers:{'Content-Type':'application/json'},...opts});let d=await r.json();if(!r.ok)throw Error(d.detail||'HTTP '+r.status);return d}
function show(id,d){$(id).textContent=JSON.stringify(d,null,2)}
async function status(){try{let d=await req('/api/groww/status');$('config').textContent=d.configured&&d.sdk_installed?'Credentials present · SDK installed':(!d.configured?'Credentials missing':'Groww SDK missing');$('connection').textContent='Authentication not yet verified. Tap Test Groww account.';let m=await req('/api/groww/market/config');$('market').textContent=m.market.is_open?'Market open · IST':'Market closed · IST';}catch(e){$('config').textContent=e.message}}
async function profile(){try{show('connection',await req('/api/groww/profile'))}catch(e){$('connection').textContent=e.message}}
async function quote(){try{let d=await req('/api/groww/market/quotes?symbols='+encodeURIComponent($('symbol').value)+'&exchange='+$('exchange').value);renderQuote(d)}catch(e){$('output').textContent=e.message}}
function renderQuote(d){$('source').textContent='Source: '+d.source;let tb=$('quotes').querySelector('tbody');tb.innerHTML='';(d.quotes||[]).forEach(q=>{let tr=document.createElement('tr');[q.symbol,q.exchange,typeof q.ltp==='object'?JSON.stringify(q.ltp):q.ltp,q.fetched_at,d.source].forEach(v=>{let td=document.createElement('td');td.textContent=v??'—';tr.append(td)});tb.append(tr)});$('market').textContent=d.market.is_open?'Market open · IST':'Market closed · IST'}
async function manual(){try{$('output').textContent='Fetching quote and historical candles…';let d=await req('/api/groww/market/refresh',{method:'POST',body:JSON.stringify({symbol:$('symbol').value,exchange:$('exchange').value})});renderQuote(d.quotes);let rows=d.historical.candles||[],tb=$('candles').querySelector('tbody');tb.innerHTML='';rows.slice(-30).reverse().forEach(c=>{let tr=document.createElement('tr');[c.timestamp,c.open,c.high,c.low,c.close,c.volume].forEach(v=>{let td=document.createElement('td');td.textContent=v??'—';tr.append(td)});tb.append(tr)});show('output',{historical_refresh:d.historical.refreshed,rows_saved:d.historical.rows_saved,interval_minutes:5,live_orders_enabled:false})}catch(e){$('output').textContent=e.message}}
async function holdings(){try{show('output',await req('/api/groww/holdings'))}catch(e){$('output').textContent=e.message}}
async function orders(){try{show('output',await req('/api/groww/orders'))}catch(e){$('output').textContent=e.message}}
let timer;async function poll(){if(document.hidden)return;try{let d=await req('/api/groww/market/quotes?symbols='+encodeURIComponent($('symbol').value)+'&exchange='+$('exchange').value);renderQuote(d)}catch(e){$('source').textContent=e.message}}
$('symbol').addEventListener('change',poll);$('exchange').addEventListener('change',poll);document.addEventListener('visibilitychange',()=>{if(!document.hidden)poll()});status();poll();timer=setInterval(poll,5000);
</script></body></html>"""

app=FastAPI(title="StockAlgo Paper Trading + Groww Read-only Integration",version="1.1.0")
security=HTTPBasic(auto_error=False)
HERE=Path(__file__).resolve().parent

@app.on_event("startup")
def startup(): DB.init_db()

def require_auth(credentials: HTTPBasicCredentials=Depends(security)):
    username=os.getenv("DASHBOARD_USERNAME","admin"); password=os.getenv("DASHBOARD_PASSWORD","")
    if not password: raise HTTPException(503,"Set DASHBOARD_PASSWORD in Render environment variables.")
    if credentials is None or not (secrets.compare_digest(credentials.username,username) and secrets.compare_digest(credentials.password,password)):
        raise HTTPException(401,"Authentication required",headers={"WWW-Authenticate":"Basic"})
    return credentials.username

@app.get("/health")
def health():
    DB.init_db(); return {"status":"ok","mode":"paper_only","live_trading_enabled":False}

@app.get("/",response_class=HTMLResponse)
def dashboard(_=Depends(require_auth)):
    page='''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>StockAlgo Cloud Paper</title><style>
*{box-sizing:border-box}body{font:14px/1.5 system-ui;background:#0b1220;color:#e5edf7;margin:0;padding:16px;max-width:1500px;margin:auto}header,.card,.module{background:#152238;border:1px solid #2a3d59;border-radius:14px;padding:16px;margin-bottom:14px}h1{font-size:24px;margin:0 0 5px}.muted{color:#9aacc4}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(155px,1fr));gap:12px}.metric{font-size:24px;font-weight:750;margin-top:6px}table{border-collapse:collapse;width:100%;min-width:480px}td,th{text-align:left;padding:10px;border-bottom:1px solid #2a3a52}button,a{background:#2868d8;color:white;border:0;padding:10px 13px;border-radius:9px;text-decoration:none;cursor:pointer;margin:3px;font-weight:650}.danger{background:#b91c1c}.status{padding:6px 9px;border-radius:7px;background:#14532d;display:inline-block}.scroll{overflow:auto}.nav{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:10px;margin:14px 0}.nav a{display:block;background:#1b2d48;border:1px solid #355173;padding:14px;min-height:82px}.nav strong{display:block;font-size:15px}.nav small{display:block;color:#c0cee0;font-weight:400;margin-top:4px}.eyebrow{font-size:11px;text-transform:uppercase;letter-spacing:.09em;color:#91a4bd}.card h3{margin-top:0}@media(max-width:600px){body{padding:10px}.card,header{padding:13px}.metric{font-size:21px}}</style></head><body>
<header><h1>StockAlgo</h1><div class="muted">NIFTY 50 · Daily swing · ₹50,000 virtual capital · PAPER ONLY</div><p><span class="status">LIVE BROKER ORDERS DISABLED</span></p><nav class="nav">
<a href="/screener"><strong>📊 Market Intelligence &amp; Screener</strong><small>Find stocks using fundamental and technical filters</small></a>
<a href="/builder"><strong>⚙️ Strategy Builder</strong><small>Create indicators, entry/exit rules and backtests</small></a>
<a href="/market-data"><strong>📡 Groww Market Data</strong><small>Check connection, quotes and 5-minute candles</small></a>
</nav><button onclick="refresh()">Refresh dashboard</button><button id="kill" class="danger" onclick="toggleKill()">Enable paper kill switch</button><span id="updated" class="muted"></span></header>
<div class="grid"><div class="card">Portfolio equity<div id="equity" class="metric">—</div></div><div class="card">Cash<div id="cash" class="metric">—</div></div><div class="card">Open positions<div id="positions" class="metric">—</div></div><div class="card">Orders today<div id="orders" class="metric">—</div></div></div>
<div class="card"><h3>Open positions</h3><div class="scroll"><table id="pos"></table></div></div><div class="card"><h3>Latest signals</h3><div class="scroll"><table id="signals"></table></div></div><div class="card"><h3>Recent trades</h3><div class="scroll"><table id="trades"></table></div></div><div class="card"><h3>Equity history</h3><div class="scroll"><table id="history"></table></div></div><div class="card"><h3>Groww integration</h3><p class="muted">Read-only broker connection. Check API credentials, test account access, fetch live quotes and inspect stored historical candles from the dedicated market-data workspace.</p><p><span id="growwStatus" class="status">Checking configuration…</span> <a href="/market-data">Open Groww Market Data →</a></p></div><div class="card"><h3>Scheduled jobs</h3><div class="scroll"><table id="jobs"></table></div></div>
<script>const money=x=>'₹'+Number(x||0).toLocaleString('en-IN',{maximumFractionDigits:2});function esc(x){return String(x??'—').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]))}function table(id,h,rows){document.getElementById(id).innerHTML='<tr>'+h.map(x=>'<th>'+esc(x)+'</th>').join('')+'</tr>'+rows.map(r=>'<tr>'+r.map(x=>'<td>'+esc(x)+'</td>').join('')+'</tr>').join('')}let killState=false;async function refresh(){let r=await fetch('/api/dashboard');if(!r.ok){alert('Dashboard request failed: '+r.status);return}let d=await r.json(),s=d.state||{},p=s.positions||{};killState=!!d.kill_switch;document.getElementById('equity').textContent=money(s.last_equity??s.cash);document.getElementById('cash').textContent=money(s.cash);document.getElementById('positions').textContent=Object.keys(p).length;document.getElementById('orders').textContent=s.orders_today??0;table('pos',['Symbol','Qty','Entry','Stop','Target','Bars'],Object.entries(p).map(([k,v])=>[k,v.qty,money(v.entry),money(v.stop),money(v.target),v.bars]));table('signals',['Date','Symbol','P(up)','Close','ATR','Entry'],(d.signals||[]).slice(0,30).map(x=>[x.date,x.symbol,x.p_up==null?'—':Number(x.p_up).toFixed(3),money(x.close),money(x.atr),x.entry?'YES':'NO']));table('trades',['Date','Symbol','Side','Qty','Price','Reason','P&L'],(d.trades||[]).slice(0,30).map(x=>[x.date,x.symbol,x.side,x.qty,money(x.price),x.reason,x.pnl==null?'—':money(x.pnl)]));table('history',['Date','Equity','Cash'],(d.equity||[]).slice(-30).reverse().map(x=>[x.date,money(x.equity),money(x.cash)]));table('jobs',['Started','Task','Status','Message'],(d.jobs||[]).map(x=>[x.started_at,x.task,x.status,x.message]));let b=document.getElementById('kill');b.textContent=killState?'Disable paper kill switch':'Enable paper kill switch';b.className=killState?'':'danger';document.getElementById('updated').textContent='Updated '+new Date().toLocaleTimeString()}async function toggleKill(){await fetch('/api/kill-switch',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled:!killState})});refresh()}async function growwCall(path){let o=document.getElementById('growwOutput');o.textContent='Connecting to Groww…';try{let r=await fetch(path);let d=await r.json();o.textContent=JSON.stringify(d,null,2);if(!r.ok)o.textContent='HTTP '+r.status+'
'+o.textContent}catch(e){o.textContent=String(e)}}async function refreshGrowwStatus(){let b=document.getElementById('growwStatus');if(!b)return;b.textContent='Checking configuration…';try{let r=await fetch('/api/groww/status');let d=await r.json();if(!r.ok)throw new Error(d.detail||('HTTP '+r.status));b.textContent=d.configured&&d.sdk_installed?'Credentials configured · SDK installed':(!d.configured?'Credentials missing':'SDK missing');b.style.background=d.configured&&d.sdk_installed?'#14532d':'#713f12';}catch(e){b.textContent='Status check failed: '+e.message;b.style.background='#7f1d1d'}}async function testGroww(){await growwCall('/api/groww/profile')}async function quoteGroww(){let s=document.getElementById('growwSymbol').value.trim().toUpperCase(),x=document.getElementById('growwExchange').value;await growwCall('/api/groww/quote/'+encodeURIComponent(s)+'?exchange='+x+'&segment=CASH')}async function holdingsGroww(){await growwCall('/api/groww/holdings')}async function ordersGroww(){await growwCall('/api/groww/orders')}let marketTimer=null;async function pollMarket(){let status=document.getElementById('marketStatus'),raw=document.getElementById('marketSymbols').value.trim(),ex=document.getElementById('growwExchange').value;if(!raw)return;try{let r=await fetch('/api/groww/market/quotes?symbols='+encodeURIComponent(raw)+'&exchange='+ex);let d=await r.json();if(!r.ok)throw new Error(d.detail||('HTTP '+r.status));table('marketQuotes',['Symbol','LTP','Fetched','Source'],(d.quotes||[]).map(q=>[q.symbol,typeof q.ltp==='object'?JSON.stringify(q.ltp):q.ltp,q.fetched_at,d.source]));status.textContent=' · '+d.source;document.getElementById('marketMeta').textContent=d.market.is_open?'Market open · IST':'Market closed · showing last available quote when cached';}catch(e){status.textContent=' · '+e.message}}async function manualMarketRefresh(){let status=document.getElementById('marketStatus'),symbol=document.getElementById('marketSymbols').value.split(',')[0].trim(),exchange=document.getElementById('growwExchange').value;status.textContent=' · Refreshing…';try{let r=await fetch('/api/groww/market/refresh',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({symbol,exchange})});let d=await r.json();if(!r.ok)throw new Error(d.detail||('HTTP '+r.status));status.textContent=' · Manual refresh complete';await pollMarket();document.getElementById('marketCandles').textContent='Saved '+d.historical.rows_saved+' candles · 5-minute interval\
'+JSON.stringify(d.historical.candles.slice(-5),null,2);}catch(e){status.textContent=' · '+e.message}}async function startMarketPolling(){let r=await fetch('/api/groww/market/config'),d=await r.json();if(marketTimer)clearInterval(marketTimer);await pollMarket();marketTimer=setInterval(pollMarket,5000)}startMarketPolling();manualMarketRefresh();setInterval(manualMarketRefresh,60000);refresh();refreshGrowwStatus();setInterval(refresh,60000);setInterval(refreshGrowwStatus,120000);</script></body></html>'''
    return HTMLResponse(page)

@app.get("/api/dashboard")
def api_dashboard(_=Depends(require_auth)): return DB.dashboard_snapshot()

@app.post("/api/kill-switch")
def api_kill_switch(body:dict,_=Depends(require_auth)):
    enabled=bool(body.get("enabled")); DB.set_kill_switch(enabled)
    return {"enabled":enabled,"note":"Paper-mode control only; it cannot submit broker orders."}

def _groww_error(exc: Exception):
    from groww_adapter import GrowwNotConfigured
    if isinstance(exc, GrowwNotConfigured):
        raise HTTPException(503, str(exc))
    if isinstance(exc, ValueError):
        raise HTTPException(400, str(exc))
    import logging
    logging.getLogger("stockalgo.groww").exception("Groww API request failed")
    raise HTTPException(502, "Groww API request failed. Check Groww approval, API credentials and service logs.")


# Groww market-data polling defaults. Browser polling drives refresh on Render Free;
# no always-on background worker or paid Cron is required.
MARKET_TZ = ZoneInfo("Asia/Kolkata")
MARKET_LOCK = threading.Lock()
MARKET_CACHE = {"quotes": {}, "quote_last_call": 0.0, "history_last_call": {}, "last_error": None}

def _market_session_now():
    now = datetime.now(MARKET_TZ)
    return now.weekday() < 5 and clock_time(9, 15) <= now.time() <= clock_time(15, 30)

def _market_window():
    now = datetime.now(MARKET_TZ)
    return {"is_open": _market_session_now(), "timezone": "Asia/Kolkata",
            "opens": "09:15", "closes": "15:30", "checked_at": now.isoformat()}

@app.get("/api/groww/market/config")
def groww_market_config(_=Depends(require_auth)):
    return {"candle_interval_minutes": 5, "quote_poll_seconds": 5,
            "historical_refresh_seconds": 60, "market_hours_only": True,
            "auto_polling_requires_open_dashboard": True, "persistent_store": "PostgreSQL",
            "market": _market_window(), "live_orders_enabled": False}

@app.get("/api/groww/market/quotes")
def groww_market_quotes(symbols: str = "RELIANCE", exchange: str = "NSE",
                        force: bool = False, _=Depends(require_auth)):
    names = [x.strip().upper() for x in symbols.split(",") if x.strip()]
    if not names or len(names) > 50:
        raise HTTPException(400, "Provide 1 to 50 comma-separated symbols.")
    if any(not re.fullmatch(r"[A-Z0-9&._-]{1,40}", x) for x in names):
        raise HTTPException(400, "One or more symbols are invalid.")
    ex = exchange.upper()
    if ex not in {"NSE", "BSE"}: raise HTTPException(400, "Exchange must be NSE or BSE.")
    now = time.monotonic()
    with MARKET_LOCK:
        age = now - MARKET_CACHE["quote_last_call"]
        cached = [MARKET_CACHE["quotes"].get((ex, name)) for name in names]
        if not force and age < 5 and all(cached):
            return {"source":"cache","quotes":cached,"market":_market_window(),"poll_seconds":5}
        if not force and not _market_session_now():
            saved = DB.latest_market_quotes(names)
            if saved:
                return {"source":"last_cached_outside_market_hours","quotes":saved,"market":_market_window(),"poll_seconds":5}
            raise HTTPException(409, "Automatic quote polling is paused outside NSE/BSE cash-market hours (09:15–15:30 IST, weekdays). Use Manual refresh for an explicit request.")

        if age < 1.0:
            raise HTTPException(429, "Groww market-data request throttled. Retry shortly.")
        try:
            from groww_market_data import get_ltp
            values = get_ltp(names, ex, "CASH")
            fetched = datetime.now(timezone.utc)
            payload = values if isinstance(values, dict) else {"data": values}
            if isinstance(payload.get("payload"), dict):
                payload = payload["payload"]
            normalized=[]
            for name in names:
                item = payload.get(f"{ex}_{name}", payload.get(name, payload))
                quote={"symbol":name,"exchange":ex,"ltp":item,"fetched_at":fetched.isoformat()}
                MARKET_CACHE["quotes"][(ex,name)] = quote
                DB.save_market_quote(name, ex, {"ltp":item}, fetched)
                normalized.append(quote)
            MARKET_CACHE["quote_last_call"] = now
            MARKET_CACHE["last_error"] = None
            return {"source":"groww","quotes":normalized,"market":_market_window(),"poll_seconds":5}
        except Exception as exc:
            MARKET_CACHE["last_error"] = str(exc)[:300]
            # Serve persisted quote as stale fallback, never represent it as live.
            saved = DB.latest_market_quotes(names)
            if saved:
                stale = [{"symbol":r["symbol"],"exchange":r["exchange"],
                          "ltp":(r.get("quote") or {}).get("ltp"),
                          "fetched_at":r["fetched_at"]} for r in saved]
                return {"source":"postgres_stale_fallback","quotes":stale,
                        "warning":"Groww request failed; values may be stale.","market":_market_window()}
            _groww_error(exc)

@app.post("/api/groww/market/refresh")
def groww_market_refresh(body: dict, _=Depends(require_auth)):
    symbol = str(body.get("symbol","RELIANCE")).strip().upper()
    exchange = str(body.get("exchange","NSE")).strip().upper()
    if not re.fullmatch(r"[A-Z0-9&._-]{1,40}", symbol) or exchange not in {"NSE","BSE"}:
        raise HTTPException(400,"Invalid symbol or exchange.")
    # Manual refresh fetches a quote now and refreshes 5-minute candles at most once/minute.
    quotes = groww_market_quotes(symbols=symbol, exchange=exchange, force=True, _=None)
    now = datetime.now(MARKET_TZ)
    key=(exchange,symbol,5)
    mono=time.monotonic()
    history_due = mono - MARKET_CACHE["history_last_call"].get(key,0) >= 60
    candles_saved=0
    if history_due:
        start=(now-timedelta(days=15)).replace(hour=9,minute=15,second=0,microsecond=0)
        end=now
        try:
            from groww_market_data import get_historical_candles
            candles=get_historical_candles(symbol,exchange,start.strftime("%Y-%m-%d %H:%M:%S"),
                end.strftime("%Y-%m-%d %H:%M:%S"),5,"CASH")
            if isinstance(candles,dict): candles=candles.get("candles",[])
            candles_saved=DB.save_market_candles(symbol,exchange,5,candles)
            MARKET_CACHE["history_last_call"][key]=mono
        except Exception as exc:
            MARKET_CACHE["last_error"]=str(exc)[:300]
    return {"quotes":quotes,"historical":{"interval_minutes":5,"refreshed":history_due,
        "rows_saved":candles_saved,"refresh_seconds":60,
        "candles":DB.latest_market_candles(symbol,exchange,5,300)},
        "market":_market_window(),"live_orders_enabled":False}

@app.get("/api/groww/market/candles/{symbol}")
def groww_market_candles(symbol: str, exchange: str="NSE", interval_minutes: int=5,
                         limit: int=500, _=Depends(require_auth)):
    if interval_minutes != 5: raise HTTPException(400,"Configured candle interval is 5 minutes.")
    return {"candles":DB.latest_market_candles(symbol.upper(),exchange.upper(),5,limit)}

@app.get("/screener", response_class=HTMLResponse)
def screener_page(_=Depends(require_auth)):
    return SCREENER_HTML

@app.get("/market-data", response_class=HTMLResponse)
def market_data_page(_=Depends(require_auth)):
    return MARKET_DATA_HTML

@app.get("/api/screener/filters")
def screener_filters(_=Depends(require_auth)):
    return {"filters":[{"field":k,"label":v[0],"category":v[1],"unit":v[2]} for k,v in Screener.FILTERS.items()],
            "operators":[">","<",">=","<=","==","!="]}

@app.post("/api/screener/run")
def screener_run(body: dict, _=Depends(require_auth)):
    try:
        return Screener.run_screen(body.get("conditions",[]),body.get("logic","AND"),
                                   body.get("exchange","NSE"),body.get("limit",250))
    except ValueError as exc: raise HTTPException(400,str(exc))

@app.post("/api/screener/import")
def screener_import(body: dict, _=Depends(require_auth)):
    rows=body.get("rows")
    if not isinstance(rows,list) or len(rows)>10000:
        raise HTTPException(400,"Provide a JSON rows array containing at most 10,000 companies.")
    allowed={"symbol","company_name","sector","period_end"}|DB.FUNDAMENTAL_FIELDS
    clean=[]
    for row in rows:
        if not isinstance(row,dict): continue
        clean.append({k:v for k,v in row.items() if k in allowed})
    count=DB.upsert_fundamentals(clean,source=str(body.get("source","user_import"))[:100])
    return {"imported":count,"total_companies":len(DB.list_fundamentals())}

@app.get("/api/screener/screens")
def screener_screens(_=Depends(require_auth)):
    return {"screens":DB.list_screens()}

@app.post("/api/screener/screens")
def screener_save(body: dict, _=Depends(require_auth)):
    name=str(body.get("name","")).strip()[:100]
    if not name: raise HTTPException(400,"Screen name is required.")
    definition={"conditions":body.get("conditions",[]),"logic":body.get("logic","AND"),"exchange":body.get("exchange","NSE")}
    DB.save_screen(name,definition)
    return {"saved":name}

@app.get("/api/groww/status")
def groww_status(_=Depends(require_auth)):
    import importlib.util
    configured = bool(os.getenv("GROWW_API_KEY", "").strip() and os.getenv("GROWW_API_SECRET", "").strip())
    return {
        "configured": configured,
        "sdk_installed": importlib.util.find_spec("growwapi") is not None,
        "authentication": "api_key_secret",
        "access_mode": "read_only",
        "paper_only": True,
        "live_orders_enabled": False,
        "note": "Use /api/groww/profile to validate the Groww connection. No order-write endpoints are exposed.",
    }


@app.get("/api/groww/profile")
def groww_profile(_=Depends(require_auth)):
    try:
        from groww_portfolio import get_profile
        return {"connected": True, "profile": get_profile(), "live_orders_enabled": False}
    except Exception as exc:
        _groww_error(exc)


@app.get("/api/groww/quote/{symbol}")
def groww_quote(symbol: str, exchange: str = "NSE", segment: str = "CASH", _=Depends(require_auth)):
    try:
        from groww_market_data import get_quote
        return {"symbol": symbol.upper(), "exchange": exchange.upper(), "quote": get_quote(symbol, exchange, segment)}
    except Exception as exc:
        _groww_error(exc)


@app.get("/api/groww/ltp")
def groww_ltp(symbols: str = Query(..., description="Comma-separated symbols; maximum 50"), exchange: str = "NSE", segment: str = "CASH", _=Depends(require_auth)):
    try:
        values = [item.strip().upper() for item in symbols.split(",") if item.strip()]
        from groww_market_data import get_ltp
        return {"ltp": get_ltp(values, exchange, segment)}
    except Exception as exc:
        _groww_error(exc)


@app.get("/api/groww/ohlc")
def groww_ohlc(symbols: str = Query(..., description="Comma-separated symbols; maximum 50"), exchange: str = "NSE", segment: str = "CASH", _=Depends(require_auth)):
    try:
        values = [item.strip().upper() for item in symbols.split(",") if item.strip()]
        from groww_market_data import get_ohlc
        return {"ohlc": get_ohlc(values, exchange, segment)}
    except Exception as exc:
        _groww_error(exc)


@app.get("/api/groww/candles/{symbol}")
def groww_candles(
    symbol: str, start_time: str, end_time: str, exchange: str = "NSE",
    segment: str = "CASH", interval_minutes: int = 5, _=Depends(require_auth),
):
    try:
        from groww_market_data import get_historical_candles
        return {"symbol": symbol.upper(), "candles": get_historical_candles(
            symbol, exchange, start_time, end_time, interval_minutes, segment
        )}
    except Exception as exc:
        _groww_error(exc)


@app.get("/api/groww/holdings")
def groww_holdings(_=Depends(require_auth)):
    try:
        from groww_portfolio import get_holdings
        return {"holdings": get_holdings()}
    except Exception as exc:
        _groww_error(exc)


@app.get("/api/groww/positions")
def groww_positions(segment: str | None = None, _=Depends(require_auth)):
    try:
        from groww_portfolio import get_positions
        return {"positions": get_positions(segment)}
    except Exception as exc:
        _groww_error(exc)


@app.get("/api/groww/orders")
def groww_orders(segment: str | None = None, page: int = 0, page_size: int = 100, _=Depends(require_auth)):
    try:
        from groww_orders import get_order_history
        return {"orders": get_order_history(segment, page, page_size)}
    except Exception as exc:
        _groww_error(exc)


@app.get("/builder")
@app.get("/builder/")
def builder_page(_=Depends(require_auth)): return FileResponse(HERE/"builder.html")

@app.get("/api/indicators")
def builder_indicators(_=Depends(require_auth)): return I.meta()

@app.post("/api/run")
def builder_run(req:Builder.RunReq,_=Depends(require_auth)): return Builder.run(req)

@app.get("/api/strategies")
def strategies(_=Depends(require_auth)): return DB.list_strategies()

@app.post("/api/strategies/{name}")
def save_strategy(name:str,req:Builder.RunReq,_=Depends(require_auth)):
    if not re.fullmatch(r"[\w\- ]{1,50}",name): raise HTTPException(400,"Invalid strategy name")
    DB.save_strategy(name,req.model_dump()); return {"saved":name,"storage":"postgres"}

@app.get("/api/strategies/{name}")
def load_strategy(name:str,_=Depends(require_auth)):
    payload=DB.get_strategy(name)
    if payload is None: raise HTTPException(404,"Strategy not found")
    return payload
