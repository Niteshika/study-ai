"""Person 1: Files & Retrieval. The real versions of the five contract functions."""

import hashlib
import json
import os
import uuid
from pathlib import Path

import llm
from . import store
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
    conn = store.db()
    dup = conn.execute("SELECT id FROM files WHERE user_id=? AND sha256=? AND status!='failed'",
                       (user_id, sha)).fetchone()
    if dup:
        return dup["id"]

    file_id = "file_" + uuid.uuid4().hex[:12]
    storage_path = store.save_upload(path, file_id, path.name)
    conn.execute("INSERT INTO files (id, user_id, filename, storage_path, sha256, status) VALUES (?,?,?,?,?,?)",
                 (file_id, user_id, path.name, storage_path, sha, "processing"))
    conn.commit()

    try:
        blocks = extract_blocks(storage_path)
        pages = pdf_page_count(storage_path) if path.suffix.lower() == ".pdf" else None
        chunks = chunk_blocks(blocks)
        if not chunks:
            # Scanned PDFs land here until Textract OCR is added (Phase 11).
            status = "empty"
            conn.execute("UPDATE files SET status=?, num_pages=?, error=? WHERE id=?",
                         (status, pages, "No text found (scanned PDF or empty file)", file_id))
            conn.commit()
            return file_id

        rows = [{"id": f"{file_id}_c{i}", "idx": i, **c} for i, c in enumerate(chunks)]
        vectors = llm.embed([_embed_text(r, path.name) for r in rows], kind="document")
        store.chunk_vectors().add(
            ids=[r["id"] for r in rows],
            embeddings=vectors,
            documents=[r["text"] for r in rows],
            metadatas=[{"user_id": user_id, "file_id": file_id, "filename": path.name,
                        "page": r["page_start"] if r["page_start"] is not None else -1} for r in rows],
        )
        conn.executemany(
            "INSERT INTO chunks (id, file_id, user_id, idx, text, section, page_start, page_end, n_tokens) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            [(r["id"], file_id, user_id, r["idx"], r["text"], r["section"],
              r["page_start"], r["page_end"], r["n_tokens"]) for r in rows])
        conn.execute("UPDATE files SET status='ready', num_pages=?, num_chunks=? WHERE id=?",
                     (pages, len(rows), file_id))
        conn.commit()
    except Exception as e:
        conn.execute("UPDATE files SET status='failed', error=? WHERE id=?", (str(e)[:500], file_id))
        conn.commit()
        raise
    finally:
        conn.close()
    return file_id


def _embed_text(chunk, filename):
    # Adding the section heading gives short chunks more context to match on.
    head = f"{chunk['section']}\n" if chunk.get("section") and not chunk["text"].startswith(chunk["section"]) else ""
    return head + chunk["text"]


# ---------------------------------------------------------------- concept matching

def match_file_to_concepts(user_id, file_id, threshold=None):
    """Link this file's chunks to the user's concepts by embedding similarity.

    Returns {
      matched:   [{concept_id, chunk_ids, score}]   best score per concept
      suggested: [{id, name, chunk_ids}]            Phase 6 (empty for now)
      conflicts: [{id, concept_id, chunk_id, notes_says, ai_says}]  Phase 7 (empty for now)
    }
    """
    threshold = MATCH_THRESHOLD if threshold is None else threshold
    conn = store.db()
    concepts = conn.execute("SELECT id, name, definition, source FROM concepts WHERE user_id=?",
                            (user_id,)).fetchall()
    got = store.chunk_vectors().get(where={"file_id": file_id}, include=["embeddings"])
    if not concepts or not got["ids"]:
        conn.close()
        return {"matched": [], "suggested": [], "conflicts": []}

    cvecs = _concept_vectors(concepts)
    links = {}  # concept_id -> [(chunk_id, score)]
    for chunk_id, vec in zip(got["ids"], got["embeddings"]):
        for c in concepts:
            score = _dot(vec, cvecs[c["id"]])
            if score >= threshold:
                links.setdefault(c["id"], []).append((chunk_id, score))

    for cid, pairs in links.items():
        conn.executemany(
            "INSERT INTO concept_chunks (concept_id, chunk_id, score, method) VALUES (?,?,?,'embedding') "
            "ON CONFLICT(concept_id, chunk_id) DO UPDATE SET score=excluded.score",
            [(cid, ch, round(s, 4)) for ch, s in pairs])
        conn.execute("UPDATE concepts SET source = CASE WHEN source IN ('ai','both') THEN 'both' ELSE 'notes' END "
                     "WHERE id=?", (cid,))
    conn.commit()

    matched = []
    for cid, pairs in links.items():
        pairs.sort(key=lambda p: -p[1])
        matched.append({"concept_id": cid, "chunk_ids": [p[0] for p in pairs], "score": round(pairs[0][1], 4)})
    matched.sort(key=lambda m: -m["score"])

    suggested = [{"id": r["id"], "name": r["name"], "chunk_ids": json.loads(r["chunk_ids"])}
                 for r in conn.execute("SELECT * FROM suggested_concepts WHERE file_id=?", (file_id,))]
    conflicts = [dict(r) for r in conn.execute(
        "SELECT x.id, x.concept_id, x.chunk_id, x.notes_says, x.ai_says FROM conflicts x "
        "JOIN chunks ch ON ch.id = x.chunk_id WHERE ch.file_id=?", (file_id,))]
    conn.close()
    return {"matched": matched, "suggested": suggested, "conflicts": conflicts}


def _concept_vectors(concepts):
    """Embed '<name>: <definition>' per concept, cached in Chroma; re-embeds if the text changed."""
    col = store.concept_vectors()
    texts = {c["id"]: f"{c['name']}: {c['definition'] or ''}".strip() for c in concepts}
    keys = {cid: hashlib.md5(t.encode()).hexdigest() for cid, t in texts.items()}
    have = col.get(ids=list(texts), include=["embeddings", "metadatas"])
    out = {}
    for cid, vec, meta in zip(have["ids"], have["embeddings"], have["metadatas"]):
        if meta.get("key") == keys[cid]:
            out[cid] = list(vec)
    missing = [cid for cid in texts if cid not in out]
    if missing:
        vecs = llm.embed([texts[cid] for cid in missing], kind="query")
        col.upsert(ids=missing, embeddings=vecs, metadatas=[{"key": keys[cid]} for cid in missing])
        out.update(zip(missing, vecs))
    return out


def _dot(a, b):
    # Vectors are unit length, so dot product = cosine similarity.
    return float(sum(x * y for x, y in zip(a, b)))


# ---------------------------------------------------------------- retrieval

def get_chunks(concept_id, k=5):
    """Passages from the user's notes linked to this concept, best first.
    Returns [{text, filename, page, score}]. Empty list if no notes cover it."""
    conn = store.db()
    rows = conn.execute(
        "SELECT ch.text, f.filename, ch.page_start AS page, cc.score FROM concept_chunks cc "
        "JOIN chunks ch ON ch.id = cc.chunk_id JOIN files f ON f.id = ch.file_id "
        "WHERE cc.concept_id=? ORDER BY cc.score DESC LIMIT ?", (concept_id, k)).fetchall()
    conn.close()
    return [{"text": r["text"], "filename": r["filename"], "page": r["page"], "score": round(r["score"], 4)}
            for r in rows]


def search(user_id, query, k=5):
    """Free-text search over all of this user's files.
    Returns [{text, filename, page, concept_id, score}]. concept_id is the best linked
    concept for that chunk, or None if the chunk isn't linked to any."""
    col = store.chunk_vectors()
    if col.count() == 0:
        return []
    qvec = llm.embed([query], kind="query")[0]
    res = col.query(query_embeddings=[qvec], n_results=k, where={"user_id": user_id},
                    include=["documents", "metadatas", "distances"])
    ids = res["ids"][0]
    if not ids:
        return []
    conn = store.db()
    marks = ",".join("?" * len(ids))
    best = {r["chunk_id"]: r["concept_id"] for r in conn.execute(
        f"SELECT chunk_id, concept_id, MAX(score) FROM concept_chunks WHERE chunk_id IN ({marks}) "
        f"GROUP BY chunk_id", ids)}
    conn.close()
    out = []
    for cid, doc, meta, dist in zip(ids, res["documents"][0], res["metadatas"][0], res["distances"][0]):
        out.append({"text": doc, "filename": meta["filename"],
                    "page": None if meta["page"] == -1 else meta["page"],
                    "concept_id": best.get(cid), "score": round(1 - dist, 4)})
    return out


def get_file_coverage(user_id):
    """One row per concept, for the files column in the UI.
    Returns [{concept_id, verified, files: [{file_id, filename, chunks}]}]."""
    conn = store.db()
    concepts = conn.execute("SELECT id, verified FROM concepts WHERE user_id=?", (user_id,)).fetchall()
    rows = conn.execute(
        "SELECT cc.concept_id, f.id AS file_id, f.filename, COUNT(*) AS n FROM concept_chunks cc "
        "JOIN chunks ch ON ch.id = cc.chunk_id JOIN files f ON f.id = ch.file_id "
        "WHERE f.user_id=? GROUP BY cc.concept_id, f.id ORDER BY n DESC", (user_id,)).fetchall()
    conn.close()
    files = {}
    for r in rows:
        files.setdefault(r["concept_id"], []).append(
            {"file_id": r["file_id"], "filename": r["filename"], "chunks": r["n"]})
    return [{"concept_id": c["id"], "verified": bool(c["verified"]), "files": files.get(c["id"], [])}
            for c in concepts]
