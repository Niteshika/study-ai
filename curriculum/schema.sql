-- Person 2 (Curriculum) writes rows here. Person 3 owns the database.
-- SQLite locally (Phases 0-3); same columns on RDS PostgreSQL from Phase 4.
--
-- Same columns Person 1 uses (id, user_id, name, definition, source, verified)
-- plus two that the plan needs:
--   prerequisites  JSON list of concept ids, e.g. '["c_ab12", "c_cd34"]'
--   position       the brief's "order" (ORDER is a reserved SQL word)
--
-- If another module created the table first without these two columns,
-- curriculum/store.py adds them, so the CREATE order doesn't matter.

CREATE TABLE IF NOT EXISTS concepts (
    id             TEXT PRIMARY KEY,
    user_id        TEXT NOT NULL,
    name           TEXT NOT NULL,
    definition     TEXT,
    source         TEXT DEFAULT 'ai',     -- 'ai' | 'notes' | 'both'  (Person 1 updates)
    verified       INTEGER DEFAULT 0,     -- Person 1 / Phase 8 updates
    prerequisites  TEXT NOT NULL DEFAULT '[]',
    position       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_concepts_user ON concepts(user_id);
