"""Shared test setup. Tests run against a REAL Postgres + pgvector database.

Start one locally (Docker) and point TEST_DATABASE_URL at it:

    docker run -d --name studyai-pg -e POSTGRES_PASSWORD=pw -e POSTGRES_DB=studyai_test \\
        -p 5432:5432 pgvector/pgvector:pg17
    export TEST_DATABASE_URL=postgresql://postgres:pw@localhost:5432/studyai_test
    pytest -q

Never point this at your real RDS database: every test wipes the tables.
"""

import os
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp())
# Must be set before anything imports core.llm (it reads LLM_PROVIDER once).
os.environ["LLM_PROVIDER"] = "fake"
os.environ["DATA_DIR"] = str(TMP / "data")
os.environ.pop("S3_BUCKET", None)          # tests store uploads in a temp folder
os.environ.pop("CURRICULUM_FAKE", None)
os.environ.pop("RETRIEVAL_STUB", None)
os.environ["DATABASE_URL"] = os.getenv(
    "TEST_DATABASE_URL", "postgresql://postgres:pw@localhost:5432/studyai_test")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psycopg  # noqa: E402
import pytest  # noqa: E402

from core import db  # noqa: E402

TABLES = "conflicts, suggested_concepts, concept_chunks, chunks, files, concepts, plans"


@pytest.fixture(scope="session", autouse=True)
def _schema():
    try:
        db.init_db()
    except psycopg.OperationalError as e:
        pytest.exit(f"No test database at {os.environ['DATABASE_URL']} ({e}). "
                    "See tests/conftest.py for how to start one.", returncode=2)
    yield
    db.close_pool()


def wipe():
    with db.connect() as conn:
        conn.execute(f"TRUNCATE {TABLES} CASCADE")


@pytest.fixture
def conn():
    """A clean database and an open connection, for one test."""
    wipe()
    with db.connect() as c:
        yield c
