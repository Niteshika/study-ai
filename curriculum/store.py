"""Database access for the curriculum module.

Uses the same database file as Person 1 (DATA_DIR/study.db, or DB_PATH),
so concepts saved here are the ones retrieval matches notes against.
Person 3 will replace this with the shared database layer later.
"""

import json
import os
import sqlite3
from pathlib import Path

_SCHEMA = Path(__file__).with_name("schema.sql")

# Columns the plans need that an older `concepts` table might be missing.
_EXTRA_COLUMNS = {
    "plan_id": "TEXT",
    "prerequisites": "TEXT NOT NULL DEFAULT '[]'",
    "position": "INTEGER NOT NULL DEFAULT 0",
}


def db_path() -> Path:
    # Read env at call time so tests can point DATA_DIR at a temp folder.
    data_dir = Path(os.getenv("DATA_DIR", "data"))
    return Path(os.getenv("DB_PATH", data_dir / "study.db"))


def db(path=None) -> sqlite3.Connection:
    path = Path(path) if path else db_path()
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA.read_text())
    have = {r["name"] for r in conn.execute("PRAGMA table_info(concepts)")}
    for col, spec in _EXTRA_COLUMNS.items():
        if col not in have:
            conn.execute(f"ALTER TABLE concepts ADD COLUMN {col} {spec}")
    # Made here, not in schema.sql: the column may only exist after the ALTER above.
    conn.execute("CREATE INDEX IF NOT EXISTS idx_concepts_plan ON concepts(plan_id)")
    conn.commit()
    return conn


def table_exists(conn, name) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def to_dict(row) -> dict:
    d = dict(row)
    d["prerequisites"] = json.loads(d.get("prerequisites") or "[]")
    d["verified"] = bool(d.get("verified"))
    d["order"] = d.pop("position")
    return d


def get_concept(conn, concept_id) -> dict | None:
    row = conn.execute("SELECT * FROM concepts WHERE id=?", (concept_id,)).fetchone()
    return to_dict(row) if row else None


def get_plan(conn, plan_id) -> list[dict]:
    """The concepts of one plan, in learning order."""
    rows = conn.execute(
        "SELECT * FROM concepts WHERE plan_id=? ORDER BY position", (plan_id,)
    ).fetchall()
    return [to_dict(r) for r in rows]


def list_plans(conn, user_id) -> list[dict]:
    """All of a user's plans, newest first, with how many concepts each has."""
    rows = conn.execute(
        "SELECT p.*, COUNT(c.id) AS num_concepts FROM plans p "
        "LEFT JOIN concepts c ON c.plan_id = p.id "
        "WHERE p.user_id=? GROUP BY p.id ORDER BY p.created_at DESC, p.rowid DESC",
        (user_id,),
    ).fetchall()
    return [dict(r) for r in rows]
