"""PostgreSQL persistence for StockAlgo cloud paper trading.

SQLite is supported for local smoke tests. Render deployment uses DATABASE_URL.
"""
from __future__ import annotations
from datetime import date, datetime, timezone
from pathlib import Path
import json, os
import pandas as pd
from sqlalchemy import create_engine, String, Integer, Float, Boolean, Date, DateTime, LargeBinary, JSON, select, desc
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
