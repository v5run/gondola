"""Explicit live-model smoke. Uses configured local key; stores sanitized evidence only."""
import argparse
import json
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def api(path, body=None):
    req = Request("http://127.0.0.1:8000/api/rush/" + path,
                  data=None if body is None else json.dumps(body).encode(),
                  headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=30) as response:
        return json.load(response)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("kind", choices=["agent", "lab"])
    args = parser.parse_args()
    start = time.perf_counter()
    created = api(args.kind, {"minute": 12, "forecast_pressure": 1.15} if args.kind == "agent" else {})
    for _ in range(150):
        job = api("jobs/" + created["id"])
        if job["status"] != "running": break
        time.sleep(1)
    path = Path(".local") / f"rush-live-{args.kind}.json"
    path.write_text(json.dumps(job, indent=2), encoding="utf-8")
    result = job.get("result", {})
    print(json.dumps({"id": created["id"], "status": job["status"], "seconds": round(time.perf_counter()-start, 2),
                      "model": result.get("model"), "tools": [e.get("tool") for e in job.get("events", []) if e.get("kind") == "tool"],
                      "receipt": result.get("receipt"), "qualified": result.get("qualification", {}).get("qualified"),
                      "error": job.get("error"), "evidence": str(path)}, indent=2))
    if job["status"] != "done": sys.exit(1)
