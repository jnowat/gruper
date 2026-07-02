<!--
  Ask a question. Two things happen here, in this order: pick which agent to
  ask (tangible cards, each showing its specialty in plain words), then type
  the question. Nothing else is asked on the common path — no role, no data
  class, no model. The specialty persona (roles.ts) is sent as the task's
  system_prompt so the chosen helper genuinely answers in character.

  "Advanced" holds the rare knobs: answer style (per-question role override),
  a one-off model override, and generation limits. The draft survives closing
  the dialog (module-scope), so a stray backdrop click never loses typed text.
-->
<script module lang="ts">
  // Survives unmount so an accidentally-closed composer keeps the draft.
  let savedDraft = '';
</script>

<script lang="ts">
  import { untrack } from 'svelte';
  import { authStore } from '$lib/stores/auth.js';
  import { tasksStore } from '$lib/stores/tasks.js';
  import { logStore } from '$lib/stores/logs.js';
  import { OrchestratorClient } from '$lib/api/client.js';
  import { agentModel, agentRole } from '$lib/agentDisplay.js';
  import { ROLES, roleInfo, rolePersona } from '$lib/roles.js';
  import AgentAvatar from '$lib/components/AgentAvatar.svelte';
  import type { Agent, TaskSubmitRequest } from '$lib/types.js';

  let {
    agents = [],
    selectedAgentId = $bindable<string | null>(null),
    onTaskSubmitted,
  }: {
    agents?: Agent[];
    selectedAgentId?: string | null;
    onTaskSubmitted?: (taskId: string) => void;
  } = $props();

  $effect(() => {
    if ((!selectedAgentId || !agents.some((a) => a.id === selectedAgentId)) && agents.length > 0) {
      selectedAgentId = agents[0].id;
    }
  });
  const agent = $derived(agents.find((a) => a.id === selectedAgentId) ?? null);
  const defaultModel = $derived(agent ? agentModel(agent) : '');
  const agentRoleInfo = $derived(agent ? roleInfo(agentRole(agent)) : null);

  let prompt = $state(savedDraft);
  $effect(() => {
    savedDraft = prompt;
  });

  let modelName = $state(''); // '' = use the agent's default (Advanced only)
  let temperature = $state(0.7);
  let maxTokens = $state(2048);
  let contextLength = $state(4096);
  let timeoutS = $state(300);
  let roleTemplate = $state('analyst');
  let showAdvanced = $state(false);
  let loading = $state(false);
  let error = $state<string | null>(null);

  // Changing agent: clear any model override and follow the agent's own
  // specialty, so the common case needs no extra decisions. Everything except
  // the id itself is read inside untrack(): the agent OBJECT is replaced on
  // every fleet_event (status flips, heartbeats), and without untrack those
  // events would re-run this effect and silently wipe a chosen model override.
  let roleEdited = $state(false);
  let lastAgentId: string | null = null;
  $effect(() => {
    const id = selectedAgentId;
    untrack(() => {
      if (id === lastAgentId) return;
      lastAgentId = id;
      modelName = '';
      const r = agent ? agentRole(agent) : null;
      if (!roleEdited && r && ROLES.some((role) => role.id === r)) roleTemplate = r;
    });
  });

  async function handleSubmit() {
    if (!agent || !prompt.trim()) return;
    const auth = $authStore;
    if (!auth.token) return;
    error = null;
    loading = true;
    try {
      const client = new OrchestratorClient(auth.orchestratorUrl, auth.token);
      const effectiveModel = modelName; // '' → the agent's default
      const persona = rolePersona(roleTemplate);
      const body: TaskSubmitRequest = {
        assigned_agent_id: agent.id,
        data_class: 'internal',
        input: {
          prompt: prompt.trim(),
          role_template: roleTemplate,
          ...(persona ? { system_prompt: persona } : {}),
          model_preferences: {
            ...(effectiveModel ? { name: effectiveModel } : {}),
            temperature,
            max_tokens: maxTokens,
            context_length: contextLength,
          },
        },
        timeout_s: timeoutS,
      };
      const task = await client.submitTask(body);
      logStore.frontend('info', 'ui', `submitted task to "${agent.name}" (model: ${effectiveModel || `${defaultModel} (default)`})`, {
        task_id: task.id,
        agent_id: agent.id,
      });
      tasksStore.prependTask(task);
      prompt = '';
      savedDraft = '';
      onTaskSubmitted?.(task.id);
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    } finally {
      loading = false;
    }
  }
</script>

<div class="glass-card p-4 space-y-4">
  <h2 class="text-sm font-semibold text-white">Ask a question</h2>

  <form class="space-y-3" onsubmit={(e) => { e.preventDefault(); handleSubmit(); }}>
    <!-- Primary choice: which agent -->
    <div>
      <span class="block text-xs text-slate-400 mb-1.5">Who should answer?</span>
      {#if agents.length > 0}
        <div class="grid grid-cols-2 gap-1.5" role="radiogroup" aria-label="Who should answer?">
          {#each agents as a (a.id)}
            {@const info = roleInfo(agentRole(a))}
            <button
              type="button"
              role="radio"
              aria-checked={a.id === selectedAgentId}
              onclick={() => { selectedAgentId = a.id; }}
              class="flex items-center gap-2 rounded-lg border px-2 py-1.5 text-left transition-colors {a.id === selectedAgentId
                ? 'border-blue-500/60 bg-blue-500/10'
                : 'border-white/10 hover:bg-white/5'} {a.status === 'offline' ? 'opacity-60' : ''}"
            >
              <AgentAvatar id={a.id} name={a.name} size={26} />
              <span class="min-w-0">
                <span class="block text-xs font-medium text-white truncate">{a.name}</span>
                <span class="block text-xs text-slate-500 truncate">
                  {#if info}{info.icon} {info.label}{/if}{#if a.status === 'offline'}{info ? ' · ' : ''}offline{/if}
                </span>
              </span>
            </button>
          {/each}
        </div>
        {#if agent}
          <p class="text-xs text-slate-500 mt-1.5 px-1 truncate">
            {#if agentRoleInfo}{agentRoleInfo.icon} {agentRoleInfo.tagline}.{/if}
            {#if agent.status === 'offline'}<span class="text-amber-400"> {agent.name} is offline — your question will wait until it reconnects.</span>{/if}
          </p>
        {/if}
      {:else}
        <p class="text-xs text-slate-500">No agents yet — add one from the sidebar first.</p>
      {/if}
    </div>

    <!-- The question -->
    <div>
      <label class="block text-xs text-slate-400 mb-1" for="prompt">Your question</label>
      <textarea
        id="prompt"
        bind:value={prompt}
        rows={6}
        placeholder="What do you want to know?"
        onkeydown={(e) => { if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); handleSubmit(); } }}
        class="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white placeholder:text-slate-500 focus:outline-none focus:border-blue-500 resize-none"
        required
      ></textarea>
    </div>

    <!-- Advanced: answer style, model override, generation limits -->
    <button
      type="button"
      class="text-xs text-slate-400 hover:text-slate-200 transition-colors"
      onclick={() => (showAdvanced = !showAdvanced)}
    >
      {showAdvanced ? '▲ Hide' : '▼ Show'} advanced options
    </button>

    {#if showAdvanced}
      <div class="bg-white/5 rounded-lg p-3">
        <label class="block text-xs text-slate-400 mb-1" for="role">Answer style</label>
        <select
          id="role"
          bind:value={roleTemplate}
          oninput={() => { roleEdited = true; }}
          class="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500"
        >
          {#each ROLES as r (r.id)}
            <option value={r.id} class="bg-slate-800 text-white">{r.icon} {r.label} — {r.tagline}</option>
          {/each}
        </select>
        <p class="text-xs mt-1 text-slate-500">
          How this one answer is approached — normally just
          {#if agent}{agent.name}'s own specialty{#if agentRoleInfo}&nbsp;({agentRoleInfo.label}){/if}{:else}the agent's specialty{/if}.
        </p>
      </div>

      {#if agent?.capabilities?.models?.length}
        <div class="bg-white/5 rounded-lg p-3">
          <label class="block text-xs text-slate-400 mb-1" for="model-override">Model</label>
          <select
            id="model-override"
            bind:value={modelName}
            class="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-1.5 text-sm text-white focus:outline-none focus:border-blue-500 font-mono"
          >
            <option value="" class="bg-slate-800 text-white">Use {agent.name}'s model ({defaultModel})</option>
            {#each agent.capabilities.models as m}
              <option value={m} class="bg-slate-800 text-white">{m}</option>
            {/each}
          </select>
          <p class="text-xs mt-1 text-slate-500">Only change this to run this one question on a different installed model.</p>
        </div>
      {/if}

      <div class="grid grid-cols-2 gap-3 bg-white/5 rounded-lg p-3">
        <div>
          <label class="block text-xs text-slate-400 mb-1" for="temp">
            Creativity <span class="text-blue-400">{temperature}</span>
          </label>
          <input id="temp" type="range" min={0} max={1} step={0.05} bind:value={temperature} class="w-full accent-blue-500" />
          <p class="text-xs text-slate-600 mt-0.5">Low = focused, high = adventurous</p>
        </div>
        <div>
          <label class="block text-xs text-slate-400 mb-1" for="max-tok">
            Answer length <span class="text-blue-400">{maxTokens}</span>
          </label>
          <input id="max-tok" type="range" min={128} max={8192} step={128} bind:value={maxTokens} class="w-full accent-blue-500" />
          <p class="text-xs text-slate-600 mt-0.5">Maximum length, in tokens</p>
        </div>
        <div>
          <label class="block text-xs text-slate-400 mb-1" for="ctx-len">
            Context window <span class="text-blue-400">{contextLength}</span>
          </label>
          <input id="ctx-len" type="range" min={512} max={16384} step={512} bind:value={contextLength} class="w-full accent-blue-500" />
          <p class="text-xs text-slate-600 mt-0.5">How much text the model can consider</p>
        </div>
        <div>
          <label class="block text-xs text-slate-400 mb-1" for="timeout">
            Time limit <span class="text-blue-400">{timeoutS >= 3600 ? `${Math.round(timeoutS / 360) / 10}h` : `${Math.round(timeoutS / 60)}m`}</span>
          </label>
          <input id="timeout" type="range" min={60} max={86400} step={60} bind:value={timeoutS} class="w-full accent-blue-500" />
          <p class="text-xs text-slate-600 mt-0.5">Give up if no answer by then</p>
        </div>
      </div>
    {/if}

    {#if error}
      <div class="bg-red-500/10 border border-red-500/30 text-red-400 text-sm rounded-lg p-2">{error}</div>
    {/if}

    <button
      type="submit"
      disabled={loading || !agent || !prompt.trim()}
      title="Ctrl+Enter also sends"
      class="w-full bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed text-white rounded-lg px-4 py-2 text-sm font-medium transition-colors"
    >
      {loading ? 'Sending…' : agent ? `Ask ${agent.name}` : 'Ask'}
    </button>
  </form>
</div>
