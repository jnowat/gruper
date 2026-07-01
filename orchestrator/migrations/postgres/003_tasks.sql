-- Migration 003: tasks table
-- SKIP LOCKED pattern: workers SELECT FOR UPDATE SKIP LOCKED on status='pending'.
-- Priority DESC + created_at ASC partial index enables fair, high-priority-first dispatch.

CREATE TABLE IF NOT EXISTS tasks (
    id                  UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    correlation_id      UUID         NULL,
    submitter_id        UUID         NOT NULL REFERENCES users(id),
    assigned_agent_id   UUID         NOT NULL REFERENCES agents(id),
    parent_task_id      UUID         NULL REFERENCES tasks(id),
    share_token_id      UUID         NULL,
    data_class          VARCHAR(16)  NOT NULL
        CHECK (data_class IN ('public','internal','confidential')),
    input               JSONB        NOT NULL,
    allowed_tools       JSONB        NOT NULL DEFAULT '[]',
    status              VARCHAR(16)  NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','dispatched','running','complete','failed','timed_out','dead_letter')),
    priority            INTEGER      NOT NULL DEFAULT 50
        CHECK (priority BETWEEN 0 AND 100),
    deadline            TIMESTAMPTZ  NULL,
    timeout_s           INTEGER      NOT NULL DEFAULT 300
        CHECK (timeout_s BETWEEN 60 AND 86400),
    retry_count         INTEGER      NOT NULL DEFAULT 0,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    dispatched_at       TIMESTAMPTZ  NULL,
    completed_at        TIMESTAMPTZ  NULL,
    result              JSONB        NULL,
    error               JSONB        NULL,
    logs_ref            TEXT         NULL,
    cost_cents          INTEGER      NULL,
    audit_hash          VARCHAR(64)  NULL,
    UNIQUE (submitter_id, correlation_id)
);

-- Partial index for the SKIP LOCKED queue: pending tasks only, priority-first FIFO.
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
