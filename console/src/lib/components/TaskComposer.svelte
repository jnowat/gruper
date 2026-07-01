<!--
  Task composer — mirrors Gruper core's task-input UX conventions:
  - Prompt textarea at top
  - Per-agent inference parameters (temperature, top-p, etc.) match core's ranges
  - Data class and priority are new to Gruper Distributed
-->
<script lang="ts">
  import { authStore } from '$lib/stores/auth.js';
  import { tasksStore } from '$lib/stores/tasks.js';
  import { logStore } from '$lib/stores/logs.js';
  import { OrchestratorClient } from '$lib/api/client.js';
  import type { Agent, DataClass, TaskSubmitRequest } from '$lib/types.js';

  let {
    agent,
    onTaskSubmitted,
  }: {
    agent: Agent | null;
    onTaskSubmitted?: (taskId: string) => void;
  } = $props();

  // Inference controls — mirrors Gruper core parameter ranges exactly.
  let prompt = $state('');
  let modelName = $state('');
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
    "devil's-advocate", 'philosopher', 'economist', 'ethicist',
    'scientist', 'psychologist', 'engineer',
  ];

  // Reset the per-task model override when the selected agent changes, so a
  // model pinned for one agent doesn't silently carry over to another that may
  // not even have it installed. '' means "use the agent's default".
  $effect(() => {
    void agent?.id;
    modelName = '';
  });

  const agentDefaultModel = $derived(
    agent?.capabilities?.default_model ?? agent?.capabilities?.models?.[0] ?? '',
  );

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
      logStore.frontend('info', 'ui', `submitted task (model: ${modelName || 'agent default'})`, {
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
  <div class="flex items-center justify-between">
    <h2 class="text-sm font-semibold text-white">Submit Task</h2>
    {#if agent}
      <span class="text-xs text-blue-400">&rarr; {agent.name}</span>
    {:else}
      <span class="text-xs text-slate-500">select an agent</span>
    {/if}
  </div>

  <form class="space-y-3" onsubmit={(e) => { e.preventDefault(); handleSubmit(); }}>
    <!-- Prompt -->
    <div>
      <label class="block text-xs text-slate-400 mb-1" for="prompt">Prompt</label>
      <textarea
        id="prompt"
        bind:value={prompt}
        rows={5}
        placeholder="Describe the task for the agent…"
        class="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white placeholder:text-slate-500 focus:outline-none focus:border-blue-500 resize-none"
        required
      ></textarea>
    </div>

    <div class="grid grid-cols-2 gap-3">
      <!-- Role template -->
      <div>
        <label class="block text-xs text-slate-400 mb-1" for="role">Role Template</label>
        <select
          id="role"
          bind:value={roleTemplate}
          class="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500"
        >
          {#each ROLE_TEMPLATES as r}
            <option value={r} class="bg-slate-800 text-white">{r}</option>
          {/each}
        </select>
      </div>

      <!-- Data class -->
      <div>
        <label class="block text-xs text-slate-400 mb-1" for="data-class">Data Class</label>
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

    <!-- Model -->
    <div>
      <label class="block text-xs text-slate-400 mb-1" for="model">Model</label>
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
    </div>

    <!-- Advanced parameters toggle -->
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
    {/if}

    {#if error}
      <div class="bg-red-500/10 border border-red-500/30 text-red-400 text-sm rounded-lg p-2">
        {error}
      </div>
    {/if}

    <button
      type="submit"
      disabled={loading || !agent}
      class="w-full bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed text-white rounded-lg px-4 py-2 text-sm font-medium transition-colors"
    >
      {loading ? 'Submitting…' : 'Submit Task'}
    </button>
  </form>
</div>
