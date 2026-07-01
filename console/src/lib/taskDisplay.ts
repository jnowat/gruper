// Shared plain-language vocabulary for task and agent states — one map, used by
// every pane. Before this existed, the History list printed raw enum values
// ("dispatched", "dead_letter") while ResultView showed friendly words for the
// same task one pane to the right; the two literally disagreed on screen.
// Internal enum values stay in the Debug panel only.

import type { AgentStatus, TaskStatus } from '$lib/types.js';

export const RUNNING_TASK_STATUSES: ReadonlySet<string> = new Set([
  'pending',
  'dispatched',
  'running',
]);

export const TASK_STATUS_LABEL: Record<TaskStatus, string> = {
  pending: 'queued',
  dispatched: 'starting',
  running: 'answering',
  complete: 'done',
  failed: 'failed',
  timed_out: 'timed out',
  dead_letter: 'agent unreachable',
};

export const TASK_STATUS_COLOUR: Record<TaskStatus, string> = {
  pending: 'text-slate-400',
  dispatched: 'text-blue-400',
  running: 'text-amber-400',
  complete: 'text-green-400',
  failed: 'text-red-400',
  timed_out: 'text-orange-400',
  dead_letter: 'text-red-400',
};

export function taskStatusLabel(status: string): string {
  return TASK_STATUS_LABEL[status as TaskStatus] ?? status;
}

export function taskStatusColour(status: string): string {
  return TASK_STATUS_COLOUR[status as TaskStatus] ?? 'text-slate-400';
}

// Agent statuses: "idle" reads as negative to a normal person but means
// "ready to work"; "degraded"/"draining" are ops jargon.
export const AGENT_STATUS_LABEL: Record<AgentStatus, string> = {
  idle: 'ready',
  busy: 'working…',
  offline: 'offline',
  degraded: 'having trouble',
  draining: 'finishing up',
};

export function agentStatusLabel(status: string): string {
  return AGENT_STATUS_LABEL[status as AgentStatus] ?? status;
}
