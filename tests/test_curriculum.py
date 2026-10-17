"""Tests for curriculum. Offline: fake LLM replies. Needs the test Postgres (see conftest.py).

    pytest tests/test_curriculum.py -q
"""

import json

import pytest

from core.curriculum import service as core
from core.curriculum import store
from core.curriculum.validate import PlanError, check_plan, parse_json


def make_plan(*items):
    """make_plan(("A", []), ("B", ["A"])) -> plan dict"""
    return {"concepts": [{"name": n, "definition": f"About {n}.", "prerequisites": p}
                         for n, p in items]}


GOOD = make_plan(("A", []), ("B", ["A"]), ("C", ["B"]), ("D", ["A"]), ("E", ["C", "D"]))
FIVE = lambda: make_plan(("A", []), ("B", []), ("C", []), ("D", []), ("E", []))  # noqa: E731


class FakeLLM:
    """Returns the replies you give it, one per call, and records the prompts."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts = []

    def __call__(self, prompt, system=None):  # same signature as llm.chat
        self.prompts.append(prompt)
        return self.replies.pop(0)


# ---------------- checks on the LLM's plan

def test_good_plan_passes():
    assert [c["name"] for c in check_plan(GOOD)] == ["A", "B", "C", "D", "E"]


def test_reorders_when_prereq_comes_late():
    plan = make_plan(("B", ["A"]), ("A", []), ("C", []), ("D", []), ("E", []))
    assert [c["name"] for c in check_plan(plan)] == ["A", "B", "C", "D", "E"]


def test_loop_is_rejected():
    plan = make_plan(("A", ["C"]), ("B", ["A"]), ("C", ["B"]), ("D", []), ("E", []))
    with pytest.raises(PlanError, match="loop"):
        check_plan(plan)


def test_missing_prereq_is_rejected():
    plan = make_plan(("A", []), ("B", ["Z"]), ("C", []), ("D", []), ("E", []))
    with pytest.raises(PlanError, match="'Z', which is not in the plan"):
        check_plan(plan)


def test_self_prereq_is_rejected():
    plan = make_plan(("A", ["A"]), ("B", []), ("C", []), ("D", []), ("E", []))
    with pytest.raises(PlanError, match="itself"):
        check_plan(plan)


def test_too_few_and_too_many():
    with pytest.raises(PlanError, match="needs 5 to 10"):
        check_plan(make_plan(("A", []), ("B", [])))
    with pytest.raises(PlanError, match="needs 5 to 10"):
        check_plan(make_plan(*[(f"C{i}", []) for i in range(11)]))


def test_duplicate_names_rejected():
    plan = make_plan(("A", []), ("a", []), ("C", []), ("D", []), ("E", []))
    with pytest.raises(PlanError, match="more than once"):
        check_plan(plan)


def test_definition_must_be_one_short_sentence():
    plan = FIVE()
    plan["concepts"][0]["definition"] = "First sentence. Second sentence."
    plan["concepts"][1]["definition"] = " ".join(["word"] * 40) + "."
    with pytest.raises(PlanError) as e:
        check_plan(plan)
    assert any("one sentence" in p for p in e.value.problems)
    assert any("too long" in p for p in e.value.problems)


def test_abbreviations_dont_count_as_new_sentences():
    plan = FIVE()
    plan["concepts"][0]["definition"] = "A value like 3.14 used in math, e.g. for circles."
    assert len(check_plan(plan)) == 5


def test_prereq_names_ignore_case():
    plan = make_plan(("Arrays", []), ("Sorting", ["arrays"]), ("C", []), ("D", []), ("E", []))
    assert len(check_plan(plan)) == 5


def test_parse_strips_code_fences_and_rejects_junk():
    assert parse_json('```json\n{"concepts": []}\n```') == {"concepts": []}
    with pytest.raises(PlanError, match="not valid JSON"):
        parse_json("Sure! Here is your plan: ...")


# ---------------- generate_plan

def test_generate_plan_saves_in_order_with_prereq_ids(conn, monkeypatch):
    monkeypatch.setattr(core.llm, "chat", FakeLLM(json.dumps(GOOD)))
    result = core.generate_plan("u1", "Graphs", "beginner", "interviews", "1 week", conn=conn)
    ids = result["concept_ids"]

    assert result["plan_id"].startswith("p_")
    plan = store.get_plan(conn, result["plan_id"])
    assert [c["id"] for c in plan] == ids
    assert all(i.startswith("c_") for i in ids)
    assert [c["name"] for c in plan] == ["A", "B", "C", "D", "E"]
    by_name = {c["name"]: c for c in plan}
    assert by_name["E"]["prerequisites"] == [by_name["C"]["id"], by_name["D"]["id"]]
    assert all(c["source"] == "ai" and c["verified"] is False for c in plan)
    assert all(c["plan_id"] == result["plan_id"] for c in plan)


def test_bad_output_is_sent_back_and_fixed(conn, monkeypatch):
    bad = make_plan(("A", []), ("B", ["Z"]), ("C", []), ("D", []), ("E", []))
    fake = FakeLLM("not json", json.dumps(bad), json.dumps(GOOD))
    monkeypatch.setattr(core.llm, "chat", fake)
    assert len(core.generate_plan("u1", "X", "b", "g", "t", conn=conn)["concept_ids"]) == 5
    assert "'Z', which is not in the plan" in fake.prompts[2]  # problem was sent back


def test_gives_up_and_saves_nothing(conn, monkeypatch):
    monkeypatch.setattr(core.llm, "chat", FakeLLM("junk", "junk", "junk"))
    with pytest.raises(PlanError, match="Gave up"):
        core.generate_plan("u1", "X", "b", "g", "t", conn=conn)
    assert core.list_plans("u1", conn=conn) == []
    assert conn.execute("SELECT COUNT(*) AS n FROM concepts").fetchone()["n"] == 0


def test_fake_mode_needs_no_llm(conn, monkeypatch):
    monkeypatch.setenv("CURRICULUM_FAKE", "1")
    monkeypatch.setattr(core.llm, "chat", lambda *a, **k: pytest.fail("LLM called"))
    assert len(core.generate_plan("u1", "Python", "b", "g", "t", conn=conn)["concept_ids"]) == 5


def test_get_definition_and_next_concept(conn, monkeypatch):
    monkeypatch.setenv("CURRICULUM_FAKE", "1")
    result = core.generate_plan("u1", "Python", "b", "g", "t", conn=conn)
    first = result["concept_ids"][0]
    d = core.get_definition(first, conn=conn)
    assert d["source"] == "ai" and d["verified"] is False and d["definition"]
    assert core.next_new_concept("u1", result["plan_id"], conn=conn) == first


# ---------------- several plans per user

def test_user_keeps_several_plans(conn, monkeypatch):
    monkeypatch.setattr(core.llm, "chat", FakeLLM(*[json.dumps(GOOD)] * 3))
    dsa = core.generate_plan("u1", "DSA", "b", "g", "t", conn=conn)
    sql = core.generate_plan("u1", "SQL", "b", "g", "t", conn=conn)
    other = core.generate_plan("u2", "DSA", "b", "g", "t", conn=conn)

    plans = core.list_plans("u1", conn=conn)
    assert {p["topic"] for p in plans} == {"DSA", "SQL"}
    assert all(p["num_concepts"] == 5 for p in plans)
    # Each plan has its own concepts, and the first plan was not replaced.
    assert [c["id"] for c in store.get_plan(conn, dsa["plan_id"])] == dsa["concept_ids"]
    assert [c["id"] for c in store.get_plan(conn, sql["plan_id"])] == sql["concept_ids"]
    assert set(dsa["concept_ids"]).isdisjoint(sql["concept_ids"])
    assert [p["topic"] for p in core.list_plans("u2", conn=conn)] == ["DSA"]
    assert other["plan_id"] not in {p["id"] for p in plans}


def test_prereqs_stay_inside_their_plan(conn, monkeypatch):
    monkeypatch.setattr(core.llm, "chat", FakeLLM(*[json.dumps(GOOD)] * 2))
    a = core.generate_plan("u1", "DSA", "b", "g", "t", conn=conn)
    core.generate_plan("u1", "SQL", "b", "g", "t", conn=conn)
    for c in store.get_plan(conn, a["plan_id"]):
        assert set(c["prerequisites"]) <= set(a["concept_ids"])


def test_delete_plan_only_removes_that_plan(conn, monkeypatch):
    monkeypatch.setenv("CURRICULUM_FAKE", "1")
    dsa = core.generate_plan("u1", "DSA", "b", "g", "t", conn=conn)
    sql = core.generate_plan("u1", "SQL", "b", "g", "t", conn=conn)

    assert core.delete_plan("u2", dsa["plan_id"], conn=conn)["ok"] is False  # not u2's plan
    assert core.delete_plan("u1", dsa["plan_id"], conn=conn) == {"ok": True}
    assert [p["topic"] for p in core.list_plans("u1", conn=conn)] == ["SQL"]
    assert store.get_plan(conn, dsa["plan_id"]) == []
    assert len(store.get_plan(conn, sql["plan_id"])) == 5


# ---------------- plans written by Claude (MCP server)

def test_save_plan_checks_claudes_plan(conn):
    result = core.save_plan("u1", "Graphs", GOOD["concepts"], level="beginner", conn=conn)
    assert len(result["concept_ids"]) == 5
    plan = core.get_plan("u1", result["plan_id"], conn=conn)
    assert plan["topic"] == "Graphs" and [c["name"] for c in plan["concepts"]] == list("ABCDE")
    assert core.get_plan("u2", result["plan_id"], conn=conn) is None  # not u2's plan

    bad = make_plan(("A", ["C"]), ("B", ["A"]), ("C", ["B"]), ("D", []), ("E", []))["concepts"]
    with pytest.raises(PlanError, match="loop"):
        core.save_plan("u1", "Bad", bad, conn=conn)
    assert len(core.list_plans("u1", conn=conn)) == 1  # the bad plan was not saved


# ---------------- fits with retrieval

def _add_note_link(conn, user_id, concept_id):
    """Insert one fake file + chunk and link it to a concept."""
    from core.db import vec
    conn.execute("INSERT INTO files (id, user_id, filename, storage_path, sha256, status)"
                 " VALUES ('f1', %s, 'n.md', '/tmp/n.md', 'x', 'ready')", (user_id,))
    conn.execute("INSERT INTO chunks (id, file_id, user_id, idx, text, embedding)"
                 " VALUES ('ch1', 'f1', %s, 0, 'hi', %s)", (user_id, vec([1.0, 0.0])))
    conn.execute("INSERT INTO concept_chunks (concept_id, chunk_id, score) VALUES (%s, 'ch1', 0.9)",
                 (concept_id,))


def test_new_plan_keeps_note_links_but_delete_removes_them(conn, monkeypatch):
    monkeypatch.setenv("CURRICULUM_FAKE", "1")
    first = core.generate_plan("u1", "Python", "b", "g", "t", conn=conn)
    _add_note_link(conn, "u1", first["concept_ids"][0])
    count = lambda: conn.execute("SELECT COUNT(*) AS n FROM concept_chunks").fetchone()["n"]  # noqa: E731

    core.generate_plan("u1", "SQL", "b", "g", "t", conn=conn)
    assert count() == 1  # a second plan doesn't touch the first plan's note links
    core.delete_plan("u1", first["plan_id"], conn=conn)
    assert count() == 0  # deleting the plan does
    # ...but the user's notes themselves are kept
    assert conn.execute("SELECT COUNT(*) AS n FROM chunks").fetchone()["n"] == 1


def test_retrieval_can_embed_our_definitions(conn, monkeypatch):
    """Retrieval embeds 'name: definition'. Every definition is one short sentence."""
    monkeypatch.setenv("CURRICULUM_FAKE", "1")
    result = core.generate_plan("u1", "Python", "b", "g", "t", conn=conn)
    for c in store.get_plan(conn, result["plan_id"]):
        assert c["definition"].count(". ") == 0 and len(c["definition"].split()) <= 35
