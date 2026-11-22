# StockAlgo — NIFTY 50 Swing Paper-Test Profile

This project is configured for the selected local research profile:

- Universe: NIFTY 50 constituents snapshot dated 19-Nov-2026 in `config/universe_nifty50.csv` (verify current membership before each research cycle)
- Style/timeframe: swing trading, daily candles
- Prediction horizon: 5 trading bars (about one week)
- Virtual capital: ₹50,000
- Risk budget: 1% of current equity per trade (₹500 initially, before sizing constraints)
- News sentiment: enabled as a separate entry filter
- Fundamental screen: enabled as a separate entry filter
- Execution: paper only; live orders hard-disabled in `execution.py`

## 1. Local installation (free software)

Use Python 3.11. From this folder:

Windows PowerShell:
```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

macOS/Linux:
```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

The default local paper workflow does not need Groww credentials or the Groww SDK. Yahoo Finance/yfinance and Google News RSS are free-source dependencies, but access, completeness, rate limits, and data quality are not guaranteed.

## 2. Inspect configuration

```bash
python local_runner.py show-config
```

Edit `config/paper_config.json` to change the universe, thresholds, filters, costs, or risk settings. The NIFTY 50 CSV is an editable constituent snapshot, not a live official constituent feed.

## 3. Train model

```bash
python local_runner.py train
```

This downloads up to five years of daily OHLCV data for the configured universe and NIFTY index, then trains the pooled model with walk-forward validation. It saves the model under `models/`. First training can take several minutes and Yahoo Finance may throttle or omit symbols. At least 35 of the 50 symbols must load.

Force a retrain:
```bash
python local_runner.py train --force
```

The model is price/volume + market-context based. News sentiment is initially used as a live paper-entry filter rather than an ML feature because the supplied pooled model requires around 250 dates of stored sentiment history before sentiment-model training is allowed. Continue collecting daily news data; after enough history, sentiment can be evaluated as a model feature in a separate experiment.

## 4. Update news sentiment

```bash
python local_runner.py news
```

Run once after market close on each trading day. `sentiment.py` uses Google News RSS and a simple word lexicon unless optional FinBERT dependencies are installed. News coverage may be missing or noisy. The configured policy blocks new entries when a symbol has no recent sentiment record or its average score is below the configured threshold.

## 5. Run one paper cycle

After training and updating news:
```bash
python local_runner.py paper
```

Run once after the daily candle is complete. It uses virtual cash and writes state/trade/equity/signal files. The paper broker currently assumes an immediate fill at the submitted limit price. This is useful for testing signal flow, risk sizing, state persistence and dashboard wiring, but it is NOT a realistic next-session fill model and should not be used to claim strategy profitability.

To monitor the ledger in another terminal:
```bash
streamlit run dashboard.py
```

## 6. Fundamental filter defaults

The configurable initial screen requires:
- Market capitalization at least ₹1,000 crore
- Positive trailing P/E no higher than 60
- Return on equity at least 8%

These are example research filters, not investment advice or an assertion that these thresholds are optimal. Yahoo Finance company metadata may be unavailable or inconsistent; missing required fields block new paper entries. Current fundamentals are not point-in-time historical fundamentals, so this screen must not be retroactively applied to historical backtests without a historical fundamentals dataset.

## 7. Risk settings

- 1% equity risk budget per trade
- 2 ATR stop distance and 3 ATR target distance
- 15% maximum notional per position
- 5 maximum open positions
- 5-bar maximum holding period
- 2% daily loss halt for new entries
- 10 orders per day
- 10 bps estimated cost per side (placeholder; replace with a detailed India-specific brokerage, STT, exchange, GST, stamp duty and slippage model)

The ₹500 initial risk budget is a sizing ceiling based on the stop distance, not a guaranteed maximum loss. Gaps and execution costs can exceed it.

## 8. Groww integration and live-trading safety

The cloud FastAPI application includes a **read-only Groww integration** for authenticated account profile, quotes, LTP, OHLC, historical candles, holdings, positions and order history. Configure `GROWW_API_KEY` and `GROWW_API_SECRET` only in the deployment environment; never commit credentials. Groww API Key + Secret authentication may require daily approval on Groww Cloud.

The Groww adapter intentionally has no working order placement, modification or cancellation path. `execution.py --mode live` exits immediately. `PAPER_ONLY=true` and `LIVE_TRADING_ENABLED=false` must remain unchanged. See [README_RENDER_CLOUD.md](README_RENDER_CLOUD.md) for deployment, environment variables and the protected `/api/groww/*` endpoints.

## 9. Known limitations before trusting results

1. `PaperBroker` assumes immediate fills at the limit; no partial fills, queue position, liquidity, or next-session OHLC fill simulation.
2. The execution ledger uses daily close data; it is not an intraday monitor.
3. News RSS and Yahoo Finance are best-effort free sources, not guaranteed exchange-grade feeds.
4. Current Yahoo fundamentals are not historical point-in-time values and can introduce survivorship/look-ahead bias in backtests.
5. Sentiment is a separate entry filter initially; it is not yet included in the pooled ML model. The original `multi.py` sentiment model requires about 250 daily observations.
6. The current pooled-model portfolio report uses next-bar returns while the classifier label horizon is five bars; treat its portfolio return as a rough diagnostic, not as a faithful simulation of the five-bar holding rule.
7. The NIFTY 50 CSV is a manually maintained 19-Nov-2026 snapshot and must be refreshed when index reviews change membership; verify against the current NSE Indices constituent download. Snapshot reference: [19-Nov-2026 constituent list](https://taurusmutualfund.com/sites/default/files/2026-11/nifty-index-constituent-as-on-19_11_2026.pdf); official index information and constituent download: [NSE Indices — NIFTY 50](https://www.niftyindices.com/indices/equity/broad-based-indices/nifty--50).
8. Cost model is approximate; strategy metrics need realistic charges, slippage, and fill assumptions.
9. This is a research prototype, not a recommendation to buy or sell securities.

## 10. Suggested test plan

- Smoke test: `python multi.py demo` (synthetic data only; does not validate market performance).
- Data test: train on 5 years and confirm at least 35 stocks load; inspect skipped symbols.
- Model test: record out-of-sample AUC, accuracy, strategy return, Sharpe, drawdown, trade count and compare against equal-weight buy-and-hold.
- Filter test: inspect `data/sentiment.csv` and `data/fundamentals_cache.json`; verify rejected/unknown symbols and reasons.
- Paper ledger: run daily after market close for at least 4–8 weeks, without changing thresholds mid-test.
- Review: calculate realized win rate, average win/loss, profit factor, max drawdown, turnover, costs and benchmark-relative return.
- Only after this review should a more realistic next-session fill simulator be built. Live execution remains out of scope and disabled.

## 11. Render Cloud deployment

The current cloud package is documented in [README_RENDER_CLOUD.md](README_RENDER_CLOUD.md). It deploys a FastAPI dashboard and Groww read-only integration with PostgreSQL. The free Blueprint contains one free web service and one free PostgreSQL database, with no Render Cron service. The free database expires after 30 days, so use it only for testing and export anything you need to retain.

The separate `.github/workflows/paper-trading.yml` workflow is an optional paper-job runner; it is not required for the Groww read-only API routes. Review its workflow configuration and repository permissions before enabling it.
