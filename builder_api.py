"""
Backend for the drag-and-drop indicator/strategy builder.

    pip install fastapi uvicorn yfinance pandas numpy
    uvicorn builder_api:app --reload        # then open http://127.0.0.1:8000

Use symbol "SYNTH" to work offline with synthetic data.
Strategies are saved as JSON in ./strategies so execution code can load them later.
"""
import json
import re
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

import indicators as I
import predictor as P

app = FastAPI(title="Strategy Builder")
STRAT_DIR = Path("strategies")
HERE = Path(__file__).parent


class Spec(BaseModel):
    id: str
    type: str
    params: dict = {}


class Block(BaseModel):
    logic: str = "AND"
    rules: list[dict] = []


class RunReq(BaseModel):
    symbol: str = "RELIANCE.NS"
    period: str = "2y"
    interval: str = "1d"
    indicators: list[Spec] = []
    entry: Block = Block()
    exit: Block = Block()
    cost: float = 0.0005
    stop_pct: float = 0.0


@lru_cache(maxsize=32)
def _load(symbol, period, interval):
    if symbol == "SYNTH":
        return P.synthetic_data(800)
    return P.load_data(P.Config(symbol=symbol, period=period, interval=interval))


def _t(ts, interval):
    return ts.strftime("%Y-%m-%d") if interval == "1d" else int(pd.Timestamp(ts).timestamp())


def _series(s, interval):
    s = s.dropna()
    return [{"time": _t(i, interval), "value": round(float(v), 4)} for i, v in s.items()]


@app.get("/")
def index():
    return FileResponse(HERE / "builder.html")


@app.get("/api/indicators")
def indicators():
    return I.meta()


@app.post("/api/run")
def run(req: RunReq):
    try:
        df = _load(req.symbol, req.period, req.interval)
        if len(df) < 60:
            raise ValueError("Not enough data returned for this symbol/period")
        specs = [s.model_dump() for s in req.indicators]
        series = I.compute(df, specs)
        ps = I.oof_series(req.symbol).reindex(df.index)
        if ps.notna().any():
            series["p_up"] = ps
        elif "p_up" in req.entry.model_dump_json() + req.exit.model_dump_json():
            raise ValueError("p_up unavailable for this symbol/interval (daily NSE symbols only). "
                             "Run `python multi.py train` first; it writes data/oof_pup.csv.")
        entry = I.eval_rules(req.entry.model_dump(), df, series)
        exit_ = I.eval_rules(req.exit.model_dump(), df, series)
        bt = I.backtest(df, entry, exit_, req.cost, req.interval, req.stop_pct)
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # data fetch problems etc.
        raise HTTPException(502, f"{type(e).__name__}: {e}")
    meta = I.meta()
    return {
        "candles": [{"time": _t(i, req.interval), "open": r.open, "high": r.high, "low": r.low, "close": r.close}
                    for i, r in df.iterrows()],
        "series": {k: _series(v, req.interval) for k, v in series.items()},
        "overlay": {s["id"]: meta[s["type"]]["overlay"] for s in specs},
        "markers": [{"time": _t(t, req.interval), "kind": k} for t, k in bt["marks"]],
        "equity": _series(bt["equity"], req.interval),
        "metrics": bt["metrics"],
        "latest": {"entry_now": bool(entry.iloc[-1]), "exit_now": bool(exit_.iloc[-1])},
    }


@app.get("/api/strategies")
def list_strategies():
    return sorted(p.stem for p in STRAT_DIR.glob("*.json")) if STRAT_DIR.exists() else []


@app.post("/api/strategies/{name}")
def save_strategy(name: str, req: RunReq):
    if not re.fullmatch(r"[\w\- ]{1,50}", name):
        raise HTTPException(400, "Invalid name")
    STRAT_DIR.mkdir(exist_ok=True)
    (STRAT_DIR / f"{name}.json").write_text(req.model_dump_json(indent=1))
    return {"saved": name}


@app.get("/api/strategies/{name}")
def load_strategy(name: str):
    f = STRAT_DIR / f"{name}.json"
    if not re.fullmatch(r"[\w\- ]{1,50}", name) or not f.exists():
        raise HTTPException(404, "Not found")
    return json.loads(f.read_text())
