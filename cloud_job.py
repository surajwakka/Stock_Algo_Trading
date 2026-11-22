"""Scheduled cloud paper runner. Persists portfolio, trades and model in PostgreSQL."""
import argparse, os, traceback
from pathlib import Path
import cloud_store as DB
import local_runner as LR
import multi as M

def assert_paper_only():
    cfg=LR.read_config()
    if cfg.get("mode")!="paper_only" or cfg.get("live_trading_enabled") is not False:
        raise SystemExit("Refusing to run: config must be paper_only and live_trading_enabled=false.")
    if os.getenv("PAPER_ONLY","true").lower()!="true": raise SystemExit("PAPER_ONLY must be true.")
    if os.getenv("LIVE_TRADING_ENABLED","false").lower()!="false": raise SystemExit("LIVE_TRADING_ENABLED must be false.")
    return cfg

def run(task="daily",force=False):
    DB.init_db(); job_id=DB.begin_job(task)
    try:
        cfg=assert_paper_only(); DB.restore_runtime_files(cfg)
        if task in ("news","daily"):
            LR.update_news(); DB.save_news_csv()
        if task=="train" or (task=="daily" and (force or DB.model_is_stale(7))):
            print("Training/retraining pooled model. Live execution remains disabled.")
            LR.train_model(force=True)
            model_path=M.model_path(LR.model_config(cfg),False)
            DB.put_artifact("model_pooled_h5",Path(model_path).read_bytes())
        if task in ("paper","daily"):
            content,_=DB.get_artifact("model_pooled_h5")
            if content is None: raise SystemExit("No model in PostgreSQL. Run cloud_job.py train first.")
            model_path=M.model_path(LR.model_config(cfg),False)
            Path(model_path).parent.mkdir(parents=True,exist_ok=True); Path(model_path).write_bytes(content)
            LR.paper_run()
        DB.save_runtime_files(cfg)
        DB.finish_job(job_id,"succeeded",f"{task} completed; paper-only mode enforced.")
        print(f"Job {job_id} completed: {task}")
    except BaseException as exc:
        DB.finish_job(job_id,"failed",f"{type(exc).__name__}: {exc}")
        traceback.print_exc(); raise

def main():
    p=argparse.ArgumentParser(); p.add_argument("task",choices=["daily","train","news","paper"]); p.add_argument("--force",action="store_true")
    a=p.parse_args(); run(a.task,a.force)
if __name__=="__main__": main()
