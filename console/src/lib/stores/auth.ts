import { writable, get } from 'svelte/store';
import type { AuthTokenResponse } from '$lib/types.js';

export interface AuthState {
  token: string | null;
  userId: string | null;
  expiresAt: string | null;
  orchestratorUrl: string;
}

const _STORE_KEY = 'gruper-console-auth';
const _DEFAULT_URL = 'http://localhost:8080';

function createAuthStore() {
  // Attempt to restore from localStorage (Tauri persists localStorage between launches).
  let initial: AuthState = {
    token: null,
    userId: null,
    expiresAt: null,
    orchestratorUrl: _DEFAULT_URL,
  };
  try {
    const raw = typeof localStorage !== 'undefined' ? localStorage.getItem(_STORE_KEY) : null;
    if (raw) {
      const parsed = JSON.parse(raw) as Partial<AuthState>;
      initial = { ...initial, ...parsed };
      // Discard expired tokens on restore.
      if (initial.expiresAt && new Date(initial.expiresAt) < new Date()) {
        initial.token = null;
        initial.userId = null;
        initial.expiresAt = null;
      }
    }
  } catch {
    // Ignore parse errors; start unauthenticated.
  }

  const store = writable<AuthState>(initial);

  function _persist(state: AuthState) {
    try {
      localStorage.setItem(_STORE_KEY, JSON.stringify(state));
    } catch {
      // Best-effort; Tauri webview may restrict storage in some contexts.
    }
  }

  return {
    subscribe: store.subscribe,

    async login(orchestratorUrl: string, pubkey: string, displayName?: string): Promise<void> {
      const url = orchestratorUrl.replace(/\/$/, '');
      const res = await fetch(`${url}/v1/auth/token`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pubkey, display_name: displayName ?? pubkey.slice(0, 12) }),
      });
      if (!res.ok) {
        const detail = await res.text();
        throw new Error(`Auth failed (${res.status}): ${detail}`);
      }
      const data: AuthTokenResponse = await res.json();
      store.update((s) => {
        const next = { ...s, token: data.token, userId: data.user_id, expiresAt: data.expires_at, orchestratorUrl: url };
        _persist(next);
        return next;
      });
    },

    logout() {
      store.update((s) => {
        const next = { ...s, token: null, userId: null, expiresAt: null };
        _persist(next);
        return next;
      });
    },

    setOrchestratorUrl(url: string) {
      store.update((s) => {
        const next = { ...s, orchestratorUrl: url.replace(/\/$/, '') };
        _persist(next);
        return next;
      });
    },

    getToken(): string | null {
      return get(store).token;
    },

    getOrchestratorUrl(): string {
      return get(store).orchestratorUrl;
    },
  };
}

export const authStore = createAuthStore();
