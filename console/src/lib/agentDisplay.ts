// Shared agent visual identity — one place so the Fleet, dropdowns, round-table,
// and result header all render an agent the same recognisable way. A stable
// per-agent colour + initials avatar makes a fleet of similarly-named agents
// scannable at a glance, and a consistent "model · role" subtitle keeps the
// distinguishing details visible everywhere an agent appears.

import type { Agent } from '$lib/types.js';

// Solid palette (applied via inline style, so Tailwind's purge never strips it).
const PALETTE = ['#3b82f6', '#10b981', '#a855f7', '#f59e0b', '#ec4899', '#06b6d4', '#f97316', '#6366f1'];

function hash(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (Math.imul(h, 31) + s.charCodeAt(i)) | 0;
  return Math.abs(h);
}

export function agentColor(id: string): string {
  return PALETTE[hash(id) % PALETTE.length];
}

export function agentInitials(name: string): string {
  const words = name.trim().split(/[\s·_/-]+/).filter(Boolean);
  if (words.length === 0) return '?';
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return (words[0][0] + words[1][0]).toUpperCase();
}

export function agentModel(agent: Agent): string {
  return agent.capabilities?.default_model ?? agent.capabilities?.models?.[0] ?? '';
}

export function agentRole(agent: Agent): string | null {
  return agent.capabilities?.roles?.[0] ?? null;
}

/** "model · role" — the distinguishing subtitle shown under an agent's name. */
export function agentSubtitle(agent: Agent): string {
  return [agentModel(agent), agentRole(agent)].filter(Boolean).join(' · ');
}

/** "name — model · role" — a single-line label for <option>s and chips. */
export function agentLabel(agent: Agent): string {
  const sub = agentSubtitle(agent);
  return sub ? `${agent.name} — ${sub}` : agent.name;
}
