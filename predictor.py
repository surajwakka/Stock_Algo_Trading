"""
NSE direction-prediction pipeline.

    pip install pandas numpy scikit-learn lightgbm yfinance joblib

    python predictor.py train   --symbol RELIANCE.NS --interval 1d --horizon 5
    python predictor.py predict --symbol RELIANCE.NS --interval 1d
    python predictor.py demo    # synthetic data, no network needed

Pipeline: data -> features -> volatility-scaled labels -> purged walk-forward CV
-> out-of-sample backtest with costs -> final model saved with joblib.
"""
import argparse
import json
from dataclasses import dataclass, asdict
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, roc_auc_score
from sklearn.model_selection import TimeSeriesSplit

try:
    from lightgbm import LGBMClassifier
    HAS_LGBM = True
except ImportError:
    from sklearn.ensemble import HistGradientBoostingClassifier
    HAS_LGBM = False

BARS_PER_YEAR = {"1d": 252, "1h": 252 * 6, "15m": 252 * 25, "5m": 252 * 75}


@dataclass
class Config:
    symbol: str = "RELIANCE.NS"
    interval: str = "1d"
    period: str = "10y"          # yfinance: 15m/5m only allow ~60d
    horizon: int = 5             # predict direction over next N bars
    label_k: float = 0.5         # ignore moves smaller than k * ATR% (noise)
    n_splits: int = 5
    long_thr: float = 0.55
    short_thr: float = 0.45
    allow_short: bool = False    # delivery = long only; intraday can short
    cost_per_trade: float = 0.0005   # 5 bps per side (brokerage+STT+slippage), tune this
    model_dir: str = "models"


# ----------------------------------------------------------------- data
def load_data(cfg: Config) -> pd.DataFrame:
    """Swap this for a Groww API fetch once you have access. Must return a
    DataFrame indexed by datetime with open, high, low, close, volume."""
    import yfinance as yf
    df = yf.download(cfg.symbol, period=cfg.period, interval=cfg.interval,
                     auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [c.lower() for c in df.columns]
    return df[["open", "high", "low", "close", "volume"]].dropna()


def synthetic_data(n=3000, seed=0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ret = np.zeros(n)
    for i in range(1, n):  # weak momentum so the model has something to find
        ret[i] = 0.08 * ret[i - 1] + rng.normal(0, 0.01)
    close = 100 * np.exp(np.cumsum(ret))
    high = close * (1 + rng.uniform(0, 0.005, n))
    low = close * (1 - rng.uniform(0, 0.005, n))
    open_ = np.r_[close[0], close[:-1]]
    vol = rng.integers(1e5, 1e6, n).astype(float)
    idx = pd.bdate_range("2012-01-01", periods=n)
    return pd.DataFrame({"open": open_, "high": high, "low": low,
                         "close": close, "volume": vol}, index=idx)


# ----------------------------------------------------------- indicators
def rsi(close, n=14):
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / (dn + 1e-12))


def atr(df, n=14):
    pc = df["close"].shift()
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(),
                    (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def make_features(df: pd.DataFrame) -> pd.DataFrame:
    c, h, l, v = df["close"], df["high"], df["low"], df["volume"]
    f = pd.DataFrame(index=df.index)
    for n in (1, 3, 5, 10, 20):
        f[f"ret_{n}"] = c.pct_change(n)
    for n in (10, 20, 50):
        f[f"ema_dist_{n}"] = c / c.ewm(span=n, adjust=False).mean() - 1
    f["ema_10_50"] = c.ewm(span=10, adjust=False).mean() / c.ewm(span=50, adjust=False).mean() - 1
    f["rsi_14"] = rsi(c)
    f["rsi_7"] = rsi(c, 7)
    macd = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    sig = macd.ewm(span=9, adjust=False).mean()
    f["macd_hist"] = (macd - sig) / c
    a = atr(df)
    f["atr_pct"] = a / c
    f["range_pct"] = (h - l) / c
    ma, sd = c.rolling(20).mean(), c.rolling(20).std()
    f["bb_pos"] = (c - ma) / (2 * sd + 1e-12)
    f["bb_width"] = 4 * sd / ma
    lo14, hi14 = l.rolling(14).min(), h.rolling(14).max()
    f["stoch_k"] = 100 * (c - lo14) / (hi14 - lo14 + 1e-12)
    f["vol_z"] = (v - v.rolling(20).mean()) / (v.rolling(20).std() + 1e-12)
    f["vol_ratio_20_100"] = c.pct_change().rolling(20).std() / (c.pct_change().rolling(100).std() + 1e-12)
    f["dow"] = df.index.dayofweek
    # --- plug news sentiment here (e.g. FinBERT daily score) as another column ---
    return f.replace([np.inf, -np.inf], np.nan)


def make_labels(df, cfg: Config) -> pd.Series:
    """1 = up move bigger than k*ATR%, 0 = down move bigger than k*ATR%, NaN = noise."""
    fwd = df["close"].shift(-cfg.horizon) / df["close"] - 1
    thr = cfg.label_k * atr(df) / df["close"]
    y = pd.Series(np.nan, index=df.index)
    y[fwd > thr] = 1.0
    y[fwd < -thr] = 0.0
    y[fwd.isna()] = np.nan
    return y


# ---------------------------------------------------------------- model
def new_model():
    if HAS_LGBM:
        return LGBMClassifier(n_estimators=300, learning_rate=0.03, num_leaves=15,
                              min_child_samples=50, subsample=0.8, subsample_freq=1,
                              colsample_bytree=0.8, reg_lambda=5.0, verbose=-1)
    return HistGradientBoostingClassifier(max_iter=300, learning_rate=0.03,
                                          max_leaf_nodes=15, l2_regularization=5.0)


def walk_forward(X, y, cfg: Config) -> pd.Series:
    """Expanding-window CV with a gap of `horizon` bars so labels never leak."""
    oof = pd.Series(np.nan, index=X.index)
    tscv = TimeSeriesSplit(n_splits=cfg.n_splits, gap=cfg.horizon)
    for tr, te in tscv.split(X):
        tr_lab = y.iloc[tr].dropna().index
        m = new_model().fit(X.loc[tr_lab], y.loc[tr_lab].astype(int))
        oof.iloc[te] = m.predict_proba(X.iloc[te])[:, 1]
    return oof


def backtest(df, proba: pd.Series, cfg: Config) -> pd.Series:
    sig = pd.Series(0, index=proba.index)
    sig[proba > cfg.long_thr] = 1
    if cfg.allow_short:
        sig[proba < cfg.short_thr] = -1
    nxt = df["close"].pct_change().shift(-1).reindex(proba.index)
    cost = cfg.cost_per_trade * sig.diff().abs().fillna(0)
    return (sig * nxt - cost).dropna(), sig


def report(df, oof, y, cfg: Config) -> dict:
    valid = oof.dropna().index
    lab = y.reindex(valid).dropna().index
    out = {"oos_bars": len(valid), "labeled_bars": len(lab)}
    out["auc"] = float(roc_auc_score(y[lab], oof[lab]))
    out["accuracy"] = float(accuracy_score(y[lab], (oof[lab] > 0.5).astype(int)))
    strat, sig = backtest(df, oof.dropna(), cfg)
    bpy = BARS_PER_YEAR.get(cfg.interval, 252)
    eq = (1 + strat).cumprod()
    bh = df["close"].pct_change().reindex(strat.index).fillna(0)
    out.update({
        "strategy_return_%": float((eq.iloc[-1] - 1) * 100),
        "buy_hold_return_%": float(((1 + bh).prod() - 1) * 100),
        "sharpe": float(strat.mean() / (strat.std() + 1e-12) * np.sqrt(bpy)),
        "max_drawdown_%": float(((eq / eq.cummax()) - 1).min() * 100),
        "time_in_market_%": float((sig != 0).mean() * 100),
        "trades": int((sig.diff().abs() > 0).sum()),
    })
    return out


# ------------------------------------------------------------------ CLI
def train(cfg: Config, df: pd.DataFrame):
    X, y = make_features(df), make_labels(df, cfg)
    mask = X.notna().all(axis=1)
    X, y, df = X[mask], y[mask], df[mask]
    oof = walk_forward(X, y, cfg)
    metrics = report(df, oof, y, cfg)
    print(json.dumps(metrics, indent=2))

    lab = y.dropna().index
    model = new_model().fit(X.loc[lab], y.loc[lab].astype(int))
    Path(cfg.model_dir).mkdir(exist_ok=True)
    path = Path(cfg.model_dir) / f"{cfg.symbol}_{cfg.interval}_h{cfg.horizon}.joblib"
    joblib.dump({"model": model, "features": list(X.columns), "cfg": asdict(cfg)}, path)
    print(f"saved -> {path}")
    return metrics


def predict(cfg: Config, df: pd.DataFrame):
    path = Path(cfg.model_dir) / f"{cfg.symbol}_{cfg.interval}_h{cfg.horizon}.joblib"
    bundle = joblib.load(path)
    X = make_features(df)[bundle["features"]].dropna()
    p = float(bundle["model"].predict_proba(X.iloc[[-1]])[:, 1][0])
    signal = "LONG" if p > cfg.long_thr else "SHORT" if (cfg.allow_short and p < cfg.short_thr) else "FLAT"
    print(f"{cfg.symbol} @ {X.index[-1]}: P(up over {cfg.horizon} bars)={p:.3f} -> {signal}")
    return p, signal


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["train", "predict", "demo"])
    ap.add_argument("--symbol", default="RELIANCE.NS")
    ap.add_argument("--interval", default="1d")
    ap.add_argument("--period", default="10y")
    ap.add_argument("--horizon", type=int, default=5)
    ap.add_argument("--allow-short", action="store_true")
    a = ap.parse_args()
    cfg = Config(symbol=a.symbol, interval=a.interval, period=a.period,
                 horizon=a.horizon, allow_short=a.allow_short)
    if a.mode == "demo":
        cfg.symbol = "SYNTH"
        train(cfg, synthetic_data())
    elif a.mode == "train":
        train(cfg, load_data(cfg))
    else:
        predict(cfg, load_data(cfg))
