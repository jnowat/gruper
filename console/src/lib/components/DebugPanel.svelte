<!--
  DebugPanel — the user-facing window into the unified debug log (Desktop
  Hardening). Shows every tier's entries (Rust/Tauri, both Python sidecars, and
  the frontend) from one ring buffer (see stores/logs.ts + lib.rs), with:
    • category chips + a level threshold + free-text search
    • a live tail (pausable) that auto-scrolls
    • Copy (filtered rows) and Export (.jsonl / .txt) for the filtered set
    • "Copy diagnostics" — logs + app/orchestrator/WS state, for bug reports
  Correlation ids (agent_id/task_id) are searchable, so typing a task id gives
  its full cross-tier trace — the whole reason the system exists.
-->
<script lang="ts">
  import { onMount } from 'svelte';
  import { logStore } from '$lib/stores/logs.js';
  import { orchestratorStore } from '$lib/stores/orchestrator.js';
  import { wsStatus } from '$lib/stores/wsStatus.js';
  import { fleetStore } from '$lib/stores/fleet.js';
  import type { LogEntry, LogLevel } from '$lib/types.js';

  let { onclose }: { onclose: () => void } = $props();

  const LEVELS: LogLevel[] = ['debug', 'info', 'warn', 'error'];
  const LEVEL_ORDER: Record<LogLevel, number> = { debug: 0, info: 1, warn: 2, error: 3 };
  // Preferred chip order; any category not listed is appended in first-seen order.
  const CATEGORY_ORDER = ['orchestrator', 'agent', 'sidecar', 'ws', 'task', 'auth', 'ollama', 'ui', 'error'];

  let minLevel = $state<LogLevel>('debug');
  let hidden = $state<Set<string>>(new Set()); // hidden categories; empty = show all
  let search = $state('');
  let paused = $state(false);
  let copied = $state<string | null>(null);

  const entries = $derived($logStore);
  const orch = $derived($orchestratorStore);
  const ws = $derived($wsStatus);
  const agents = $derived($fleetStore);

  const categories = $derived.by(() => {
    const seen = new Set(entries.map((e) => e.category));
    const ordered = CATEGORY_ORDER.filter((c) => seen.has(c));
    const extra = [...seen].filter((c) => !CATEGORY_ORDER.includes(c)).sort();
    return [...ordered, ...extra];
  });

  const filtered = $derived.by(() => {
    const q = search.trim().toLowerCase();
    const min = LEVEL_ORDER[minLevel];
    return entries.filter((e) => {
      if (LEVEL_ORDER[e.level] < min) return false;
      if (hidden.has(e.category)) return false;
      if (q) {
        const hay = `${e.msg} ${e.category} ${e.tier} ${e.agent_id ?? ''} ${e.task_id ?? ''}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  });

  function toggleCategory(cat: string) {
    const next = new Set(hidden);
    if (next.has(cat)) next.delete(cat);
    else next.add(cat);
    hidden = next;
  }

  const LEVEL_COLOUR: Record<LogLevel, string> = {
    debug: 'text-slate-500',
    info: 'text-slate-300',
    warn: 'text-amber-400',
    error: 'text-red-400',
  };

  function fmtTime(ts: string): string {
    // Show HH:MM:SS.mmm; fall back to the raw string if unparseable.
    const d = new Date(ts);
    if (Number.isNaN(d.getTime())) return ts;
    return d.toISOString().slice(11, 23);
  }

  function toText(rows: LogEntry[]): string {
    return rows
      .map((e) => {
        const ids = [e.task_id ? `task:${e.task_id}` : '', e.agent_id ? `agent:${e.agent_id}` : '']
          .filter(Boolean)
          .join(' ');
        const suffix = ids ? ` [${ids}]` : '';
        return `${fmtTime(e.ts)} ${e.level.toUpperCase().padEnd(5)} ${e.category.padEnd(12)} ${e.tier.padEnd(12)} ${e.msg}${suffix}`;
      })
      .join('\n');
  }

  async function flash(label: string) {
    copied = label;
    setTimeout(() => {
      if (copied === label) copied = null;
    }, 1500);
  }

  async function copyFiltered() {
    try {
      await navigator.clipboard.writeText(toText(filtered));
      flash('copy');
    } catch {
      copied = 'copy-failed';
    }
  }

  function stamp(): string {
    return new Date().toISOString().replace(/[:.]/g, '-');
  }

  function download(filename: string, text: string, mime: string) {
    const blob = new Blob([text], { type: mime });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  function exportJsonl() {
    download(`gruper-logs-${stamp()}.jsonl`, filtered.map((e) => JSON.stringify(e)).join('\n'), 'application/x-ndjson');
  }

  function exportTxt() {
    download(`gruper-logs-${stamp()}.txt`, toText(filtered), 'text/plain');
  }

  function diagnosticsText(): string {
    const online = agents.filter((a) => a.status !== 'offline').length;
    const header = [
      'Gruper Console — diagnostics',
      `generated:    ${new Date().toISOString()}`,
      `orchestrator: ${orch.status}${orch.url ? ` (${orch.url})` : ''}${orch.error ? ` — ${orch.error}` : ''}`,
      `console ws:   ${ws}`,
      `agents:       ${online}/${agents.length} online`,
      `log entries:  ${filtered.length} shown / ${entries.length} total`,
      `filters:      level>=${minLevel}${hidden.size ? `, hidden=[${[...hidden].join(',')}]` : ''}${search ? `, search="${search}"` : ''}`,
      '--- logs ---',
    ].join('\n');
    return `${header}\n${toText(filtered)}\n`;
  }

  async function copyDiagnostics() {
    try {
      await navigator.clipboard.writeText(diagnosticsText());
      flash('diag');
    } catch {
      copied = 'copy-failed';
    }
  }

  // Live tail: auto-scroll to newest unless paused or the user scrolled up.
  let scroller = $state<HTMLDivElement | null>(null);
  $effect(() => {
    // Depend on filtered length so this re-runs as new entries arrive.
    void filtered.length;
    if (!paused && scroller) {
      scroller.scrollTop = scroller.scrollHeight;
    }
  });

  onMount(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onclose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });
</script>

<div class="fixed inset-0 z-50 flex justify-end">
  <!-- Backdrop: click to close, but keep the app visible behind it. -->
  <button class="flex-1 bg-black/30 cursor-default" aria-label="Close debug panel" onclick={onclose}></button>

  <aside class="w-full max-w-2xl h-full bg-slate-900/95 backdrop-blur-md border-l border-white/10 flex flex-col shadow-2xl">
    <!-- Header -->
    <div class="flex items-center gap-2 px-3 py-2 border-b border-white/10 flex-wrap">
      <span class="text-sm font-semibold text-white">Debug Log</span>
      <span class="text-xs text-slate-500">{filtered.length}/{entries.length}</span>
      <div class="flex-1"></div>
      <button onclick={copyFiltered} class="text-xs px-2 py-1 rounded bg-white/5 border border-white/10 text-slate-300 hover:bg-white/10">
        {copied === 'copy' ? 'Copied ✓' : 'Copy'}
      </button>
      <button onclick={copyDiagnostics} class="text-xs px-2 py-1 rounded bg-white/5 border border-white/10 text-slate-300 hover:bg-white/10">
        {copied === 'diag' ? 'Copied ✓' : 'Copy diagnostics'}
      </button>
      <button onclick={exportJsonl} class="text-xs px-2 py-1 rounded bg-white/5 border border-white/10 text-slate-300 hover:bg-white/10">.jsonl</button>
      <button onclick={exportTxt} class="text-xs px-2 py-1 rounded bg-white/5 border border-white/10 text-slate-300 hover:bg-white/10">.txt</button>
      <button onclick={() => logStore.clear()} class="text-xs px-2 py-1 rounded bg-white/5 border border-white/10 text-slate-400 hover:text-red-400 hover:bg-white/10">Clear</button>
      <button onclick={onclose} class="text-slate-400 hover:text-slate-200 text-sm px-1" aria-label="Close">✕</button>
    </div>

    <!-- Filters -->
    <div class="px-3 py-2 border-b border-white/10 space-y-2">
      <div class="flex items-center gap-1 flex-wrap">
        {#each categories as cat}
          <button
            onclick={() => toggleCategory(cat)}
            class="text-xs px-2 py-0.5 rounded-full border transition-colors {hidden.has(cat)
              ? 'border-white/10 text-slate-600'
              : 'border-blue-500/40 bg-blue-500/10 text-blue-300'}"
          >
            {cat}
          </button>
        {/each}
        {#if categories.length === 0}
          <span class="text-xs text-slate-600">no log entries yet</span>
        {/if}
      </div>
      <div class="flex items-center gap-2">
        <div class="flex items-center gap-1">
          {#each LEVELS as lvl}
            <button
              onclick={() => (minLevel = lvl)}
              class="text-xs px-2 py-0.5 rounded border transition-colors {minLevel === lvl
                ? 'border-blue-500/60 bg-blue-500/10 text-white'
                : 'border-white/10 text-slate-500 hover:text-slate-300'}"
              title="Show {lvl} and above"
            >
              {lvl}
            </button>
          {/each}
        </div>
        <input
          type="text"
          bind:value={search}
          placeholder="search msg / task id / agent id…"
          class="flex-1 min-w-0 bg-white/5 border border-white/10 rounded px-2 py-1 text-xs text-white placeholder:text-slate-600 focus:outline-none focus:border-blue-500"
        />
        <button
          onclick={() => (paused = !paused)}
          class="text-xs px-2 py-1 rounded border transition-colors {paused
            ? 'border-amber-500/50 bg-amber-500/10 text-amber-300'
            : 'border-white/10 text-slate-400 hover:text-slate-200'}"
          title={paused ? 'Resume live tail' : 'Pause live tail'}
        >
          {paused ? '▶ paused' : '⏸ live'}
        </button>
      </div>
    </div>

    <!-- Log rows -->
    <div bind:this={scroller} class="flex-1 overflow-y-auto font-mono text-xs px-2 py-1">
      {#each filtered as e (e.ts + e.msg + e.category)}
        <div class="flex gap-2 py-0.5 border-b border-white/5 last:border-0 items-baseline">
          <span class="text-slate-600 flex-shrink-0">{fmtTime(e.ts)}</span>
          <span class="{LEVEL_COLOUR[e.level]} flex-shrink-0 w-10 uppercase">{e.level}</span>
          <span class="text-blue-400/80 flex-shrink-0 w-24 truncate" title={`${e.category} · ${e.tier}`}>{e.category}</span>
          <span class="text-slate-300 break-words min-w-0 flex-1">
            {e.msg}
            {#if e.task_id}<span class="text-slate-600"> [task:{e.task_id.slice(0, 8)}]</span>{/if}
            {#if e.agent_id}<span class="text-slate-600"> [agent:{e.agent_id.slice(0, 8)}]</span>{/if}
          </span>
        </div>
      {:else}
        <div class="text-slate-600 text-center py-8">No log entries match the current filters.</div>
      {/each}
    </div>

    <div class="px-3 py-1.5 border-t border-white/10 text-xs text-slate-600">
      Logs are in-memory (last {5000} entries) and redacted (JWTs, tokens, keys). Nothing is sent anywhere — Export or Copy to share.
    </div>
  </aside>
</div>
