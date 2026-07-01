-- Migration 004: events table (SQLite variant — see migrations/postgres/004_events.sql)
-- Append-only audit log. Hash-chain fields (prev_hash, entry_hash) are stored
-- as NULL until WP-17 activates SHA-256 chaining (gd-0.5).

CREATE TABLE IF NOT EXISTS events (
    id                   TEXT         PRIMARY KEY,
    ts                   TEXT         NOT NULL,
    actor_id             TEXT         NOT NULL,
    action               TEXT         NOT NULL,
    subject_id           TEXT         NOT NULL,
    secondary_subject_id TEXT         NULL,
    payload_hash         TEXT         NULL,
    prev_hash            TEXT         NULL,   -- null until WP-17
    entry_hash           TEXT         NULL,   -- null until WP-17
    metadata             TEXT         NULL
);

CREATE INDEX IF NOT EXISTS idx_events_ts      ON events(ts DESC);
CREATE INDEX IF NOT EXISTS idx_events_subject ON events(subject_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_events_actor   ON events(actor_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_events_action  ON events(action, ts DESC);
