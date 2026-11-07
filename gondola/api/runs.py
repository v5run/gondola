"""Background runs with replayable event logs, streamed to the browser as Server-Sent Events."""
from __future__ import annotations

import json
import threading
import time
import uuid


class Run:
    def __init__(self, kind: str):
        self.id = f"{kind}-{uuid.uuid4().hex[:10]}"
        self.kind = kind
        self.events: list[tuple[str, dict]] = []
        self.done = False
        self.lock = threading.Lock()
        self.inbox: dict = {}  # messages from the client (e.g. a recount)
        self.created = time.time()

    def emit(self, name: str, payload: dict):
        with self.lock:
            self.events.append((name, payload))
            if name == "done":
                self.done = True


RUNS: dict[str, Run] = {}


def new_run(kind: str) -> Run:
    r = Run(kind)
    RUNS[r.id] = r
    # keep memory bounded
    if len(RUNS) > 200:
        for k in sorted(RUNS, key=lambda k: RUNS[k].created)[:50]:
            RUNS.pop(k, None)
    return r


def sse_format(name: str, payload: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(payload, default=str)}\n\n"


def stream(run: Run, poll: float = 0.05, timeout: float = 900):
    """Yield every event so far, then new ones until `done` (late subscribers get the full history)."""
    i = 0
    start = time.time()
    while True:
        with run.lock:
            batch = run.events[i:]
            i += len(batch)
            finished = run.done
        for name, payload in batch:
            yield sse_format(name, payload)
        if finished and not batch:
            return
        if finished:
            continue
        if time.time() - start > timeout:
            yield sse_format("done", {"status": "timeout"})
            return
        time.sleep(poll)
