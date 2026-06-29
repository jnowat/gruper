-- Migration 001: users table
-- Tracks identity anchored to an ed25519 pubkey (full verification at WP-07).

CREATE TABLE IF NOT EXISTS users (
    id               UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    pubkey           TEXT         NOT NULL UNIQUE,
    display_name     VARCHAR(64)  NOT NULL,
    org_id           UUID         NULL,
    recovery_method  VARCHAR(32)  NULL
        CHECK (recovery_method IN ('oauth_google', 'oauth_github', 'backup_key')),
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    metadata         JSONB        NULL
);

CREATE INDEX IF NOT EXISTS idx_users_pubkey ON users(pubkey);
