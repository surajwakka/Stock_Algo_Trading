"""Read paper ledger files locally or from a GitHub state branch (dashboard only)."""
import os
from pathlib import Path

import requests


def read_text(relative_path: str):
    repo = os.getenv("STATE_GITHUB_REPOSITORY", "").strip()
    branch = os.getenv("STATE_GITHUB_BRANCH", "paper-state").strip()
    if not repo:
        path = Path(relative_path)
        return path.read_text() if path.exists() else None

    url = f"https://raw.githubusercontent.com/{repo}/{branch}/{relative_path}"
    headers = {"Accept": "text/plain", "User-Agent": "StockAlgo-Paper-Dashboard"}
    token = os.getenv("STATE_GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = requests.get(url, headers=headers, timeout=15)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.text
