-- Migration 003: tasks table (SQLite variant — see migrations/postgres/003_tasks.sql)
-- Dispatch claiming uses a single atomic UPDATE instead of PostgreSQL's
-- FOR UPDATE SKIP LOCKED (see dispatcher.py) — SQLite serializes all writes
-- through one connection, so no row-level lock hint is needed or available.

CREATE TABLE IF NOT EXISTS tasks (
    id                  TEXT         PRIMARY KEY,
    correlation_id      TEXT         NULL,
    submitter_id        TEXT         NOT NULL REFERENCES users(id),
    assigned_agent_id   TEXT         NOT NULL REFERENCES agents(id),
    parent_task_id      TEXT         NULL REFERENCES tasks(id),
    share_token_id      TEXT         NULL,
    data_class          TEXT         NOT NULL
        CHECK (data_class IN ('public','internal','confidential')),
    input               TEXT         NOT NULL,
    allowed_tools       TEXT         NOT NULL DEFAULT '[]',
    status              TEXT         NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','dispatched','running','complete','failed','timed_out','dead_letter')),
    priority            INTEGER      NOT NULL DEFAULT 50
        CHECK (priority BETWEEN 0 AND 100),
    deadline            TEXT         NULL,
    timeout_s           INTEGER      NOT NULL DEFAULT 300
        CHECK (timeout_s BETWEEN 60 AND 86400),
    retry_count         INTEGER      NOT NULL DEFAULT 0,
    created_at          TEXT         NOT NULL,
    dispatched_at       TEXT         NULL,
    completed_at        TEXT         NULL,
    result              TEXT         NULL,
    error               TEXT         NULL,
    logs_ref            TEXT         NULL,
    cost_cents          INTEGER      NULL,
    audit_hash          TEXT         NULL,
    UNIQUE (submitter_id, correlation_id)
);

-- Partial index for the single-writer dispatch queue: pending tasks only,
-- priority-first FIFO. Same shape as the PostgreSQL SKIP LOCKED index —
-- SQLite supports partial indexes natively (3.8.0+).
CREATE INDEX IF NOT EXISTS idx_tasks_queue
    ON tasks(priority DESC, created_at ASC)
    WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_tasks_assigned_agent
    ON tasks(assigned_agent_id, status);

CREATE INDEX IF NOT EXISTS idx_tasks_submitter
    ON tasks(submitter_id, status);

CREATE INDEX IF NOT EXISTS idx_tasks_correlation
    ON tasks(submitter_id, correlation_id)
    WHERE correlation_id IS NOT NULL;
