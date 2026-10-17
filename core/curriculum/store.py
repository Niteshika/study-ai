"""Database reads for the curriculum module. Uses the shared core.db connection."""

from core import db


def to_dict(row) -> dict:
    d = dict(row)
    d.pop("embedding", None)       # internal, for matching notes
    d.pop("embedding_key", None)
    d["prerequisites"] = list(d.get("prerequisites") or [])
    d["verified"] = bool(d.get("verified"))
    d["order"] = d.pop("position")
    return d


def get_concept(conn, user_id, concept_id) -> dict | None:
    row = conn.execute(
        "SELECT * FROM concepts WHERE id = %s AND user_id = %s",
        (concept_id, user_id)).fetchone()
    return to_dict(row) if row else None


def get_plan(conn, plan_id) -> list[dict]:
    """The concepts of one plan, in learning order."""
    rows = conn.execute(
        "SELECT * FROM concepts WHERE plan_id = %s ORDER BY position", (plan_id,)
    ).fetchall()
    return [to_dict(r) for r in rows]


def get_plan_row(conn, plan_id) -> dict | None:
    return conn.execute("SELECT * FROM plans WHERE id = %s", (plan_id,)).fetchone()


def list_plans(conn, user_id) -> list[dict]:
    """All of a user's plans, newest first, with how many concepts each has."""
    return conn.execute(
        "SELECT p.*, COUNT(c.id)::int AS num_concepts FROM plans p "
        "LEFT JOIN concepts c ON c.plan_id = p.id "
        "WHERE p.user_id = %s GROUP BY p.id ORDER BY p.created_at DESC, p.id",
        (user_id,),
    ).fetchall()


def table_exists(conn, name) -> bool:
    return db.table_exists(conn, name)
