"""
Daily news-sentiment store for NSE stocks.

    pip install requests pandas transformers torch   # transformers/torch optional (lexicon fallback)
    python sentiment.py --update            # run once a day after market close (cron)

Google News RSS only returns the last few days, so history is built by running
this daily. Until you have months of data, sentiment adds little to the model.
For instant history, buy/download a historical news dataset and write it into
data/sentiment.csv with columns: date, symbol, score, n.
"""
import argparse
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo

import pandas as pd
import requests

STORE = Path("data/sentiment.csv")

# Yahoo symbol -> company name. Read the configured universe when available.
NAMES = {}
_universe_file = Path("config/universe_nifty50.csv")
if _universe_file.exists():
    _universe = pd.read_csv(_universe_file)
    NAMES = {f"{r.symbol}.NS": str(r.company) for r in _universe.itertuples(index=False)}
else:
    NAMES = {
        "RELIANCE.NS": "Reliance Industries", "TCS.NS": "Tata Consultancy Services",
        "HDFCBANK.NS": "HDFC Bank", "INFY.NS": "Infosys", "ICICIBANK.NS": "ICICI Bank",
        "HINDUNILVR.NS": "Hindustan Unilever", "ITC.NS": "ITC Limited", "SBIN.NS": "State Bank of India",
        "BHARTIARTL.NS": "Bharti Airtel", "KOTAKBANK.NS": "Kotak Mahindra Bank", "LT.NS": "Larsen & Toubro",
        "AXISBANK.NS": "Axis Bank", "ASIANPAINT.NS": "Asian Paints", "MARUTI.NS": "Maruti Suzuki",
        "SUNPHARMA.NS": "Sun Pharma", "TITAN.NS": "Titan Company", "WIPRO.NS": "Wipro",
        "HCLTECH.NS": "HCL Technologies", "NESTLEIND.NS": "Nestle India", "ULTRACEMCO.NS": "UltraTech Cement",
    }

POS = {"surge", "jump", "beat", "beats", "record", "upgrade", "gain", "gains", "rally", "profit", "growth",
       "strong", "wins", "order", "buy", "outperform", "soars", "rises", "dividend"}
NEG = {"fall", "falls", "drop", "plunge", "miss", "misses", "downgrade", "loss", "probe", "fraud", "weak",
       "sell", "underperform", "slump", "cuts", "penalty", "default", "raid", "ban", "decline"}

_pipe = None


def score_texts(texts):
    """Returns sentiment in [-1, 1] per text. FinBERT if available, else a crude lexicon."""
    global _pipe
    if not texts:
        return []
    if _pipe is None:
        try:
            from transformers import pipeline
            _pipe = pipeline("text-classification", model="ProsusAI/finbert", top_k=None)
        except Exception:
            _pipe = False
    if _pipe:
        out = []
        for r in _pipe(texts, truncation=True):
            d = {x["label"].lower(): x["score"] for x in r}
            out.append(d.get("positive", 0.0) - d.get("negative", 0.0))
        return out
    res = []
    for t in texts:
        w = set(t.lower().split())
        res.append(max(-1, min(1, (len(w & POS) - len(w & NEG)) / 3)))
    return res


def fetch_headlines(name: str) -> pd.DataFrame:
    url = f"https://news.google.com/rss/search?q={quote_plus(name + ' stock')}+when:7d&hl=en-IN&gl=IN&ceid=IN:en"
    r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    rows = []
    for it in ET.fromstring(r.content).iter("item"):
        try:
            dt = parsedate_to_datetime(it.findtext("pubDate")).astimezone(ZoneInfo("Asia/Kolkata"))
            rows.append({"date": dt.date(), "title": it.findtext("title")})
        except Exception:
            continue
    return pd.DataFrame(rows, columns=["date", "title"])


def update_store(symbols=None) -> pd.DataFrame:
    symbols = symbols or list(NAMES)
    parts = []
    for sym in symbols:
        try:
            h = fetch_headlines(NAMES.get(sym, sym.replace(".NS", "")))
        except Exception as e:
            print(f"skip {sym}: {e}")
            continue
        if h.empty:
            continue
        h["score"] = score_texts(h["title"].tolist())
        g = h.groupby("date")["score"].agg(["mean", "count"]).reset_index()
        g.columns = ["date", "score", "n"]
        g["symbol"] = sym
        parts.append(g)
    new = pd.concat(parts) if parts else pd.DataFrame(columns=["date", "symbol", "score", "n"])
    STORE.parent.mkdir(exist_ok=True)
    if STORE.exists():
        old = pd.read_csv(STORE)
        new["date"] = new["date"].astype(str)
        new = pd.concat([old, new])
    new["date"] = new["date"].astype(str)
    new = new.drop_duplicates(["date", "symbol"], keep="last").sort_values(["symbol", "date"])
    new[["date", "symbol", "score", "n"]].to_csv(STORE, index=False)
    print(f"store: {len(new)} rows, {new['symbol'].nunique()} symbols")
    return new


def load_daily(symbol: str) -> pd.DataFrame:
    """Daily [score, n] for one symbol, indexed by calendar date (empty if none)."""
    if not STORE.exists():
        return pd.DataFrame(columns=["score", "n"])
    s = pd.read_csv(STORE)
    s = s[s["symbol"] == symbol].copy()
    s["date"] = pd.to_datetime(s["date"])
    return s.set_index("date")[["score", "n"]].sort_index()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--update", action="store_true")
    ap.add_argument("--symbols", nargs="*")
    a = ap.parse_args()
    if a.update:
        update_store(a.symbols)
