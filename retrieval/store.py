"""Storage for Phases 0-3: SQLite for rows, ChromaDB for vectors, a folder for files.

Phase 4 swaps these for RDS PostgreSQL + pgvector + S3. Only this file
should need to change; core.py talks to storage through these helpers.
"""

import os
import shutil
import sqlite3
from pathlib import Path

import chromadb

DATA_DIR = Path(os.getenv("DATA_DIR", "data"))
DB_PATH = Path(os.getenv("DB_PATH", DATA_DIR / "study.db"))
UPLOAD_DIR = DATA_DIR / "uploads"
CHROMA_DIR = DATA_DIR / "chroma"
_SCHEMA = Path(__file__).with_name("schema.sql")

_chroma = None


def db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA.read_text())
    return conn


def _client():
    global _chroma
    if _chroma is None:
        CHROMA_DIR.mkdir(parents=True, exist_ok=True)
        _chroma = chromadb.PersistentClient(path=str(CHROMA_DIR))
    return _chroma


def chunk_vectors():
    return _client().get_or_create_collection("chunks", metadata={"hnsw:space": "cosine"})


def concept_vectors():
    return _client().get_or_create_collection("concepts", metadata={"hnsw:space": "cosine"})


def save_upload(src_path, file_id, filename):
    """Copy the upload into storage and return where it lives (S3 key later)."""
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    dest = UPLOAD_DIR / f"{file_id}_{filename}"
    shutil.copyfile(src_path, dest)
    return str(dest)
