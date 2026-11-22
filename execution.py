"""
Signals -> risk checks -> orders (paper by default, Groww live behind a hard gate).

Run once per day after market close (data is daily). Orders are DAY limit orders.

    python execution.py --mode paper                 # simulated, state in state_paper.json
    python execution.py --mode live                  # needs env: CONFIRM_LIVE=YES, GROWW_API_KEY, GROWW_TOTP_SECRET

Kill switch: create a file named KILL in the working folder -> no new entries, all positions exited.

Live prerequisites (verify in Groww's current docs): API key + TOTP secret, static IP registered
for order placement, `pip install growwapi pyotp`. Data/market-feed APIs may need a paid plan.
"""
import argparse
import csv
import datetime as dt
import json
import math
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

import indicators as I
import multi as M
import predictor as P


@dataclass
class Risk:
    capital: float = 100_000.0
    risk_per_trade_pct: float = 0.5     # max loss per trade if stop is hit, % of equity
    max_position_pct: float = 15.0      # max notional per stock, % of equity
    max_positions: int = 5
    stop_atr: float = 2.0
    target_atr: float = 3.0
    max_hold_bars: int = 5              # match model horizon
    exit_prob: float = 0.48             # exit if P(up) falls below this
    max_daily_loss_pct: float = 2.0     # halts new entries
    max_orders_per_day: int = 10
    limit_buffer_bps: float = 10.0      # how far through the last close the limit is placed
    min_price: float = 50.0
    max_order_value: float = 50_000.0   # hard cap per order (fat-finger guard)
    max_data_age_days: int = 4          # refuse stale data in live mode
    kill_file: str = "KILL"


def tick(x):  # NSE equity tick = 0.05
    return round(round(x * 20) / 20, 2)


# ---------------------------------------------------------------- brokers
class PaperBroker:
    """Fills every limit order at its limit price (conservative: you always pay the buffer)."""
    def place_limit(self, sym, side, qty, price):
        return {"id": f"paper-{uuid.uuid4().hex[:8]}", "status": "FILLED", "price": price}


class GrowwBroker:
    """Intentionally unavailable in this paper-only release."""
    def __init__(self):
        raise PermissionError("Groww live trading is disabled in this StockAlgo release.")

    def place_limit(self, *args, **kwargs):
        raise PermissionError("Live broker orders are disabled.")


# ------------------------------------------------------------------ state
def load_state(path, risk):
    p = Path(path)
    if p.exists():
        return json.loads(p.read_text())
    return {"cash": risk.capital, "positions": {}, "date": None, "orders_today": 0, "last_equity": None}


def equity(st, last):
    return st["cash"] + sum(p["qty"] * last.get(s, p["entry"]) for s, p in st["positions"].items())


def log_trade(row, path="trades.csv"):
    new = not Path(path).exists()
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(row))
        if new:
            w.writeheader()
        w.writerow(row)


# ------------------------------------------------------------------- core
def get_signals(cfg, data, idx, use_sent, risk, strategy=None):
    """Returns (p_up Series, as-of date, ordered entry symbols, set of exit symbols).
    ML mode: thresholds on P(up). Strategy mode: evaluates a saved builder strategy on every stock."""
    if strategy is None:
        p, asof = M.score(cfg, data, idx, use_sent)
        return p, asof, list(p[p > cfg.long_thr].index), set(p[p < risk.exit_prob].index)
    spec = json.loads((Path("strategies") / f"{strategy}.json").read_text())
    needs_p = "p_up" in json.dumps([spec["entry"], spec["exit"]])
    if needs_p:
        p, asof = M.score(cfg, data, idx, use_sent)
    else:
        p, asof = pd.Series(dtype=float), max(df.index[-1] for df in data.values())
    entries, exits = [], set()
    for sym, df in data.items():
        series = I.compute(df, spec["indicators"])
        if needs_p:
            s = I.oof_series(sym).reindex(df.index)
            if sym in p.index:
                s.iloc[-1] = p[sym]          # newest bar uses the live model score
            series["p_up"] = s
        if I.eval_rules(spec["entry"], df, series).iloc[-1]:
            entries.append(sym)
        if I.eval_rules(spec["exit"], df, series).iloc[-1]:
            exits.add(sym)
    entries.sort(key=lambda s: -p.get(s, 0.0))
    return p, asof, entries, exits


def write_dashboard_files(tag, today, st, p, last, atr_, entry_syms=()):
    """Files read by dashboard.py: latest signals and equity history."""
    sig = pd.DataFrame({"p_up": p.round(4), "close": pd.Series(last), "atr": pd.Series(atr_)})
    sig["entry"] = [s in set(entry_syms) for s in sig.index]
    sig.rename_axis("symbol").reset_index().assign(date=today).to_csv(f"signals_{tag}.csv", index=False)
    f = Path(f"equity_{tag}.csv")
    eq = pd.read_csv(f) if f.exists() else pd.DataFrame(columns=["date", "equity", "cash"])
    eq = eq[eq["date"] != today]
    eq.loc[len(eq)] = [today, round(st["last_equity"], 2), round(st["cash"], 2)]
    eq.to_csv(f, index=False)

def run_daily(cfg, data, idx, broker, risk, use_sent=False, state_path="state_paper.json",
              live=False, log=print, strategy=None, entry_filter=None):
    p, asof, entry_syms, exit_syms = get_signals(cfg, data, idx, use_sent, risk, strategy)
    if entry_filter is not None:
        kept = []
        for sym in entry_syms:
            ok, reason = entry_filter(sym, data.get(sym), asof)
            if ok:
                kept.append(sym)
            else:
                log(f"FILTERED {sym}: {reason}")
        entry_syms = kept
    if live and (dt.date.today() - asof.date()).days > risk.max_data_age_days:
        raise SystemExit(f"Stale data (last bar {asof.date()}). Aborting.")
    last = {s: float(df["close"].iloc[-1]) for s, df in data.items()}
    atr_ = {s: float(P.atr(df).iloc[-1]) for s, df in data.items()}
    st, today = load_state(state_path, risk), str(asof.date())
    if st["date"] != today:
        st["date"], st["orders_today"] = today, 0
    eq = equity(st, last)
    halted = False
    if st["last_equity"] and eq < st["last_equity"] * (1 - risk.max_daily_loss_pct / 100):
        halted = True
        log(f"DAILY LOSS LIMIT hit ({eq:.0f} vs {st['last_equity']:.0f}): no new entries")
    kill = Path(risk.kill_file).exists()
    if kill:
        log("KILL file present: exiting everything, no entries")
    cost = cfg.cost_per_trade
    buf = risk.limit_buffer_bps / 1e4

    # ---- exits first
    for sym, pos in list(st["positions"].items()):
        if sym not in last:
            log(f"SKIP EXIT {sym}: no current price data; position retained")
            continue
        px = last[sym]
        if pos["last_date"] != today:
            pos["bars"] += 1
            pos["last_date"] = today
        reason = ("kill" if kill else "stop" if px <= pos["stop"] else "target" if px >= pos["target"]
                  else "time" if pos["bars"] >= risk.max_hold_bars
                  else "signal" if sym in exit_syms else None)
        if not reason:
            continue
        res = broker.place_limit(sym, "SELL", pos["qty"], tick(px * (1 - buf)))
        st["orders_today"] += 1
        st["cash"] += res["price"] * pos["qty"] * (1 - cost)
        pnl = (res["price"] - pos["entry"]) * pos["qty"]
        log_trade({"date": today, "symbol": sym, "side": "SELL", "qty": pos["qty"], "price": res["price"],
                   "reason": reason, "pnl": round(pnl, 2), "order_id": res["id"]})
        log(f"SELL {sym} x{pos['qty']} @ {res['price']} ({reason}) pnl {pnl:.0f}")
        del st["positions"][sym]

    # ---- entries
    if not (halted or kill):
        eq = equity(st, last)
        for sym in entry_syms:
            if sym in st["positions"] or len(st["positions"]) >= risk.max_positions:
                continue
            if st["orders_today"] >= risk.max_orders_per_day:
                break
            px, a = last[sym], atr_[sym]
            pu = float(p.get(sym, float("nan")))
            why = f"strategy:{strategy}" if strategy else f"p_up={pu:.3f}"
            if px < risk.min_price or not a or math.isnan(a):
                continue
            stop_dist = risk.stop_atr * a
            limit = tick(px * (1 + buf))
            qty = math.floor(min(eq * risk.risk_per_trade_pct / 100 / stop_dist,
                                 eq * risk.max_position_pct / 100 / px,
                                 risk.max_order_value / limit,
                                 st["cash"] / (limit * (1 + cost))))
            if qty < 1:
                continue
            res = broker.place_limit(sym, "BUY", qty, limit)
            st["orders_today"] += 1
            st["cash"] -= res["price"] * qty * (1 + cost)
            st["positions"][sym] = {"qty": qty, "entry": res["price"], "stop": tick(px - stop_dist),
                                    "target": tick(px + risk.target_atr * a), "bars": 0,
                                    "entry_date": today, "last_date": today, "p_up": round(pu, 3) if pu == pu else None}
            log_trade({"date": today, "symbol": sym, "side": "BUY", "qty": qty, "price": res["price"],
                       "reason": why, "pnl": "", "order_id": res["id"]})
            log(f"BUY  {sym} x{qty} @ {res['price']} stop {px - stop_dist:.2f} ({why})")

    st["last_equity"] = equity(st, last)
    Path(state_path).write_text(json.dumps(st, indent=1))
    write_dashboard_files(Path(state_path).stem.replace("state_", ""), today, st, p, last, atr_, entry_syms)
    log(f"{today}: equity {st['last_equity']:.0f}, cash {st['cash']:.0f}, open {list(st['positions'])}")
    return st


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["paper", "live"], default="paper")
    ap.add_argument("--horizon", type=int, default=5)
    ap.add_argument("--sentiment", action="store_true")
    ap.add_argument("--capital", type=float, default=100_000)
    ap.add_argument("--strategy", help="name of a strategy saved in ./strategies by the builder")
    a = ap.parse_args()
    cfg = P.Config(horizon=a.horizon, interval="1d")
    risk = Risk(capital=a.capital, max_hold_bars=10**6 if a.strategy else a.horizon)  # strategies exit via their own rules
    tag = a.mode + (("_" + re.sub(r"\W+", "_", a.strategy)) if a.strategy else "")
    if a.mode == "live":
        raise SystemExit("LIVE TRADING IS DISABLED in this local StockAlgo build. Use --mode paper only.")
    broker = PaperBroker()
    data, idx = M.fetch(cfg)
    run_daily(cfg, data, idx, broker, risk, a.sentiment, f"state_{tag}.json", live=a.mode == "live", strategy=a.strategy)
