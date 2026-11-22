"""PostgreSQL persistence for StockAlgo cloud paper trading.

SQLite is supported for local smoke tests. Render deployment uses DATABASE_URL.
"""
from __future__ import annotations
from datetime import date, datetime, timezone
from pathlib import Path
import json, os
import pandas as pd
from sqlalchemy import create_engine, String, Integer, Float, Boolean, Date, DateTime, LargeBinary, JSON, select, desc, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

def _database_url():
    url = os.getenv("DATABASE_URL", "sqlite:///./stockalgo_cloud.db")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url

URL = _database_url()
connect_args = {"check_same_thread": False} if URL.startswith("sqlite") else {}
engine = create_engine(URL, pool_pre_ping=True, pool_size=2, max_overflow=2, connect_args=connect_args)
Session = sessionmaker(bind=engine, expire_on_commit=False)

class Base(DeclarativeBase): pass



class MarketQuote(Base):
    __tablename__ = "market_quotes"
    symbol: Mapped[str] = mapped_column(String(40), primary_key=True)
    exchange: Mapped[str] = mapped_column(String(8), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

class MarketCandle(Base):
    __tablename__ = "market_candles"
    __table_args__ = (UniqueConstraint("symbol", "exchange", "interval_minutes", "candle_time", name="uq_market_candle"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(40), index=True)
    exchange: Mapped[str] = mapped_column(String(8))
    interval_minutes: Mapped[int] = mapped_column(Integer)
    candle_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float, default=0)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class FundamentalSnapshot(Base):
    __tablename__ = "fundamental_snapshots"
    symbol: Mapped[str] = mapped_column(String(40), primary_key=True)
    company_name: Mapped[str] = mapped_column(String(160), default="")
    sector: Mapped[str] = mapped_column(String(100), default="")
    market_cap_cr: Mapped[float | None] = mapped_column(Float, nullable=True)
    pe: Mapped[float | None] = mapped_column(Float, nullable=True)
    pb: Mapped[float | None] = mapped_column(Float, nullable=True)
    roe: Mapped[float | None] = mapped_column(Float, nullable=True)
    roce: Mapped[float | None] = mapped_column(Float, nullable=True)
    debt_equity: Mapped[float | None] = mapped_column(Float, nullable=True)
    sales_growth_3y: Mapped[float | None] = mapped_column(Float, nullable=True)
    profit_growth_3y: Mapped[float | None] = mapped_column(Float, nullable=True)
    opm: Mapped[float | None] = mapped_column(Float, nullable=True)
    dividend_yield: Mapped[float | None] = mapped_column(Float, nullable=True)
    promoter_holding: Mapped[float | None] = mapped_column(Float, nullable=True)
    pledged_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    interest_coverage: Mapped[float | None] = mapped_column(Float, nullable=True)
    free_cash_flow_cr: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(100), default="user_import")
    period_end: Mapped[str] = mapped_column(String(20), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class SavedScreen(Base):
    __tablename__ = "saved_screens"
    name: Mapped[str] = mapped_column(String(100), primary_key=True)
    definition: Mapped[dict] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class PortfolioState(Base):
    __tablename__ = "portfolio_state"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class Artifact(Base):
    __tablename__ = "artifacts"
    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class Trade(Base):
    __tablename__ = "trades"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    symbol: Mapped[str] = mapped_column(String(40), index=True)
    side: Mapped[str] = mapped_column(String(8))
    qty: Mapped[int] = mapped_column(Integer)
    price: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(String(200), default="")
    pnl: Mapped[float | None] = mapped_column(Float, nullable=True)

class EquityPoint(Base):
    __tablename__ = "equity_points"
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    equity: Mapped[float] = mapped_column(Float)
    cash: Mapped[float] = mapped_column(Float)

class SignalPoint(Base):
    __tablename__ = "signal_points"
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(40), primary_key=True)
    p_up: Mapped[float | None] = mapped_column(Float, nullable=True)
    close: Mapped[float | None] = mapped_column(Float, nullable=True)
    atr: Mapped[float | None] = mapped_column(Float, nullable=True)
    entry: Mapped[bool] = mapped_column(Boolean, default=False)

class NewsPoint(Base):
    __tablename__ = "news_sentiment"
    news_date: Mapped[date] = mapped_column(Date, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(40), primary_key=True)
    score: Mapped[float] = mapped_column(Float)
    count: Mapped[int] = mapped_column(Integer)

class Strategy(Base):
    __tablename__ = "strategies"
    name: Mapped[str] = mapped_column(String(60), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class Control(Base):
    __tablename__ = "controls"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, nullable=False)

class JobRun(Base):
    __tablename__ = "job_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(20))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    message: Mapped[str] = mapped_column(String(2000), default="")

def init_db():
    Base.metadata.create_all(engine)
    with Session.begin() as s:
        if s.get(Control, "kill_switch") is None:
            s.add(Control(key="kill_switch", value={"enabled": False}))

def save_state(payload):
    init_db()
    with Session.begin() as s:
        row = s.get(PortfolioState, 1)
        if row is None: s.add(PortfolioState(id=1, payload=payload, updated_at=datetime.now(timezone.utc)))
        else: row.payload, row.updated_at = payload, datetime.now(timezone.utc)

def load_state():
    init_db()
    with Session() as s:
        row = s.get(PortfolioState, 1)
        return row.payload if row else None

def put_artifact(key, content):
    init_db()
    with Session.begin() as s:
        row = s.get(Artifact, key)
        if row is None: s.add(Artifact(key=key, content=content, updated_at=datetime.now(timezone.utc)))
        else: row.content, row.updated_at = content, datetime.now(timezone.utc)

def get_artifact(key):
    init_db()
    with Session() as s:
        row = s.get(Artifact, key)
        return (row.content, row.updated_at) if row else (None, None)

def save_csv_tables(trades_path="trades.csv", equity_path="equity_paper_nifty50.csv", signals_path="signals_paper_nifty50.csv"):
    init_db()
    with Session.begin() as s:
        p = Path(trades_path)
        if p.exists():
            for r in pd.read_csv(p).fillna("").to_dict("records"):
                oid = str(r.get("order_id", "")).strip()
                if not oid: continue
                row = s.scalar(select(Trade).where(Trade.order_id == oid))
                vals = dict(trade_date=pd.to_datetime(r["date"]).date(), symbol=str(r.get("symbol", "")),
                    side=str(r.get("side", "")), qty=int(float(r.get("qty") or 0)),
                    price=float(r.get("price") or 0), reason=str(r.get("reason", "")),
                    pnl=None if r.get("pnl", "") in ("", None) else float(r["pnl"]))
                if row is None: s.add(Trade(order_id=oid, **vals))
                else:
                    for k,v in vals.items(): setattr(row,k,v)
        p = Path(equity_path)
        if p.exists():
            for r in pd.read_csv(p).to_dict("records"):
                d = pd.to_datetime(r["date"]).date(); row = s.get(EquityPoint, d)
                if row is None: s.add(EquityPoint(trade_date=d, equity=float(r["equity"]), cash=float(r["cash"])))
                else: row.equity, row.cash = float(r["equity"]), float(r["cash"])
        p = Path(signals_path)
        if p.exists():
            for r in pd.read_csv(p).fillna("").to_dict("records"):
                d = pd.to_datetime(r["date"]).date(); sym = str(r["symbol"]); row = s.get(SignalPoint, (d,sym))
                vals = dict(p_up=None if r.get("p_up","")=="" else float(r["p_up"]),
                    close=None if r.get("close","")=="" else float(r["close"]),
                    atr=None if r.get("atr","")=="" else float(r["atr"]),
                    entry=str(r.get("entry","")).lower() in ("true","1"))
                if row is None: s.add(SignalPoint(trade_date=d, symbol=sym, **vals))
                else:
                    for k,v in vals.items(): setattr(row,k,v)

def restore_csv_tables(trades_path="trades.csv", equity_path="equity_paper_nifty50.csv", signals_path="signals_paper_nifty50.csv"):
    init_db()
    with Session() as s:
        trades = s.scalars(select(Trade).order_by(Trade.trade_date, Trade.id)).all()
        pd.DataFrame([{"date":x.trade_date.isoformat(),"symbol":x.symbol,"side":x.side,"qty":x.qty,"price":x.price,"reason":x.reason,"pnl":x.pnl if x.pnl is not None else "","order_id":x.order_id} for x in trades], columns=["date","symbol","side","qty","price","reason","pnl","order_id"]).to_csv(trades_path,index=False)
        eq = s.scalars(select(EquityPoint).order_by(EquityPoint.trade_date)).all()
        pd.DataFrame([{"date":x.trade_date.isoformat(),"equity":x.equity,"cash":x.cash} for x in eq], columns=["date","equity","cash"]).to_csv(equity_path,index=False)
        sig = s.scalars(select(SignalPoint).order_by(SignalPoint.trade_date, SignalPoint.symbol)).all()
        pd.DataFrame([{"date":x.trade_date.isoformat(),"symbol":x.symbol,"p_up":x.p_up,"close":x.close,"atr":x.atr,"entry":x.entry} for x in sig], columns=["date","symbol","p_up","close","atr","entry"]).to_csv(signals_path,index=False)

def save_news_csv(path="data/sentiment.csv"):
    init_db(); p=Path(path)
    if not p.exists(): return
    with Session.begin() as s:
        for r in pd.read_csv(p).to_dict("records"):
            d=pd.to_datetime(r["date"]).date(); sym=str(r["symbol"]); row=s.get(NewsPoint,(d,sym))
            if row is None: s.add(NewsPoint(news_date=d,symbol=sym,score=float(r["score"]),count=int(r["n"])))
            else: row.score,row.count=float(r["score"]),int(r["n"])

def restore_news_csv(path="data/sentiment.csv"):
    init_db(); Path(path).parent.mkdir(parents=True,exist_ok=True)
    with Session() as s:
        rows=s.scalars(select(NewsPoint).order_by(NewsPoint.symbol,NewsPoint.news_date)).all()
        pd.DataFrame([{"date":x.news_date.isoformat(),"symbol":x.symbol,"score":x.score,"n":x.count} for x in rows],columns=["date","symbol","score","n"]).to_csv(path,index=False)

def save_runtime_files(config):
    p=Path(config["state_file"])
    if p.exists(): save_state(json.loads(p.read_text()))
    save_csv_tables(); save_news_csv()
    for key,path in [("model_pooled_h5","models/pooled_h5.joblib"),("fundamentals_cache","data/fundamentals_cache.json")]:
        f=Path(path)
        if f.exists(): put_artifact(key,f.read_bytes())

def restore_runtime_files(config):
    Path("models").mkdir(exist_ok=True); Path("data").mkdir(exist_ok=True)
    state=load_state()
    if state is not None: Path(config["state_file"]).write_text(json.dumps(state,indent=2))
    restore_csv_tables(); restore_news_csv()
    for key,path in [("model_pooled_h5","models/pooled_h5.joblib"),("fundamentals_cache","data/fundamentals_cache.json")]:
        content,_=get_artifact(key)
        if content is not None: Path(path).parent.mkdir(parents=True,exist_ok=True); Path(path).write_bytes(content)
    with Session() as s:
        row=s.get(Control,"kill_switch"); enabled=bool(row.value.get("enabled")) if row else False
    kill=Path(config.get("kill_file","KILL"))
    if enabled: kill.touch()
    elif kill.exists(): kill.unlink()

def model_is_stale(max_age_days=7):
    _,updated=get_artifact("model_pooled_h5")
    if updated is None: return True
    if updated.tzinfo is None: updated=updated.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc)-updated).total_seconds()>max_age_days*86400

def begin_job(task):
    init_db()
    with Session.begin() as s:
        row=JobRun(task=task,status="running",started_at=datetime.now(timezone.utc),message=""); s.add(row); s.flush(); return row.id

def finish_job(job_id,status,message=""):
    with Session.begin() as s:
        row=s.get(JobRun,job_id)
        if row: row.status,row.message,row.finished_at=status,message[:2000],datetime.now(timezone.utc)

def set_kill_switch(enabled):
    init_db()
    with Session.begin() as s:
        row=s.get(Control,"kill_switch")
        if row is None: s.add(Control(key="kill_switch",value={"enabled":bool(enabled)}))
        else: row.value={"enabled":bool(enabled)}

def get_kill_switch():
    init_db()
    with Session() as s:
        row=s.get(Control,"kill_switch"); return bool(row.value.get("enabled")) if row else False

def dashboard_snapshot():
    init_db()
    with Session() as s:
        sr=s.get(PortfolioState,1); state=sr.payload if sr else {"cash":50000,"positions":{},"last_equity":50000,"orders_today":0}
        eq=s.scalars(select(EquityPoint).order_by(desc(EquityPoint.trade_date)).limit(120)).all()
        trades=s.scalars(select(Trade).order_by(desc(Trade.trade_date),desc(Trade.id)).limit(100)).all()
        signals=s.scalars(select(SignalPoint).order_by(desc(SignalPoint.trade_date),SignalPoint.p_up.desc()).limit(50)).all()
        jobs=s.scalars(select(JobRun).order_by(desc(JobRun.started_at)).limit(10)).all()
        return {"state":state,"equity":[{"date":x.trade_date.isoformat(),"equity":x.equity,"cash":x.cash} for x in reversed(eq)],
          "trades":[{"date":x.trade_date.isoformat(),"symbol":x.symbol,"side":x.side,"qty":x.qty,"price":x.price,"reason":x.reason,"pnl":x.pnl,"order_id":x.order_id} for x in trades],
          "signals":[{"date":x.trade_date.isoformat(),"symbol":x.symbol,"p_up":x.p_up,"close":x.close,"atr":x.atr,"entry":x.entry} for x in signals],
          "jobs":[{"id":x.id,"task":x.task,"status":x.status,"started_at":x.started_at.isoformat(),"finished_at":x.finished_at.isoformat() if x.finished_at else None,"message":x.message} for x in jobs],
          "kill_switch":get_kill_switch()}

def list_strategies():
    init_db()
    with Session() as s: return [x.name for x in s.scalars(select(Strategy).order_by(Strategy.name)).all()]

def save_strategy(name,payload):
    init_db()
    with Session.begin() as s:
        row=s.get(Strategy,name)
        if row is None: s.add(Strategy(name=name,payload=payload,updated_at=datetime.now(timezone.utc)))
        else: row.payload,row.updated_at=payload,datetime.now(timezone.utc)

def get_strategy(name):
    init_db()
    with Session() as s:
        row=s.get(Strategy,name); return row.payload if row else None


def save_market_quote(symbol, exchange, payload, fetched_at=None):
    init_db()
    fetched_at = fetched_at or datetime.now(timezone.utc)
    with Session.begin() as session:
        row = session.get(MarketQuote, (symbol, exchange))
        if row is None:
            session.add(MarketQuote(symbol=symbol, exchange=exchange, payload=payload, fetched_at=fetched_at))
        else:
            row.payload, row.fetched_at = payload, fetched_at

def latest_market_quotes(symbols=None):
    init_db()
    with Session() as session:
        rows = session.scalars(select(MarketQuote).order_by(MarketQuote.symbol)).all()
        if symbols:
            wanted = set(symbols)
            rows = [r for r in rows if r.symbol in wanted]
        return [{"symbol":r.symbol,"exchange":r.exchange,"quote":r.payload,"fetched_at":r.fetched_at.isoformat()} for r in rows]

def save_market_candles(symbol, exchange, interval_minutes, candles, fetched_at=None):
    init_db()
    fetched_at = fetched_at or datetime.now(timezone.utc)
    saved = 0
    with Session.begin() as session:
        for candle in candles or []:
            if isinstance(candle, dict):
                ts = candle.get("timestamp") or candle.get("time")
                vals = [candle.get(k) for k in ("open","high","low","close","volume")]
            else:
                if len(candle) < 6: continue
                ts, *vals = candle[:6]
            try:
                ts = datetime.fromtimestamp(float(ts), tz=timezone.utc)
                o,h,l,c,v = [float(x or 0) for x in vals]
            except (TypeError, ValueError, OverflowError):
                continue
            row = session.scalar(select(MarketCandle).where(
                MarketCandle.symbol==symbol, MarketCandle.exchange==exchange,
                MarketCandle.interval_minutes==interval_minutes, MarketCandle.candle_time==ts))
            if row is None:
                session.add(MarketCandle(symbol=symbol,exchange=exchange,interval_minutes=interval_minutes,
                    candle_time=ts,open=o,high=h,low=l,close=c,volume=v,fetched_at=fetched_at))
            else:
                row.open,row.high,row.low,row.close,row.volume,row.fetched_at=o,h,l,c,v,fetched_at
            saved += 1
    return saved

def latest_market_candles(symbol, exchange="NSE", interval_minutes=5, limit=500):
    init_db()
    with Session() as session:
        rows = session.scalars(select(MarketCandle).where(
            MarketCandle.symbol==symbol, MarketCandle.exchange==exchange,
            MarketCandle.interval_minutes==interval_minutes
        ).order_by(desc(MarketCandle.candle_time)).limit(min(max(limit,1),2000))).all()
        return [{"timestamp":r.candle_time.isoformat(),"open":r.open,"high":r.high,
            "low":r.low,"close":r.close,"volume":r.volume} for r in reversed(rows)]


FUNDAMENTAL_FIELDS = {
    "market_cap_cr","pe","pb","roe","roce","debt_equity","sales_growth_3y",
    "profit_growth_3y","opm","dividend_yield","promoter_holding","pledged_percent",
    "current_ratio","interest_coverage","free_cash_flow_cr"
}
def upsert_fundamentals(rows, source="user_import"):
    init_db(); count=0
    with Session.begin() as session:
        for raw in rows:
            symbol=str(raw.get("symbol","")).strip().upper()
            if not symbol: continue
            data={"company_name":str(raw.get("company_name",""))[:160],
                  "sector":str(raw.get("sector",""))[:100],"source":source,
                  "period_end":str(raw.get("period_end",""))[:20],
                  "updated_at":datetime.now(timezone.utc)}
            for key in FUNDAMENTAL_FIELDS:
                value=raw.get(key)
                if value in (None,""): data[key]=None
                else:
                    try: data[key]=float(value)
                    except (TypeError,ValueError): data[key]=None
            row=session.get(FundamentalSnapshot,symbol)
            if row is None: session.add(FundamentalSnapshot(symbol=symbol,**data))
            else:
                for key,value in data.items(): setattr(row,key,value)
            count+=1
    return count

def list_fundamentals():
    init_db()
    with Session() as session:
        rows=session.scalars(select(FundamentalSnapshot).order_by(FundamentalSnapshot.symbol)).all()
        return [{k:getattr(r,k) for k in ["symbol","company_name","sector","market_cap_cr","pe","pb","roe","roce","debt_equity","sales_growth_3y","profit_growth_3y","opm","dividend_yield","promoter_holding","pledged_percent","current_ratio","interest_coverage","free_cash_flow_cr","source","period_end","updated_at"]} for r in rows]

def save_screen(name, definition):
    init_db()
    with Session.begin() as session:
        row=session.get(SavedScreen,name)
        if row is None: session.add(SavedScreen(name=name,definition=definition,updated_at=datetime.now(timezone.utc)))
        else: row.definition=definition; row.updated_at=datetime.now(timezone.utc)

def list_screens():
    init_db()
    with Session() as session:
        return [{"name":r.name,"definition":r.definition,"updated_at":r.updated_at.isoformat()} for r in session.scalars(select(SavedScreen).order_by(SavedScreen.name)).all()]
