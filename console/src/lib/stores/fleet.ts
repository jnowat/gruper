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

    /** Mark all agents offline (used on WS disconnect so UI reflects reality). */
    markAllOffline() {
      store.update((agents) =>
        agents.map((a) => (a.status === 'offline' ? a : { ...a, status: 'offline' as AgentStatus })),
      );
    },

    reset() {
      store.set([]);
    },
  };
}

export const fleetStore = createFleetStore();
