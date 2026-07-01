import { writable } from 'svelte/store';
import type { Agent, AgentStatus, FleetEvent, FleetSnapshot } from '$lib/types.js';

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
      store.update((agents) => {
        const idx = agents.findIndex((a) => a.id === event.payload.agent_id);
        if (idx === -1) return agents; // agent not yet registered via REST; ignore
        const updated = { ...agents[idx], status: event.payload.status };
        if (event.payload.last_seen) updated.last_seen = event.payload.last_seen;
        return [...agents.slice(0, idx), updated, ...agents.slice(idx + 1)];
      });
    },

    /** Update an agent's display name in place (after a successful rename). */
    rename(agentId: string, name: string) {
      store.update((agents) =>
        agents.map((a) => (a.id === agentId ? { ...a, name } : a)),
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
     * There is no orchestrator DELETE endpoint for agents, so this doesn't
     * remove the row; the orchestrator converges to the same "offline"
     * status on its own once it notices the WebSocket connection drop.
     */
    setOffline(agentId: string) {
      store.update((agents) =>
        agents.map((a) => (a.id === agentId ? { ...a, status: 'offline' as AgentStatus } : a)),
      );
    },

    reset() {
      store.set([]);
    },
  };
}

export const fleetStore = createFleetStore();
