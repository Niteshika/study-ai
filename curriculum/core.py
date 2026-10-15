"""Person 2: Curriculum Builder. Turns "I want to learn X" into an ordered concept plan.

Status:
  generate_plan  - REAL (Phase 1). CURRICULUM_FAKE=1 gives the Phase 0 fake plan.
  get_definition - REAL for saved definitions (Phase 2/4 add more).
  the rest       - STUBS with the right return shapes, so others can build now.
"""

import json
import os
import uuid

import llm
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


def new_id() -> str:
    # Text ids, same style as Person 1's ("file_ab12...").
    return "c_" + uuid.uuid4().hex[:12]


# ---------------------------------------------------------------- Phase 1

def generate_plan(user_id, topic, level, goal, time, conn=None) -> list[str]:
    """Build and save an ordered concept plan. Returns concept ids in learning order.

    A new plan REPLACES the user's old one (open team question: one plan or many?).
    After a new plan, Person 1's match_file_to_concepts should be re-run on the
    user's files, because the old concept ids are gone.
    """
    conn = conn or store.db()
    if os.getenv("CURRICULUM_FAKE") == "1":
        concepts = check_plan(FAKE_PLAN)
    else:
        concepts = _ask_llm_for_plan(topic, level, goal, time)
    return _save_plan(conn, user_id, concepts)


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


def _save_plan(conn, user_id, concepts: list[dict]) -> list[str]:
    """Write checked concepts with source='ai'. All saved, or nothing saved."""
    ids = {c["name"].lower(): new_id() for c in concepts}
    with conn:
        old = [r["id"] for r in conn.execute("SELECT id FROM concepts WHERE user_id=?", (user_id,))]
        if old and store.table_exists(conn, "concept_chunks"):
            # Person 1's links from notes to the old concepts would point at nothing.
            marks = ",".join("?" * len(old))
            conn.execute(f"DELETE FROM concept_chunks WHERE concept_id IN ({marks})", old)
        conn.execute("DELETE FROM concepts WHERE user_id=?", (user_id,))

        conn.executemany(
            "INSERT INTO concepts (id, user_id, name, definition, prerequisites, position, source, verified)"
            " VALUES (?, ?, ?, ?, ?, ?, 'ai', 0)",
            [(ids[c["name"].lower()], user_id, c["name"], c["definition"],
              json.dumps([ids[p.lower()] for p in c["prerequisites"]]), pos)
             for pos, c in enumerate(concepts)],
        )
    return [ids[c["name"].lower()] for c in concepts]


# ---------------------------------------------------------------- Phase 2

def get_definition(concept_id, conn=None) -> dict:
    """The saved definition, so every explanation of a concept stays the same."""
    conn = conn or store.db()
    c = store.get_concept(conn, concept_id)
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


def generate_diagnostic(user_id) -> list[dict]:
    """STUB (Phase 5). 1-2 questions per early concept."""
    return generate_quiz("c_stub", n=2)


def edit_plan(user_id, action, concept) -> dict:
    """STUB (Phase 5). action: 'add' | 'remove' | 'reorder'."""
    if action not in ("add", "remove", "reorder"):
        return {"ok": False, "error": f"Unknown action {action!r}"}
    return {"ok": True}


def next_new_concept(user_id, conn=None) -> str | None:
    """STUB (Phase 7). First concept in the plan for now; later, the first one
    whose prerequisites are all mastered (needs Person 3's mastery data)."""
    conn = conn or store.db()
    plan = store.get_plan(conn, user_id)
    return plan[0]["id"] if plan else None


def generate_practice(user_id, concept_id) -> dict:
    """STUB (Phase 9). Mixes the current concept with older ones."""
    return {"concept_id": concept_id, "mixes_with": [], "problem": "Fake practice problem.",
            "answer": "Fake answer."}
