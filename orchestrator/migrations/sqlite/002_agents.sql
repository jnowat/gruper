-- Migration 002: agents table (SQLite variant — see migrations/postgres/002_agents.sql)
-- Represents a Gruper agent node that dials outbound to this orchestrator.
-- JSONB columns become TEXT (JSON-encoded); encode/decode happens at the
-- db/sqlite.py boundary, not in this schema.

CREATE TABLE IF NOT EXISTS agents (
    id               TEXT         PRIMARY KEY,
    owner_id         TEXT         NOT NULL REFERENCES users(id),
    pubkey           TEXT         NOT NULL UNIQUE,
    x25519_pubkey    TEXT         NULL,   -- populated at gd-0.5 (WP-16)
    name             TEXT         NOT NULL,
    location_tag     TEXT         NULL,
    jurisdiction     TEXT         NULL,
    capabilities     TEXT         NOT NULL,
    availability     TEXT         NULL,
    share_policies   TEXT         NOT NULL DEFAULT '[]',
    status           TEXT         NOT NULL DEFAULT 'offline'
        CHECK (status IN ('idle','busy','offline','degraded','draining')),
    runtime_version  TEXT         NOT NULL,
    last_seen        TEXT         NULL,
    created_at       TEXT         NOT NULL,
    metadata         TEXT         NULL
);

CREATE INDEX IF NOT EXISTS idx_agents_owner_id ON agents(owner_id);
CREATE INDEX IF NOT EXISTS idx_agents_status   ON agents(status);
CREATE INDEX IF NOT EXISTS idx_agents_pubkey   ON agents(pubkey);
