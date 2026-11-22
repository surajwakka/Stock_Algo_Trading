"""Read-only monitoring dashboard for the NIFTY 50 paper-trading ledger."""
import json
from io import StringIO

import pandas as pd
import streamlit as st

from runtime_state import read_text

st.set_page_config(page_title="StockAlgo | NIFTY 50 Paper", layout="wide")
st.title("StockAlgo — NIFTY 50 Swing Paper Trading")
st.caption("Paper trading only · Daily timeframe · No broker connectivity · Live orders disabled")

if st.sidebar.button("Refresh data"):
    st.cache_data.clear()
    st.rerun()

STATE_TAG = "paper_nifty50"
state_text = read_text(f"state_{STATE_TAG}.json")
if not state_text:
    st.info("No paper ledger has been published yet. Enable the scheduled GitHub Actions workflow and run it once manually.")
    st.stop()

state = json.loads(state_text)
sig_text = read_text(f"signals_{STATE_TAG}.csv")
eq_text = read_text(f"equity_{STATE_TAG}.csv")
trades_text = read_text("trades.csv")
status_text = read_text("cloud_run_status.json")
sig = pd.read_csv(StringIO(sig_text)) if sig_text else pd.DataFrame()
eq = pd.read_csv(StringIO(eq_text)) if eq_text else pd.DataFrame()
trades = pd.read_csv(StringIO(trades_text)) if trades_text else pd.DataFrame()
status = json.loads(status_text) if status_text else {}

st.sidebar.subheader("Automation status")
st.sidebar.write(f"Last run: {status.get('status', 'not available')}")
st.sidebar.write(f"Completed: {status.get('finished_at_utc', '—')}")
st.sidebar.success("Live broker orders: DISABLED")

last_px = dict(zip(sig["symbol"], sig["close"])) if not sig.empty else {}
pos = pd.DataFrame(state.get("positions", {})).T if state.get("positions") else pd.DataFrame()
if not pos.empty:
    pos["last"] = [last_px.get(s, e) for s, e in zip(pos.index, pos["entry"])]
    pos["pnl"] = (pos["last"] - pos["entry"]) * pos["qty"]
    pos["pnl_%"] = (pos["last"] / pos["entry"] - 1) * 100
    pos["to_stop_%"] = (pos["last"] / pos["stop"] - 1) * 100

equity = float(state.get("last_equity") or state.get("cash", 0))
start = float(eq["equity"].iloc[0]) if not eq.empty else equity
k = st.columns(4)
k[0].metric("Virtual equity", f"₹{equity:,.0f}", f"{(equity / start - 1) * 100:.2f}% since first record" if start else None)
k[1].metric("Virtual cash", f"₹{float(state.get('cash', 0)):,.0f}")
k[2].metric("Open positions", len(pos))
k[3].metric("Orders this cycle", int(state.get("orders_today", 0)))

if not eq.empty and len(eq) > 1:
    st.subheader("Equity curve")
    chart = eq.copy()
    chart["date"] = pd.to_datetime(chart["date"])
    st.line_chart(chart.set_index("date")["equity"])
    dd = (chart["equity"] / chart["equity"].cummax() - 1) * 100
    st.caption(f"Recorded maximum drawdown: {dd.min():.2f}%")

st.subheader("Open paper positions")
if pos.empty:
    st.info("No open positions.")
else:
    st.dataframe(pos[[c for c in ["qty", "entry", "last", "stop", "target", "bars", "pnl", "pnl_%", "to_stop_%", "p_up"] if c in pos.columns]].round(2), use_container_width=True)

st.subheader("Latest model signals")
if sig.empty:
    st.info("No signal snapshot available yet.")
else:
    sig = sig.copy()
    sig["signal"] = sig.get("entry", False).map(lambda x: "ENTRY" if bool(x) else "FLAT") if "entry" in sig else "FLAT"
    st.dataframe(sig.sort_values("p_up", ascending=False), use_container_width=True)

st.subheader("Paper trade history")
if trades.empty:
    st.info("No paper trades recorded yet.")
else:
    sells = trades[(trades["side"] == "SELL") & trades["pnl"].notna()] if {"side", "pnl"}.issubset(trades.columns) else pd.DataFrame()
    if not sells.empty:
        w = sells[sells["pnl"] > 0]
        m = st.columns(3)
        m[0].metric("Closed trades", len(sells))
        m[1].metric("Win rate", f"{len(w) / len(sells) * 100:.1f}%")
        m[2].metric("Realized P&L", f"₹{sells['pnl'].sum():,.0f}")
    st.dataframe(trades.iloc[::-1], use_container_width=True)

st.caption("Research prototype. Paper fills currently use an immediate limit-price assumption and do not model partial fills, queue priority, or realistic next-session execution.")
