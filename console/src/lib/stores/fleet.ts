import { derived, writable } from 'svelte/store';
import type { Agent, AgentStatus, FleetEvent } from '$lib/types.js';

// There is no orchestrator DELETE endpoint for agents, so "removing" one is a
// local decision: the id goes into a persisted hidden map and the agent stops
// rendering. If a hidden agent ever comes back online (fleet_event with a
// non-offline status), it un-hides itself — a helper that is actually running
// should never be invisible. The map stores WHEN each id was hidden so that a
// stale heartbeat already queued on the socket at remove time (the process was
// just stopped, but its last event is still in flight) can't instantly undo
// the removal — only events arriving after a short grace window un-hide.
const HIDDEN_KEY = 'gruper.hidden_agents';
const UNHIDE_GRACE_MS = 5_000;

function loadHidden(): Map<string, number> {
  try {
    const raw = localStorage.getItem(HIDDEN_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as Record<string, number> | string[];
      // Migrate the earlier plain-array shape.
      if (Array.isArray(parsed)) return new Map(parsed.map((id) => [id, 0]));
      return new Map(Object.entries(parsed));
    }
  } catch {
    // localStorage unavailable (SSR) or corrupted — start clean.
  }
  return new Map();
}

function saveHidden(hidden: Map<string, number>): void {
  try {
    localStorage.setItem(HIDDEN_KEY, JSON.stringify(Object.fromEntries(hidden)));
  } catch {
    // best-effort persistence only
  }
}

interface FleetState {
  agents: Agent[];
  hidden: Map<string, number>;
}

function createFleetStore() {
  const state = writable<FleetState>({ agents: [], hidden: loadHidden() });
  const visible = derived(state, (s) => s.agents.filter((a) => !s.hidden.has(a.id)));

  return {
    /** Subscribes to the VISIBLE fleet (hidden agents filtered out). */
    subscribe: visible.subscribe,

    /** Replace the full fleet from the console WS initial snapshot. */
    setSnapshot(agents: Agent[]) {
      state.update((s) => ({ ...s, agents }));
    },

    /**
     * Add a freshly-registered agent (e.g. via "Add Local Agent") so it
     * appears in the fleet immediately, rather than waiting for the next
     * full REST reload. Its first fleet_event (on WS register) then updates
     * it in place via applyEvent.
     */
    add(agent: Agent) {
      state.update((s) => {
        const hidden = new Map(s.hidden);
        hidden.delete(agent.id); // a re-added agent must be visible
        if (hidden.size !== s.hidden.size) saveHidden(hidden);
        return {
          agents: s.agents.some((a) => a.id === agent.id) ? s.agents : [agent, ...s.agents],
          hidden,
        };
      });
    },

    /** Apply a real-time fleet_event from the console WS. */
    applyEvent(event: FleetEvent) {
      state.update((s) => {
        const idx = s.agents.findIndex((a) => a.id === event.payload.agent_id);
        if (idx === -1) return s; // agent not yet registered via REST; ignore
        const updated = { ...s.agents[idx], status: event.payload.status };
        if (event.payload.last_seen) updated.last_seen = event.payload.last_seen;
        // Renames made from another console arrive on the same event.
        if (event.payload.name) updated.name = event.payload.name;
        let hidden = s.hidden;
        const hiddenAt = hidden.get(updated.id);
        if (
          event.payload.status !== 'offline' &&
          hiddenAt !== undefined &&
          Date.now() - hiddenAt > UNHIDE_GRACE_MS
        ) {
          hidden = new Map(hidden);
          hidden.delete(updated.id);
          saveHidden(hidden);
        }
        return {
          agents: [...s.agents.slice(0, idx), updated, ...s.agents.slice(idx + 1)],
          hidden,
        };
      });
    },

    /** Update an agent's display name in place (after a successful rename). */
    rename(agentId: string, name: string) {
      state.update((s) => ({
        ...s,
        agents: s.agents.map((a) => (a.id === agentId ? { ...a, name } : a)),
      }));
    },

    /** Update an agent's specialty in place (after a successful PATCH). */
    setRole(agentId: string, role: string) {
      state.update((s) => ({
        ...s,
        agents: s.agents.map((a) =>
          a.id === agentId
            ? { ...a, capabilities: { ...a.capabilities, roles: [role] } }
            : a,
        ),
      }));
    },

    /** Mark all agents offline (used on WS disconnect so UI reflects reality). */
    markAllOffline() {
      state.update((s) => ({
        ...s,
        agents: s.agents.map((a) =>
          a.status === 'offline' ? a : { ...a, status: 'offline' as AgentStatus },
        ),
      }));
    },

    /**
     * Mark one agent offline immediately (used after stopping a locally-
     * spawned agent — see stop_local_agent in console/src-tauri/src/lib.rs).
     */
    setOffline(agentId: string) {
      state.update((s) => ({
        ...s,
        agents: s.agents.map((a) =>
          a.id === agentId ? { ...a, status: 'offline' as AgentStatus } : a,
        ),
      }));
    },

    /**
     * Hide an agent from the fleet (persisted locally). This is what the ✕ on
     * an agent card does after stopping the process — the orchestrator keeps
     * the row (no DELETE endpoint), but the user's mental model of "get rid of
     * it" is satisfied. Coming back online un-hides automatically.
     */
    hide(agentId: string) {
      state.update((s) => {
        const hidden = new Map(s.hidden);
        hidden.set(agentId, Date.now());
        saveHidden(hidden);
        return { ...s, hidden };
      });
    },

    reset() {
      state.update((s) => ({ agents: [], hidden: s.hidden }));
    },
  };
}

export const fleetStore = createFleetStore();
