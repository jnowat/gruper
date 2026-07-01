-- Migration 001: users table (SQLite variant — see migrations/postgres/001_users.sql)
-- Tracks identity anchored to an ed25519 pubkey (full verification at WP-07).
-- id/created_at are always supplied by the application (see db/util.py);
-- SQLite has no gen_random_uuid()/NOW() equivalent to fall back on.

CREATE TABLE IF NOT EXISTS users (
    id               TEXT         PRIMARY KEY,
    pubkey           TEXT         NOT NULL UNIQUE,
    display_name     TEXT         NOT NULL,
    org_id           TEXT         NULL,
    recovery_method  TEXT         NULL
        CHECK (recovery_method IN ('oauth_google', 'oauth_github', 'backup_key')),
    created_at       TEXT         NOT NULL,
    metadata         TEXT         NULL
);

CREATE INDEX IF NOT EXISTS idx_users_pubkey ON users(pubkey);
