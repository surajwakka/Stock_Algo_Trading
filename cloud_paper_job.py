"""Scheduled cloud paper-trading entry point. No broker imports or live orders."""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import multi as M
import local_runner as L


def main():
    cfg = L.read_config()
    if cfg.get("mode") != "paper_only" or cfg.get("live_trading_enabled") is not False:
        raise SystemExit("Safety stop: cloud runner requires paper_only and live_trading_enabled=false")
    if os.getenv("ALLOW_LIVE_ORDERS", "NO").strip().upper() == "YES":
        raise SystemExit("Safety stop: ALLOW_LIVE_ORDERS=YES is forbidden in this deployment")
    if os.getenv("CONFIRM_LIVE", "NO").strip().upper() == "YES":
        raise SystemExit("Safety stop: CONFIRM_LIVE=YES is forbidden in this deployment")

    status_path = Path("cloud_run_status.json")
    status = {
        "mode": "paper_only",
        "live_orders_enabled": False,
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "running",
    }
    status_path.write_text(json.dumps(status, indent=2))
    try:
        model_cfg = L.model_config(cfg)
        model_file = M.model_path(model_cfg, False)
        if not model_file.exists():
            print("No persisted pooled model found; training initial NIFTY 50 model.", flush=True)
            L.train_model(force=False)
        else:
            print(f"Using persisted model: {model_file}", flush=True)

        print("Refreshing daily news sentiment...", flush=True)
        L.update_news()
        print("Running idempotent paper-trading cycle...", flush=True)
        L.paper_run()
        status.update({
            "status": "success",
            "finished_at_utc": datetime.now(timezone.utc).isoformat(),
            "live_orders_enabled": False,
        })
        status_path.write_text(json.dumps(status, indent=2))
    except Exception as exc:
        status.update({
            "status": "failed",
            "finished_at_utc": datetime.now(timezone.utc).isoformat(),
            "error": f"{type(exc).__name__}: {exc}",
            "live_orders_enabled": False,
        })
        status_path.write_text(json.dumps(status, indent=2))
        raise


if __name__ == "__main__":
    main()
