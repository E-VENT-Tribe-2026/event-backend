"""A small in-memory stand-in for the Supabase client, for tests that drive routes end to end.

Supports the query-builder calls the backend uses: select/eq/neq/in_/ilike/is_/not_.in_/or_/
order/range/limit/single, insert/upsert/update/delete, rpc, and the embedded
`events(...)` / `events!inner(...)` select used on event_participants and saved_events.
"""
import re
from types import SimpleNamespace


def _split_top(expr: str) -> list:
    parts, depth, cur = [], 0, ""
    for ch in expr:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    if cur:
        parts.append(cur)
    return parts


def _get(row: dict, col: str):
    cur = row
    for part in col.split("."):
        cur = cur.get(part) if isinstance(cur, dict) else None
    return cur


def _same(a, b) -> bool:
    return a is not None and b is not None and str(a).lower() == str(b).lower()


def _term(term: str):
    """Compile one PostgREST filter term of an `or` expression into a predicate."""
    term = term.strip()
    if term.startswith("and(") and term.endswith(")"):
        preds = [_term(t) for t in _split_top(term[4:-1])]
        return lambda row: all(p(row) for p in preds)
    m = re.match(r"^([\w.]+)\.not\.in\.\((.*)\)$", term)
    if m:
        col, vals = m.group(1), [v for v in m.group(2).split(",") if v]
        return lambda row: _get(row, col) is not None and not any(_same(_get(row, col), v) for v in vals)
    m = re.match(r"^([\w.]+)\.in\.\((.*)\)$", term)
    if m:
        col, vals = m.group(1), [v for v in m.group(2).split(",") if v]
        return lambda row: any(_same(_get(row, col), v) for v in vals)
    m = re.match(r"^([\w.]+)\.is\.null$", term)
    if m:
        return lambda row: _get(row, m.group(1)) is None
    m = re.match(r"^([\w.]+)\.eq\.(.*)$", term)
    if m:
        return lambda row: _same(_get(row, m.group(1)), m.group(2))
    raise NotImplementedError(f"fake supabase cannot parse filter term: {term}")


class FakeQuery:
    def __init__(self, db, name):
        self.db, self.name = db, name
        self.action, self.payload, self.on_conflict = "select", None, None
        self.cols, self.want_count = "*", False
        self.preds, self.orders = [], []
        self.window, self.is_single = None, False

    # ---- verbs
    def select(self, cols="*", count=None):
        self.cols, self.want_count = cols, bool(count)
        return self

    def insert(self, payload):
        self.action, self.payload = "insert", payload
        return self

    def upsert(self, payload, on_conflict=None):
        self.action, self.payload, self.on_conflict = "upsert", payload, on_conflict
        return self

    def update(self, payload):
        self.action, self.payload = "update", payload
        return self

    def delete(self):
        self.action = "delete"
        return self

    # ---- filters
    def eq(self, col, val):
        self.preds.append(lambda r: _same(_get(r, col), val))
        return self

    def neq(self, col, val):
        self.preds.append(lambda r: not _same(_get(r, col), val))
        return self

    def in_(self, col, vals):
        self.preds.append(lambda r: any(_same(_get(r, col), v) for v in vals))
        return self

    def is_(self, col, val):
        self.preds.append(lambda r: _get(r, col) is None)
        return self

    def ilike(self, col, pattern):
        needle = pattern.replace("%", "").replace("\\", "").lower()
        self.preds.append(lambda r: needle in str(_get(r, col) or "").lower())
        return self

    def gte(self, col, val):
        self.preds.append(lambda r: str(_get(r, col) or "") >= str(val))
        return self

    def gt(self, col, val):
        self.preds.append(lambda r: str(_get(r, col) or "") > str(val))
        return self

    @property
    def not_(self):
        outer = self

        class _Not:
            def in_(_self, col, vals):
                outer.preds.append(lambda r: not any(_same(_get(r, col), v) for v in vals))
                return outer

        return _Not()

    def or_(self, expr):
        expr = expr[1:-1] if expr.startswith("(") and expr.endswith(")") else expr
        preds = [_term(t) for t in _split_top(expr)]
        self.preds.append(lambda r: any(p(r) for p in preds))
        return self

    def order(self, col, desc=False):
        self.orders.append((col, desc))
        return self

    def range(self, start, end):
        self.window = (start, end)
        return self

    def limit(self, n):
        self.window = (0, n - 1)
        return self

    def single(self):
        self.is_single = True
        return self

    # ---- run
    def _rows(self):
        rows = self.db.tables.setdefault(self.name, [])
        if "events" in self.cols and self.name in ("event_participants", "saved_events"):
            joined = []
            for row in rows:
                event = next((e for e in self.db.tables.get("events", []) if e["id"] == row["event_id"]), None)
                if event is None and "!inner" in self.cols:
                    continue
                joined.append({**row, "events": event})
            return joined
        return rows

    def execute(self):
        db = self.db
        if self.action == "insert":
            items = self.payload if isinstance(self.payload, list) else [self.payload]
            out = [db.add(self.name, dict(i)) for i in items]
            return SimpleNamespace(data=out, count=None)
        if self.action == "upsert":
            keys = (self.on_conflict or "").split(",")
            item = dict(self.payload)
            rows = db.tables.setdefault(self.name, [])
            for row in rows:
                if all(_same(row.get(k), item.get(k)) for k in keys if k):
                    return SimpleNamespace(data=[row], count=None)
            return SimpleNamespace(data=[db.add(self.name, item)], count=None)

        matched = [r for r in self._rows() if all(p(r) for p in self.preds)]
        if self.action == "delete":
            table = db.tables[self.name]
            for row in matched:
                table.remove(row)
            return SimpleNamespace(data=matched, count=None)
        if self.action == "update":
            for row in matched:
                row.update(self.payload)
            return SimpleNamespace(data=matched, count=None)

        for col, desc in reversed(self.orders):
            matched = sorted(matched, key=lambda r: str(_get(r, col) or ""), reverse=desc)
        total = len(matched)
        if self.window:
            matched = matched[self.window[0]:self.window[1] + 1]
        if self.is_single:
            return SimpleNamespace(data=matched[0] if matched else None, count=total)
        return SimpleNamespace(data=matched, count=total if self.want_count else None)


class FakeSupabase:
    def __init__(self):
        self.tables, self.rpc_results, self._seq = {}, {}, 0

    def add(self, name, row):
        self._seq += 1
        row.setdefault("created_at", f"2026-01-01T00:00:{self._seq:02d}+00:00")
        if name in ("friend_requests", "friendships", "notifications"):
            row.setdefault("id", self._seq)
        self.tables.setdefault(name, []).append(row)
        return row

    def table(self, name):
        return FakeQuery(self, name)

    def rpc(self, name, params=None):
        data = self.rpc_results.get(name, [])
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=data, count=None))
