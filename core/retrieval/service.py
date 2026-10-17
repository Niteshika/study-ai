"""Files & retrieval: upload notes, chunk them, embed them, link them to concepts.

Storage: rows and vectors both live in Postgres (pgvector). Files go to S3
(or a local folder when S3_BUCKET isn't set). See core/db.py and core/storage.py.
"""

import hashlib
import os
import uuid
from pathlib import Path

from core import db, llm, storage
from core.db import vec
from .chunker import chunk_blocks
from .extract import SUPPORTED, UnsupportedFile, extract_blocks, pdf_page_count

MATCH_THRESHOLD = float(os.getenv("MATCH_THRESHOLD", "0.5"))
MAX_FILE_MB = float(os.getenv("MAX_FILE_MB", "50"))


# ---------------------------------------------------------------- ingest

def ingest_file(user_id, file_path):
    """Store the file, chunk it, embed the chunks. Returns file_id.

    Check files.status afterwards: 'ready' | 'empty' | 'failed' (error in files.error).
    Uploading the same file twice returns the first file_id.
    """
    path = Path(file_path)
    if path.suffix.lower() not in SUPPORTED:
        raise UnsupportedFile(f"Unsupported file type '{path.suffix}'")
    if path.stat().st_size > MAX_FILE_MB * 1024 * 1024:
        raise ValueError(f"File is larger than {MAX_FILE_MB:.0f} MB")

    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    with db.connect() as conn:
        dup = conn.execute("SELECT id FROM files WHERE user_id = %s AND sha256 = %s AND status != 'failed'",
                           (user_id, sha)).fetchone()
        if dup:
            return dup["id"]

        file_id = "file_" + uuid.uuid4().hex[:12]
        storage_path = storage.save_upload(path, file_id, path.name)
        conn.execute("INSERT INTO files (id, user_id, filename, storage_path, sha256, status) "
                     "VALUES (%s, %s, %s, %s, %s, 'processing')",
                     (file_id, user_id, path.name, storage_path, sha))

        try:
            # Read from the local copy we were given; the stored copy may be in S3.
            blocks = extract_blocks(str(path))
            pages = pdf_page_count(str(path)) if path.suffix.lower() == ".pdf" else None
            chunks = chunk_blocks(blocks)
            if not chunks:
                # Scanned PDFs land here until Textract OCR is added.
                conn.execute("UPDATE files SET status = 'empty', num_pages = %s, error = %s WHERE id = %s",
                             (pages, "No text found (scanned PDF or empty file)", file_id))
                return file_id

            rows = [{"id": f"{file_id}_c{i}", "idx": i, **c} for i, c in enumerate(chunks)]
            vectors = llm.embed([_embed_text(r) for r in rows], kind="document")
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.executemany(
                        "INSERT INTO chunks (id, file_id, user_id, idx, text, section, page_start,"
                        " page_end, n_tokens, embedding) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        [(r["id"], file_id, user_id, r["idx"], r["text"], r["section"],
                          r["page_start"], r["page_end"], r["n_tokens"], vec(v))
                         for r, v in zip(rows, vectors)])
                conn.execute("UPDATE files SET status = 'ready', num_pages = %s, num_chunks = %s WHERE id = %s",
                             (pages, len(rows), file_id))
        except Exception as e:
            conn.execute("UPDATE files SET status = 'failed', error = %s WHERE id = %s",
                         (str(e)[:500], file_id))
            raise
    return file_id


def _embed_text(chunk):
    # Adding the section heading gives short chunks more context to match on.
    head = f"{chunk['section']}\n" if chunk.get("section") and not chunk["text"].startswith(chunk["section"]) else ""
    return head + chunk["text"]


# ---------------------------------------------------------------- concept matching

def match_file_to_concepts(user_id, file_id, threshold=None):
    """Link this file's chunks to the user's concepts by embedding similarity.

    Returns {
      matched:   [{concept_id, chunk_ids, score}]   best score per concept
      suggested: [{id, name, chunk_ids}]            later phase (empty for now)
      conflicts: [{id, concept_id, chunk_id, notes_says, ai_says}]  later phase (empty for now)
    }
    """
    threshold = MATCH_THRESHOLD if threshold is None else threshold
    with db.connect() as conn:
        _ensure_concept_vectors(conn, user_id)
        # Postgres does the similarity maths. <=> is cosine distance, so 1 - distance = similarity.
        pairs = conn.execute(
            "SELECT c.id AS concept_id, ch.id AS chunk_id,"
            "       1 - (ch.embedding <=> c.embedding) AS score"
            "  FROM chunks ch JOIN concepts c ON c.user_id = ch.user_id"
            " WHERE ch.file_id = %s AND ch.user_id = %s AND c.embedding IS NOT NULL"
            "   AND 1 - (ch.embedding <=> c.embedding) >= %s"
            " ORDER BY score DESC",
            (file_id, user_id, threshold)).fetchall()

        with conn.transaction():
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO concept_chunks (concept_id, chunk_id, score, method)"
                    " VALUES (%s, %s, %s, 'embedding')"
                    " ON CONFLICT (concept_id, chunk_id) DO UPDATE SET score = excluded.score",
                    [(p["concept_id"], p["chunk_id"], round(p["score"], 4)) for p in pairs])
            ids = sorted({p["concept_id"] for p in pairs})
            if ids:
                conn.execute("UPDATE concepts SET source = CASE WHEN source IN ('ai','both') THEN 'both'"
                             " ELSE 'notes' END WHERE id = ANY(%s)", (ids,))

        matched = {}
        for p in pairs:  # already best-first
            m = matched.setdefault(p["concept_id"], {"concept_id": p["concept_id"], "chunk_ids": [],
                                                     "score": round(p["score"], 4)})
            m["chunk_ids"].append(p["chunk_id"])

        suggested = [{"id": r["id"], "name": r["name"], "chunk_ids": r["chunk_ids"]}
                     for r in conn.execute("SELECT * FROM suggested_concepts WHERE file_id = %s", (file_id,))]
        conflicts = conn.execute(
            "SELECT x.id, x.concept_id, x.chunk_id, x.notes_says, x.ai_says FROM conflicts x "
            "JOIN chunks ch ON ch.id = x.chunk_id WHERE ch.file_id = %s", (file_id,)).fetchall()
    return {"matched": list(matched.values()), "suggested": suggested, "conflicts": conflicts}


def _ensure_concept_vectors(conn, user_id):
    """Embed '<name>: <definition>' for any concept that has no vector yet,
    or whose name/definition changed since it was embedded."""
    rows = conn.execute("SELECT id, name, definition, embedding_key FROM concepts WHERE user_id = %s",
                        (user_id,)).fetchall()
    todo = []
    for r in rows:
        text = f"{r['name']}: {r['definition'] or ''}".strip()
        key = hashlib.md5(text.encode()).hexdigest()
        if r["embedding_key"] != key:
            todo.append((r["id"], text, key))
    if not todo:
        return
    vectors = llm.embed([t for _, t, _ in todo], kind="query")
    with conn.cursor() as cur:
        cur.executemany("UPDATE concepts SET embedding = %s, embedding_key = %s WHERE id = %s",
                        [(vec(v), key, cid) for (cid, _, key), v in zip(todo, vectors)])


# ---------------------------------------------------------------- retrieval

def get_chunks(user_id, concept_id, k=5):
    """Passages from the user's notes linked to this concept, best first.
    Returns [{text, filename, page, score}]. Empty list if no notes cover it."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT ch.text, f.filename, ch.page_start AS page, cc.score FROM concept_chunks cc "
            "JOIN concepts c ON c.id = cc.concept_id "
            "JOIN chunks ch ON ch.id = cc.chunk_id JOIN files f ON f.id = ch.file_id "
            "WHERE cc.concept_id = %s AND c.user_id = %s AND ch.user_id = %s "
            "ORDER BY cc.score DESC LIMIT %s",
            (concept_id, user_id, user_id, k)).fetchall()
    return [{**r, "score": round(r["score"], 4)} for r in rows]


def search(user_id, query, k=5):
    """Free-text search over all of this user's files.
    Returns [{text, filename, page, concept_id, score}]. concept_id is the best linked
    concept for that chunk, or None if the chunk isn't linked to any."""
    with db.connect() as conn:
        has_any = conn.execute("SELECT 1 FROM chunks WHERE user_id = %s LIMIT 1", (user_id,)).fetchone()
        if not has_any:
            return []
        qvec = vec(llm.embed([query], kind="query")[0])
        rows = conn.execute(
            "SELECT ch.text, f.filename, ch.page_start AS page,"
            "       1 - (ch.embedding <=> %s) AS score,"
            "       (SELECT cc.concept_id FROM concept_chunks cc WHERE cc.chunk_id = ch.id"
            "         ORDER BY cc.score DESC LIMIT 1) AS concept_id"
            "  FROM chunks ch JOIN files f ON f.id = ch.file_id"
            " WHERE ch.user_id = %s"
            " ORDER BY ch.embedding <=> %s LIMIT %s",
            (qvec, user_id, qvec, k)).fetchall()
    return [{"text": r["text"], "filename": r["filename"], "page": r["page"],
             "concept_id": r["concept_id"], "score": round(r["score"], 4)} for r in rows]


def get_file_coverage(user_id):
    """One row per concept, for the files column in the UI.
    Returns [{concept_id, verified, files: [{file_id, filename, chunks}]}]."""
    with db.connect() as conn:
        concepts = conn.execute("SELECT id, verified FROM concepts WHERE user_id = %s",
                                (user_id,)).fetchall()
        rows = conn.execute(
            "SELECT cc.concept_id, f.id AS file_id, f.filename, COUNT(*)::int AS n FROM concept_chunks cc "
            "JOIN chunks ch ON ch.id = cc.chunk_id JOIN files f ON f.id = ch.file_id "
            "WHERE f.user_id = %s GROUP BY cc.concept_id, f.id, f.filename ORDER BY n DESC",
            (user_id,)).fetchall()
    files = {}
    for r in rows:
        files.setdefault(r["concept_id"], []).append(
            {"file_id": r["file_id"], "filename": r["filename"], "chunks": r["n"]})
    return [{"concept_id": c["id"], "verified": bool(c["verified"]), "files": files.get(c["id"], [])}
            for c in concepts]
