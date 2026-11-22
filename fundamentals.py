"""Free-source fundamentals snapshot and configurable paper-entry filter.

Yahoo Finance metadata is best-effort and may be missing, delayed, or inconsistent.
This is a current snapshot, NOT point-in-time historical fundamentals.
"""
import json
import time
from pathlib import Path

CACHE = Path("data/fundamentals_cache.json")


def _load_cache():
    if CACHE.exists():
        try:
            return json.loads(CACHE.read_text())
        except Exception:
            return {}
    return {}


def get_snapshot(symbol: str, cache_hours: int = 24, refresh: bool = False) -> dict:
    cache = _load_cache()
    item = cache.get(symbol)
    now = time.time()
    if item and not refresh and now - item.get("fetched_at", 0) < cache_hours * 3600:
        return item.get("metrics", {})
    try:
        import yfinance as yf
        info = yf.Ticker(symbol).info or {}
        metrics = {
            "market_cap_inr": info.get("marketCap"),
            "trailing_pe": info.get("trailingPE"),
            "return_on_equity": info.get("returnOnEquity"),
            "currency": info.get("currency"),
            "short_name": info.get("shortName"),
        }
        cache[symbol] = {"fetched_at": now, "metrics": metrics}
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(cache, indent=2, default=str))
        return metrics
    except Exception as exc:
        return {"_error": str(exc)}


def evaluate(metrics: dict, rules: dict) -> tuple[bool, str]:
    if metrics.get("_error"):
        return False, f"fundamental data unavailable ({metrics['_error']})"
    required = ["market_cap_inr", "trailing_pe", "return_on_equity"]
    missing = [k for k in required if metrics.get(k) is None]
    if missing:
        return False, "missing metrics: " + ", ".join(missing)
    try:
        mcap = float(metrics["market_cap_inr"])
        pe = float(metrics["trailing_pe"])
        roe = float(metrics["return_on_equity"])
    except (TypeError, ValueError):
        return False, "non-numeric fundamental metrics"
    if mcap < float(rules["min_market_cap_inr"]):
        return False, f"market cap below ₹{rules['min_market_cap_inr']:,.0f}"
    if pe <= 0 or pe > float(rules["max_trailing_pe"]):
        return False, f"trailing P/E outside (0, {rules['max_trailing_pe']}]"
    if roe < float(rules["min_return_on_equity"]):
        return False, f"ROE below {rules['min_return_on_equity']:.0%}"
    return True, "fundamental rules passed"
