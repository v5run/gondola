"""Tests run on a frozen store clock: after close on the last demo night (the full day counts), unless a test sets its
own GONDOLA_NOW. See gondola/now.py."""
import os

os.environ.setdefault("GONDOLA_NOW", "2026-11-05T23:30:00")
os.environ.setdefault("GONDOLA_CLOCK", "frozen")

# Starlette's in-process TestClient uses this synthetic host. Never enable it in deployments.
os.environ.setdefault("GONDOLA_ADDITIONAL_HOSTS", "testserver")
