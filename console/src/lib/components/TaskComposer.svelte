<!--
  Task composer. The one primary choice is WHICH AGENT runs the task; each agent
  already has a default model, so the model is not shown at all unless you ask to
  change it ("using <default> · change"). This removes the "choosing a model
  twice" confusion — the common path is: pick agent → type prompt → submit.
-->
<script lang="ts">
  import { authStore } from '$lib/stores/auth.js';
  import { tasksStore } from '$lib/stores/tasks.js';
  import { logStore } from '$lib/stores/logs.js';
  import { OrchestratorClient } from '$lib/api/client.js';
  import { agentModel, agentRole, agentLabel } from '$lib/agentDisplay.js';
  import AgentAvatar from '$lib/components/AgentAvatar.svelte';
  import type { Agent, DataClass, TaskSubmitRequest } from '$lib/types.js';

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

  let prompt = $state('');
  let overrideModel = $state(false);
  let modelName = $state(''); // '' = use the agent's default
  let temperature = $state(0.7);
  let topP = $state(0.9);
  let topK = $state(40);
  let repeatPenalty = $state(1.1);
  let maxTokens = $state(2048);
  let contextLength = $state(4096);
  let roleTemplate = $state('analyst');
  let dataClass = $state<DataClass>('internal');
  let priority = $state(50);
  let timeoutS = $state(300);
  let showAdvanced = $state(false);
  let loading = $state(false);
  let error = $state<string | null>(null);

  const ROLE_TEMPLATES = [
    'analyst', 'creative', 'critic', 'synthesizer', 'expert',
    'devil_advocate', 'philosopher', 'economist', 'ethicist',
    'scientist', 'psychologist', 'engineer',
  ];

  // Changing agent: clear any model override and default the role to the agent's
  // own role, so the common case needs no extra decisions.
  let roleEdited = $state(false);
  $effect(() => {
    void selectedAgentId;
    overrideModel = false;
    modelName = '';
    const r = agent ? agentRole(agent) : null;
    if (!roleEdited && r && ROLE_TEMPLATES.includes(r)) roleTemplate = r;
  });

  async function handleSubmit() {
    if (!agent || !prompt.trim()) return;
    const auth = $authStore;
    if (!auth.token) return;
    error = null;
    loading = true;
    try {
      const client = new OrchestratorClient(auth.orchestratorUrl, auth.token);
      const effectiveModel = overrideModel ? modelName : '';
      const body: TaskSubmitRequest = {
        assigned_agent_id: agent.id,
        data_class: dataClass,
        input: {
          prompt: prompt.trim(),
          role_template: roleTemplate,
          model_preferences: {
            ...(effectiveModel ? { name: effectiveModel } : {}),
            temperature, top_p: topP, top_k: topK, repeat_penalty: repeatPenalty,
            max_tokens: maxTokens, context_length: contextLength,
          },
        },
        priority,
        timeout_s: timeoutS,
      };
      const task = await client.submitTask(body);
      logStore.frontend('info', 'ui', `submitted task to "${agent.name}" (model: ${effectiveModel || `${defaultModel} (default)`})`, {
        task_id: task.id,
        agent_id: agent.id,
      });
      tasksStore.prependTask(task);
      prompt = '';
      onTaskSubmitted?.(task.id);
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    } finally {
      loading = false;
    }
  }
</script>

<div class="glass-card p-4 space-y-4">
  <h2 class="text-sm font-semibold text-white">New task</h2>

  <form class="space-y-3" onsubmit={(e) => { e.preventDefault(); handleSubmit(); }}>
    <!-- Primary choice: which agent -->
    <div>
      <label class="block text-xs text-slate-400 mb-1" for="task-agent">Send to which agent?</label>
      {#if agents.length > 0}
        <select
          id="task-agent"
          bind:value={selectedAgentId}
          class="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500"
        >
          {#each agents as a (a.id)}
            <option value={a.id} class="bg-slate-800 text-white">{agentLabel(a)}{a.status === 'offline' ? ' · offline' : ''}</option>
          {/each}
        </select>
        {#if agent}
          <div class="flex items-center gap-2 mt-2 px-1">
            <AgentAvatar id={agent.id} name={agent.name} size={30} />
            <div class="min-w-0">
              <p class="text-sm text-white truncate">{agent.name}</p>
              <p class="text-xs text-slate-500 truncate">
                {#if defaultModel}<span class="font-mono text-slate-400">{defaultModel}</span>{/if}
                {#if agentRole(agent)}<span class="text-blue-300"> · {agentRole(agent)}</span>{/if}
                {#if agent.status === 'offline'}<span class="text-amber-400"> · offline (task will queue)</span>{/if}
              </p>
            </div>
          </div>
        {/if}
      {:else}
        <p class="text-xs text-slate-500">No agents yet — add one from the Fleet sidebar first.</p>
      {/if}
    </div>

    <!-- Prompt -->
    <div>
      <label class="block text-xs text-slate-400 mb-1" for="prompt">Prompt</label>
      <textarea
        id="prompt"
        bind:value={prompt}
        rows={6}
        placeholder="Describe the task for the agent…"
        class="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white placeholder:text-slate-500 focus:outline-none focus:border-blue-500 resize-none"
        required
      ></textarea>
    </div>

    <div class="grid grid-cols-2 gap-3">
      <div>
        <label class="block text-xs text-slate-400 mb-1" for="role">Role</label>
        <select
          id="role"
          bind:value={roleTemplate}
          oninput={() => { roleEdited = true; }}
          class="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500"
        >
          {#each ROLE_TEMPLATES as r}
            <option value={r} class="bg-slate-800 text-white">{r}</option>
          {/each}
        </select>
      </div>
      <div>
        <label class="block text-xs text-slate-400 mb-1" for="data-class">Data class</label>
        <select
          id="data-class"
          bind:value={dataClass}
          class="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500"
        >
          <option value="public" class="bg-slate-800 text-white">Public</option>
          <option value="internal" class="bg-slate-800 text-white">Internal</option>
          <option value="confidential" class="bg-slate-800 text-white">Confidential</option>
        </select>
      </div>
    </div>

    <!-- Model: hidden by default; the agent's default is used unless you change it. -->
    {#if agent}
      <div class="text-xs text-slate-500">
        {#if !overrideModel}
          Model: <span class="font-mono text-slate-400">{defaultModel || 'agent default'}</span>
          {#if agent.capabilities?.models?.length}
            · <button type="button" class="text-blue-400 hover:text-blue-300" onclick={() => (overrideModel = true)}>change for this task</button>
          {/if}
        {:else}
          <div class="flex items-center gap-2">
            <select
              bind:value={modelName}
              class="flex-1 bg-white/5 border border-white/10 rounded-lg px-3 py-1.5 text-sm text-white focus:outline-none focus:border-blue-500 font-mono"
            >
              <option value="" class="bg-slate-800 text-white">Agent default ({defaultModel})</option>
              {#each agent.capabilities?.models ?? [] as m}
                <option value={m} class="bg-slate-800 text-white">{m}</option>
              {/each}
            </select>
            <button type="button" class="text-slate-400 hover:text-slate-200" onclick={() => { overrideModel = false; modelName = ''; }}>use default</button>
          </div>
        {/if}
      </div>
    {/if}

    <!-- Advanced: inference parameters -->
    <button
      type="button"
      class="text-xs text-slate-400 hover:text-slate-200 transition-colors"
      onclick={() => (showAdvanced = !showAdvanced)}
    >
      {showAdvanced ? '▲ Hide' : '▼ Show'} inference parameters
    </button>

    {#if showAdvanced}
      <div class="grid grid-cols-2 gap-3 bg-white/5 rounded-lg p-3">
        {#each [
          { label: 'Temperature', id: 'temp', bind: temperature, min: 0, max: 1, step: 0.05 },
          { label: 'Top-P', id: 'top-p', bind: topP, min: 0, max: 1, step: 0.05 },
          { label: 'Top-K', id: 'top-k', bind: topK, min: 1, max: 100, step: 1 },
          { label: 'Repeat Penalty', id: 'rep', bind: repeatPenalty, min: 0.5, max: 2, step: 0.05 },
        ] as param}
          <div>
            <label class="block text-xs text-slate-400 mb-1" for={param.id}>
              {param.label} <span class="text-blue-400">{param.bind}</span>
            </label>
            <input id={param.id} type="range" min={param.min} max={param.max} step={param.step}
              bind:value={param.bind} class="w-full accent-blue-500" />
          </div>
        {/each}
        <div>
          <label class="block text-xs text-slate-400 mb-1" for="max-tok">Max Tokens <span class="text-blue-400">{maxTokens}</span></label>
          <input id="max-tok" type="range" min={128} max={8192} step={128} bind:value={maxTokens} class="w-full accent-blue-500" />
        </div>
        <div>
          <label class="block text-xs text-slate-400 mb-1" for="ctx-len">Context Length <span class="text-blue-400">{contextLength}</span></label>
          <input id="ctx-len" type="range" min={512} max={16384} step={512} bind:value={contextLength} class="w-full accent-blue-500" />
        </div>
        <div>
          <label class="block text-xs text-slate-400 mb-1" for="priority">Priority <span class="text-blue-400">{priority}</span></label>
          <input id="priority" type="range" min={1} max={100} step={1} bind:value={priority} class="w-full accent-blue-500" />
        </div>
        <div>
          <label class="block text-xs text-slate-400 mb-1" for="timeout">Timeout (s) <span class="text-blue-400">{timeoutS}</span></label>
          <input id="timeout" type="range" min={60} max={86400} step={60} bind:value={timeoutS} class="w-full accent-blue-500" />
        </div>
      </div>
    {/if}

    {#if error}
      <div class="bg-red-500/10 border border-red-500/30 text-red-400 text-sm rounded-lg p-2">{error}</div>
    {/if}

    <button
      type="submit"
      disabled={loading || !agent || !prompt.trim()}
      class="w-full bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed text-white rounded-lg px-4 py-2 text-sm font-medium transition-colors"
    >
      {loading ? 'Submitting…' : agent ? `Submit to ${agent.name}` : 'Submit Task'}
    </button>
  </form>
</div>
