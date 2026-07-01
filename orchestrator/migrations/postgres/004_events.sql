-- Migration 004: events table
-- Append-only audit log. Hash-chain fields (prev_hash, entry_hash) are stored
-- as NULL until WP-17 activates SHA-256 chaining (gd-0.5).

CREATE TABLE IF NOT EXISTS events (
    id                   UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    ts                   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    actor_id             UUID         NOT NULL,
    action               VARCHAR(64)  NOT NULL,
    subject_id           UUID         NOT NULL,
    secondary_subject_id UUID         NULL,
    payload_hash         VARCHAR(64)  NULL,
    prev_hash            VARCHAR(64)  NULL,   -- null until WP-17
    entry_hash           VARCHAR(64)  NULL,   -- null until WP-17
    metadata             JSONB        NULL
);

CREATE INDEX IF NOT EXISTS idx_events_ts      ON events(ts DESC);
CREATE INDEX IF NOT EXISTS idx_events_subject ON events(subject_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_events_actor   ON events(actor_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_events_action  ON events(action, ts DESC);
