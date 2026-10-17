-- The ONE schema for the whole app (website + MCP server + workers).
-- PostgreSQL + pgvector. Safe to run many times (everything is IF NOT EXISTS).
-- Run it with:  python -m core.db init

CREATE EXTENSION IF NOT EXISTS vector;

-- ---------------------------------------------------------------- plans
-- One row per learning plan. A user can have many plans (e.g. "DSA" and "SQL").
CREATE TABLE IF NOT EXISTS plans (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    topic       TEXT NOT NULL,
    level       TEXT,
    goal        TEXT,
    time        TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_plans_user ON plans(user_id);

-- ---------------------------------------------------------------- concepts
-- Every concept belongs to exactly one plan. Deleting a plan deletes its
-- concepts, and (through concept_chunks) their links to the user's notes.
CREATE TABLE IF NOT EXISTS concepts (
    id             TEXT PRIMARY KEY,
    user_id        TEXT NOT NULL,
    plan_id        TEXT NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
    name           TEXT NOT NULL,
    definition     TEXT,
    source         TEXT NOT NULL DEFAULT 'ai',     -- 'ai' | 'notes' | 'both'
    verified       BOOLEAN NOT NULL DEFAULT false,
    prerequisites  JSONB NOT NULL DEFAULT '[]',    -- concept ids from the SAME plan
    position       INTEGER NOT NULL DEFAULT 0,     -- learning order inside the plan
    embedding      vector,                         -- of "name: definition", for matching notes
    embedding_key  TEXT                            -- md5 of the embedded text; re-embed when it changes
);
CREATE INDEX IF NOT EXISTS idx_concepts_user ON concepts(user_id);
CREATE INDEX IF NOT EXISTS idx_concepts_plan ON concepts(plan_id);

-- ---------------------------------------------------------------- files and chunks
CREATE TABLE IF NOT EXISTS files (
    id           TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL,
    filename     TEXT NOT NULL,
    storage_path TEXT NOT NULL,          -- s3://bucket/key, or a local path in dev/tests
    sha256       TEXT NOT NULL,
    status       TEXT NOT NULL,          -- 'processing' | 'ready' | 'empty' | 'failed'
    error        TEXT,
    num_pages    INTEGER,
    num_chunks   INTEGER NOT NULL DEFAULT 0,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_files_user ON files(user_id);

-- Only the user's real material. Never AI-generated text.
CREATE TABLE IF NOT EXISTS chunks (
    id          TEXT PRIMARY KEY,
    file_id     TEXT NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    user_id     TEXT NOT NULL,
    idx         INTEGER NOT NULL,        -- order within the file
    text        TEXT NOT NULL,
    section     TEXT,                    -- nearest heading, if any
    page_start  INTEGER,
    page_end    INTEGER,
    n_tokens    INTEGER,
    embedding   vector NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunks_file ON chunks(file_id);
CREATE INDEX IF NOT EXISTS idx_chunks_user ON chunks(user_id);
-- Note: no HNSW vector index yet. It needs a fixed vector size, which depends
-- on the embedding provider (OpenAI 1536, Gemini 768). Add it once you pick one.

CREATE TABLE IF NOT EXISTS concept_chunks (
    concept_id  TEXT NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
    chunk_id    TEXT NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
    score       REAL NOT NULL,
    method      TEXT NOT NULL DEFAULT 'embedding',   -- 'embedding' | 'llm'
    PRIMARY KEY (concept_id, chunk_id)
);

-- ---------------------------------------------------------------- later phases
CREATE TABLE IF NOT EXISTS suggested_concepts (     -- notes topics not in the plan
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    file_id     TEXT NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    chunk_ids   JSONB NOT NULL DEFAULT '[]',
    status      TEXT NOT NULL DEFAULT 'pending'    -- 'pending' | 'accepted' | 'dismissed'
);

CREATE TABLE IF NOT EXISTS conflicts (              -- notes disagree with the AI definition
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    concept_id  TEXT NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
    chunk_id    TEXT NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
    notes_says  TEXT NOT NULL,
    ai_says     TEXT NOT NULL,
    resolution  TEXT NOT NULL DEFAULT 'notes'      -- 'notes' | 'ai' | 'both'
);
