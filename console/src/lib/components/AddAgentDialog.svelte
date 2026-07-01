<!--
  "Add Local Agent" — minimum viable agent onboarding (see ROADMAP.md WP-32).

  Closes the biggest gap called out across prior audits: a desktop user had
  no way to go from "Console installed" to "a task actually runs" without
  hand-editing agent-runtime/.env and copy-pasting a JWT from a curl command.
  This dialog does the whole thing in the UI:
    1. probe local Ollama for installed models, with clear guidance if it
       isn't running or has none — and refuse to register a placeholder
       agent that can't actually do anything (the previous version silently
       fell back to a fake "llama3.1:8b" capability and registered anyway)
    2. generate a fresh agent identity (pubkey) — same pattern the Console
       already uses for its own identity (see stores/auth.ts)
    3. POST /v1/agents with the Console's own JWT (valid because gd-0.1
       tokens are per-owner, not per-agent — see orchestrator/ws/agent_ws.py)
    4. ask the Rust side to spawn the gruper-agent sidecar with the right
       env vars (including the detected models, so task execution actually
       uses them — see agent-runtime/ws_client.py) and wait for it to show
       up online in the fleet, surfacing a real error if it crashes instead
       of a generic "should appear online in a few seconds" platitude
  Scope: single machine, same owner as the Console. Remote/cross-machine
  agent registration is unaffected and stays manual.
-->
<script lang="ts">
  import { onMount } from 'svelte';
  import { authStore, generateRandomPubkey } from '$lib/stores/auth.js';
  import { fleetStore } from '$lib/stores/fleet.js';
  import { OrchestratorClient } from '$lib/api/client.js';
  import type { Agent, AgentCapabilities } from '$lib/types.js';

  let { onclose }: { onclose: () => void } = $props();

  const RUNTIME_VERSION = 'gd-0.1.0';
  // Only used in guidance text (e.g. "ollama pull llama3.1") — never
  // registered as a fake capability.
  const SUGGESTED_MODEL = 'llama3.1';
  const AGENT_ONLINE_TIMEOUT_MS = 20_000;

  let name = $state('Local Agent');
  let ollamaUrl = $state('http://localhost:11434');
  let role = $state('analyst');

  type Step = 'form' | 'registering' | 'spawning' | 'waiting' | 'done';
  let step = $state<Step>('form');

  // Ollama detection state machine — deliberately distinguishes *why* no
  // models are available so the guidance shown is actually actionable,
  // rather than one generic "no models detected" message.
  type OllamaState = 'idle' | 'checking' | 'ready' | 'no_models' | 'unreachable' | 'error';
  let ollamaState = $state<OllamaState>('idle');
  let ollamaMessage = $state<string | null>(null);
  let detectedModels = $state<string[]>([]);

  let error = $state<string | null>(null);
  let timedOut = $state(false);

  const hasTauri = typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;

  function normalizedOllamaUrl(): string {
    return ollamaUrl.trim().replace(/\/$/, '');
  }

  async function detectOllama() {
    ollamaState = 'checking';
    ollamaMessage = null;
    const url = normalizedOllamaUrl();
    if (!url) {
      ollamaState = 'error';
      ollamaMessage = 'Enter an Ollama URL first.';
      detectedModels = [];
      return;
    }

    try {
      const res = await fetch(`${url}/api/tags`, { signal: AbortSignal.timeout(3000) });
      if (!res.ok) {
        ollamaState = 'error';
        ollamaMessage = `Ollama responded with an unexpected status (HTTP ${res.status}).`;
        detectedModels = [];
        return;
      }
      const data = await res.json();
      detectedModels = Array.isArray(data.models)
        ? data.models.map((m: { name: string }) => m.name).filter(Boolean)
        : [];
      if (detectedModels.length > 0) {
        ollamaState = 'ready';
        ollamaMessage = null;
      } else {
        ollamaState = 'no_models';
        ollamaMessage = `Ollama is running but has no models installed. Run "ollama pull ${SUGGESTED_MODEL}" in a terminal, then click Retry.`;
      }
    } catch (err) {
      detectedModels = [];
      ollamaState = 'unreachable';
      if (err instanceof DOMException && err.name === 'TimeoutError') {
        ollamaMessage = `Timed out connecting to Ollama at ${url}. Is it running?`;
      } else {
        ollamaMessage = `Ollama is not running (or not reachable) at ${url}. Start Ollama, then click Retry.`;
      }
    }
  }

  // Auto-run detection as soon as the dialog opens — a user shouldn't have
  // to know to click a button before the form tells them anything useful.
  onMount(() => {
    detectOllama();
  });

  function onOllamaUrlInput() {
    // The last detection result no longer applies to whatever URL is now
    // typed in; require an explicit re-check rather than silently reusing
    // stale results (or worse, silently allowing submission against them).
    ollamaState = 'idle';
    ollamaMessage = null;
    detectedModels = [];
  }

  /**
   * Resolves once the freshly-spawned agent either (a) shows up in the
   * fleet with a non-offline status — the WS "registered" handshake sets it
   * to "idle" — (b) is reported as crashed via the Rust side's
   * agent-sidecar-exited event, or (c) the timeout elapses. Listening for
   * the crash event is attached before the timeout starts so a fast crash
   * (bad Ollama URL, missing binary on a fresh install) is reported as a
   * real error instead of a generic "hasn't come online yet" message.
   */
  function waitForAgentOnline(
    agentId: string,
    timeoutMs: number,
  ): Promise<{ outcome: 'online' | 'timeout' } | { outcome: 'crashed'; detail: string }> {
    return new Promise((resolve) => {
      let settled = false;
      let unlistenCrash: (() => void) | null = null;

      const unsubFleet = fleetStore.subscribe((agents: Agent[]) => {
        const a = agents.find((x) => x.id === agentId);
        if (a && a.status !== 'offline' && !settled) {
          finish({ outcome: 'online' });
        }
      });

      const timer = setTimeout(() => {
        if (!settled) finish({ outcome: 'timeout' });
      }, timeoutMs);

      function finish(result: Parameters<typeof resolve>[0]) {
        settled = true;
        clearTimeout(timer);
        unsubFleet();
        unlistenCrash?.();
        resolve(result);
      }

      if (hasTauri) {
        import('@tauri-apps/api/event').then(({ listen }) => {
          if (settled) return;
          listen<{ agent_id: string; error?: string; code?: number | null }>(
            'agent-sidecar-exited',
            (event) => {
              if (event.payload.agent_id !== agentId || settled) return;
              const detail =
                event.payload.error ??
                `agent process exited (code ${event.payload.code ?? 'unknown'})`;
              finish({ outcome: 'crashed', detail });
            },
          ).then((un) => {
            if (settled) un();
            else unlistenCrash = un;
          });
        });
      }
    });
  }

  async function handleSubmit() {
    error = null;
    timedOut = false;

    if (ollamaState !== 'ready' || detectedModels.length === 0) {
      error = 'At least one Ollama model must be detected before an agent can be added.';
      return;
    }
    if (!hasTauri) {
      error = 'Spawning a local agent process requires the desktop app (Tauri) — this only works in the packaged/dev Console, not a plain browser tab.';
      return;
    }

    const token = authStore.getToken();
    const orchestratorUrl = authStore.getOrchestratorUrl();
    if (!token) {
      error = 'Not connected to an orchestrator.';
      return;
    }

    const capabilities: AgentCapabilities = {
      models: detectedModels,
      roles: [role],
      tools: [],
      hardware: {
        cpu_cores: navigator.hardwareConcurrency || 4,
        ram_gb: 8,
      },
    };

    let agent: Agent;
    try {
      step = 'registering';
      const client = new OrchestratorClient(orchestratorUrl, token);
      agent = await client.registerAgent({
        name: name.trim() || 'Local Agent',
        pubkey: generateRandomPubkey(),
        capabilities,
        runtime_version: RUNTIME_VERSION,
      });
      fleetStore.add(agent);
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
      step = 'form';
      return;
    }

    try {
      step = 'spawning';
      const { invoke } = await import('@tauri-apps/api/core');
      await invoke('spawn_local_agent', {
        agentId: agent.id,
        jwtToken: token,
        orchestratorUrl,
        ollamaUrl: normalizedOllamaUrl() || undefined,
        capabilitiesJson: JSON.stringify(capabilities),
      });
    } catch (err) {
      error = `Agent was registered, but the local process failed to start: ${err instanceof Error ? err.message : String(err)}`;
      step = 'form';
      return;
    }

    step = 'waiting';
    const result = await waitForAgentOnline(agent.id, AGENT_ONLINE_TIMEOUT_MS);
    if (result.outcome === 'crashed') {
      error = `The agent process was registered and started, but exited before coming online: ${result.detail}. Check that Ollama is reachable at the URL above, then try again.`;
      step = 'form';
      return;
    }
    timedOut = result.outcome === 'timeout';
    step = 'done';
  }
</script>

<div class="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50">
  <div class="glass-card p-6 w-full max-w-md mx-4 space-y-4">
    <div class="flex items-center justify-between">
      <h2 class="text-lg font-semibold text-white">Add Local Agent</h2>
      <button onclick={onclose} class="text-slate-500 hover:text-slate-300 text-sm">✕</button>
    </div>

    {#if step === 'done'}
      {#if timedOut}
        <div class="bg-amber-500/10 border border-amber-500/30 text-amber-300 text-sm rounded-lg p-3">
          Agent registered and the local process started, but it hasn't shown up online yet
          (waited {Math.round(AGENT_ONLINE_TIMEOUT_MS / 1000)}s). This can happen on first run
          while antivirus scans the freshly-installed executable — it may still connect in the
          next few seconds. If it doesn't, check that Ollama is reachable at the URL you entered.
        </div>
      {:else}
        <div class="bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 text-sm rounded-lg p-3">
          Agent is online and ready to run tasks.
        </div>
      {/if}
      <button
        onclick={onclose}
        class="w-full bg-blue-600 hover:bg-blue-500 text-white rounded-lg px-4 py-2 text-sm font-medium transition-colors"
      >
        Close
      </button>
    {:else}
      <p class="text-sm text-slate-400">
        Registers a new agent identity with this orchestrator and starts it as a local background
        process — no config files, no manual JWT copy-paste.
      </p>

      <div>
        <label class="block text-xs text-slate-400 mb-1" for="agent-name">Name</label>
        <input
          id="agent-name"
          type="text"
          bind:value={name}
          class="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500"
        />
      </div>

      <div>
        <label class="block text-xs text-slate-400 mb-1" for="ollama-url">Ollama URL</label>
        <div class="flex gap-2">
          <input
            id="ollama-url"
            type="text"
            bind:value={ollamaUrl}
            oninput={onOllamaUrlInput}
            class="flex-1 bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500"
          />
          <button
            type="button"
            onclick={detectOllama}
            disabled={ollamaState === 'checking'}
            class="text-xs px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-slate-300 hover:bg-white/10 disabled:opacity-50"
          >
            {#if ollamaState === 'checking'}
              Checking…
            {:else if ollamaState === 'idle'}
              Detect models
            {:else}
              Retry
            {/if}
          </button>
        </div>

        {#if ollamaState === 'ready'}
          <p class="text-xs mt-1 text-emerald-400">
            Found {detectedModels.length} model{detectedModels.length === 1 ? '' : 's'}: {detectedModels.join(', ')}
          </p>
        {:else if ollamaState === 'no_models'}
          <p class="text-xs mt-1 text-amber-400">{ollamaMessage}</p>
        {:else if ollamaState === 'unreachable'}
          <p class="text-xs mt-1 text-amber-400">{ollamaMessage}</p>
        {:else if ollamaState === 'error'}
          <p class="text-xs mt-1 text-red-400">{ollamaMessage}</p>
        {:else if ollamaState === 'checking'}
          <p class="text-xs mt-1 text-slate-500">Checking for installed models…</p>
        {/if}
      </div>

      <div>
        <label class="block text-xs text-slate-400 mb-1" for="agent-role">Role template</label>
        <select
          id="agent-role"
          bind:value={role}
          class="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500"
        >
          {#each ['analyst', 'creative', 'critic', 'synthesizer', 'expert', 'devil_advocate', 'philosopher', 'economist', 'ethicist', 'scientist', 'psychologist', 'engineer'] as r}
            <option value={r}>{r}</option>
          {/each}
        </select>
      </div>

      {#if !hasTauri}
        <div class="bg-amber-500/10 border border-amber-500/30 text-amber-300 text-xs rounded-lg p-3">
          Running outside the desktop app (e.g. a plain browser dev tab) — agent registration will
          work, but spawning the local process requires the Tauri shell.
        </div>
      {/if}

      {#if error}
        <div class="bg-red-500/10 border border-red-500/30 text-red-400 text-sm rounded-lg p-3">
          {error}
        </div>
      {/if}

      <button
        onclick={handleSubmit}
        disabled={step === 'registering' || step === 'spawning' || step === 'waiting' || ollamaState !== 'ready'}
        title={ollamaState !== 'ready' ? 'At least one Ollama model must be detected first' : undefined}
        class="w-full bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white rounded-lg px-4 py-2 text-sm font-medium transition-colors"
      >
        {#if step === 'registering'}
          Registering…
        {:else if step === 'spawning'}
          Starting agent…
        {:else if step === 'waiting'}
          Waiting for agent to connect…
        {:else}
          Add Agent
        {/if}
      </button>
    {/if}
  </div>
</div>
