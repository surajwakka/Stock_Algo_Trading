# StockAlgo — Render Free Cloud + Groww Read-only Integration

This release adds a protected cloud dashboard, database-backed strategy builder, PostgreSQL persistence, and a **read-only Groww integration** for account profile, market quotes, LTP, OHLC, historical candles, holdings, positions and order history.

## Safety guarantees

- `PAPER_ONLY=true`
- `LIVE_TRADING_ENABLED=false`
- Groww adapter exposes no working order-write path. `place_order`, `modify_order` and `cancel_order` fail closed with `PermissionError`.
- Groww API routes are protected by the same HTTP Basic authentication as the dashboard.
- API credentials are read only from environment variables and are never returned by the API.
- Access tokens are cached in process memory for up to 20 hours and the cache is keyed to the credential pair.

This is a research and paper-trading prototype, not investment advice. Do not enable real-money order submission in this release.

## Render Free deployment

`render.yaml` provisions only:

- `stockalgo-cloud`: Free web service
- `stockalgo-postgres`: Free PostgreSQL

There is **no Cron service** in this Blueprint. Run paper jobs manually from a trusted local environment when required. Render Free Postgres expires after 30 days and has limited storage/no production backup guarantee. The Free web service may spin down after inactivity and has an ephemeral filesystem; persistent application data belongs in PostgreSQL.

1. Push the contents of this directory to the root of your GitHub repository.
2. In Render choose **New → Blueprint**, connect the repository and review the resources.
3. Confirm the web service and database both show **Free**. Do not apply if Render displays a paid resource.
4. Set `DASHBOARD_PASSWORD` to a strong unique password when prompted.
5. Apply the Blueprint and wait for `/health` to return `status: ok`.
6. Open the service URL and authenticate with username `admin` and your password.

## Groww environment variables

In Render → `stockalgo-cloud` → **Environment**, add the following exact variable names:

- `GROWW_API_KEY` — Groww API key
- `GROWW_API_SECRET` — matching Groww API secret

Do not put credentials in GitHub, `.env.example`, source files, screenshots or chat. Restart/redeploy the web service after changing environment variables. The API Key + Secret flow requires the daily approval process on Groww Cloud before token generation may succeed.

The deployment also expects:

- `PAPER_ONLY=true`
- `LIVE_TRADING_ENABLED=false`

Keep these values unchanged.

## Groww read-only endpoints

All endpoints below require HTTP Basic Authentication.

| Endpoint | Purpose |
|---|---|
| `GET /api/groww/status` | Check whether credentials and SDK are configured (does not authenticate with Groww) |
| `GET /api/groww/profile` | Authenticate and fetch Groww user profile |
| `GET /api/groww/quote/RELIANCE?exchange=NSE&segment=CASH` | Single-instrument quote |
| `GET /api/groww/ltp?symbols=RELIANCE,TCS&exchange=NSE&segment=CASH` | LTP for up to 50 instruments |
| `GET /api/groww/ohlc?symbols=RELIANCE,TCS&exchange=NSE&segment=CASH` | Current OHLC snapshot for up to 50 instruments |
| `GET /api/groww/candles/RELIANCE?start_time=2026-11-20%2009:15:00&end_time=2026-11-20%2015:30:00&interval_minutes=5` | Historical candles |
| `GET /api/groww/holdings` | Read holdings |
| `GET /api/groww/positions` | Read positions; optional `segment=CASH` or `FNO` |
| `GET /api/groww/orders` | Read order history; optional `segment`, `page`, `page_size` |

The dashboard includes a small Groww connection test and NSE quote panel. Groww API calls are made only when a protected endpoint is requested; application startup does not attempt broker authentication.

## Groww SDK and access restrictions

The official `growwapi` SDK is installed by `requirements-render.txt`. API Key + Secret authentication uses `GrowwAPI.get_access_token(api_key=..., secret=...)`. Daily approval on the Groww Cloud API Keys page may be required. Groww may require a registered static IP for order-related access. Render Free does not provide a dedicated static outbound IP; therefore this deployment is not represented as a supported live-order host. This release does not submit, modify or cancel orders regardless.

## Local development

Python 3.11 is recommended.

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

Set `DATABASE_URL`, `DASHBOARD_PASSWORD`, `GROWW_API_KEY` and `GROWW_API_SECRET` in your local environment. Keep `.env` out of Git. Then run:

```bash
uvicorn cloud_app:app --reload
```

Open `/`, sign in, then use the Groww connection panel or the endpoints above. To check configuration without making a Groww API call, open `/api/groww/status`.

## Market data notes

Groww provides quote, LTP, OHLC and historical candle APIs. The SDK documentation states up to 50 instruments per LTP/OHLC call. Historical data interval availability and maximum request windows depend on the interval; follow Groww's current documentation and rate limits. Groww API data should not be described as direct NSE/BSE exchange-feed integration. Moneycontrol integration and licensed exchange data feeds are not included in this release.

## Validation

- `python -m compileall -q .`
- `python -m pytest -q`
- `/health` reports paper mode and live orders disabled.
- `/api/groww/status` reports configured credentials and SDK availability without exposing secrets.
- `/api/groww/profile` validates Groww authentication after daily approval.
- All Groww routes require dashboard authentication.
- No broker order-write endpoint is registered.

## Known limitations

- No live order placement, modification or cancellation.
- No static-IP broker worker in this Free deployment.
- No automated Cron job in this Free deployment.
- Groww credentials/API availability and daily approval are external dependencies.
- No direct NSE/BSE licensed data feed or Moneycontrol API integration.
- Yahoo Finance and Google News RSS remain best-effort sources for existing model/news jobs.
- Existing paper broker fill assumptions are simplified and do not model exchange queue position or partial fills.
