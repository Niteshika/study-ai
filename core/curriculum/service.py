"""Curriculum: turns "I want to learn X" into an ordered concept plan.

Status:
  generate_plan  - REAL. Our own LLM call (OpenAI/Gemini). Used by the website.
  save_plan      - REAL. Saves a plan someone else wrote (Claude, via the MCP
                   server) after the same checks. Used by the MCP server.
  list_plans, delete_plan, get_definition - REAL.
  the rest       - STUBS with the right return shapes.

Every function takes an optional `conn`. Without one, it opens and closes its own.
CURRICULUM_FAKE=1 gives a fixed fake plan (no API key needed).
"""

import os
import uuid
from contextlib import contextmanager

from core import db, llm
from core.db import Jsonb
from . import store
from .prompts import FIX_PROMPT, PLAN_PROMPT, PLAN_SYSTEM
from .validate import MAX_CONCEPTS, MIN_CONCEPTS, PlanError, check_plan, parse_json

MAX_TRIES = 3  # first attempt + 2 fix attempts

FAKE_PLAN = {
    "concepts": [
        {"name": "Variables", "definition": "A named place in memory that stores a value your program can read and change.", "prerequisites": []},
        {"name": "Data types", "definition": "The kind of value a variable holds, such as a whole number, decimal, text or true/false.", "prerequisites": ["Variables"]},
        {"name": "Conditionals", "definition": "Statements like if and else that run a block of code only when a condition is true.", "prerequisites": ["Data types"]},
        {"name": "Loops", "definition": "Statements like for and while that repeat a block of code until a condition stops them.", "prerequisites": ["Conditionals"]},
        {"name": "Functions", "definition": "A named, reusable block of code that takes inputs, does a task and can return a result.", "prerequisites": ["Variables"]},
    ]
}


def new_id(prefix="c_") -> str:
    # Text ids, same style as files ("file_ab12...").
    return prefix + uuid.uuid4().hex[:12]


@contextmanager
def _use(conn):
    """Use the caller's connection, or open (and later close) our own."""
    if conn is not None:
        yield conn
    else:
        with db.connect() as own:
            yield own


# ---------------------------------------------------------------- Phase 1

def generate_plan(user_id, topic, level, goal, time, conn=None) -> dict:
    """Build and save a NEW ordered concept plan. The user's other plans are kept.

    Returns {"plan_id": "p_...", "concept_ids": [...in learning order...]}.
    After a new plan, retrieval's match_file_to_concepts can be re-run on the
    user's files so their notes link to the new concepts too.
    """
    if os.getenv("CURRICULUM_FAKE") == "1":
        concepts = check_plan(FAKE_PLAN)
    else:
        concepts = _ask_llm_for_plan(topic, level, goal, time)
    with _use(conn) as c:
        return _save_plan(c, user_id, topic, level, goal, time, concepts)


def save_plan(user_id, topic, concepts, level=None, goal=None, time=None, conn=None) -> dict:
    """Save a plan that was written somewhere else (e.g. by Claude through the
    MCP server). It goes through exactly the same checks as our own plans.

    concepts = [{"name": ..., "definition": ..., "prerequisites": [names]}]
    Raises PlanError with a list of problems, so the caller can fix and retry.
    """
    checked = check_plan({"concepts": concepts})
    with _use(conn) as c:
        return _save_plan(c, user_id, topic, level, goal, time, checked)


def list_plans(user_id, conn=None) -> list[dict]:
    """All of a user's plans, newest first.
    Returns [{id, user_id, topic, level, goal, time, created_at, num_concepts}]."""
    with _use(conn) as c:
        return store.list_plans(c, user_id)


def get_plan(user_id, plan_id, conn=None) -> dict | None:
    """One plan with its concepts in learning order, or None if it isn't this user's."""
    with _use(conn) as c:
        row = store.get_plan_row(c, plan_id)
        if row is None or row["user_id"] != user_id:
            return None
        return {**row, "concepts": store.get_plan(c, plan_id)}


def delete_plan(user_id, plan_id, conn=None) -> dict:
    """Delete one plan. The database also removes its concepts and their links
    to the user's notes (ON DELETE CASCADE). Other plans are untouched."""
    with _use(conn) as c:
        res = c.execute("DELETE FROM plans WHERE id = %s AND user_id = %s", (plan_id, user_id))
        if res.rowcount == 0:
            return {"ok": False, "error": "No such plan for this user"}
    return {"ok": True}


def _ask_llm_for_plan(topic, level, goal, time) -> list[dict]:
    """Ask for a plan, check it, and send any problems back to the LLM to fix."""
    prompt = PLAN_PROMPT.format(topic=topic, level=level, goal=goal, time=time,
                                min_n=MIN_CONCEPTS, max_n=MAX_CONCEPTS)
    problems: list[str] = []
    for _ in range(MAX_TRIES):
        text = llm.chat(prompt, system=PLAN_SYSTEM)
        try:
            return check_plan(parse_json(text))
        except PlanError as e:
            problems = e.problems
            prompt = FIX_PROMPT.format(problems="\n".join(f"- {p}" for p in problems), previous=text)
    raise PlanError([f"Gave up after {MAX_TRIES} tries."] + problems)


def _save_plan(conn, user_id, topic, level, goal, time, concepts: list[dict]) -> dict:
    """Write a new plan row and its checked concepts (source='ai').
    All saved, or nothing saved."""
    plan_id = new_id("p_")
    ids = {c["name"].lower(): new_id() for c in concepts}
    with conn.transaction():
        conn.execute(
            "INSERT INTO plans (id, user_id, topic, level, goal, time) VALUES (%s, %s, %s, %s, %s, %s)",
            (plan_id, user_id, topic, level, goal, time),
        )
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO concepts (id, user_id, plan_id, name, definition, prerequisites, position,"
                " source, verified) VALUES (%s, %s, %s, %s, %s, %s, %s, 'ai', false)",
                [(ids[c["name"].lower()], user_id, plan_id, c["name"], c["definition"],
                  Jsonb([ids[p.lower()] for p in c["prerequisites"]]), pos)
                 for pos, c in enumerate(concepts)],
            )
    return {"plan_id": plan_id, "concept_ids": [ids[c["name"].lower()] for c in concepts]}


# ---------------------------------------------------------------- Phase 2

def get_definition(user_id,concept_id, conn=None) -> dict:
    """The saved definition, so every explanation of a concept stays the same."""
    with _use(conn) as cn:
        c = store.get_concept(cn, user_id, concept_id)
    if c is None:
        raise KeyError(f"No concept with id {concept_id}")
    return {"definition": c["definition"], "source": c["source"], "verified": c["verified"]}


# ---------------------------------------------------------------- stubs (later phases)

def generate_quiz(concept_id, n=3, target_misconception=None) -> list[dict]:
    """STUB (Phase 3). The question shape others can rely on."""
    qs = [
        {"concept_id": concept_id, "type": "mcq",
         "question": "Fake question: which of these is a variable?",
         "options": ["x = 5", "if", "for", "print"], "answer": "x = 5",
         "misconception": target_misconception},
        {"concept_id": concept_id, "type": "short",
         "question": "Fake question: explain a variable in one sentence.",
         "options": None, "answer": "A named place that stores a value.",
         "misconception": target_misconception},
    ]
    return qs[:n]


def generate_diagnostic(user_id, plan_id) -> list[dict]:
    """STUB (Phase 5). 1-2 questions per early concept of this plan."""
    return generate_quiz("c_stub", n=2)


def edit_plan(user_id, plan_id, action, concept) -> dict:
    """STUB (Phase 5). action: 'add' | 'remove' | 'reorder', inside one plan."""
    if action not in ("add", "remove", "reorder"):
        return {"ok": False, "error": f"Unknown action {action!r}"}
    return {"ok": True}


def next_new_concept(user_id, plan_id, conn=None) -> str | None:
    """STUB (Phase 7). First concept of this plan for now; later, the first one
    whose prerequisites are all mastered (needs the mastery data from Phase 3)."""
    with _use(conn) as c:
        row = store.get_plan_row(c, plan_id)
        if row is None or row["user_id"] != user_id:   # missing, or not this user's
            return None
        plan = store.get_plan(c, plan_id)
    return plan[0]["id"] if plan else None


def generate_practice(user_id, concept_id) -> dict:
    """STUB (Phase 9). Mixes the current concept with older ones."""
    return {"concept_id": concept_id, "mixes_with": [], "problem": "Fake practice problem.",
            "answer": "Fake answer."}
