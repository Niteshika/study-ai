-- Person 1 (Files & Retrieval) tables.
-- SQLite locally (Phases 0-3); same columns on RDS PostgreSQL from Phase 4.
-- The `concepts` table belongs to Person 2/3. The CREATE below is only a
-- local fallback so this module runs on its own; their schema wins.

CREATE TABLE IF NOT EXISTS concepts (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    name        TEXT NOT NULL,
    definition  TEXT,
    source      TEXT DEFAULT 'ai',      -- 'ai' | 'notes' | 'both'   (Person 1 updates)
    verified    INTEGER DEFAULT 0       -- 1 when notes agree with AI definition (Person 1 updates)
);

CREATE TABLE IF NOT EXISTS files (
    id           TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL,
    filename     TEXT NOT NULL,
    storage_path TEXT NOT NULL,          -- local path now, s3://bucket/key later
    sha256       TEXT NOT NULL,
    status       TEXT NOT NULL,          -- 'processing' | 'ready' | 'empty' | 'failed'
    error        TEXT,
    num_pages    INTEGER,
    num_chunks   INTEGER DEFAULT 0,
    created_at   TEXT DEFAULT CURRENT_TIMESTAMP
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
    n_tokens    INTEGER
);
CREATE INDEX IF NOT EXISTS idx_chunks_file ON chunks(file_id);

CREATE TABLE IF NOT EXISTS concept_chunks (
    concept_id  TEXT NOT NULL,
    chunk_id    TEXT NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
    score       REAL NOT NULL,
    method      TEXT DEFAULT 'embedding', -- 'embedding' | 'llm' (Phase 5)
    PRIMARY KEY (concept_id, chunk_id)
);

CREATE TABLE IF NOT EXISTS suggested_concepts (  -- Phase 6
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    file_id     TEXT NOT NULL,
    name        TEXT NOT NULL,
    chunk_ids   TEXT NOT NULL,           -- JSON list
    status      TEXT DEFAULT 'pending'   -- 'pending' | 'accepted' | 'dismissed'
);

CREATE TABLE IF NOT EXISTS conflicts (           -- Phase 7
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    concept_id  TEXT NOT NULL,
    chunk_id    TEXT NOT NULL,
    notes_says  TEXT NOT NULL,
    ai_says     TEXT NOT NULL,
    resolution  TEXT DEFAULT 'notes'     -- 'notes' (default) | 'ai' | 'both'
);
