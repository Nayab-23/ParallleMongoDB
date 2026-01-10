"""
Minimal admin contract smoke test.
Usage:
  ADMIN_BASE=http://localhost:8000/api/admin ADMIN_TOKEN=<bearer> python scripts/admin_smoke.py
"""

import os
import sys
import json
import requests

ADMIN_BASE = os.getenv("ADMIN_BASE", "http://localhost:8000/api/admin")
TOKEN = os.getenv("ADMIN_TOKEN")
HEADERS = {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}


def check(path):
    url = f"{ADMIN_BASE}{path}"
    resp = requests.get(url, headers=HEADERS, timeout=10)
    try:
        data = resp.json()
    except Exception:
        print(f"[FAIL] {path}: non-JSON response status {resp.status_code}")
        return False
    ok = isinstance(data, dict) and all(k in data for k in ["success", "data", "error", "debug", "request_id"])
    print(f"[{'OK' if ok else 'FAIL'}] {path} status={resp.status_code} request_id={data.get('request_id')}")
    if not ok:
        print(json.dumps(data, indent=2))
    return ok


def main():
    paths = [
        "/_health",
        "/_routes",
        "/timeline-debug/test@example.com",
        "/collaboration-debug?users=test@example.com&users=test2@example.com",
        "/waitlist",
        "/waitlist/stats",
        "/collaboration-graph",
    ]
    failures = 0
    for p in paths:
        if not check(p):
            failures += 1

    # Stage detail check (best effort)
    check("/timeline-debug/test@example.com/stage/stage_final")

    # Probe and audit (POST)
    try:
        resp = requests.post(f"{ADMIN_BASE}/timeline/probe?user_email=test@example.com", headers=HEADERS, timeout=10)
        data = resp.json()
        ok = isinstance(data, dict) and "success" in data
        print(f"[{'OK' if ok else 'FAIL'}] POST /timeline/probe request_id={data.get('request_id')}")
    except Exception as exc:
        print(f"[FAIL] /timeline/probe error {exc}")
        failures += 1

    try:
        resp = requests.post(f"{ADMIN_BASE}/collaboration-audit/run", headers=HEADERS, timeout=10)
        data = resp.json()
        ok = isinstance(data, dict) and "success" in data
        print(f"[{'OK' if ok else 'FAIL'}] POST /collaboration-audit/run request_id={data.get('request_id')}")
    except Exception as exc:
        print(f"[FAIL] /collaboration-audit/run error {exc}")
        failures += 1

    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
