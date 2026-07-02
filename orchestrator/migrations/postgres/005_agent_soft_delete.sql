-- Migration 005: agent soft delete
-- A deleted agent keeps its row (tasks reference assigned_agent_id, and the
-- events audit trail must stay coherent) but is excluded from every listing,
-- cannot re-register over the WebSocket, and cannot be assigned new tasks.
-- NULL = live agent; a timestamp = when the owner removed it.

ALTER TABLE agents ADD COLUMN deleted_at TIMESTAMPTZ NULL;
