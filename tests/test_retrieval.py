"""End-to-end tests for retrieval. Offline: fake embedder. Needs the test Postgres (see conftest.py).

    pytest tests/test_retrieval.py -q
"""

import pymupdf
import pytest

from conftest import TMP, wipe
from core import db
from core.retrieval import service as core, stubs
from core.retrieval.chunker import chunk_blocks, count_tokens

USER = "u1"
GD = ("Gradient descent is an optimization method. It updates each weight by taking a small step "
      "against the gradient of the loss function. Repeating these gradient steps lowers the loss. ")
OVERFIT = ("Overfitting happens when a model memorizes noise in the training data. The model then "
           "performs badly on new unseen data. Regularization and more training data reduce overfitting. ")


def make_pdf(path):
    doc = pymupdf.open()
    p1 = doc.new_page()
    p1.insert_text((72, 72), "Gradient Descent", fontsize=20)
    p1.insert_textbox(pymupdf.Rect(72, 100, 540, 760), GD * 6, fontsize=10)
    p2 = doc.new_page()
    p2.insert_text((72, 72), "Overfitting", fontsize=20)
    p2.insert_textbox(pymupdf.Rect(72, 100, 540, 760), OVERFIT * 6, fontsize=10)
    doc.save(path)


@pytest.fixture(scope="module", autouse=True)
def _clean_db():
    wipe()  # these tests build on each other, so wipe once for the whole file


@pytest.fixture(scope="module")
def files():
    pdf = TMP / "ml_notes.pdf"
    make_pdf(pdf)
    md = TMP / "lecture.md"
    md.write_text("# Learning rate\nThe learning rate sets the step size of each gradient update. "
                  "If the learning rate is too large the loss diverges.\n\n## Batches\n"
                  "Mini-batches estimate the gradient from a small sample of training examples.\n")
    empty = TMP / "empty.txt"
    empty.write_text("   \n\n ")
    blank_pdf = TMP / "scan.pdf"
    d = pymupdf.open(); d.new_page(); d.save(blank_pdf)
    return {"pdf": pdf, "md": md, "empty": empty, "scan": blank_pdf}


@pytest.fixture(scope="module")
def concepts():
    with db.connect() as conn:
        conn.execute("INSERT INTO plans (id, user_id, topic) VALUES ('p_ml', %s, 'ML')", (USER,))
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO concepts (id, user_id, plan_id, name, definition) VALUES (%s,%s,'p_ml',%s,%s)", [
                    ("c_gd", USER, "Gradient descent", "Optimization that steps weights against the gradient of the loss."),
                    ("c_overfit", USER, "Overfitting", "Model memorizes training data noise and performs badly on new data."),
                    ("c_attention", USER, "Attention", "Transformers weigh tokens with query key value attention scores."),
                ])


def test_chunk_sizes_and_pages(files):
    from core.retrieval.extract import extract_blocks
    chunks = chunk_blocks(extract_blocks(str(files["pdf"])))
    assert len(chunks) >= 2
    assert all(c["n_tokens"] <= 520 for c in chunks)
    assert chunks[0]["page_start"] == 1 and chunks[-1]["page_end"] == 2
    assert chunks[0]["section"] == "Gradient Descent"


def test_long_paragraph_is_split():
    blocks = [{"text": "word " * 2000 + ".", "page": 1, "heading": False}]
    chunks = chunk_blocks(blocks)
    assert len(chunks) >= 4 and all(count_tokens(c["text"]) <= 520 for c in chunks)


def test_ingest_and_dedupe(files):
    fid = core.ingest_file(USER, files["pdf"])
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM files WHERE id = %s", (fid,)).fetchone()
    assert row["status"] == "ready" and row["num_pages"] == 2 and row["num_chunks"] >= 2
    assert core.ingest_file(USER, files["pdf"]) == fid  # same file twice -> same id
    core.ingest_file(USER, files["md"])


def test_empty_and_scanned(files):
    with db.connect() as conn:
        for key in ("empty", "scan"):
            fid = core.ingest_file(USER, files[key])
            assert conn.execute("SELECT status FROM files WHERE id = %s", (fid,)).fetchone()["status"] == "empty"


def test_unsupported(tmp_path):
    p = tmp_path / "x.docx"; p.write_text("hi")
    with pytest.raises(ValueError):
        core.ingest_file(USER, p)


def test_search_finds_right_file_and_page(files):
    hits = core.search(USER, "what happens when the model memorizes noise in training data", k=3)
    assert hits[0]["filename"] == "ml_notes.pdf" and hits[0]["page"] == 2
    hits = core.search(USER, "learning rate too large diverges", k=3)
    assert hits[0]["filename"] == "lecture.md" and hits[0]["page"] is None
    assert core.search("someone_else", "gradient", k=3) == []  # users never see each other's notes


def test_match_and_coverage(files, concepts):
    fid = core.ingest_file(USER, files["pdf"])
    res = core.match_file_to_concepts(USER, fid, threshold=0.3)
    got = {m["concept_id"] for m in res["matched"]}
    assert {"c_gd", "c_overfit"} <= got and "c_attention" not in got
    assert set(res) == {"matched", "suggested", "conflicts"}

    top = core.get_chunks("u1","c_overfit", k=2)
    assert top and "Overfitting" in top[0]["text"] and top[0]["page"] == 2
    assert set(top[0]) == {"text", "filename", "page", "score"}

    cov = {c["concept_id"]: c for c in core.get_file_coverage(USER)}
    assert cov["c_gd"]["files"][0]["filename"] == "ml_notes.pdf"
    assert cov["c_attention"]["files"] == []

    with db.connect() as conn:
        assert conn.execute("SELECT source FROM concepts WHERE id='c_gd'").fetchone()["source"] == "both"
    hit = core.search(USER, "overfitting memorizes noise", k=1)[0]
    assert hit["concept_id"] == "c_overfit"


def test_stubs_match_real_shapes():
    assert set(stubs.get_chunks("u","c", 1)[0]) == {"text", "filename", "page", "score"}
    assert set(stubs.search("u", "q", 1)[0]) == {"text", "filename", "page", "concept_id", "score"}
    assert set(stubs.match_file_to_concepts("u", "f")) == {"matched", "suggested", "conflicts"}
    assert set(stubs.get_file_coverage("u")[0]) == {"concept_id", "verified", "files"}
