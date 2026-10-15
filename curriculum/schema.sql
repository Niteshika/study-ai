-- Person 2 (Curriculum) writes rows here. Person 3 owns the database.
-- SQLite locally (Phases 0-3); same columns on RDS PostgreSQL from Phase 4.

-- One row per learning plan. A user can have many plans at once
-- (e.g. "DSA" and "SQL"). Each plan has its own concepts.
CREATE TABLE IF NOT EXISTS plans (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    topic       TEXT NOT NULL,
    level       TEXT,
    goal        TEXT,
    time        TEXT,
    created_at  TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_plans_user ON plans(user_id);

-- Same columns Person 1 uses (id, user_id, name, definition, source, verified)
-- plus three that plans need:
--   plan_id        which plan this concept belongs to
--   prerequisites  JSON list of concept ids from the SAME plan, e.g. '["c_ab12", "c_cd34"]'
--   position       the brief's "order" inside its plan (ORDER is a reserved SQL word)
--
-- If another module created the table first without these columns,
-- curriculum/store.py adds them, so the CREATE order doesn't matter.
CREATE TABLE IF NOT EXISTS concepts (
    id             TEXT PRIMARY KEY,
    user_id        TEXT NOT NULL,
    name           TEXT NOT NULL,
    definition     TEXT,
    source         TEXT DEFAULT 'ai',     -- 'ai' | 'notes' | 'both'  (Person 1 updates)
    verified       INTEGER DEFAULT 0,     -- Person 1 / Phase 8 updates
    plan_id        TEXT,
    prerequisites  TEXT NOT NULL DEFAULT '[]',
    position       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_concepts_user ON concepts(user_id);
