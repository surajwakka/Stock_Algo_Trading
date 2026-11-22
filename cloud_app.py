"""Protected StockAlgo dashboard, JSON API, and database-backed strategy builder."""
import os, re, secrets
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import HTMLResponse, FileResponse
import indicators as I
import builder_api as Builder
import cloud_store as DB

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
body{font:14px system-ui;background:#0d1420;color:#e5edf7;margin:0;padding:22px}header,.card{background:#172234;border:1px solid #2a3a52;border-radius:12px;padding:16px;margin-bottom:14px}h1{font-size:23px;margin:0 0 5px}.muted{color:#91a4bd}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px}.metric{font-size:24px;font-weight:700;margin-top:6px}table{border-collapse:collapse;width:100%}td,th{text-align:left;padding:9px;border-bottom:1px solid #2a3a52}button,a{background:#2563eb;color:white;border:0;padding:9px 12px;border-radius:7px;text-decoration:none;cursor:pointer;margin-right:6px}.danger{background:#b91c1c}.status{padding:5px 8px;border-radius:6px;background:#14532d}.scroll{overflow:auto}</style></head><body>
<header><h1>StockAlgo</h1><div class="muted">NIFTY 50 · Daily swing · ₹50,000 virtual capital · PAPER ONLY</div><p><span class="status">LIVE BROKER ORDERS DISABLED</span></p><a href="/builder">Open Strategy Builder</a><button onclick="refresh()">Refresh</button><button id="kill" class="danger" onclick="toggleKill()">Enable paper kill switch</button><span id="updated" class="muted"></span></header>
<div class="grid"><div class="card">Portfolio equity<div id="equity" class="metric">—</div></div><div class="card">Cash<div id="cash" class="metric">—</div></div><div class="card">Open positions<div id="positions" class="metric">—</div></div><div class="card">Orders today<div id="orders" class="metric">—</div></div></div>
<div class="card"><h3>Open positions</h3><div class="scroll"><table id="pos"></table></div></div><div class="card"><h3>Latest signals</h3><div class="scroll"><table id="signals"></table></div></div><div class="card"><h3>Recent trades</h3><div class="scroll"><table id="trades"></table></div></div><div class="card"><h3>Equity history</h3><div class="scroll"><table id="history"></table></div></div><div class="card"><h3>Groww broker connection · Read-only</h3><p class="muted">Live order placement, modification and cancellation are disabled.</p><input id="growwSymbol" value="RELIANCE" maxlength="40" style="padding:9px;border-radius:6px;border:1px solid #40516b;background:#0d1420;color:#e5edf7;width:150px"/><button onclick="testGroww()">Test account connection</button><button onclick="quoteGroww()">Get NSE quote</button><pre id="growwOutput" class="scroll" style="white-space:pre-wrap;overflow-wrap:anywhere"></pre></div><div class="card"><h3>Scheduled jobs</h3><div class="scroll"><table id="jobs"></table></div></div>
<script>const money=x=>'₹'+Number(x||0).toLocaleString('en-IN',{maximumFractionDigits:2});function esc(x){return String(x??'—').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]))}function table(id,h,rows){document.getElementById(id).innerHTML='<tr>'+h.map(x=>'<th>'+esc(x)+'</th>').join('')+'</tr>'+rows.map(r=>'<tr>'+r.map(x=>'<td>'+esc(x)+'</td>').join('')+'</tr>').join('')}let killState=false;async function refresh(){let r=await fetch('/api/dashboard');if(!r.ok){alert('Dashboard request failed: '+r.status);return}let d=await r.json(),s=d.state||{},p=s.positions||{};killState=!!d.kill_switch;document.getElementById('equity').textContent=money(s.last_equity??s.cash);document.getElementById('cash').textContent=money(s.cash);document.getElementById('positions').textContent=Object.keys(p).length;document.getElementById('orders').textContent=s.orders_today??0;table('pos',['Symbol','Qty','Entry','Stop','Target','Bars'],Object.entries(p).map(([k,v])=>[k,v.qty,money(v.entry),money(v.stop),money(v.target),v.bars]));table('signals',['Date','Symbol','P(up)','Close','ATR','Entry'],(d.signals||[]).slice(0,30).map(x=>[x.date,x.symbol,x.p_up==null?'—':Number(x.p_up).toFixed(3),money(x.close),money(x.atr),x.entry?'YES':'NO']));table('trades',['Date','Symbol','Side','Qty','Price','Reason','P&L'],(d.trades||[]).slice(0,30).map(x=>[x.date,x.symbol,x.side,x.qty,money(x.price),x.reason,x.pnl==null?'—':money(x.pnl)]));table('history',['Date','Equity','Cash'],(d.equity||[]).slice(-30).reverse().map(x=>[x.date,money(x.equity),money(x.cash)]));table('jobs',['Started','Task','Status','Message'],(d.jobs||[]).map(x=>[x.started_at,x.task,x.status,x.message]));let b=document.getElementById('kill');b.textContent=killState?'Disable paper kill switch':'Enable paper kill switch';b.className=killState?'':'danger';document.getElementById('updated').textContent='Updated '+new Date().toLocaleTimeString()}async function toggleKill(){await fetch('/api/kill-switch',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled:!killState})});refresh()}async function growwCall(path){let o=document.getElementById('growwOutput');o.textContent='Connecting to Groww…';try{let r=await fetch(path);let d=await r.json();o.textContent=JSON.stringify(d,null,2);if(!r.ok)o.textContent='HTTP '+r.status+'\n'+o.textContent}catch(e){o.textContent=String(e)}}async function testGroww(){await growwCall('/api/groww/profile')}async function quoteGroww(){let s=document.getElementById('growwSymbol').value.trim().toUpperCase();await growwCall('/api/groww/quote/'+encodeURIComponent(s)+'?exchange=NSE&segment=CASH')}refresh();setInterval(refresh,60000);</script></body></html>'''
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
