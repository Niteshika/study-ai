"""Tests for Person 2 (Curriculum). Offline: fake LLM replies, temp database.

    pytest tests/test_curriculum.py -q
"""

import json
import os
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp())
os.environ["DATA_DIR"] = str(TMP / "data")
os.environ.pop("CURRICULUM_FAKE", None)
# llm.py reads LLM_PROVIDER once, on import. Set it before anything imports llm,
# or Person 1's tests (run in the same session) would try the real OpenAI API.
os.environ["LLM_PROVIDER"] = "fake"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from curriculum import core, store  # noqa: E402
from curriculum.validate import PlanError, check_plan, parse_json  # noqa: E402


def make_plan(*items):
    """make_plan(("A", []), ("B", ["A"])) -> plan dict"""
    return {"concepts": [{"name": n, "definition": f"About {n}.", "prerequisites": p}
                         for n, p in items]}


GOOD = make_plan(("A", []), ("B", ["A"]), ("C", ["B"]), ("D", ["A"]), ("E", ["C", "D"]))
FIVE = lambda: make_plan(("A", []), ("B", []), ("C", []), ("D", []), ("E", []))  # noqa: E731


@pytest.fixture
def conn():
    return store.db(":memory:")


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
    ids = core.generate_plan("u1", "Graphs", "beginner", "interviews", "1 week", conn=conn)

    plan = store.get_plan(conn, "u1")
    assert [c["id"] for c in plan] == ids
    assert all(i.startswith("c_") for i in ids)
    assert [c["name"] for c in plan] == ["A", "B", "C", "D", "E"]
    by_name = {c["name"]: c for c in plan}
    assert by_name["E"]["prerequisites"] == [by_name["C"]["id"], by_name["D"]["id"]]
    assert all(c["source"] == "ai" and c["verified"] is False for c in plan)


def test_bad_output_is_sent_back_and_fixed(conn, monkeypatch):
    bad = make_plan(("A", []), ("B", ["Z"]), ("C", []), ("D", []), ("E", []))
    fake = FakeLLM("not json", json.dumps(bad), json.dumps(GOOD))
    monkeypatch.setattr(core.llm, "chat", fake)
    assert len(core.generate_plan("u1", "X", "b", "g", "t", conn=conn)) == 5
    assert "'Z', which is not in the plan" in fake.prompts[2]  # problem was sent back


def test_gives_up_and_saves_nothing(conn, monkeypatch):
    monkeypatch.setattr(core.llm, "chat", FakeLLM("junk", "junk", "junk"))
    with pytest.raises(PlanError, match="Gave up"):
        core.generate_plan("u1", "X", "b", "g", "t", conn=conn)
    assert store.get_plan(conn, "u1") == []


def test_new_plan_replaces_old_and_users_are_separate(conn, monkeypatch):
    monkeypatch.setattr(core.llm, "chat", FakeLLM(*[json.dumps(GOOD)] * 3))
    core.generate_plan("u1", "X", "b", "g", "t", conn=conn)
    core.generate_plan("u1", "Y", "b", "g", "t", conn=conn)
    core.generate_plan("u2", "X", "b", "g", "t", conn=conn)
    assert len(store.get_plan(conn, "u1")) == 5
    assert len(store.get_plan(conn, "u2")) == 5


def test_fake_mode_needs_no_llm(conn, monkeypatch):
    monkeypatch.setenv("CURRICULUM_FAKE", "1")
    monkeypatch.setattr(core.llm, "chat", lambda *a, **k: pytest.fail("LLM called"))
    assert len(core.generate_plan("u1", "Python", "b", "g", "t", conn=conn)) == 5


def test_get_definition_and_next_concept(conn, monkeypatch):
    monkeypatch.setenv("CURRICULUM_FAKE", "1")
    ids = core.generate_plan("u1", "Python", "b", "g", "t", conn=conn)
    d = core.get_definition(ids[0], conn=conn)
    assert d["source"] == "ai" and d["verified"] is False and d["definition"]
    assert core.next_new_concept("u1", conn=conn) == ids[0]


# ---------------- fits with Person 1 (retrieval)

def test_works_on_person1s_concepts_table(tmp_path, monkeypatch):
    """If retrieval created `concepts` first (no prerequisites/position), we add them."""
    from retrieval import store as rstore
    monkeypatch.setattr(rstore, "DB_PATH", tmp_path / "shared.db")
    rstore.db().close()  # Person 1's fallback CREATE runs first

    monkeypatch.setenv("CURRICULUM_FAKE", "1")
    conn = store.db(tmp_path / "shared.db")
    ids = core.generate_plan("u1", "Python", "b", "g", "t", conn=conn)
    assert len(store.get_plan(conn, "u1")) == len(ids) == 5


def test_new_plan_removes_note_links_to_old_concepts(tmp_path, monkeypatch):
    from retrieval import store as rstore
    monkeypatch.setattr(rstore, "DB_PATH", tmp_path / "shared.db")
    rstore.db().close()

    monkeypatch.setenv("CURRICULUM_FAKE", "1")
    conn = store.db(tmp_path / "shared.db")
    old = core.generate_plan("u1", "Python", "b", "g", "t", conn=conn)
    conn.execute("INSERT INTO concept_chunks (concept_id, chunk_id, score) VALUES (?, 'ch1', 0.9)", (old[0],))
    conn.commit()
    core.generate_plan("u1", "Python", "b", "g", "t", conn=conn)
    assert conn.execute("SELECT COUNT(*) FROM concept_chunks").fetchone()[0] == 0


def test_person1_can_embed_our_definitions(tmp_path, monkeypatch):
    """Person 1 embeds 'name: definition'. Every definition is one short sentence."""
    monkeypatch.setenv("CURRICULUM_FAKE", "1")
    conn = store.db(tmp_path / "x.db")
    core.generate_plan("u1", "Python", "b", "g", "t", conn=conn)
    for c in store.get_plan(conn, "u1"):
        assert c["definition"].count(". ") == 0 and len(c["definition"].split()) <= 35
