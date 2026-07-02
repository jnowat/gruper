import { writable, get } from 'svelte/store';
import type { AuthTokenResponse } from '$lib/types.js';

export interface AuthState {
  token: string | null;
  userId: string | null;
  expiresAt: string | null;
  orchestratorUrl: string;
}

const _STORE_KEY = 'gruper-console-auth';
const _IDENTITY_KEY = 'gruper-console-identity';
const _MANUAL_DISCONNECT_KEY = 'gruper-console-manual-disconnect';
const _DEFAULT_URL = 'http://localhost:8080';

function _base64UrlEncode(bytes: Uint8Array): string {
  let binary = '';
  for (const b of bytes) binary += String.fromCharCode(b);
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

/**
 * gd-0.1's /v1/auth/token and POST /v1/agents stub out real ed25519 signature
 * verification and accept any syntactically valid pubkey (see
 * orchestrator/routers/auth.py, orchestrator/routers/agents.py), so a random
 * 32-byte value serves as a stable identity just as well. Shared by the
 * console's own identity (getOrCreatePubkey) and by "Add Local Agent"
 * (AddAgentDialog.svelte), which needs a fresh one per agent.
 */
export function generateRandomPubkey(): string {
  return _base64UrlEncode(crypto.getRandomValues(new Uint8Array(32)));
}

/**
 * WP-32: a desktop user should never have to run a Python one-liner to get a
 * pubkey before they can connect. A random identity is generated once and
 * persisted separately from the auth token/session so logging out doesn't
 * spawn a new orchestrator-side user on the next login.
 */
export function getOrCreatePubkey(): string {
  try {
    const raw = typeof localStorage !== 'undefined' ? localStorage.getItem(_IDENTITY_KEY) : null;
    if (raw) {
      const parsed = JSON.parse(raw) as { pubkey?: string };
      if (parsed.pubkey) return parsed.pubkey;
    }
  } catch {
    // Fall through and generate a fresh one.
  }
  const pubkey = generateRandomPubkey();
  try {
    localStorage.setItem(_IDENTITY_KEY, JSON.stringify({ pubkey }));
  } catch {
    // Best-effort; worst case we generate a new identity next launch too.
  }
  return pubkey;
}

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
      // Timeout matters: the splash-first ConnectDialog auto-connects with no
      // form visible, so a request that never settles (wedged engine, squatted
      // port) would otherwise leave the user on "Almost ready…" forever with
      // the manual Connect button disabled. An error here surfaces the form.
      const res = await fetch(`${url}/v1/auth/token`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pubkey, display_name: displayName ?? pubkey.slice(0, 12) }),
        signal: AbortSignal.timeout(10_000),
      });
      if (!res.ok) {
        const detail = await res.text();
        throw new Error(`Couldn't sign in to the engine at ${url} (${res.status}): ${detail}`);
      }
      const data: AuthTokenResponse = await res.json();
      try {
        sessionStorage.removeItem(_MANUAL_DISCONNECT_KEY);
      } catch {
        // best-effort
      }
      store.update((s) => {
        const next = { ...s, token: data.token, userId: data.user_id, expiresAt: data.expires_at, orchestratorUrl: url };
        _persist(next);
        return next;
      });
    },

    logout() {
      // Remember that this was an explicit disconnect, so the connect screen
      // shows the form instead of instantly auto-reconnecting — otherwise the
      // manual form is unreachable on a healthy desktop install.
      try {
        sessionStorage.setItem(_MANUAL_DISCONNECT_KEY, '1');
      } catch {
        // best-effort
      }
      store.update((s) => {
        const next = { ...s, token: null, userId: null, expiresAt: null };
        _persist(next);
        return next;
      });
    },

    /** True once per explicit Disconnect (consumed by the connect screen). */
    consumeManualDisconnect(): boolean {
      try {
        if (sessionStorage.getItem(_MANUAL_DISCONNECT_KEY)) {
          sessionStorage.removeItem(_MANUAL_DISCONNECT_KEY);
          return true;
        }
      } catch {
        // best-effort
      }
      return false;
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
