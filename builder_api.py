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
from pydantic import BaseModel, Field, field_validator, model_validator

import indicators as I
import predictor as P

app = FastAPI(title="Strategy Builder")
STRAT_DIR = Path("strategies")
HERE = Path(__file__).parent


class Spec(BaseModel):
    id: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z][A-Za-z0-9_]*$")
    type: str
    params: dict = Field(default_factory=dict)

    @field_validator("type")
    @classmethod
    def supported_type(cls, value):
        if value not in I.REGISTRY:
            raise ValueError(f"Unsupported indicator: {value}")
        return value

    @field_validator("params")
    @classmethod
    def valid_params(cls, value):
        clean = {}
        for key, raw in value.items():
            try:
                number = float(raw)
            except (TypeError, ValueError):
                raise ValueError(f"Indicator parameter '{key}' must be numeric")
            if not np.isfinite(number) or number <= 0:
                raise ValueError(f"Indicator parameter '{key}' must be greater than zero")
            clean[key] = number
        return clean


class Block(BaseModel):
    logic: str = "AND"
    rules: list[dict] = Field(default_factory=list)

    @field_validator("logic")
    @classmethod
    def valid_logic(cls, value):
        value = value.upper()
        if value not in {"AND", "OR"}:
            raise ValueError("Rule logic must be AND or OR")
        return value

    @field_validator("rules")
    @classmethod
    def valid_rules(cls, rules):
        for index, rule in enumerate(rules, 1):
            if not isinstance(rule, dict):
                raise ValueError(f"Rule {index} must be an object")
            if not str(rule.get("left", "")).strip() or not str(rule.get("right", "")).strip():
                raise ValueError(f"Rule {index}: both left and right operands are required")
            if rule.get("op") not in {">", "<", "crosses_above", "crosses_below"}:
                raise ValueError(f"Rule {index}: unsupported comparison operator")
        return rules


class RunReq(BaseModel):
    symbol: str = Field(default="RELIANCE.NS", min_length=1, max_length=40)
    period: str = "2y"
    interval: str = "1d"
    indicators: list[Spec] = Field(default_factory=list)
    entry: Block = Field(default_factory=Block)
    exit: Block = Field(default_factory=Block)
    cost: float = Field(default=0.0005, ge=0, le=0.05)
    stop_pct: float = Field(default=0.0, ge=0, le=99)

    @field_validator("period")
    @classmethod
    def valid_period(cls, value):
        if value not in {"1mo", "3mo", "6mo", "1y", "2y", "5y", "10y"}:
            raise ValueError("Choose a supported history period")
        return value

    @field_validator("interval")
    @classmethod
    def valid_interval(cls, value):
        if value not in {"1d", "1h", "15m", "5m"}:
            raise ValueError("Choose a supported timeframe")
        return value

    @model_validator(mode="after")
    def compatible_history(self):
        if self.interval in {"15m", "5m"} and self.period != "1mo":
            raise ValueError("Yahoo Finance 5m/15m history is limited: choose 1 month.")
        if self.interval == "1h" and self.period in {"5y", "10y"}:
            raise ValueError("Hourly data history is limited: choose 2 years or less.")
        return self


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
        ids = [item["id"] for item in specs]
        if len(ids) != len(set(ids)):
            raise ValueError("Indicator names must be unique. Remove or rename duplicate indicators.")
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
