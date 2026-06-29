-- Migration 002: agents table
-- Represents a Gruper agent node that dials outbound to this orchestrator.

CREATE TABLE IF NOT EXISTS agents (
    id               UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id         UUID         NOT NULL REFERENCES users(id),
    pubkey           TEXT         NOT NULL UNIQUE,
    x25519_pubkey    TEXT         NULL,   -- populated at gd-0.5 (WP-16)
    name             VARCHAR(64)  NOT NULL,
    location_tag     VARCHAR(64)  NULL,
    jurisdiction     VARCHAR(8)   NULL,
    capabilities     JSONB        NOT NULL,
    availability     JSONB        NULL,
    share_policies   JSONB        NOT NULL DEFAULT '[]',
    status           VARCHAR(16)  NOT NULL DEFAULT 'offline'
        CHECK (status IN ('idle','busy','offline','degraded','draining')),
    runtime_version  VARCHAR(32)  NOT NULL,
    last_seen        TIMESTAMPTZ  NULL,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    metadata         JSONB        NULL
);

CREATE INDEX IF NOT EXISTS idx_agents_owner_id ON agents(owner_id);
CREATE INDEX IF NOT EXISTS idx_agents_status   ON agents(status);
CREATE INDEX IF NOT EXISTS idx_agents_pubkey   ON agents(pubkey);
