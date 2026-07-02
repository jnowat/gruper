-- Migration 005: agent soft delete (SQLite variant — see migrations/postgres/005_agent_soft_delete.sql)
-- A deleted agent keeps its row (tasks reference assigned_agent_id, and the
-- events audit trail must stay coherent) but is excluded from every listing,
-- cannot re-register over the WebSocket, and cannot be assigned new tasks.
-- NULL = live agent; an ISO-8601 timestamp = when the owner removed it.

ALTER TABLE agents ADD COLUMN deleted_at TEXT NULL;
