"""
Indicator registry + rule engine + backtester used by the drag-and-drop builder.

To add an indicator: write fn(df, **params) -> {output_name: Series} and add it to REGISTRY.
"""
import numpy as np
import pandas as pd

import predictor as P


# ------------------------------------------------------------ indicators
def _sma(df, period=20):
    return {"": df["close"].rolling(int(period)).mean()}


def _ema(df, period=20):
    return {"": df["close"].ewm(span=int(period), adjust=False).mean()}


def _rsi(df, period=14):
    return {"": P.rsi(df["close"], int(period))}


def _macd(df, fast=12, slow=26, signal=9):
    m = df["close"].ewm(span=int(fast), adjust=False).mean() - df["close"].ewm(span=int(slow), adjust=False).mean()
    s = m.ewm(span=int(signal), adjust=False).mean()
    return {"macd": m, "signal": s, "hist": m - s}


def _bbands(df, period=20, mult=2.0):
    ma, sd = df["close"].rolling(int(period)).mean(), df["close"].rolling(int(period)).std()
    return {"mid": ma, "upper": ma + mult * sd, "lower": ma - mult * sd}


def _atr(df, period=14):
    return {"": P.atr(df, int(period))}


def _stoch(df, period=14, smooth=3):
    lo, hi = df["low"].rolling(int(period)).min(), df["high"].rolling(int(period)).max()
    k = 100 * (df["close"] - lo) / (hi - lo + 1e-12)
    return {"k": k, "d": k.rolling(int(smooth)).mean()}


def _supertrend(df, period=10, mult=3.0):
    a = P.atr(df, int(period)).values
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    hl2 = (h + l) / 2
    ub, lb = hl2 + mult * a, hl2 - mult * a
    n = len(c)
    fu, fl, st, d = ub.copy(), lb.copy(), np.full(n, np.nan), np.ones(n)
    for i in range(1, n):
        fu[i] = ub[i] if (ub[i] < fu[i - 1] or c[i - 1] > fu[i - 1]) else fu[i - 1]
        fl[i] = lb[i] if (lb[i] > fl[i - 1] or c[i - 1] < fl[i - 1]) else fl[i - 1]
        if d[i - 1] == 1 and c[i] < fl[i]:
            d[i] = -1
        elif d[i - 1] == -1 and c[i] > fu[i]:
            d[i] = 1
        else:
            d[i] = d[i - 1]
        st[i] = fl[i] if d[i] == 1 else fu[i]
    st[: int(period)] = np.nan
    return {"line": pd.Series(st, df.index), "dir": pd.Series(d, df.index)}


def _volsma(df, period=20):
    return {"": df["volume"].rolling(int(period)).mean()}


REGISTRY = {
    "SMA": dict(fn=_sma, params={"period": 20}, overlay=True),
    "EMA": dict(fn=_ema, params={"period": 20}, overlay=True),
    "BBANDS": dict(fn=_bbands, params={"period": 20, "mult": 2.0}, overlay=True),
    "SUPERTREND": dict(fn=_supertrend, params={"period": 10, "mult": 3.0}, overlay=True),
    "RSI": dict(fn=_rsi, params={"period": 14}, overlay=False),
    "MACD": dict(fn=_macd, params={"fast": 12, "slow": 26, "signal": 9}, overlay=False),
    "STOCH": dict(fn=_stoch, params={"period": 14, "smooth": 3}, overlay=False),
    "ATR": dict(fn=_atr, params={"period": 14}, overlay=False),
    "VOLSMA": dict(fn=_volsma, params={"period": 20}, overlay=False),
}


def meta():
    out = {}
    for k, v in REGISTRY.items():
        names = list(v["fn"](pd.DataFrame({c: np.arange(60.0) + 1 for c in ("open", "high", "low", "close", "volume")})))
        out[k] = {"params": v["params"], "overlay": v["overlay"], "outputs": names}
    return out


def compute(df, specs):
    """specs: [{id, type, params}] -> {series_name: Series}. Name = id, or id.output for multi-output."""
    out = {}
    for s in specs:
        reg = REGISTRY[s["type"]]
        params = {**reg["params"], **{k: float(v) for k, v in (s.get("params") or {}).items()}}
        for o, ser in reg["fn"](df, **params).items():
            out[f"{s['id']}.{o}" if o else s["id"]] = ser
    return out


# ------------------------------------------------------------ rules
def _operand(x, df, series):
    x = str(x).strip()
    try:
        return pd.Series(float(x), index=df.index)
    except ValueError:
        pass
    if x in df.columns:
        return df[x]
    if x in series:
        return series[x]
    raise ValueError(f"Unknown operand '{x}'")


def eval_rules(block, df, series):
    """block: {logic: AND|OR, rules: [{left, op, right}]} -> boolean Series (False if no rules)."""
    rules = block.get("rules") or []
    if not rules:
        return pd.Series(False, index=df.index)
    res = []
    for r in rules:
        a, b = _operand(r["left"], df, series), _operand(r["right"], df, series)
        op = r["op"]
        if op == ">":
            m = a > b
        elif op == "<":
            m = a < b
        elif op == "crosses_above":
            m = (a > b) & (a.shift() <= b.shift())
        elif op == "crosses_below":
            m = (a < b) & (a.shift() >= b.shift())
        else:
            raise ValueError(f"Unknown operator {op}")
        res.append(m.fillna(False))
    out = res[0]
    for m in res[1:]:
        out = (out & m) if block.get("logic", "AND") == "AND" else (out | m)
    return out


# ------------------------------------------------------------ backtest
def backtest(df, entry, exit_, cost=0.0005, interval="1d", stop_pct=0.0, allow_short=False):
    """Long-only. Signal on bar t close -> position held for bar t+1 return. Optional % stop."""
    e, x = entry.values, exit_.values
    close = df["close"].values
    n = len(close)
    pos = np.zeros(n)
    entry_px, cur = 0.0, 0
    marks = []
    for i in range(n):
        if cur == 1:
            stopped = stop_pct > 0 and close[i] <= entry_px * (1 - stop_pct / 100)
            if x[i] or stopped:
                cur = 0
                marks.append((i, "exit"))
        elif e[i]:
            cur, entry_px = 1, close[i]
            marks.append((i, "entry"))
        pos[i] = cur
    pos = pd.Series(pos, df.index)
    nxt = df["close"].pct_change().shift(-1)
    strat = (pos * nxt - cost * pos.diff().abs().fillna(pos.abs())).dropna()
    eq = (1 + strat).cumprod()
    bpy = P.BARS_PER_YEAR.get(interval, 252)
    n_trades = sum(1 for _, k in marks if k == "entry")
    return {
        "equity": eq, "marks": [(df.index[i], k) for i, k in marks],
        "metrics": {
            "total_return_%": round((eq.iloc[-1] - 1) * 100, 2) if len(eq) else 0.0,
            "buy_hold_%": round(((1 + nxt.dropna()).prod() - 1) * 100, 2),
            "sharpe": round(strat.mean() / (strat.std() + 1e-12) * np.sqrt(bpy), 2) if len(strat) else 0.0,
            "max_drawdown_%": round(((eq / eq.cummax()) - 1).min() * 100, 2) if len(eq) else 0.0,
            "trades": n_trades,
            "time_in_market_%": round(float(pos.mean()) * 100, 1),
        },
    }


def oof_series(symbol, path="data/oof_pup.csv"):
    """Out-of-fold ML P(up) history for one symbol (written by `python multi.py train`). Daily bars only."""
    from pathlib import Path
    if not Path(path).exists():
        return pd.Series(dtype=float)
    d = pd.read_csv(path, parse_dates=["date"])
    return d[d["symbol"] == symbol].set_index("date")["p_up"].sort_index()
