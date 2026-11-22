"""StockAlgo fundamental + technical screening engine.

Fundamentals are populated from an authorized provider or a user-supplied CSV/JSON import.
Market price/technical values are derived from persisted Groww quotes and candles.
"""
from __future__ import annotations
import math
import cloud_store as DB

FILTERS = {
 "market_cap_cr":("Market cap (₹ Cr)","fundamental","cr"),
 "pe":("P/E","fundamental","x"), "pb":("P/B","fundamental","x"),
 "roe":("ROE","fundamental","%"), "roce":("ROCE","fundamental","%"),
 "debt_equity":("Debt / Equity","fundamental","x"),
 "sales_growth_3y":("Sales growth 3Y","fundamental","%"),
 "profit_growth_3y":("Profit growth 3Y","fundamental","%"),
 "opm":("Operating margin","fundamental","%"),
 "dividend_yield":("Dividend yield","fundamental","%"),
 "promoter_holding":("Promoter holding","fundamental","%"),
 "pledged_percent":("Promoter pledged","fundamental","%"),
 "current_ratio":("Current ratio","fundamental","x"),
 "interest_coverage":("Interest coverage","fundamental","x"),
 "free_cash_flow_cr":("Free cash flow (₹ Cr)","fundamental","cr"),
 "last_price":("Last price (₹)","market","₹"),
 "return_5bar":("5-bar return","technical","%"),
 "return_20bar":("20-bar return","technical","%"),
 "rsi_14":("RSI (14)","technical",""),
 "sma20_distance":("Price vs SMA20","technical","%"),
 "sma50_distance":("Price vs SMA50","technical","%"),
 "volume_ratio":("Volume / 20-bar average","technical","x"),
}
OPS={">","<",">=","<=","==","!="}
def _num(v):
 try:
  x=float(v)
  return x if math.isfinite(x) else None
 except (TypeError,ValueError): return None

def _technical(symbol, exchange="NSE"):
 candles=DB.latest_market_candles(symbol,exchange,5,500)
 closes=[_num(c.get("close")) for c in candles]
 closes=[x for x in closes if x is not None and x>0]
 out={}
 if closes:
  out["last_price"]=closes[-1]
  if len(closes)>5: out["return_5bar"]=(closes[-1]/closes[-6]-1)*100
  if len(closes)>20: out["return_20bar"]=(closes[-1]/closes[-21]-1)*100
  if len(closes)>=20:
   sma=sum(closes[-20:])/20
   out["sma20_distance"]=(closes[-1]/sma-1)*100 if sma else None
  if len(closes)>=50:
   sma=sum(closes[-50:])/50
   out["sma50_distance"]=(closes[-1]/sma-1)*100 if sma else None
  if len(closes)>=15:
   diffs=[closes[i]-closes[i-1] for i in range(1,len(closes))]
   gains=sum(max(x,0) for x in diffs[-14:])/14
   losses=sum(max(-x,0) for x in diffs[-14:])/14
   out["rsi_14"]=100 if losses==0 else 100-(100/(1+gains/losses))
 vols=[_num(c.get("volume")) for c in candles if _num(c.get("volume")) is not None]
 if len(vols)>=21 and sum(vols[-21:-1])>0:
  out["volume_ratio"]=vols[-1]/(sum(vols[-21:-1])/20)
 return out

def run_screen(conditions=None, logic="AND", exchange="NSE", limit=250):
 if logic not in {"AND","OR"}: raise ValueError("logic must be AND or OR")
 fundamentals=DB.list_fundamentals()
 quotes=DB.latest_market_quotes()
 quote_map={(q["symbol"],q["exchange"]):q for q in quotes}
 evaluated=[]
 for f in fundamentals:
  symbol=f["symbol"]; values={k:f.get(k) for k in FILTERS}
  tech=_technical(symbol,exchange)
  values.update(tech)
  q=quote_map.get((symbol,exchange))
  if q:
   raw=(q.get("quote") or {}).get("ltp")
   if isinstance(raw,(int,float)): values["last_price"]=float(raw)
  matches=[]
  for c in conditions or []:
   field=c.get("field"); op=c.get("op"); target=_num(c.get("value"))
   actual=_num(values.get(field))
   if field not in FILTERS or op not in OPS or target is None or actual is None:
    matches.append(False); continue
   matches.append({">":actual>target,"<":actual<target,">=":actual>=target,
                   "<=":actual<=target,"==":actual==target,"!=":actual!=target}[op])
  passed=(all(matches) if logic=="AND" else any(matches)) if matches else True
  if passed:
   evaluated.append({"symbol":symbol,"company_name":f.get("company_name"),"sector":f.get("sector"),
     "market_cap_cr":values.get("market_cap_cr"),"last_price":values.get("last_price"),
     "pe":values.get("pe"),"roe":values.get("roe"),"roce":values.get("roce"),
     "sales_growth_3y":values.get("sales_growth_3y"),"debt_equity":values.get("debt_equity"),
     "rsi_14":values.get("rsi_14"),"return_20bar":values.get("return_20bar"),
     "source":f.get("source"),"period_end":f.get("period_end"),"values":values})
 return {"count":len(evaluated),"logic":logic,"exchange":exchange,"results":evaluated[:max(1,min(limit,1000))],
         "fundamental_universe_count":len(fundamentals),
         "note":"Fundamental metrics come from imported/provider snapshots; technical metrics require persisted 5-minute candles. Missing metrics do not pass a filter."}
