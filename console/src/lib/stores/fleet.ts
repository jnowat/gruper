import { writable } from 'svelte/store';
import type { Agent, AgentStatus, FleetEvent } from '$lib/types.js';

// Agent removal is a real server-side operation now (DELETE /v1/agents/{id}
// soft-deletes the row, kicks a live connection, and fails outstanding work),
// so this store is a plain mirror of the orchestrator's fleet — the previous
// localStorage "hidden agents" workaround is gone along with the ghost-agent
// problem it papered over.

function createFleetStore() {
  const store = writable<Agent[]>([]);

  return {
    subscribe: store.subscribe,

    /** Replace the full fleet from the console WS initial snapshot. */
    setSnapshot(agents: Agent[]) {
      store.set(agents);
    },

    /**
     * Add a freshly-registered agent (e.g. via "Add Local Agent") so it
     * appears in the fleet immediately, rather than waiting for the next
     * full REST reload. Its first fleet_event (on WS register) then updates
     * it in place via applyEvent.
     */
    add(agent: Agent) {
      store.update((agents) =>
        agents.some((a) => a.id === agent.id) ? agents : [agent, ...agents],
      );
    },

    /** Apply a real-time fleet_event from the console WS. */
    applyEvent(event: FleetEvent) {
      // Deleted (possibly from another console session) → drop the row.
      if (event.payload.event === 'agent_deleted') {
        store.update((agents) => agents.filter((a) => a.id !== event.payload.agent_id));
        return;
      }
      store.update((agents) => {
        const idx = agents.findIndex((a) => a.id === event.payload.agent_id);
        if (idx === -1) return agents; // agent not yet registered via REST; ignore
        const updated = { ...agents[idx], status: event.payload.status };
        if (event.payload.last_seen) updated.last_seen = event.payload.last_seen;
        // Renames made from another console arrive on the same event.
        if (event.payload.name) updated.name = event.payload.name;
        return [...agents.slice(0, idx), updated, ...agents.slice(idx + 1)];
      });
    },

    /** Update an agent's display name in place (after a successful rename). */
    rename(agentId: string, name: string) {
      store.update((agents) =>
        agents.map((a) => (a.id === agentId ? { ...a, name } : a)),
      );
    },

    /** Update an agent's specialty in place (after a successful PATCH). */
    setRole(agentId: string, role: string) {
      store.update((agents) =>
        agents.map((a) =>
          a.id === agentId
            ? { ...a, capabilities: { ...a.capabilities, roles: [role] } }
            : a,
        ),
      );
    },

    /** Mark all agents offline (used on WS disconnect so UI reflects reality). */
    markAllOffline() {
      store.update((agents) =>
        agents.map((a) => (a.status === 'offline' ? a : { ...a, status: 'offline' as AgentStatus })),
      );
    },

    /**
     * Mark one agent offline immediately (used after stopping a locally-
     * spawned agent — see stop_local_agent in console/src-tauri/src/lib.rs).
     */
    setOffline(agentId: string) {
      store.update((agents) =>
        agents.map((a) => (a.id === agentId ? { ...a, status: 'offline' as AgentStatus } : a)),
      );
    },

    /** Drop an agent's row after a successful server-side delete. */
    remove(agentId: string) {
      store.update((agents) => agents.filter((a) => a.id !== agentId));
    },

    reset() {
      store.set([]);
    },
  };
}

export const fleetStore = createFleetStore();
