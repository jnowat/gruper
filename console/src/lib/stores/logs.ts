// Unified debug log store (Desktop Hardening).
//
// The single source of truth is the Rust-side ring buffer (see
// console/src-tauri/src/lib.rs). This store mirrors it for the DebugPanel:
//   • start()  — backfill via get_logs(), then stream new entries from the
//                'log-entry' Tauri event. Called once at app startup.
//   • frontend() — record a UI-tier log line: append locally (optimistic) AND
//                  forward to the Rust buffer via push_log so exports include
//                  UI events. push_log does not re-emit, so there is no echo.
//   • installConsoleBridge() — route existing console.info/warn/error through
//                  frontend() (category 'ui') while preserving devtools output.
//
// Outside Tauri (a plain `vite dev` browser tab) this degrades to a local-only
// buffer so the panel still works for UI iteration.

import { writable } from 'svelte/store';
import type { LogEntry, LogLevel } from '$lib/types.js';

const CAP = 5000; // mirrors LOG_BUFFER_CAP in lib.rs
const hasTauri = typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;

function createLogStore() {
  const store = writable<LogEntry[]>([]);
  let started = false;

  function _append(entry: LogEntry) {
    store.update((list) => {
      const next = list.length >= CAP ? list.slice(list.length - CAP + 1) : list.slice();
      next.push(entry);
      return next;
    });
  }

  async function start(): Promise<void> {
    if (started) return;
    started = true;
    if (!hasTauri) return;
    try {
      const [{ listen }, { invoke }] = await Promise.all([
        import('@tauri-apps/api/event'),
        import('@tauri-apps/api/core'),
      ]);
      // Backfill BEFORE the live stream: an event fired before listen() attaches
      // is dropped, not queued (the same race the orchestrator store documents),
      // so the ring-buffer snapshot catches whatever happened during boot.
      const existing = await invoke<LogEntry[]>('get_logs').catch(() => [] as LogEntry[]);
      store.set(existing.slice(-CAP));
      await listen<LogEntry>('log-entry', (e) => _append(e.payload));
    } catch {
      // Best-effort — the local buffer + frontend() still work.
    }
  }

  function frontend(
    level: LogLevel,
    category: string,
    msg: string,
    opts?: { fields?: Record<string, unknown>; agent_id?: string; task_id?: string },
  ): void {
    const entry: LogEntry = {
      ts: new Date().toISOString(),
      level,
      category,
      tier: 'frontend',
      agent_id: opts?.agent_id ?? null,
      task_id: opts?.task_id ?? null,
      msg,
      fields: opts?.fields ?? {},
    };
    _append(entry);
    if (hasTauri) {
      import('@tauri-apps/api/core')
        .then(({ invoke }) => invoke('push_log', { entry }))
        .catch(() => {});
    }
  }

  async function clear(): Promise<void> {
    store.set([]);
    if (hasTauri) {
      try {
        const { invoke } = await import('@tauri-apps/api/core');
        await invoke('clear_logs');
      } catch {
        // ignore
      }
    }
  }

  return { subscribe: store.subscribe, start, frontend, clear };
}

export const logStore = createLogStore();

// ── console.* bridge ──────────────────────────────────────────────────────────
let _bridged = false;
let _inBridge = false;

function _stringify(v: unknown): string {
  if (typeof v === 'string') return v;
  try {
    return JSON.stringify(v);
  } catch {
    return String(v);
  }
}

/**
 * Wrap console.info/warn/error so the existing scattered calls (console_ws.ts,
 * +page.svelte, orchestrator.ts) also land in the unified buffer, while still
 * printing to devtools. Reentrancy-guarded so a subscriber that logs can't loop.
 */
export function installConsoleBridge(): void {
  if (_bridged || typeof console === 'undefined') return;
  _bridged = true;
  const wrap =
    (level: LogLevel, orig: (...a: unknown[]) => void) =>
    (...args: unknown[]) => {
      if (!_inBridge) {
        _inBridge = true;
        try {
          logStore.frontend(level, 'ui', args.map(_stringify).join(' '));
        } catch {
          // ignore
        } finally {
          _inBridge = false;
        }
      }
      orig(...args);
    };
  console.info = wrap('info', console.info.bind(console));
  console.warn = wrap('warn', console.warn.bind(console));
  console.error = wrap('error', console.error.bind(console));
}
