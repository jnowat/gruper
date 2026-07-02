<!--
  "Add agent" — minimum viable agent onboarding (see ROADMAP.md WP-32).

  Closes the biggest gap called out across prior audits: a desktop user had
  no way to go from "Console installed" to "a task actually runs" without
  hand-editing agent-runtime/.env and copy-pasting a JWT from a curl command.
  This dialog does the whole thing in the UI:
    1. probe local Ollama for installed models, with clear guidance if it
       isn't running or has none — and refuse to register a placeholder
       agent that can't actually do anything (the previous version silently
       fell back to a fake "llama3.1:8b" capability and registered anyway).
       Detection runs through the Rust-side `detect_ollama_models` command,
       not a frontend `fetch()` — a real Windows test run showed the
       webview's own `fetch()` gets blocked by Chromium's Private Network
       Access policy even when Ollama is genuinely running, so the actual
       HTTP call has to happen outside the webview (see that command's doc
       comment in console/src-tauri/src/lib.rs for the full story)
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

  The form is ordered for a person, not the plumbing: detection runs silently
  and reads as one status line; name and specialty lead; the model picker only
  appears when there's actually a choice; the Ollama URL hides under Advanced
  unless detection fails (then it surfaces right inside the guidance).
-->
<script lang="ts">
  import { onMount } from 'svelte';
  import { get } from 'svelte/store';
  import { authStore, generateRandomPubkey } from '$lib/stores/auth.js';
  import { fleetStore } from '$lib/stores/fleet.js';
  import { logStore } from '$lib/stores/logs.js';
  import { OrchestratorClient } from '$lib/api/client.js';
  import { friendlyName } from '$lib/agentDisplay.js';
  import { ROLES, roleInfo } from '$lib/roles.js';
  import type { Agent, AgentCapabilities } from '$lib/types.js';

  let { onclose }: { onclose: () => void } = $props();

  const RUNTIME_VERSION = 'gd-0.1.0';
  // Only used in guidance text (e.g. "ollama pull llama3.1") — never
  // registered as a fake capability.
  const SUGGESTED_MODEL = 'llama3.1';
  const AGENT_ONLINE_TIMEOUT_MS = 20_000;

  // Generate the agent's identity once so the suggested name is stable and so
  // the same key is used at registration. A memorable name ("Sage") beats a
  // wall of "Local Agent" / "gemma3 · analyst"; the specialty and model show
  // as the agent's details everywhere else.
  const agentPubkey = generateRandomPubkey();
  const suggestedName = friendlyName(agentPubkey);

  let name = $state(suggestedName);
  let ollamaUrl = $state('http://localhost:11434');
  let role = $state('analyst');
  let showAdvanced = $state(false);
  const selectedRole = $derived(roleInfo(role));

  type Step = 'form' | 'registering' | 'spawning' | 'waiting' | 'done';
  let step = $state<Step>('form');

  // Ollama detection state machine — deliberately distinguishes *why* no
  // models are available so the guidance shown is actually actionable,
  // rather than one generic "no models detected" message.
  type OllamaState = 'idle' | 'checking' | 'ready' | 'no_models' | 'unreachable' | 'error';
  let ollamaState = $state<OllamaState>('idle');
  let ollamaMessage = $state<string | null>(null);
  let detectedModels = $state<string[]>([]);
  // The URL the current detection result belongs to. Editing the URL field
  // does NOT reset the state machine (a previous version flipped to 'idle' on
  // every keystroke, which unmounted the very input being typed into) — it
  // just makes the result stale, which blocks submission until re-checked.
  let lastDetectedUrl = $state('');
  const urlDirty = $derived(lastDetectedUrl !== '' && normalizedOllamaUrl() !== lastDetectedUrl);
  // The model this agent will use by default (picked by the user, not silently
  // detectedModels[0]). Kept valid as detection results change.
  let defaultModel = $state('');
  $effect(() => {
    if (detectedModels.length === 0) {
      defaultModel = '';
    } else if (!detectedModels.includes(defaultModel)) {
      defaultModel = detectedModels[0];
    }
  });

  let error = $state<string | null>(null);
  let timedOut = $state(false);

  const hasTauri = typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;

  function normalizedOllamaUrl(): string {
    return ollamaUrl.trim().replace(/\/$/, '');
  }

  interface OllamaProbeResult {
    reachable: boolean;
    models: string[];
    error: string | null;
  }

  /**
   * The obvious approach — a plain `fetch()` to Ollama's REST API — does
   * NOT work reliably from inside the Tauri webview, confirmed on real
   * Windows hardware with Ollama genuinely running and models installed.
   * Chromium/WebView2 enforces Private Network Access for a request from
   * the app's origin into `http://localhost:11434`: it requires an
   * `Access-Control-Allow-Private-Network: true` response header that
   * Ollama's server never sends, so the request is silently blocked with a
   * generic network error indistinguishable from "Ollama isn't running." A
   * page served by a plain `python -m http.server` (e.g. legacy
   * Gruper.html) never hits this because it's itself served from
   * `localhost`, which is why that path "just worked" while this dialog
   * didn't. The fix is to make the request from Rust instead — see
   * `detect_ollama_models` in console/src-tauri/src/lib.rs — which talks
   * raw sockets and isn't a browser page, so none of this applies.
   */
  async function detectViaTauri(url: string): Promise<void> {
    const { invoke } = await import('@tauri-apps/api/core');
    const result = await invoke<OllamaProbeResult>('detect_ollama_models', { url });
    detectedModels = result.models ?? [];

    if (!result.reachable) {
      ollamaState = 'unreachable';
      ollamaMessage = result.error ?? null;
    } else if (detectedModels.length > 0) {
      ollamaState = 'ready';
      ollamaMessage = null;
    } else if (result.error) {
      ollamaState = 'error';
      ollamaMessage = result.error;
    } else {
      ollamaState = 'no_models';
      ollamaMessage = null;
    }
  }

  /**
   * Only used outside Tauri (e.g. a plain `vite dev` browser tab during UI
   * work) — a Vite dev server is itself served from `localhost`, so the
   * Private Network Access restriction that breaks this inside the packaged
   * app doesn't apply here, same as the legacy Gruper.html case above.
   */
  async function detectViaBrowserFetch(url: string): Promise<void> {
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
        ollamaMessage = null;
      }
    } catch {
      detectedModels = [];
      ollamaState = 'unreachable';
      ollamaMessage = null;
    }
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

    if (hasTauri) {
      try {
        await detectViaTauri(url);
      } catch (err) {
        detectedModels = [];
        ollamaState = 'error';
        ollamaMessage = `Could not run Ollama detection: ${err instanceof Error ? err.message : String(err)}`;
      }
    } else {
      await detectViaBrowserFetch(url);
    }
    lastDetectedUrl = url;
  }

  // Auto-run detection as soon as the dialog opens — a user shouldn't have
  // to know to click a button before the form tells them anything useful.
  onMount(() => {
    detectOllama();
  });

  // Set by the user clicking "Stop waiting" — checked at the top of every
  // poll iteration in waitForAgentOnline so the wait can always be cut
  // short manually, independent of whatever the timeout/polling is doing.
  let cancelWaiting = $state(false);

  const AGENT_POLL_INTERVAL_MS = 1500;

  function sleep(ms: number): Promise<void> {
    return new Promise((r) => setTimeout(r, ms));
  }

  /**
   * Waits for the freshly-spawned agent to either come online, be reported
   * as crashed, or time out — implemented as a plain bounded polling loop
   * rather than a hand-rolled Promise/event-listener graph. That rewrite is
   * deliberate: a previous version resolved (or so it seemed from code
   * review) via a fleetStore subscription + a Tauri crash-event listener +
   * a setTimeout, all wired together with manual cleanup bookkeeping — and
   * a real Windows test run showed the dialog getting stuck on "Waiting for
   * agent to connect" indefinitely even though a fleet entry existed. This
   * version is provably bounded: the `while` condition is wall-clock time
   * strictly counting down, so barring a JS engine failure it always
   * returns within `timeoutMs` (plus one poll's REST round-trip).
   *
   * Each iteration checks THREE independent signals, not just one:
   *   1. a crash event from the Rust side (agent-sidecar-exited)
   *   2. the local fleetStore (fast path — updated by the console WS's
   *      fleet_event push, when that arrives)
   *   3. a direct REST re-fetch of GET /v1/agents (authoritative — doesn't
   *      depend on the WS push ever arriving at all, which is a single
   *      point of failure this dialog previously depended on entirely)
   * Depending on only the WS push meant that if it was ever dropped
   * (reconnect race, a console WS hiccup, whatever) the dialog would sit on
   * a fleet entry that had, in reality, already come online — this is very
   * likely what a real user saw as "a new entry does appear in the Fleet
   * sidebar, but the agent never becomes usable." Polling REST directly
   * self-heals that regardless of the root cause.
   */
  async function waitForAgentOnline(
    agentId: string,
    timeoutMs: number,
    client: OrchestratorClient,
  ): Promise<{ outcome: 'online' | 'timeout' | 'cancelled' } | { outcome: 'crashed'; detail: string }> {
    let crashDetail: string | null = null;
    let unlistenCrash: (() => void) | null = null;

    if (hasTauri) {
      try {
        const { listen } = await import('@tauri-apps/api/event');
        unlistenCrash = await listen<{ agent_id: string; error?: string; code?: number | null }>(
          'agent-sidecar-exited',
          (event) => {
            if (event.payload.agent_id !== agentId) return;
            crashDetail =
              event.payload.error ?? `agent process exited (code ${event.payload.code ?? 'unknown'})`;
          },
        );
      } catch {
        // Best-effort — if the listener can't be attached for some reason,
        // the REST/fleetStore polling below still covers the common cases.
      }
    }

    try {
      const deadline = Date.now() + timeoutMs;
      while (Date.now() < deadline) {
        if (cancelWaiting) return { outcome: 'cancelled' };
        if (crashDetail) return { outcome: 'crashed', detail: crashDetail };

        const localAgents = get(fleetStore);
        const local = localAgents.find((a) => a.id === agentId);
        if (local && local.status !== 'offline') {
          return { outcome: 'online' };
        }

        try {
          const fresh = await client.listAgents();
          fleetStore.setSnapshot(fresh);
          const freshAgent = fresh.find((a) => a.id === agentId);
          if (freshAgent && freshAgent.status !== 'offline') {
            return { outcome: 'online' };
          }
        } catch {
          // Network hiccup talking to the orchestrator — keep polling
          // rather than failing the whole wait over one bad request.
        }

        if (cancelWaiting) return { outcome: 'cancelled' };
        if (crashDetail) return { outcome: 'crashed', detail: crashDetail };
        await sleep(AGENT_POLL_INTERVAL_MS);
      }
      return { outcome: 'timeout' };
    } finally {
      unlistenCrash?.();
    }
  }

  async function handleSubmit() {
    error = null;
    timedOut = false;

    if (ollamaState !== 'ready' || detectedModels.length === 0) {
      error = 'Ollama needs to be running with at least one model before an agent can be added.';
      return;
    }
    if (urlDirty) {
      error = 'The Ollama address changed since the last check — check it again first.';
      return;
    }
    if (!hasTauri) {
      error = 'Starting a local agent requires the desktop app — this only works in the packaged/dev Console, not a plain browser tab.';
      return;
    }

    const token = authStore.getToken();
    const orchestratorUrl = authStore.getOrchestratorUrl();
    if (!token) {
      error = 'Not connected.';
      return;
    }

    const capabilities: AgentCapabilities = {
      models: detectedModels,
      default_model: defaultModel || detectedModels[0],
      roles: [role],
      tools: [],
      hardware: {
        cpu_cores: navigator.hardwareConcurrency || 4,
        ram_gb: 8,
      },
    };

    const client = new OrchestratorClient(orchestratorUrl, token);

    let agent: Agent;
    try {
      step = 'registering';
      logStore.frontend('info', 'ui', `registering agent "${name.trim() || suggestedName}" (default model ${capabilities.default_model})`);
      agent = await client.registerAgent({
        name: name.trim() || suggestedName,
        pubkey: agentPubkey,
        capabilities,
        runtime_version: RUNTIME_VERSION,
      });
      fleetStore.add(agent);
      logStore.frontend('info', 'ui', `agent registered with orchestrator`, { agent_id: agent.id });
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
      logStore.frontend('error', 'ui', `agent registration failed: ${error}`);
      step = 'form';
      return;
    }

    try {
      step = 'spawning';
      logStore.frontend('info', 'ui', 'starting local agent sidecar', { agent_id: agent.id });
      const { invoke } = await import('@tauri-apps/api/core');
      await invoke('spawn_local_agent', {
        agentId: agent.id,
        jwtToken: token,
        orchestratorUrl,
        ollamaUrl: normalizedOllamaUrl() || undefined,
        capabilitiesJson: JSON.stringify(capabilities),
      });
    } catch (err) {
      error = `${name.trim() || suggestedName} was created, but its local process failed to start: ${err instanceof Error ? err.message : String(err)}`;
      step = 'form';
      return;
    }

    step = 'waiting';
    cancelWaiting = false;
    try {
      const result = await waitForAgentOnline(agent.id, AGENT_ONLINE_TIMEOUT_MS, client);
      if (result.outcome === 'crashed') {
        error = `${name.trim() || suggestedName} was created and started, but stopped before coming online: ${result.detail}. Check that Ollama is running, then try again.`;
        step = 'form';
        return;
      }
      if (result.outcome === 'cancelled') {
        // The agent is already registered and spawned — it keeps trying to
        // connect on its own even after this dialog closes. There is
        // deliberately nothing else to clean up here.
        onclose();
        return;
      }
      timedOut = result.outcome === 'timeout';
      step = 'done';
    } catch (err) {
      // waitForAgentOnline is a bounded loop and should never throw, but if
      // it somehow does, never leave the dialog frozen on "Waiting for
      // agent to connect" — surface it and let the user retry or check the
      // fleet manually instead.
      error = `The agent was created and started, but something unexpected happened while waiting for it to come online: ${err instanceof Error ? err.message : String(err)}. Check the sidebar — it may still connect on its own.`;
      step = 'form';
    }
  }
</script>

<div
  class="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50"
  onkeydown={(e) => { if (e.key === 'Escape') { cancelWaiting = true; onclose(); } }}
  role="presentation"
>
  <div class="glass-card p-6 w-full max-w-md mx-4 space-y-4 max-h-[90vh] overflow-y-auto">
    <div class="flex items-center justify-between">
      <h2 class="text-lg font-semibold text-white">Add an agent</h2>
      <button
        onclick={() => { cancelWaiting = true; onclose(); }}
        class="text-slate-500 hover:text-slate-300 text-sm"
      >✕</button>
    </div>

    {#if step === 'done'}
      {#if timedOut}
        <div class="bg-amber-500/10 border border-amber-500/30 text-amber-300 text-sm rounded-lg p-3">
          {name.trim() || suggestedName} was created and started, but hasn't come online yet.
          This can happen on first run while antivirus checks the freshly-installed app — it may
          still connect in the next few seconds. If it doesn't, check that Ollama is running.
        </div>
      {:else}
        <div class="bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 text-sm rounded-lg p-3">
          {name.trim() || suggestedName} is online and ready — go ahead and ask a question.
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
        A new AI helper that runs privately on this computer.
      </p>

      <!-- Ollama status — one line when fine, actionable guidance when not. -->
      {#if ollamaState === 'checking' || ollamaState === 'idle'}
        <p class="text-xs text-slate-500 progress-pulse">Checking for Ollama (the app that runs AI models)…</p>
      {:else if ollamaState === 'ready'}
        <p class="text-xs text-emerald-400">
          ✓ Ollama is running — {detectedModels.length} model{detectedModels.length === 1 ? '' : 's'} installed.
        </p>
        {#if urlDirty}
          <div class="flex items-center gap-2 text-xs text-amber-400">
            <span class="flex-1">The Ollama address changed — check it again to continue.</span>
            <button
              type="button"
              onclick={detectOllama}
              class="px-2 py-1 rounded-lg bg-white/10 border border-white/10 text-slate-200 hover:bg-white/20"
            >
              Check
            </button>
          </div>
        {/if}
      {:else}
        <div class="bg-amber-500/10 border border-amber-500/30 rounded-lg p-3 space-y-2 text-xs">
          {#if ollamaState === 'no_models'}
            <p class="text-amber-300">
              Ollama is running, but no AI models are installed yet.
            </p>
            <p class="text-slate-400">
              Open a terminal and run
              <code class="text-slate-300 bg-white/10 rounded px-1">ollama pull {SUGGESTED_MODEL}</code>
              to download one (a few GB), then try again.
            </p>
          {:else}
            <p class="text-amber-300">
              Can't find Ollama — the free app this agent needs to run AI models.
            </p>
            <p class="text-slate-400">
              If it isn't installed yet,
              <a
                href="https://ollama.com/download"
                target="_blank"
                rel="noreferrer"
                class="text-blue-400 hover:text-blue-300 underline"
              >download Ollama</a>, start it, then try again.
            </p>
          {/if}
          {#if ollamaMessage}
            <p class="text-slate-500">{ollamaMessage}</p>
          {/if}
          <div class="flex gap-2 items-center">
            <input
              type="text"
              bind:value={ollamaUrl}
              title="Where Ollama is running — the standard address is already filled in"
              class="flex-1 bg-white/5 border border-white/10 rounded-lg px-2 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500 font-mono"
            />
            <button
              type="button"
              onclick={detectOllama}
              class="text-xs px-3 py-1.5 rounded-lg bg-white/10 border border-white/10 text-slate-200 hover:bg-white/20"
            >
              Try again
            </button>
          </div>
        </div>
      {/if}

      <div>
        <label class="block text-xs text-slate-400 mb-1" for="agent-name">Name</label>
        <input
          id="agent-name"
          type="text"
          bind:value={name}
          placeholder={suggestedName}
          class="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500"
        />
        <p class="text-xs mt-1 text-slate-500">
          Something memorable — you'll ask for it by name.
        </p>
      </div>

      <div>
        <span class="block text-xs text-slate-400 mb-1.5">Specialty</span>
        <div class="grid grid-cols-3 gap-1.5" role="radiogroup" aria-label="Specialty">
          {#each ROLES as r (r.id)}
            <button
              type="button"
              role="radio"
              aria-checked={role === r.id}
              onclick={() => { role = r.id; }}
              class="flex items-center gap-1.5 rounded-lg border px-2 py-1.5 text-xs text-left transition-colors {role === r.id
                ? 'border-blue-500/60 bg-blue-500/10 text-white'
                : 'border-white/10 text-slate-400 hover:bg-white/5'}"
            >
              <span>{r.icon}</span>
              <span class="truncate">{r.label}</span>
            </button>
          {/each}
        </div>
        {#if selectedRole}
          <p class="text-xs mt-1.5 text-slate-500">{selectedRole.icon} {selectedRole.tagline}. You can change this later.</p>
        {/if}
      </div>

      {#if ollamaState === 'ready' && detectedModels.length > 1}
        <div>
          <label class="block text-xs text-slate-400 mb-1" for="agent-default-model">Model</label>
          <select
            id="agent-default-model"
            bind:value={defaultModel}
            class="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500 font-mono"
          >
            {#each detectedModels as m}
              <option value={m} class="bg-slate-800 text-white">{m}</option>
            {/each}
          </select>
          <p class="text-xs mt-1 text-slate-500">
            The AI model this agent thinks with.
          </p>
        </div>
      {/if}

      {#if ollamaState === 'ready'}
        <div>
          <button
            type="button"
            onclick={() => { showAdvanced = !showAdvanced; }}
            class="text-xs text-slate-500 hover:text-slate-300 transition-colors"
          >
            {showAdvanced ? '▾' : '▸'} Advanced
          </button>
          {#if showAdvanced}
            <div class="mt-2">
              <label class="block text-xs text-slate-400 mb-1" for="ollama-url">Where Ollama runs</label>
              <div class="flex gap-2">
                <input
                  id="ollama-url"
                  type="text"
                  bind:value={ollamaUrl}
                  class="flex-1 bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500 font-mono"
                />
                <button
                  type="button"
                  onclick={detectOllama}
                  class="text-xs px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-slate-300 hover:bg-white/10"
                >
                  Re-check
                </button>
              </div>
              <p class="text-xs mt-1 text-slate-500">
                Only change this if Ollama runs somewhere other than the standard address.
              </p>
            </div>
          {/if}
        </div>
      {/if}

      {#if !hasTauri}
        <div class="bg-amber-500/10 border border-amber-500/30 text-amber-300 text-xs rounded-lg p-3">
          Running outside the desktop app (e.g. a plain browser dev tab) — agent registration will
          work, but starting the local process requires the desktop app.
        </div>
      {/if}

      {#if error}
        <div class="bg-red-500/10 border border-red-500/30 text-red-400 text-sm rounded-lg p-3">
          {error}
        </div>
      {/if}

      <button
        onclick={handleSubmit}
        disabled={step === 'registering' || step === 'spawning' || step === 'waiting' || ollamaState !== 'ready' || urlDirty}
        title={ollamaState !== 'ready' || urlDirty ? 'Ollama needs to be running (and checked) with at least one model first' : undefined}
        class="w-full bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white rounded-lg px-4 py-2 text-sm font-medium transition-colors"
      >
        {#if step === 'registering'}
          Creating…
        {:else if step === 'spawning'}
          Starting…
        {:else if step === 'waiting'}
          Waiting for {name.trim() || suggestedName} to connect…
        {:else}
          Add agent
        {/if}
      </button>

      {#if step === 'waiting'}
        <p class="text-xs text-slate-500 text-center">
          This usually takes a few seconds. The agent keeps starting in the background
          even if you stop waiting.
        </p>
        <button
          type="button"
          onclick={() => { cancelWaiting = true; }}
          class="w-full text-xs text-slate-400 hover:text-slate-200 transition-colors"
        >
          Stop waiting and close
        </button>
      {/if}
    {/if}
  </div>
</div>
