"""
Multi-stock pooled model (needs predictor.py and sentiment.py in the same folder).

    python multi.py train   --horizon 5                  # price + market features
    python multi.py train   --horizon 5 --sentiment      # + news sentiment (needs history in data/sentiment.csv)
    python multi.py predict --horizon 5 [--sentiment]    # ranked P(up) for every stock, latest bar
    python multi.py demo                                 # synthetic data, no network

One model is trained on all stocks together (more data, more robust), with
market-relative and cross-sectional features. Daily bars only.
"""
import argparse
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, roc_auc_score
from sklearn.model_selection import TimeSeriesSplit

import predictor as P
import sentiment as S

# Verify against the current Nifty 50 constituents; the list changes.
UNIVERSE_FILE = Path("config/universe_nifty50.csv")
if UNIVERSE_FILE.exists():
    _universe_frame = pd.read_csv(UNIVERSE_FILE)
    UNIVERSE = [f"{s}.NS" for s in _universe_frame["symbol"].dropna().astype(str).str.strip().tolist()]
else:
    # Fallback for running the original scaffold outside the configured project folder.
    UNIVERSE = [f"{s}.NS" for s in (
        "RELIANCE TCS HDFCBANK INFY ICICIBANK HINDUNILVR ITC SBIN BHARTIARTL KOTAKBANK "
        "LT AXISBANK ASIANPAINT MARUTI SUNPHARMA TITAN WIPRO HCLTECH NESTLEIND ULTRACEMCO").split()]
INDEX_SYMBOL = "^NSEI"
SENT_COLS = ["sent_1d", "sent_3d", "news_cnt"]


# ------------------------------------------------------------- features
def market_feats(df, idx):
    m = idx["close"].reindex(df.index).ffill()
    f = pd.DataFrame(index=df.index)
    for n in (1, 5, 20):
        f[f"mkt_ret_{n}"] = m.pct_change(n)
    f["mkt_vol_20"] = m.pct_change().rolling(20).std()
    f["rel_5"] = df["close"].pct_change(5) - f["mkt_ret_5"]
    f["rel_20"] = df["close"].pct_change(20) - f["mkt_ret_20"]
    return f


def sent_feats(sym, index):
    """News known up to the PREVIOUS day only, so there is no look-ahead."""
    out = pd.DataFrame(np.nan, index=index, columns=SENT_COLS)
    s = S.load_daily(sym)
    if s.empty:
        return out
    cal = s.reindex(pd.date_range(s.index.min(), max(index.max(), s.index.max())))
    f = pd.DataFrame({
        "sent_1d": cal["score"].shift(1).ffill(limit=3),
        "sent_3d": cal["score"].rolling(3, min_periods=1).mean().shift(1).ffill(limit=3),
        "news_cnt": cal["n"].shift(1),
    })
    return f.reindex(index)


def build_panel(data, idx, cfg, use_sent):
    frames = []
    for sym, df in data.items():
        f = P.make_features(df).join(market_feats(df, idx))
        if use_sent:
            f = f.join(sent_feats(sym, df.index))
        f["y"] = P.make_labels(df, cfg)
        f["nxt"] = df["close"].pct_change().shift(-1)
        f["symbol"] = sym
        frames.append(f)
    panel = pd.concat(frames).set_index("symbol", append=True).sort_index()
    panel.index.names = ["date", "symbol"]
    panel["xs_rank_ret_5"] = panel.groupby(level=0)["ret_5"].rank(pct=True)
    panel["xs_rank_rsi"] = panel.groupby(level=0)["rsi_14"].rank(pct=True)
    base = [c for c in panel.columns if c not in SENT_COLS + ["y", "nxt"]]
    panel = panel[panel[base].notna().all(axis=1)]
    if use_sent:
        first = panel.index.get_level_values(0)[panel["sent_1d"].notna().values]
        if len(first) == 0 or panel.index.get_level_values(0).nunique() == 0:
            raise SystemExit("No sentiment history found. Run `python sentiment.py --update` daily first.")
        panel = panel[panel.index.get_level_values(0) >= first.min()]  # avoid NaN acting as a time proxy
        n_dates = panel.index.get_level_values(0).nunique()
        if n_dates < 250:
            raise SystemExit(f"Only {n_dates} dates of sentiment history; need ~250+. Train without --sentiment for now.")
    feats = [c for c in panel.columns if c not in ("y", "nxt")]
    return panel, feats


# ------------------------------------------------- validation + backtest
def walk_forward(panel, feats, cfg):
    d = panel.index.get_level_values(0)
    dates = d.unique().sort_values()
    oof = pd.Series(np.nan, index=panel.index)
    for tr_d, te_d in TimeSeriesSplit(n_splits=cfg.n_splits, gap=cfg.horizon).split(dates):
        tr = panel[d.isin(dates[tr_d]) & panel["y"].notna().values]
        te_mask = d.isin(dates[te_d])
        m = P.new_model().fit(tr[feats], tr["y"].astype(int))
        oof[te_mask] = m.predict_proba(panel.loc[te_mask, feats])[:, 1]
    return oof


def portfolio_report(panel, oof, cfg):
    lab = panel["y"].notna() & oof.notna()
    out = {"oos_rows": int(oof.notna().sum()),
           "auc": float(roc_auc_score(panel.loc[lab, "y"], oof[lab])),
           "accuracy": float(accuracy_score(panel.loc[lab, "y"], (oof[lab] > 0.5).astype(int)))}
    p = oof.dropna()
    sig = pd.Series(0, index=p.index)
    sig[p > cfg.long_thr] = 1
    if cfg.allow_short:
        sig[p < cfg.short_thr] = -1
    turnover = sig.groupby(level=1).diff().abs().fillna(sig.abs())
    strat = (sig * panel.loc[p.index, "nxt"] - cfg.cost_per_trade * turnover).dropna()
    port = strat.groupby(level=0).mean()                      # equal weight across the universe
    bh = panel.loc[strat.index, "nxt"].groupby(level=0).mean()
    eq = (1 + port).cumprod()
    out.update({
        "strategy_return_%": float((eq.iloc[-1] - 1) * 100),
        "equal_weight_buy_hold_%": float(((1 + bh).prod() - 1) * 100),
        "sharpe": float(port.mean() / (port.std() + 1e-12) * np.sqrt(252)),
        "max_drawdown_%": float((eq / eq.cummax() - 1).min() * 100),
        "avg_stocks_long_per_day": float((sig == 1).groupby(level=0).sum().mean()),
    })
    # Does a higher P(up) rank actually mean a higher forward return? (cross-sectional check)
    tmp = pd.DataFrame({"p": p, "r": panel.loc[p.index, "nxt"]}).dropna()
    tmp["q"] = tmp.groupby(level=0)["p"].transform(lambda s: pd.qcut(s.rank(method="first"), 4, labels=False))
    out["fwd_1bar_return_bps_by_quartile"] = (tmp.groupby("q")["r"].mean() * 1e4).round(2).to_dict()
    return out


# ------------------------------------------------------------------ run
def model_path(cfg, use_sent):
    return Path(cfg.model_dir) / f"pooled_h{cfg.horizon}{'_sent' if use_sent else ''}.joblib"


def train(cfg, data, idx, use_sent):
    panel, feats = build_panel(data, idx, cfg, use_sent)
    print(f"panel: {len(panel)} rows, {panel.index.get_level_values(1).nunique()} stocks, {len(feats)} features")
    oof = walk_forward(panel, feats, cfg)
    print(json.dumps(portfolio_report(panel, oof, cfg), indent=2))
    Path("data").mkdir(exist_ok=True)   # honest (out-of-fold) P(up) history, used by the builder as `p_up`
    oof.dropna().rename("p_up").reset_index().to_csv("data/oof_pup.csv", index=False)
    lab = panel[panel["y"].notna()]
    model = P.new_model().fit(lab[feats], lab["y"].astype(int))
    if hasattr(model, "feature_importances_"):
        imp = pd.Series(model.feature_importances_, feats).sort_values(ascending=False)
        print("top features:", imp.head(10).to_dict())
    Path(cfg.model_dir).mkdir(exist_ok=True)
    joblib.dump({"model": model, "features": feats, "cfg": cfg.__dict__, "use_sent": use_sent}, model_path(cfg, use_sent))
    print(f"saved -> {model_path(cfg, use_sent)}")


def score(cfg, data, idx, use_sent):
    """Latest-bar P(up) per stock (Series) and the as-of date."""
    b = joblib.load(model_path(cfg, use_sent))
    frames = []
    for sym, df in data.items():
        f = P.make_features(df).join(market_feats(df, idx))
        if use_sent:
            f = f.join(sent_feats(sym, df.index))
        f["symbol"] = sym
        frames.append(f)
    pan = pd.concat(frames).set_index("symbol", append=True).sort_index()
    pan.index.names = ["date", "symbol"]
    pan["xs_rank_ret_5"] = pan.groupby(level=0)["ret_5"].rank(pct=True)
    pan["xs_rank_rsi"] = pan.groupby(level=0)["rsi_14"].rank(pct=True)
    last = pan.index.get_level_values(0).max()
    X = pan.xs(last, level=0)[b["features"]]
    X = X.dropna(subset=[c for c in b["features"] if c not in SENT_COLS])
    p = pd.Series(b["model"].predict_proba(X)[:, 1], X.index, name="P_up").sort_values(ascending=False)
    return p, last


def predict(cfg, data, idx, use_sent):
    p, last = score(cfg, data, idx, use_sent)
    sig = np.where(p > cfg.long_thr, "LONG", np.where(cfg.allow_short & (p < cfg.short_thr), "SHORT", "FLAT"))
    print(f"as of {last.date()}, horizon {cfg.horizon} bars")
    print(pd.DataFrame({"P_up": p.round(3), "signal": sig}).to_string())


def fetch(cfg):
    data = {}
    for s in UNIVERSE:
        try:
            cfg.symbol = s
            data[s] = P.load_data(cfg)
        except Exception as e:
            print(f"skip {s}: {e}")
    cfg.symbol = INDEX_SYMBOL
    return data, P.load_data(cfg)


def demo_data():
    data = {f"SYN{i}.NS": P.synthetic_data(3000, seed=i) for i in range(8)}
    idx = pd.DataFrame({"close": pd.concat([d["close"] / d["close"].iloc[0] for d in data.values()], axis=1).mean(axis=1)})
    rng = np.random.default_rng(1)
    days = pd.date_range(idx.index[1500], idx.index[-1])   # fake sentiment for the last ~half only
    S.load_daily = lambda sym: pd.DataFrame({"score": rng.normal(0, .3, len(days)),
                                             "n": rng.integers(1, 20, len(days)).astype(float)}, index=days)
    return data, idx


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["train", "predict", "demo"])
    ap.add_argument("--horizon", type=int, default=5)
    ap.add_argument("--period", default="10y")
    ap.add_argument("--sentiment", action="store_true")
    ap.add_argument("--allow-short", action="store_true")
    a = ap.parse_args()
    cfg = P.Config(horizon=a.horizon, period=a.period, interval="1d", allow_short=a.allow_short)
    if a.mode == "demo":
        d, i = demo_data()
        train(cfg, d, i, False)
        train(cfg, d, i, True)
    else:
        d, i = fetch(cfg)
        (train if a.mode == "train" else predict)(cfg, d, i, a.sentiment)
