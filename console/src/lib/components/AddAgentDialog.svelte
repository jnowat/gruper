<!--
  "Add Local Agent" — minimum viable agent onboarding (see ROADMAP.md WP-32).

  Closes the biggest gap called out across prior audits: a desktop user had
  no way to go from "Console installed" to "a task actually runs" without
  hand-editing agent-runtime/.env and copy-pasting a JWT from a curl command.
  This dialog does the whole thing in the UI:
    1. generate a fresh agent identity (pubkey) — same pattern the Console
       already uses for its own identity (see stores/auth.ts)
    2. probe local Ollama for installed models, so capabilities aren't a lie
    3. POST /v1/agents with the Console's own JWT (valid because gd-0.1
       tokens are per-owner, not per-agent — see orchestrator/ws/agent_ws.py)
    4. ask the Rust side to spawn the gruper-agent sidecar with the right
       env vars — the agent shows up in the fleet once it connects
  Scope: single machine, same owner as the Console. Remote/cross-machine
  agent registration is unaffected and stays manual.
-->
<script lang="ts">
  import { authStore, generateRandomPubkey } from '$lib/stores/auth.js';
  import { fleetStore } from '$lib/stores/fleet.js';
  import { OrchestratorClient } from '$lib/api/client.js';
  import type { AgentCapabilities } from '$lib/types.js';

  let { onclose }: { onclose: () => void } = $props();

  const RUNTIME_VERSION = 'gd-0.1.0';
  const DEFAULT_MODEL = 'llama3.1:8b';

  let name = $state('Local Agent');
  let ollamaUrl = $state('http://localhost:11434');
  let role = $state('analyst');

  type Step = 'form' | 'detecting' | 'registering' | 'spawning' | 'done';
  let step = $state<Step>('form');
  let detectedModels = $state<string[]>([]);
  let detectAttempted = $state(false);
  let error = $state<string | null>(null);

  const hasTauri = typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;

  async function detectOllama() {
    step = 'detecting';
    error = null;
    try {
      const res = await fetch(`${ollamaUrl.replace(/\/$/, '')}/api/tags`, { signal: AbortSignal.timeout(3000) });
      if (res.ok) {
        const data = await res.json();
        detectedModels = Array.isArray(data.models) ? data.models.map((m: { name: string }) => m.name) : [];
      } else {
        detectedModels = [];
      }
    } catch {
      detectedModels = [];
    } finally {
      detectAttempted = true;
      step = 'form';
    }
  }

  async function handleSubmit() {
    error = null;
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
      models: detectedModels.length > 0 ? detectedModels : [DEFAULT_MODEL],
      roles: [role],
      tools: [],
      hardware: {
        cpu_cores: navigator.hardwareConcurrency || 4,
        ram_gb: 8,
      },
    };

    try {
      step = 'registering';
      const client = new OrchestratorClient(orchestratorUrl, token);
      const agent = await client.registerAgent({
        name: name.trim() || 'Local Agent',
        pubkey: generateRandomPubkey(),
        capabilities,
        runtime_version: RUNTIME_VERSION,
      });
      fleetStore.add(agent);

      step = 'spawning';
      const { invoke } = await import('@tauri-apps/api/core');
      await invoke('spawn_local_agent', {
        agentId: agent.id,
        jwtToken: token,
        orchestratorUrl,
        ollamaUrl: ollamaUrl.trim() || undefined,
      });

      step = 'done';
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
      step = 'form';
    }
  }
</script>

<div class="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50">
  <div class="glass-card p-6 w-full max-w-md mx-4 space-y-4">
    <div class="flex items-center justify-between">
      <h2 class="text-lg font-semibold text-white">Add Local Agent</h2>
      <button onclick={onclose} class="text-slate-500 hover:text-slate-300 text-sm">✕</button>
    </div>

    {#if step === 'done'}
      <div class="bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 text-sm rounded-lg p-3">
        Agent registered and started. It should appear online in the fleet within a few seconds
        (heartbeat + registration handshake).
      </div>
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
            class="flex-1 bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500"
          />
          <button
            type="button"
            onclick={detectOllama}
            disabled={step === 'detecting'}
            class="text-xs px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-slate-300 hover:bg-white/10 disabled:opacity-50"
          >
            {step === 'detecting' ? 'Detecting…' : 'Detect models'}
          </button>
        </div>
        {#if detectAttempted}
          <p class="text-xs mt-1 {detectedModels.length ? 'text-emerald-400' : 'text-amber-400'}">
            {#if detectedModels.length}
              Found {detectedModels.length} model{detectedModels.length === 1 ? '' : 's'}: {detectedModels.join(', ')}
            {:else}
              No Ollama models detected — will register with a placeholder model
              ({DEFAULT_MODEL}) that must be pulled before tasks can run.
            {/if}
          </p>
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
        disabled={step === 'registering' || step === 'spawning'}
        class="w-full bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white rounded-lg px-4 py-2 text-sm font-medium transition-colors"
      >
        {#if step === 'registering'}
          Registering…
        {:else if step === 'spawning'}
          Starting agent…
        {:else}
          Add Agent
        {/if}
      </button>
    {/if}
  </div>
</div>
