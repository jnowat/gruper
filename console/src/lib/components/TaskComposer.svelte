<!--
  Task composer. The PRIMARY choice is which agent runs the task; each agent
  already has a default model (chosen when it was added), so the model is
  secondary — shown read-only, overridable only under "Advanced" for a single
  task. This removes the "why am I choosing a model twice?" confusion.
-->
<script lang="ts">
  import { authStore } from '$lib/stores/auth.js';
  import { tasksStore } from '$lib/stores/tasks.js';
  import { logStore } from '$lib/stores/logs.js';
  import { OrchestratorClient } from '$lib/api/client.js';
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

  // The chosen agent (the primary decision). Default to the first agent if the
  // caller didn't pre-select one, so the composer is never in a "no agent" state
  // when agents exist.
  $effect(() => {
    if ((!selectedAgentId || !agents.some((a) => a.id === selectedAgentId)) && agents.length > 0) {
      selectedAgentId = agents[0].id;
    }
  });
  const agent = $derived(agents.find((a) => a.id === selectedAgentId) ?? null);

  function defaultModelOf(a: Agent | null): string {
    return a?.capabilities?.default_model ?? a?.capabilities?.models?.[0] ?? '';
  }
  const agentDefaultModel = $derived(defaultModelOf(agent));
  const agentRole = $derived(agent?.capabilities?.roles?.[0] ?? null);

  // Inference controls.
  let prompt = $state('');
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

  // When the agent changes, drop any per-task model override (a model pinned for
  // one agent may not exist on another) and default the role to that agent's
  // configured role, so the common case needs no extra choices.
  let roleEdited = $state(false);
  $effect(() => {
    void selectedAgentId;
    modelName = '';
    if (!roleEdited && agentRole && ROLE_TEMPLATES.includes(agentRole)) {
      roleTemplate = agentRole;
    }
  });

  function optionLabel(a: Agent): string {
    const bits = [defaultModelOf(a) || 'no model'];
    const r = a.capabilities?.roles?.[0];
    if (r) bits.push(r);
    if (a.status === 'offline') bits.push('offline');
    return `${a.name} — ${bits.join(' · ')}`;
  }

  async function handleSubmit() {
    if (!agent || !prompt.trim()) return;
    const auth = $authStore;
    if (!auth.token) return;

    error = null;
    loading = true;
    try {
      const client = new OrchestratorClient(auth.orchestratorUrl, auth.token);
      const body: TaskSubmitRequest = {
        assigned_agent_id: agent.id,
        data_class: dataClass,
        input: {
          prompt: prompt.trim(),
          role_template: roleTemplate,
          model_preferences: {
            ...(modelName ? { name: modelName } : {}),
            temperature,
            top_p: topP,
            top_k: topK,
            repeat_penalty: repeatPenalty,
            max_tokens: maxTokens,
            context_length: contextLength,
          },
        },
        priority,
        timeout_s: timeoutS,
      };
      const task = await client.submitTask(body);
      logStore.frontend('info', 'ui', `submitted task to "${agent.name}" (model: ${modelName || `${agentDefaultModel} (default)`})`, {
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
      <label class="block text-xs text-slate-400 mb-1" for="task-agent">Send to agent</label>
      {#if agents.length > 0}
        <select
          id="task-agent"
          bind:value={selectedAgentId}
          class="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500"
        >
          {#each agents as a (a.id)}
            <option value={a.id} class="bg-slate-800 text-white">{optionLabel(a)}</option>
          {/each}
        </select>
        {#if agent}
          <p class="text-xs mt-1 text-slate-500">
            Runs on <span class="font-mono text-slate-400">{agentDefaultModel || 'the agent default'}</span>
            {#if agent.status === 'offline'}<span class="text-amber-400"> · agent is offline; the task will queue until it reconnects</span>{/if}
          </p>
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
        <label class="block text-xs text-slate-400 mb-1" for="role">Role template</label>
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

    <!-- Advanced: per-task model override + inference parameters -->
    <button
      type="button"
      class="text-xs text-slate-400 hover:text-slate-200 transition-colors"
      onclick={() => (showAdvanced = !showAdvanced)}
    >
      {showAdvanced ? '▲ Hide' : '▼ Show'} advanced (model override, inference parameters)
    </button>

    {#if showAdvanced}
      <div class="space-y-3 bg-white/5 rounded-lg p-3">
        <div>
          <label class="block text-xs text-slate-400 mb-1" for="model">Override model (this task only)</label>
          {#if agent?.capabilities?.models?.length}
            <select
              id="model"
              bind:value={modelName}
              class="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500 font-mono"
            >
              <option value="" class="bg-slate-800 text-white">
                Agent default{agentDefaultModel ? ` (${agentDefaultModel})` : ''}
              </option>
              {#each agent.capabilities.models as m}
                <option value={m} class="bg-slate-800 text-white">{m}</option>
              {/each}
            </select>
          {:else}
            <input
              id="model"
              type="text"
              bind:value={modelName}
              placeholder="e.g. llama3.1:8b"
              class="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white placeholder:text-slate-500 focus:outline-none focus:border-blue-500 font-mono"
            />
          {/if}
          <p class="text-xs mt-1 text-slate-500">
            Leave as “Agent default” unless you want this one task to use a different installed model.
          </p>
        </div>

        <div class="grid grid-cols-2 gap-3">
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
              <input
                id={param.id}
                type="range"
                min={param.min}
                max={param.max}
                step={param.step}
                bind:value={param.bind}
                class="w-full accent-blue-500"
              />
            </div>
          {/each}

          <div>
            <label class="block text-xs text-slate-400 mb-1" for="max-tok">
              Max Tokens <span class="text-blue-400">{maxTokens}</span>
            </label>
            <input id="max-tok" type="range" min={128} max={8192} step={128}
              bind:value={maxTokens} class="w-full accent-blue-500" />
          </div>
          <div>
            <label class="block text-xs text-slate-400 mb-1" for="ctx-len">
              Context Length <span class="text-blue-400">{contextLength}</span>
            </label>
            <input id="ctx-len" type="range" min={512} max={16384} step={512}
              bind:value={contextLength} class="w-full accent-blue-500" />
          </div>
          <div>
            <label class="block text-xs text-slate-400 mb-1" for="priority">
              Priority <span class="text-blue-400">{priority}</span>
            </label>
            <input id="priority" type="range" min={1} max={100} step={1}
              bind:value={priority} class="w-full accent-blue-500" />
          </div>
          <div>
            <label class="block text-xs text-slate-400 mb-1" for="timeout">
              Timeout (s) <span class="text-blue-400">{timeoutS}</span>
            </label>
            <input id="timeout" type="range" min={60} max={86400} step={60}
              bind:value={timeoutS} class="w-full accent-blue-500" />
          </div>
        </div>
      </div>
    {/if}

    {#if error}
      <div class="bg-red-500/10 border border-red-500/30 text-red-400 text-sm rounded-lg p-2">
        {error}
      </div>
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
