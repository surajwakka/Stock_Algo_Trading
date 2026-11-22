"""Local NIFTY 50 swing-trading research runner. PAPER ONLY; no broker connection."""
import argparse
import json
from pathlib import Path

import pandas as pd

import execution as E
import fundamentals as F
import multi as M
import predictor as P
import sentiment as S

CONFIG_PATH = Path("config/paper_config.json")


def read_config():
    if not CONFIG_PATH.exists():
        raise SystemExit("Missing config/paper_config.json. Run from the stockalgo_phase1 project directory.")
    return json.loads(CONFIG_PATH.read_text())


def universe(cfg):
    frame = pd.read_csv(cfg["universe_file"])
    return [f"{x}.NS" for x in frame["symbol"].dropna().astype(str).str.strip()]


def model_config(c):
    return P.Config(
        symbol="RELIANCE.NS", interval=c["interval"], period=c["period"],
        horizon=int(c["prediction_horizon_bars"]), long_thr=float(c["long_probability_threshold"]),
        short_thr=0.45, allow_short=bool(c["allow_short"]),
        cost_per_trade=float(c["estimated_cost_per_side_bps"]) / 10000.0,
    )


def fetch_all(c):
    cfg = model_config(c)
    data, failures = {}, []
    symbols = universe(c)
    for i, sym in enumerate(symbols, 1):
        try:
            cfg.symbol = sym
            df = P.load_data(cfg)
            if len(df) < 260:
                raise ValueError(f"only {len(df)} daily bars; need at least 260")
            data[sym] = df
            print(f"[{i:02d}/{len(symbols)}] loaded {sym}: {len(df)} bars")
        except Exception as exc:
            failures.append((sym, str(exc)))
            print(f"[{i:02d}/{len(symbols)}] SKIP {sym}: {exc}")
    cfg.symbol = M.INDEX_SYMBOL
    idx = P.load_data(cfg)[["close"]]
    if len(data) < 35:
        raise SystemExit(f"Only {len(data)} stocks loaded successfully; at least 35 of 50 are required. Check data access and retry.")
    print(f"Loaded {len(data)}/{len(symbols)} stocks; failed: {len(failures)}")
    return cfg, data, idx


def train_model(force=False):
    c = read_config()
    cfg, data, idx = fetch_all(c)
    path = M.model_path(cfg, False)
    if path.exists() and not force:
        print(f"Model already exists: {path}. Use --force to retrain.")
        return
    print("Training pooled price/volume + market model. Sentiment is applied as a separate entry filter initially.")
    M.train(cfg, data, idx, False)


def update_news():
    c = read_config()
    symbols = universe(c)
    print(f"Updating Google News RSS sentiment for {len(symbols)} NIFTY 50 symbols...")
    S.update_store(symbols)


def make_entry_filter(c):
    fr = c["fundamental_filter"]
    nr = c["news_sentiment"]
    def check(sym, df, asof):
        if fr.get("enabled", False):
            metrics = F.get_snapshot(sym, cache_hours=int(fr.get("cache_hours", 24)))
            ok, reason = F.evaluate(metrics, fr)
            if not ok:
                return False, reason
        if nr.get("enabled", False):
            hist = S.load_daily(sym)
            if hist.empty:
                return False, "no stored news sentiment; run `python local_runner.py news`"
            cutoff = pd.Timestamp(asof).normalize() - pd.Timedelta(days=int(nr.get("max_news_age_days", 7)))
            hist = hist[(hist.index <= pd.Timestamp(asof).normalize()) & (hist.index >= cutoff)].tail(int(nr.get("lookback_days", 3)))
            if hist.empty:
                return False, "news sentiment is stale or unavailable"
            score = float(hist["score"].mean())
            if score < float(nr.get("block_below_score", -0.25)):
                return False, f"negative news sentiment ({score:.2f})"
        return True, "fundamental and sentiment filters passed"
    return check


def paper_run():
    c = read_config()
    if c.get("live_trading_enabled") is not False or c.get("mode") != "paper_only":
        raise SystemExit("Safety check failed: this runner requires mode=paper_only and live_trading_enabled=false.")
    cfg, data, idx = fetch_all(c)
    path = M.model_path(cfg, False)
    if not path.exists():
        raise SystemExit("No trained model found. Run `python local_runner.py train` first.")

    # Idempotency guard for scheduled cloud runs and manual retries. A market
    # holiday or duplicate workflow invocation must not create a second cycle.
    latest_bar = max(df.index[-1] for df in data.values())
    state_path = Path(c["state_file"])
    if state_path.exists():
        try:
            prior_state = json.loads(state_path.read_text())
        except (OSError, json.JSONDecodeError):
            prior_state = {}
        if prior_state.get("date") == str(latest_bar.date()):
            print(f"Paper cycle already completed for market date {latest_bar.date()}; skipping duplicate run.")
            return

    risk = E.Risk(
        capital=float(c["starting_virtual_capital_inr"]),
        risk_per_trade_pct=float(c["risk_per_trade_pct"]),
        max_position_pct=float(c["max_position_pct"]),
        max_positions=int(c["max_open_positions"]),
        stop_atr=float(c["stop_atr_multiple"]), target_atr=float(c["target_atr_multiple"]),
        max_hold_bars=int(c["max_holding_bars"]),
        exit_prob=float(c["exit_probability_threshold"]),
        max_daily_loss_pct=float(c["max_daily_loss_pct"]),
        max_orders_per_day=int(c["max_orders_per_day"]),
        limit_buffer_bps=float(c["limit_buffer_bps"]),
        min_price=float(c["min_share_price_inr"]),
        max_order_value=float(c["max_order_value_inr"]),
        kill_file=c["kill_file"],
    )
    print("PAPER-ONLY MODE: no Groww SDK, API credentials, or live order endpoint is used.")
    print(f"Profile: {c['profile_name']} | virtual capital ₹{risk.capital:,.0f} | risk/trade {risk.risk_per_trade_pct:.2f}%")
    print("Note: current PaperBroker assumes immediate fills at its submitted limit price; this is a smoke-test ledger, not a realistic market-fill simulation.")
    E.run_daily(
        cfg, data, idx, E.PaperBroker(), risk,
        use_sent=False, state_path=c["state_file"], live=False,
        entry_filter=make_entry_filter(c),
    )


def main():
    ap = argparse.ArgumentParser(description="Local NIFTY 50 swing strategy research — paper only")
    sub = ap.add_subparsers(dest="command", required=True)
    t = sub.add_parser("train", help="download history and train the pooled model")
    t.add_argument("--force", action="store_true")
    sub.add_parser("news", help="update recent news sentiment store")
    sub.add_parser("paper", help="run one daily paper-trading cycle after market close")
    sub.add_parser("show-config", help="print the active paper configuration")
    args = ap.parse_args()
    if args.command == "train":
        train_model(args.force)
    elif args.command == "news":
        update_news()
    elif args.command == "paper":
        paper_run()
    elif args.command == "show-config":
        print(json.dumps(read_config(), indent=2))

if __name__ == "__main__":
    main()
