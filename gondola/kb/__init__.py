"""Knowledge base: small, typed, evidence-backed facts and rules that carry what was learned from one day to the next.

Design: docs/architecture/TRI_WORKFLOW.md section 6. SQLite at out/kb.sqlite (override with GONDOLA_KB_DB; follows
gondola.pipeline.OUT like the ledger). Items follow design section 6.2:

    {id, kind, scope, statement, effect, evidence, n, confidence, status, created, last_confirmed, source, ...}

kinds: event_effect | item_behavior | capacity | pricing | ops_rule | action_item
status: proposed (n < 3) | needs_approval (behavior-changing, waiting for the manager) | active | retired | rejected

How an insight becomes memory (`propose`):
  1. `validate` RECOMPUTES the claimed number from the data (gondola.kb.measures) and rejects anything it can't
     reproduce within tolerance; the stored number is always the recomputed one. n >= 3 for active.
  2. Behavior-changing kinds (capacity, ops_rule, or an item with `changes`) wait in needs_approval for the manager.
  3. Same slot (kind + metric + scope) already known: a matching number re-confirms it (n, evidence, last_confirmed
     refresh); a different number is a conflict: the newer evidence with the higher n wins and the old item is retired
     with `superseded_by`.
  4. `decay(as_of)`: confidence drops 15% per full week without re-confirmation; below 0.3 it is retired.
     `compact()` merges duplicates.
`retrieve(scope, kinds, k, budget_tokens)` returns whole items ranked by scope match, then confidence x recency, never
more than the token budget (~len(json)/4 per item).
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
import threading
from datetime import date as Date
from pathlib import Path

import pandas as pd

from ..ledger import out_dir

KINDS = ["event_effect", "item_behavior", "capacity", "pricing", "ops_rule", "action_item"]
BEHAVIOR_CHANGING = {"capacity", "ops_rule"}
MIN_N = 3
DECAY_PER_WEEK = 0.85
RETIRE_BELOW = 0.3
_LOCK = threading.Lock()


def db_path() -> Path:
    p = os.getenv("GONDOLA_KB_DB")
    return Path(p) if p else out_dir() / "kb.sqlite"


def tokens(obj) -> int:
    """Token estimate used for every budget: ~4 characters per token of compact JSON."""
    s = obj if isinstance(obj, str) else json.dumps(obj, separators=(",", ":"), default=str)
    return (len(s) + 3) // 4


def _norm(v):
    if isinstance(v, str):
        return v.strip().lower()
    return v


def slot_of(item: dict) -> str:
    """Identity of what an item is about: kind + metric + normalized scope (statement wording does not matter)."""
    sc = {k: _norm(v) for k, v in sorted((item.get("scope") or {}).items()) if v not in (None, "", "all")}
    if item.get("kind") == "action_item":
        return f"action_item|{(item.get('measure') or {}).get('metric')}|{json.dumps(sc, sort_keys=True)}|{_norm(item.get('topic') or '')}"
    m = (item.get("effect") or {}).get("metric")
    w = (item.get("effect") or {}).get("window")
    return f"{item.get('kind')}|{m}|{w}|{json.dumps(sc, sort_keys=True)}"


def confidence_for(n: int, agreement: float | None = 1.0) -> float:
    return round(min(0.95, 0.4 + 0.1 * n) * (agreement if agreement is not None else 1.0), 2)


class KB:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._con() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS items (id TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL,
                         slot TEXT NOT NULL, created TEXT, last_confirmed TEXT, confidence REAL, body TEXT NOT NULL)""")
            c.execute("CREATE INDEX IF NOT EXISTS ix_slot ON items(slot, status)")
            c.execute("""CREATE TABLE IF NOT EXISTS log (seq INTEGER PRIMARY KEY AUTOINCREMENT, as_of TEXT, item_id TEXT,
                         op TEXT, detail TEXT)""")
            c.execute("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)")

    @contextmanager
    def _con(self):
        c = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        try:
            c.execute("PRAGMA journal_mode=WAL")
            with c:  # Commit/rollback before releasing the Windows file handle.
                yield c
        finally:
            c.close()

    # ---------------------------------------------------------------- storage
    def _next_id(self, c) -> str:
        r = c.execute("SELECT v FROM meta WHERE k = 'seq'").fetchone()
        n = int(r[0]) + 1 if r else 1
        c.execute("INSERT OR REPLACE INTO meta(k, v) VALUES ('seq', ?)", (str(n),))
        return f"kb-{n:04d}"

    def save(self, item: dict, op: str = "update", as_of: str | None = None, detail: dict | None = None) -> dict:
        with _LOCK, self._con() as c:
            if not item.get("id"):
                item["id"] = self._next_id(c)
            c.execute("INSERT OR REPLACE INTO items(id, kind, status, slot, created, last_confirmed, confidence, body) "
                      "VALUES (?,?,?,?,?,?,?,?)",
                      (item["id"], item["kind"], item["status"], slot_of(item), item.get("created"),
                       item.get("last_confirmed"), item.get("confidence"), json.dumps(item, default=str)))
            c.execute("INSERT INTO log(as_of, item_id, op, detail) VALUES (?,?,?,?)",
                      (as_of, item["id"], op, json.dumps(detail or {}, default=str)))
        return item

    def get(self, id: str) -> dict | None:
        with self._con() as c:
            r = c.execute("SELECT body FROM items WHERE id = ?", (id,)).fetchone()
        return json.loads(r[0]) if r else None

    def list(self, status: str | list[str] | None = None, kind: str | list[str] | None = None) -> list[dict]:
        where, args = [], []
        for col, v in (("status", status), ("kind", kind)):
            if v:
                vs = [v] if isinstance(v, str) else list(v)
                where.append(f"{col} IN ({','.join('?' * len(vs))})"); args += vs
        sql = "SELECT body FROM items" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY id"
        with self._con() as c:
            return [json.loads(r[0]) for r in c.execute(sql, args).fetchall()]

    def by_slot(self, slot: str, statuses=("active", "needs_approval", "proposed")) -> list[dict]:
        with self._con() as c:
            rows = c.execute(f"SELECT body FROM items WHERE slot = ? AND status IN ({','.join('?' * len(statuses))}) ORDER BY id",
                             [slot, *statuses]).fetchall()
        return [json.loads(r[0]) for r in rows]

    def history(self, item_id: str | None = None, as_of: str | None = None, limit: int = 200) -> list[dict]:
        where, args = [], []
        if item_id:
            where.append("item_id = ?"); args.append(item_id)
        if as_of:
            where.append("as_of = ?"); args.append(as_of)
        sql = "SELECT seq, as_of, item_id, op, detail FROM log" + (" WHERE " + " AND ".join(where) if where else "")
        with self._con() as c:
            rows = c.execute(sql + f" ORDER BY seq DESC LIMIT {int(limit)}", args).fetchall()
        return [{"seq": r[0], "as_of": r[1], "item_id": r[2], "op": r[3], "detail": json.loads(r[4])} for r in rows]

    def clear(self) -> None:
        with _LOCK, self._con() as c:
            c.execute("DELETE FROM items"); c.execute("DELETE FROM log"); c.execute("DELETE FROM meta")

    # ---------------------------------------------------------------- lifecycle
    def propose(self, item: dict, as_of: str | None = None, db=None, led=None, source: str | None = None) -> dict:
        """Validate and file a proposed item. Returns {ok, op, item, reason, validation}.
        op: add | confirm | supersede | rejected | conflict_kept."""
        from .validate import validate, same_value, DB
        item = json.loads(json.dumps(item, default=str))  # never mutate the caller's dict
        as_of = as_of or str(Date.today())
        item.setdefault("source", source or "review-agent")
        v = validate(item, as_of=as_of, db=db or DB, led=led)
        if not v["ok"]:
            rej = {**item, "status": "rejected", "rejected_reason": v["reason"], "created": as_of, "validation": v}
            self._log_only(rej, as_of)
            return {"ok": False, "op": "rejected", "item": rej, "reason": v["reason"], "validation": v}
        new = v["item"]
        same = [x for x in self.by_slot(slot_of(new)) if x["kind"] == new["kind"]]
        if not same:
            new["created"] = as_of
            self.save(new, "add", as_of, {"validation": _brief(v)})
            return {"ok": True, "op": "add", "item": new, "reason": None, "validation": v}
        old = max(same, key=lambda x: (x.get("n") or 0, x.get("last_confirmed") or ""))
        if same_value(old, new):
            if as_of < (old.get("last_confirmed") or ""):  # an older day replayed: never move memory backwards
                return {"ok": True, "op": "confirm", "item": old, "reason": "already confirmed later", "validation": v}
            # re-confirmation: refresh the existing item with the fresh evidence
            old.update({k: new[k] for k in ("effect", "evidence", "n", "measure", "statement", "validation") if k in new})
            old["last_confirmed"] = as_of
            old["base_confidence"] = old["confidence"] = new["confidence"]
            if old["status"] == "proposed" and new["status"] != "proposed":
                old["status"] = new["status"]
            old["confirmations"] = int(old.get("confirmations", 0)) + 1
            self.save(old, "confirm", as_of, {"validation": _brief(v)})
            return {"ok": True, "op": "confirm", "item": old, "reason": None, "validation": v}
        # conflict: newer evidence with the higher n wins
        if (new.get("n") or 0) >= (old.get("n") or 0):
            new["created"] = as_of
            new["supersedes"] = old["id"]
            self.save(new, "add", as_of, {"validation": _brief(v), "supersedes": old["id"]})
            self.retire(old["id"], f"superseded by {new['id']} (n {new.get('n')} vs {old.get('n')})", as_of, superseded_by=new["id"])
            return {"ok": True, "op": "supersede", "item": new, "reason": f"replaces {old['id']}", "validation": v}
        self._log_only({**new, "status": "rejected", "rejected_reason": f"conflicts with {old['id']} which has more evidence"}, as_of)
        return {"ok": False, "op": "conflict_kept", "item": old, "reason": f"conflicts with {old['id']} (n {old.get('n')} > {new.get('n')})",
                "validation": v}

    def _log_only(self, item: dict, as_of: str) -> None:
        with _LOCK, self._con() as c:
            c.execute("INSERT INTO log(as_of, item_id, op, detail) VALUES (?,?,?,?)",
                      (as_of, item.get("id"), "rejected", json.dumps({"statement": item.get("statement"), "kind": item.get("kind"),
                                                                      "reason": item.get("rejected_reason"),
                                                                      "claimed": item.get("effect") or item.get("measure")}, default=str)))

    def approve(self, id: str, as_of: str | None = None, by: str = "manager") -> dict | None:
        it = self.get(id)
        if not it:
            return None
        if it["status"] in ("needs_approval", "proposed"):
            if it["status"] == "proposed" and (it.get("n") or 0) < MIN_N:
                it["approved_note"] = f"approved with n={it.get('n')} (< {MIN_N})"
            it["status"] = "active"
            it["approved_by"], it["approved_on"] = by, as_of or str(Date.today())
            self.save(it, "approve", as_of, {"by": by})
        return it

    def retire(self, id: str, reason: str = "retired by manager", as_of: str | None = None,
               superseded_by: str | None = None) -> dict | None:
        it = self.get(id)
        if not it:
            return None
        it["status"] = "retired"
        it["retired_on"], it["retired_reason"] = as_of or str(Date.today()), reason
        if superseded_by:
            it["superseded_by"] = superseded_by
        self.save(it, "retire", as_of, {"reason": reason, "superseded_by": superseded_by})
        return it

    def decay(self, as_of: str) -> dict:
        """Confidence = confidence at last confirmation x 0.85 per full week since; retire below 0.3. Idempotent."""
        changed, retired = 0, []
        for it in self.list(["active", "needs_approval", "proposed"]):
            if it["kind"] == "action_item":
                continue
            base = it.get("base_confidence", it.get("confidence") or 0)
            weeks = max(0, (pd.Timestamp(as_of) - pd.Timestamp(it.get("last_confirmed") or it.get("created") or as_of)).days // 7)
            c = round(base * DECAY_PER_WEEK ** weeks, 3)
            if c != it.get("confidence"):
                it["base_confidence"], it["confidence"] = base, c
                changed += 1
                if c < RETIRE_BELOW:
                    self.save(it, "decay", as_of, {"confidence": c})
                    self.retire(it["id"], f"confidence {c} < {RETIRE_BELOW} (not re-confirmed for {weeks} weeks)", as_of)
                    retired.append(it["id"])
                    continue
                self.save(it, "decay", as_of, {"confidence": c, "weeks": weeks})
        return {"changed": changed, "retired": retired}

    def compact(self, as_of: str | None = None) -> dict:
        """Merge live items about the same slot: keep the one with the most evidence, union the evidence dates,
        retire the rest with a pointer."""
        groups: dict[str, list] = {}
        for it in self.list(["active", "needs_approval", "proposed"]):
            groups.setdefault(slot_of(it), []).append(it)
        merged = []
        for items in groups.values():
            if len(items) < 2:
                continue
            keep = max(items, key=lambda x: (x.get("n") or 0, x.get("last_confirmed") or ""))
            ev = set(keep.get("evidence") or [])
            for o in items:
                if o["id"] == keep["id"]:
                    continue
                ev |= set(o.get("evidence") or [])
                self.retire(o["id"], f"merged into {keep['id']}", as_of, superseded_by=keep["id"])
                merged.append(o["id"])
            keep["evidence"] = sorted(ev)[-12:]
            keep["last_confirmed"] = max(x.get("last_confirmed") or "" for x in items) or keep.get("last_confirmed")
            self.save(keep, "compact", as_of, {"merged": [o["id"] for o in items if o["id"] != keep["id"]]})
        return {"merged": merged}

    # ---------------------------------------------------------------- retrieval
    def retrieve(self, scope: dict | None = None, kinds: list[str] | None = None, k: int = 8, budget_tokens: int = 600,
                 statuses=("active",), as_of: str | None = None) -> list[dict]:
        scope = {kk: v for kk, v in (scope or {}).items() if v not in (None, "", [])}
        as_of = as_of or str(Date.today())
        ranked = []
        for it in self.list(list(statuses), kinds):
            m = scope_match(it.get("scope") or {}, scope)
            if m is None:
                continue
            age = max(0, (pd.Timestamp(as_of) - pd.Timestamp(it.get("last_confirmed") or it.get("created") or as_of)).days)
            recency = 0.5 ** (age / 28)
            ranked.append((m, (it.get("confidence") or 0) * recency, it.get("last_confirmed") or "", it))
        ranked.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
        out, used = [], 0
        for _, _, _, it in ranked:
            if len(out) >= k:
                break
            c = compact_item(it)
            t = tokens(c)
            if used + t > budget_tokens:
                break  # caps are hard: the lowest-ranked items are dropped, never truncated
            out.append(c)
            used += t
        return out


def scope_match(item_scope: dict, query: dict) -> int | None:
    """Number of query keys the item matches; None if a key both define disagrees (item doesn't apply)."""
    score = 0
    for k, qv in query.items():
        iv = item_scope.get(k)
        if iv in (None, "", "all"):
            continue
        qs = [str(x).lower() for x in (qv if isinstance(qv, (list, tuple, set)) else [qv])]
        ivs = str(iv).lower()
        if k in ("event", "condition", "item", "station"):
            ok = any(ivs in q or q in ivs for q in qs)
        elif k == "weekday":
            ok = any(ivs[:3] == q[:3] for q in qs)
        elif k == "channel":
            apps = {"delivery", "apps", "doordash", "ubereats", "grubhub"}
            ok = any(ivs == q or (ivs in apps and q in apps and "delivery" in (ivs, q)) for q in qs)
        else:
            ok = ivs in qs
        if not ok:
            return None
        score += 1
    return score


def compact_item(it: dict) -> dict:
    """What an agent sees of an item (whole, but without bookkeeping)."""
    keep = ["id", "kind", "scope", "statement", "effect", "n", "confidence", "status", "last_confirmed"]
    if it.get("kind") == "action_item":
        keep += ["owner", "check_on", "measure", "action_status"]
    return {k: it[k] for k in keep if it.get(k) not in (None, [], {})}


def _brief(v: dict) -> dict:
    return {k: v.get(k) for k in ("recomputed", "claimed", "n", "tolerance", "status") if k in v}


_DEFAULT: KB | None = None


def kb() -> KB:
    global _DEFAULT
    if _DEFAULT is None or _DEFAULT.path != db_path():
        _DEFAULT = KB()
    return _DEFAULT


# ---------------------------------------------------------------- module-level API (docs/architecture/TRI_WORKFLOW_API.md)
def retrieve(scope: dict | None = None, kinds: list[str] | None = None, k: int = 8, budget_tokens: int = 600,
             as_of: str | None = None) -> list[dict]:
    """Ranked by scope match, then confidence x recency; whole items only; total ~tokens <= budget_tokens."""
    return kb().retrieve(scope, kinds, k, budget_tokens, as_of=as_of)


def propose(item: dict, as_of: str | None = None, db=None, led=None) -> dict:
    return kb().propose(item, as_of, db, led)


def validate(item: dict, as_of: str | None = None, db=None, led=None) -> dict:
    from .validate import validate as _v, DB
    return _v(item, as_of=as_of, db=db or DB, led=led)
