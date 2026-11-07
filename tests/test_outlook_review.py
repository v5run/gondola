"""Cheap regressions for forecast provenance, with no model or forecasting run."""
from gondola.future import horizon as H


def test_agent_issuance_keeps_its_observation_cut(monkeypatch):
    from gondola import ledger as module
    captured = []
    class Capture:
        def extend(self, rows):
            captured.extend(rows)
    monkeypatch.setattr(module, "ledger", Capture)
    H.issue_events([{"date": "2026-11-06", "horizon": 1, "p10": 80, "p50": 105, "p90": 130,
                     "rush": None, "outlook": {"run_id": "checked-run", "uncertainty": "scenario",
                     "issue_day": "2026-11-05", "issue_minute": 1170}}], "2026-11-05")
    assert len(captured) == 1
    assert captured[0]["ts"] == "2026-11-05T19:30:00"
    assert captured[0]["payload"]["outlook"]["issue_minute"] == 1170


def test_baseline_issuance_keeps_existing_morning_timestamp(monkeypatch):
    from gondola import ledger as module
    captured = []
    class Capture:
        def extend(self, rows):
            captured.extend(rows)
    monkeypatch.setattr(module, "ledger", Capture)
    H.issue_events([{"date": "2026-11-06", "horizon": 1, "p10": 80, "p50": 100, "p90": 120,
                     "rush": None, "outlook": None}], "2026-11-05")
    assert len(captured) == 1
    assert captured[0]["ts"] == "2026-11-05T00:00:00"


def test_snapshot_retention_preserves_save_order_when_wall_clock_ties(monkeypatch, tmp_path):
    from gondola.future import outlook as O
    monkeypatch.setenv("GONDOLA_FUTURE_DIR", str(tmp_path))
    monkeypatch.setattr(O, "HISTORY_LIMIT", 2)
    monkeypatch.setattr(O.time, "time_ns", lambda: 123)
    sequences = []
    for marker in range(3):
        O._save("2026-11-05", {"status": "fallback", "marker": marker})
        sequences.append(O.read("2026-11-05")["sequence"])
    assert len(set(sequences)) == 3
    assert sequences == sorted(sequences)
    import json
    records = [json.loads(p.read_text(encoding="utf-8"))
               for p in (O._path("2026-11-05").parent / "history" / "2026-11-05").glob("*.json")]
    assert sorted(r["marker"] for r in records) == [1, 2]
