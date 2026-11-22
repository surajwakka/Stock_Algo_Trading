# StockAlgo — Render Cloud Paper Platform

This deployment adds a protected dashboard, JSON API, existing drag/drop strategy builder, persistent PostgreSQL ledger, and a scheduled daily paper runner.

## Active profile

- NIFTY 50 constituent snapshot in `config/universe_nifty50.csv`
- Swing trading, daily candles, 5-bar prediction horizon
- Virtual starting capital: ₹50,000
- Risk budget: 1% per trade
- News sentiment and fundamental entry filters enabled
- Long-only; maximum 5 open positions
- **PAPER ONLY. LIVE BROKER ORDERS ARE HARD-DISABLED.**

## Added files

| File | Purpose |
|---|---|
| `cloud_app.py` | Protected dashboard, JSON API and database-backed strategy-builder routes |
| `cloud_store.py` | PostgreSQL persistence for portfolio, trades, signals, equity, news, models, strategies and job history |
| `cloud_job.py` | Scheduled paper job: restore database state, update news, retrain stale model, paper run, persist results |
| `render.yaml` | Render Blueprint for web service, scheduled Cron Job and PostgreSQL |
| `builder.html` | Existing drag/drop strategy builder, served at `/builder` |

## Deploy on Render

1. Push the **contents** of this folder to the root of a GitHub repository.
2. In Render choose **New → Blueprint** and connect the repository.
3. Review `render.yaml`. It provisions:
   - `stockalgo-cloud`: protected dashboard/API web service
   - `stockalgo-daily-paper`: scheduled weekday paper job
   - `stockalgo-postgres`: persistent paid PostgreSQL database
4. When prompted, set `DASHBOARD_PASSWORD` to a strong unique password. Do not commit it to GitHub.
5. Apply the Blueprint and wait for the web service and database to become healthy.
6. Open the web service URL. Browser Basic Authentication uses username `admin` and the password you supplied.
7. Open `/health` to confirm status, `/` for the dashboard, and `/builder` for the drag/drop strategy builder.
8. Trigger the Cron Job manually once from Render to initialize the first model and paper ledger; then check its logs.

The scheduled expression is `0 11 * * 1-5` UTC (16:30 India time), after the NSE cash-market close. Render Cron schedules use UTC.

## What the first scheduled run does

1. Restores portfolio, trade history, sentiment and model artifacts from PostgreSQL.
2. Updates Google News RSS sentiment.
3. Trains the pooled model if no model exists or the stored model is older than seven days.
4. Runs one NIFTY 50 paper cycle.
5. Persists model, sentiment, portfolio state, trades, signals, equity history and job status to PostgreSQL.

The first run can take longer because it downloads historical data for the universe and trains the model. Check Cron logs if fewer than 35 symbols load or data providers throttle requests.

## Cost and free-tier limitations

This Blueprint deliberately selects a **paid PostgreSQL plan** so the ledger is not subject to the 30-day expiry of Render Free Postgres. The dashboard web service uses Render's free plan and may sleep after inactivity. The selected smallest paid PostgreSQL plan is currently listed at $6/month; the Cron Job is separately billed by active minutes, with a $1/month minimum per Cron Job service. That makes the baseline roughly $7/month before taxes, additional Cron usage, bandwidth, or plan changes. Check Render pricing before applying the Blueprint.

A free Render Postgres database expires after 30 days. Free web services have ephemeral local filesystems and may spin down; this build stores critical state in PostgreSQL rather than relying on local files. The dashboard can be free, but the persistent database and daily automation are not a guaranteed $0 setup.

## Environment and safety

The Blueprint injects `DATABASE_URL` from Render Postgres and sets:

- `DASHBOARD_USERNAME=admin`
- `DASHBOARD_PASSWORD` — prompted at deployment
- `PAPER_ONLY=true`
- `LIVE_TRADING_ENABLED=false`

There are no Groww credentials in the Blueprint. `execution.GrowwBroker` and `groww_adapter.GrowwAdapter` both raise `PermissionError` in this release. The scheduled runner constructs only `PaperBroker`.

The dashboard kill switch is database-backed. It affects paper-mode behavior only; it cannot submit, cancel, or modify broker orders.

## Local smoke test

Use Python 3.11:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

Set local environment variables (SQLite is used if DATABASE_URL is omitted):

```powershell
# Windows PowerShell
$env:DATABASE_URL="sqlite:///./stockalgo_cloud.db"
$env:PAPER_ONLY="true"
$env:LIVE_TRADING_ENABLED="false"
$env:DASHBOARD_PASSWORD="local-test-password"
```

```bash
# macOS/Linux
export DATABASE_URL="sqlite:///./stockalgo_cloud.db"
export PAPER_ONLY="true"
export LIVE_TRADING_ENABLED="false"
export DASHBOARD_PASSWORD="local-test-password"
```

Then run:

```bash
python -c "import cloud_store; cloud_store.init_db(); print('DB ready')"
uvicorn cloud_app:app --reload
```

Open `http://127.0.0.1:8000`, sign in as `admin`, and visit `/builder` for strategy design. To execute the first full data/news/model/paper workflow locally, run `python cloud_job.py daily`. That command downloads market/news data and can take time.

## Known limitations

- Yahoo Finance and Google News RSS are best-effort free sources; availability, completeness, rate limits and correctness are not guaranteed.
- Fundamental filters use current Yahoo Finance metadata, not historical point-in-time fundamentals.
- The paper broker currently assumes immediate fills at its submitted limit price. It is not a realistic exchange queue/partial-fill simulator.
- The daily engine uses completed daily bars; it is not an intraday monitor.
- Model portfolio metrics use next-bar returns while the classifier label horizon is five bars; treat them as diagnostic, not as a faithful simulation of the five-bar holding strategy.
- This is a research and paper-trading prototype, not investment advice.

## Validation checklist

1. Trigger one daily Cron run manually and inspect its logs.
2. Confirm the latest job status is `succeeded` on the dashboard.
3. Confirm virtual cash begins at ₹50,000 and generated order IDs start with `paper-`.
4. Restart/redeploy the web service and confirm the portfolio and trade history remain available from PostgreSQL.
5. Let it run for 4–8 weeks; compare returns with NIFTY 50 buy-and-hold.
6. Review model AUC/accuracy, win rate, profit factor, drawdown, costs and benchmark-relative returns.

Live trading is not part of this release.
