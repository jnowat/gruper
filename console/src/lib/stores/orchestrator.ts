// WP-32: reflects the Rust side's sidecar lifecycle (see
// console/src-tauri/src/lib.rs::manage_orchestrator) so the UI can auto-fill
// and auto-connect the Connect dialog instead of asking a desktop user to
// find and type an orchestrator URL by hand.
import { writable } from 'svelte/store';

export type OrchestratorStatus = 'checking' | 'existing' | 'ready' | 'failed' | 'unavailable';

export interface OrchestratorState {
  status: OrchestratorStatus;
  url: string | null;
  error: string | null;
}

interface OrchestratorStatusPayload {
  status: string;
  url?: string;
  error?: string | null;
}

const _DEFAULT_URL = 'http://127.0.0.1:8080';

function createOrchestratorStore() {
  const store = writable<OrchestratorState>({ status: 'checking', url: null, error: null });

  function _apply(payload: OrchestratorStatusPayload) {
    store.set({
      status: (payload.status as OrchestratorStatus) ?? 'failed',
      url: payload.url ?? _DEFAULT_URL,
      error: payload.error ?? null,
    });
  }

  // The Rust side only exists inside the Tauri webview. A plain browser tab
  // (e.g. `vite dev` used for fast UI iteration) has nothing to emit this
  // event, so fall back to "unavailable" immediately rather than leaving the
  // dialog stuck on "checking…" forever.
  const hasTauri = typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;
  if (hasTauri) {
    Promise.all([import('@tauri-apps/api/event'), import('@tauri-apps/api/core')])
      .then(([{ listen }, { invoke }]) => {
        // Listen FIRST, then fetch current state: a Tauri event fired before
        // listen() attaches is dropped (not queued), so the sidecar can
        // already be "ready" by the time this module finishes loading —
        // confirmed by testing, this is a real race, not a hypothetical one.
        // Querying get_orchestrator_status right after listening covers
        // whatever was missed; the listener covers anything that changes
        // after that.
        listen<OrchestratorStatusPayload>('orchestrator-status', (event) => _apply(event.payload));
        invoke<OrchestratorStatusPayload>('get_orchestrator_status').then(_apply);
      })
      .catch((e) => {
        console.error('orchestrator store init failed', e);
        store.set({ status: 'unavailable', url: null, error: null });
      });
  } else {
    store.set({ status: 'unavailable', url: null, error: null });
  }

  return { subscribe: store.subscribe };
}

export const orchestratorStore = createOrchestratorStore();
