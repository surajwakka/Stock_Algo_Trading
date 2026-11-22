> **Render cloud deployment:** see [README_RENDER_CLOUD.md](README_RENDER_CLOUD.md) for the protected dashboard, PostgreSQL persistence, scheduled daily paper job, and paper-only safety gates.

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

## 8. Live trading is disabled

`execution.py --mode live` exits immediately. The local runner never instantiates Groww or submits broker orders. `.env.example` sets live flags to `NO`. Do not change this for the testing phase.

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

## 11. Cloud paper-trading automation (Render dashboard + GitHub Actions)

This deployment keeps the trading engine paper-only. Render hosts the read-only Streamlit dashboard; GitHub Actions runs the daily scheduled paper cycle and persists the model/ledger on a separate `paper-state` branch. This avoids relying on Render's ephemeral filesystem for the trading state.

### Why the scheduler is GitHub Actions, not a Render Cron Job

Render's Free plan does not include Cron Jobs or Background Workers. Free web services also sleep after 15 minutes without inbound traffic and lose local filesystem changes on spin-down/redeploy. The GitHub Actions workflow runs at 16:30 India time Monday-Friday (`11:00 UTC`) and can be manually triggered. Standard GitHub-hosted runners are free for public repositories; private repositories use the included plan quota. See the official pricing/limits before relying on a private-repository schedule.

### A. Push the project to GitHub

1. Create a GitHub repository and push the contents of this folder to its default branch (the workflow currently expects `main`; update the checkout ref in `.github/workflows/paper-trading.yml` if your default branch has another name).
2. In GitHub, create a second branch named `paper-state`. It can contain only a README initially. Do not put credentials in this branch; it will contain the model file, sentiment/fundamental cache and simulated trade ledger.
3. In **Settings → Actions → General**, allow GitHub Actions to run. The workflow needs `contents: write` to update the `paper-state` branch.
4. Open **Actions → Daily NIFTY 50 Paper Trading → Run workflow** for the first run. The first run trains the model if no saved model exists, so it may take longer than subsequent daily runs.

The workflow restores `models/`, `data/`, `state_paper_nifty50.json`, `trades.csv`, `equity_paper_nifty50.csv`, and `signals_paper_nifty50.csv` from `paper-state`; runs the paper job; then commits updated runtime files back to that branch. `local_runner.py` includes a market-date idempotency guard so a duplicate workflow run or an NSE holiday does not execute the same daily bar twice.

### B. Deploy the dashboard on Render

1. In Render choose **New → Blueprint** and select the GitHub repository, or create a Web Service using the `render.yaml` settings.
2. The dashboard is a Free web service. It reads ledger files from the `paper-state` branch over GitHub's raw-content endpoint; it does not expect runtime files on Render's ephemeral disk.
3. Set these Render environment variables:
   - `STATE_GITHUB_REPOSITORY` = `owner/repository` (for example `your-account/StockAlgo`)
   - `STATE_GITHUB_BRANCH` = `paper-state`
   - `STATE_GITHUB_TOKEN` = a fine-grained GitHub token with **Contents: Read-only** access to this repository. For a public repository the token can be omitted, but keep it private if the state branch should not be publicly readable.
   - `ALLOW_LIVE_ORDERS` = `NO`
   - `CONFIRM_LIVE` = `NO`
4. Deploy. Open the Render URL and use **Refresh data** after a workflow completes.

### C. First-run order

1. Run the GitHub Actions workflow manually once.
2. Confirm it finishes successfully and updates the `paper-state` branch.
3. Confirm `cloud_run_status.json` says `success` and `live_orders_enabled` is `false`.
4. Open the Render dashboard and confirm virtual capital, signals and paper ledger appear.
5. Leave the weekday schedule enabled and review the Actions logs after each run.

### Cloud automation limitations

- Render hosts only the dashboard. The scheduled engine runs in GitHub Actions, not continuously on Render. This is appropriate for this daily-candle swing profile; it is not an intraday/real-time system.
- Scheduled GitHub Actions can start late; it is not a guaranteed exchange-grade scheduler. If a run fails, inspect logs and manually rerun it. Idempotency prevents a second paper cycle for an already processed market date.
- Yahoo Finance, Google News RSS and Yahoo company metadata are best-effort sources. Missing sentiment/fundamental data blocks new entries under the current configuration.
- The initial model training and daily data retrieval can take time or be throttled. Check the Actions log for skipped symbols and ensure the configured minimum stock count is met.
- The current paper broker still assumes an immediate fill at the submitted limit price. It does not model partial fills, queue position, liquidity or next-session OHLC execution.
- Render Free web services sleep after 15 minutes idle and have ephemeral local storage. The dashboard may take about a minute to wake up. GitHub Actions is the durable scheduler/state writer for this setup; the state branch is the persistent ledger.
- GitHub Actions standard runners are free for public repositories. Private repositories draw from the account's included Actions compute allowance and may incur charges after it is exhausted.

### Paper-only safety boundary

`cloud_paper_job.py` validates `mode=paper_only`, requires `live_trading_enabled=false`, and aborts if either `ALLOW_LIVE_ORDERS` or `CONFIRM_LIVE` is set to `YES`. It calls only `local_runner.py`, whose paper broker is used for simulated orders. Do not add Groww credentials to GitHub Actions or Render. The Groww adapter is not called by this cloud workflow.
