"""The one database module. Everything (website, MCP server, workers) uses this.

Where the database is comes from DATABASE_URL, e.g.
    postgresql://postgres:PASSWORD@my-db.xxxx.ap-south-1.rds.amazonaws.com:5432/studyai?sslmode=require

On EC2 you can instead set DB_SECRET_ID to the RDS secret's name (rds!db-...)
plus DB_HOST; the password is then read from Secrets Manager at startup.

Usage:
    from core import db
    with db.connect() as conn:
        conn.execute("SELECT ... WHERE id = %s", (some_id,)).fetchone()   # -> dict

    python -m core.db init     # create the tables (safe to re-run)
    python -m core.db check    # print Postgres + pgvector versions
"""

import json
import os
import sys
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

import numpy as np
import psycopg
from dotenv import load_dotenv
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

load_dotenv()

SCHEMA = Path(__file__).with_name("schema.sql")

__all__ = ["connect", "close_pool", "init_db", "vec", "Jsonb", "table_exists"]


@lru_cache(maxsize=1)
def database_url() -> str:
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    secret_id = os.getenv("DB_SECRET_ID")
    if secret_id:
        # RDS-managed secret holds {"username": ..., "password": ...}.
        import boto3
        sm = boto3.client("secretsmanager", region_name=os.getenv("AWS_REGION", "ap-south-1"))
        s = json.loads(sm.get_secret_value(SecretId=secret_id)["SecretString"])
        host = os.environ["DB_HOST"]
        name = os.getenv("DB_NAME", "studyai")
        return (f"postgresql://{quote(s['username'])}:{quote(s['password'])}@{host}:5432/{name}"
                "?sslmode=require")
    raise RuntimeError("Set DATABASE_URL (or DB_SECRET_ID + DB_HOST). See .env.example.")


_pool: ConnectionPool | None = None


def _get_pool() -> ConnectionPool:
    """One pool per process, opened on first use.

    The server keeps a few connections open and reuses them, instead of paying
    for a new connection (network + SSL + login) on every request. It never
    opens more than DB_POOL_SIZE, so Postgres is never overloaded.
    """
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            conninfo=database_url(),
            min_size=1,
            max_size=int(os.getenv("DB_POOL_SIZE", "5")),
            kwargs={"row_factory": dict_row, "autocommit": True},
            configure=register_vector,   # runs once per new connection
            check=ConnectionPool.check_connection,  # skip connections the DB closed
            open=True,
        )
    return _pool


def connect():
    """Borrow a connection from the pool. Rows come back as dicts.

    Always use it as `with db.connect() as conn:` - the connection goes back
    to the pool at the end of the block (it is not closed).

    Autocommit is ON: each statement is saved straight away. For several
    statements that must succeed or fail together, use:
        with conn.transaction():
            ...
    """
    return _get_pool().connection()


def close_pool() -> None:
    """Close all pooled connections. Called when the server shuts down."""
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def init_db() -> None:
    """Create the extension and all tables. Safe to run many times."""
    with psycopg.connect(database_url(), autocommit=True) as conn:
        conn.execute(SCHEMA.read_text())


def vec(values) -> np.ndarray:
    """Turn a list of floats (from llm.embed) into something pgvector can store."""
    return np.asarray(values, dtype=np.float32)


def table_exists(conn, name: str) -> bool:
    return conn.execute("SELECT to_regclass(%s) IS NOT NULL AS ok", (name,)).fetchone()["ok"]


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd == "init":
        init_db()
        print("Tables created (or already there).")
    with connect() as c:
        pg = c.execute("SHOW server_version").fetchone()["server_version"]
        v = c.execute("SELECT extversion FROM pg_extension WHERE extname='vector'").fetchone()
        print(f"Postgres {pg}, pgvector {v['extversion'] if v else 'NOT INSTALLED'}")
