<!--
  Gruper Console — main page.
  Master/detail layout: Fleet sidebar | Tasks list | wide detail pane (result /
  analytics). The wide pane is where results are READ; task composition is a
  modal ("+ New task"); a slide-over Debug panel exposes the unified log.
-->
<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { authStore } from '$lib/stores/auth.js';
  import { fleetStore } from '$lib/stores/fleet.js';
  import { tasksStore } from '$lib/stores/tasks.js';
  import { orchestratorStore } from '$lib/stores/orchestrator.js';
  import { wsStatus } from '$lib/stores/wsStatus.js';
  import { logStore } from '$lib/stores/logs.js';
  import { OrchestratorClient } from '$lib/api/client.js';
  import { ConsoleWS } from '$lib/ws/console_ws.js';
  import ConnectDialog from '$lib/components/ConnectDialog.svelte';
  import AddAgentDialog from '$lib/components/AddAgentDialog.svelte';
  import AgentCard from '$lib/components/AgentCard.svelte';
  import TaskComposer from '$lib/components/TaskComposer.svelte';
  import ResultView from '$lib/components/ResultView.svelte';
  import AgentAnalytics from '$lib/components/AgentAnalytics.svelte';
  import RoundTable from '$lib/components/RoundTable.svelte';
  import DebugPanel from '$lib/components/DebugPanel.svelte';

  let ws: ConsoleWS | null = null;
  let activeAgentId = $state<string | null>(null);
  let activeTaskId = $state<string | null>(null);
  let detailTab = $state<'result' | 'analytics' | 'roundtable'>('result');
  let loadingData = $state(false);
  let showAddAgent = $state(false);
  let showComposer = $state(false);
  let showDebug = $state(false);
  let agentActionError = $state<string | null>(null);

  const hasTauri = typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;

  const auth = $derived($authStore);
  const agents = $derived($fleetStore);
  const tasks = $derived($tasksStore.tasks);
  const activeAgent = $derived(agents.find((a) => a.id === activeAgentId) ?? null);
  const orch = $derived($orchestratorStore);
  const wsState = $derived($wsStatus);

  const onlineCount = $derived(agents.filter((a) => a.status !== 'offline').length);

  // Name of the agent a task/row was sent to, for clearer Fleet↔Tasks linkage.
  function agentNameFor(agentId: string | undefined): string | null {
    if (!agentId) return null;
    return agents.find((a) => a.id === agentId)?.name ?? null;
  }
  const activeTask = $derived(tasks.find((t) => t.id === activeTaskId) ?? null);
  const activeTaskAgentName = $derived(agentNameFor(activeTask?.assigned_agent_id));

  // Connect WS and load initial data whenever token becomes available.
  $effect(() => {
    const token = auth.token;
    if (!token) {
      ws?.disconnect();
      ws = null;
      fleetStore.reset();
      tasksStore.reset();
      return;
    }

    ws?.disconnect();
    ws = new ConsoleWS(auth.orchestratorUrl, token);
    ws.connect();

    loadingData = true;
    const client = new OrchestratorClient(auth.orchestratorUrl, token);
    Promise.all([client.listAgents(), client.listTasks()])
      .then(([agentList, taskList]) => {
        fleetStore.setSnapshot(agentList);
        tasksStore.setTasks(taskList);
        if (agentList.length > 0 && !activeAgentId) {
          activeAgentId = agentList[0].id;
        }
      })
      .catch((err: unknown) => console.warn('[Console] Initial data load failed:', err))
      .finally(() => { loadingData = false; });

    return () => ws?.disconnect();
  });

  onDestroy(() => ws?.disconnect());

  // Ctrl/Cmd + ` opens the debug panel (a subtle, always-available affordance
  // alongside the header bug icon).
  onMount(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === '`') {
        e.preventDefault();
        showDebug = !showDebug;
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  function selectAgent(id: string) {
    activeAgentId = id;
    detailTab = 'result';
  }

  function selectTask(id: string) {
    activeTaskId = id;
    detailTab = 'result';
  }

  function openComposer() {
    if (agents.length === 0) return;
    if (!activeAgentId) activeAgentId = agents[0].id;
    showComposer = true;
  }

  function onComposerSubmitted(taskId: string) {
    activeTaskId = taskId;
    detailTab = 'result';
    showComposer = false;
  }

  /**
   * Minimum-viable agent management (see ROADMAP.md WP-32.1): stops a locally-
   * spawned agent and marks it offline. There is no orchestrator DELETE
   * endpoint for agents, so this can't remove the row outright — the
   * orchestrator converges to "offline" once it notices the WebSocket drop.
   */
  async function removeAgent(id: string) {
    agentActionError = null;
    if (!hasTauri) {
      agentActionError = 'Stopping a local agent process requires the desktop app (Tauri).';
      return;
    }
    try {
      const { invoke } = await import('@tauri-apps/api/core');
      await invoke('stop_local_agent', { agentId: id });
      fleetStore.setOffline(id);
    } catch (err) {
      agentActionError = err instanceof Error ? err.message : String(err);
    }
  }

  async function renameAgent(id: string, name: string) {
    agentActionError = null;
    const token = authStore.getToken();
    if (!token) return;
    try {
      const client = new OrchestratorClient(authStore.getOrchestratorUrl(), token);
      await client.renameAgent(id, name);
      fleetStore.rename(id, name);
      logStore.frontend('info', 'ui', `renamed agent to "${name}"`, { agent_id: id });
    } catch (err) {
      agentActionError = err instanceof Error ? err.message : String(err);
    }
  }

  // Connection indicator colours.
  const orchDot = $derived(
    orch.status === 'ready' || orch.status === 'existing' ? 'bg-green-500'
    : orch.status === 'checking' ? 'bg-amber-400 animate-pulse'
    : orch.status === 'failed' ? 'bg-red-500'
    : 'bg-slate-600',
  );
  const orchLabel = $derived(
    orch.status === 'ready' ? 'local' : orch.status === 'existing' ? 'connected' : orch.status,
  );
  const wsDot = $derived(
    wsState === 'live' ? 'bg-green-500'
    : wsState === 'connecting' || wsState === 'reconnecting' ? 'bg-amber-400 animate-pulse'
    : 'bg-slate-600',
  );
</script>

{#if !auth.token}
  <ConnectDialog />
{:else}
  <div class="h-screen flex flex-col bg-slate-900 text-slate-100 overflow-hidden">

    <!-- Top bar -->
    <header class="flex-shrink-0 px-4 py-2 border-b border-white/5 flex items-center justify-between">
      <div class="flex items-center gap-3">
        <span class="text-sm font-semibold text-white">Gruper Console</span>
        <span class="text-xs text-slate-500">gd-0.2</span>
      </div>
      <div class="flex items-center gap-4">
        <div class="flex items-center gap-1.5" title="Local orchestrator: {orch.status}{orch.error ? ` — ${orch.error}` : ''}">
          <span class="w-2 h-2 rounded-full {orchDot}"></span>
          <span class="text-xs text-slate-500">orchestrator {orchLabel}</span>
        </div>
        <div class="flex items-center gap-1.5" title="Console WebSocket: {wsState}">
          <span class="w-2 h-2 rounded-full {wsDot}"></span>
          <span class="text-xs text-slate-500">live {onlineCount}/{agents.length}</span>
        </div>
        <button
          onclick={() => { showDebug = true; }}
          class="text-xs text-slate-400 hover:text-blue-400 transition-colors"
          title="Open the debug log (Ctrl/Cmd + `)"
        >
          🐞 Debug
        </button>
        <button
          onclick={() => authStore.logout()}
          class="text-xs text-slate-400 hover:text-red-400 transition-colors"
        >
          Disconnect
        </button>
      </div>
    </header>

    <!-- Three-pane content -->
    <div class="flex-1 flex min-h-0">

      <!-- Left: Fleet sidebar -->
      <aside class="w-56 flex-shrink-0 border-r border-white/5 flex flex-col overflow-hidden">
        <div class="px-3 py-2 flex items-center justify-between">
          <span class="text-xs font-medium text-slate-400 uppercase tracking-wider">Fleet</span>
          <div class="flex items-center gap-2">
            {#if loadingData}
              <span class="text-xs text-blue-400 progress-pulse">loading…</span>
            {/if}
            <button
              onclick={() => { showAddAgent = true; }}
              class="text-xs text-blue-400 hover:text-blue-300 transition-colors {agents.length === 0 && !loadingData ? 'animate-pulse font-semibold' : ''}"
              title="Add Local Agent"
            >
              + Add
            </button>
          </div>
        </div>

        {#if agentActionError}
          <div class="mx-2 mb-1 bg-red-500/10 border border-red-500/30 text-red-400 text-xs rounded-lg p-2">
            {agentActionError}
          </div>
        {/if}

        <div class="flex-1 overflow-y-auto px-2 pb-2 space-y-1">
          {#each agents as agent (agent.id)}
            <AgentCard
              {agent}
              selected={agent.id === activeAgentId}
              onclick={() => selectAgent(agent.id)}
              onRemove={() => removeAgent(agent.id)}
              onRename={(name) => renameAgent(agent.id, name)}
            />
          {/each}
          {#if agents.length === 0 && !loadingData}
            <div class="text-center py-6 px-2 space-y-2">
              <p class="text-xs text-slate-400">
                No agents registered yet.
              </p>
              <p class="text-xs text-slate-600">
                Click <span class="text-blue-400 font-medium">"+ Add"</span> above to register and
                start your first agent. You'll need
                <a
                  href="https://ollama.ai"
                  target="_blank"
                  rel="noreferrer"
                  class="text-blue-400 hover:text-blue-300 underline"
                >Ollama</a>
                installed and running locally with at least one model pulled
                (e.g. <code class="text-slate-500">ollama pull llama3.1</code>).
              </p>
            </div>
          {/if}
        </div>
      </aside>

      <!-- Middle: Tasks master list -->
      <div class="w-72 flex-shrink-0 flex flex-col border-r border-white/5 overflow-hidden">
        <div class="px-3 py-2 border-b border-white/5 flex items-center justify-between gap-2">
          <span class="text-xs font-medium text-slate-400 uppercase tracking-wider">Tasks</span>
          <button
            onclick={openComposer}
            disabled={agents.length === 0}
            title={agents.length > 0 ? 'Compose a new task' : 'Add an agent first'}
            class="text-xs text-blue-400 hover:text-blue-300 disabled:text-slate-600 disabled:cursor-not-allowed transition-colors"
          >
            + New task
          </button>
        </div>
        {#if tasks.length > 0}
          <div class="px-3 py-1 flex items-center gap-3 border-b border-white/5">
            {#if tasks.some((t) => t.status === 'failed' || t.status === 'timed_out' || t.status === 'dead_letter')}
              <button
                onclick={() => tasksStore.clearFailed()}
                class="text-xs text-slate-500 hover:text-amber-400 transition-colors"
                title="Remove failed/timed-out tasks from this list (session-only)"
              >
                Clear failed
              </button>
            {/if}
            <button
              onclick={() => { activeTaskId = null; tasksStore.clearAll(); }}
              class="text-xs text-slate-500 hover:text-red-400 transition-colors"
              title="Clear this list (session-only — does not delete tasks on the orchestrator)"
            >
              Clear all
            </button>
          </div>
        {/if}
        <div class="flex-1 overflow-y-auto p-2 space-y-1">
          {#each tasks as task (task.id)}
            <button
              onclick={() => selectTask(task.id)}
              class="w-full text-left glass-card px-3 py-2 transition-all {activeTaskId === task.id ? 'border-blue-500/60' : ''}"
            >
              <div class="flex items-center justify-between gap-2">
                <span class="text-xs text-white truncate flex-1">
                  {task.input?.prompt?.slice(0, 60) ?? '—'}
                </span>
                <span class="text-xs flex-shrink-0 {
                  task.status === 'complete' ? 'text-green-400' :
                  task.status === 'running'  ? 'text-amber-400' :
                  task.status === 'failed'   ? 'text-red-400'   :
                  'text-slate-500'
                }">{task.status}</span>
              </div>
              <p class="text-xs text-slate-600 mt-0.5 truncate">
                {#if agentNameFor(task.assigned_agent_id)}→ {agentNameFor(task.assigned_agent_id)}{:else}<span class="font-mono">{task.id.slice(0, 8)}…</span>{/if}
              </p>
            </button>
          {:else}
            <div class="text-center py-6 px-2 space-y-2">
              <p class="text-xs text-slate-600">No tasks yet.</p>
              {#if agents.length > 0}
                <button onclick={openComposer} class="text-xs text-blue-400 hover:text-blue-300">
                  + New task
                </button>
              {/if}
            </div>
          {/each}
        </div>
      </div>

      <!-- Right: wide detail pane (result / analytics) -->
      <div class="flex-1 flex flex-col min-w-0 overflow-hidden">
        <div class="flex border-b border-white/5">
          {#each [
            { key: 'result' as const, label: 'Result' },
            { key: 'roundtable' as const, label: 'Round Table' },
            { key: 'analytics' as const, label: 'Analytics' },
          ] as tab}
            <button
              onclick={() => { detailTab = tab.key; }}
              class="px-6 text-xs py-2 transition-colors {detailTab === tab.key
                ? 'text-white border-b border-blue-500'
                : 'text-slate-500 hover:text-slate-300'}"
            >
              {tab.label}
            </button>
          {/each}
        </div>

        <div class="flex-1 overflow-y-auto p-4">
          {#if detailTab === 'result'}
            {#if agents.length === 0}
              <div class="glass-card p-8 text-center space-y-3 max-w-md mx-auto mt-8">
                <p class="text-white text-sm font-medium">Welcome to Gruper</p>
                <p class="text-xs text-slate-400">
                  Add your first local agent to get started. You'll need
                  <a href="https://ollama.ai" target="_blank" rel="noreferrer" class="text-blue-400 hover:text-blue-300 underline">Ollama</a>
                  running with at least one model pulled.
                </p>
                <button
                  onclick={() => { showAddAgent = true; }}
                  class="bg-blue-600 hover:bg-blue-500 text-white rounded-lg px-4 py-2 text-sm font-medium transition-colors"
                >
                  + Add your first agent
                </button>
              </div>
            {:else if !activeTaskId}
              <div class="glass-card p-8 text-center space-y-3 max-w-md mx-auto mt-8">
                <p class="text-white text-sm font-medium">No task selected</p>
                <p class="text-xs text-slate-400">Pick a task from the list, or start a new one — pick which agent to send it to, type a prompt, and submit.</p>
                <button
                  onclick={openComposer}
                  class="bg-blue-600 hover:bg-blue-500 text-white rounded-lg px-4 py-2 text-sm font-medium transition-colors"
                >
                  + New task
                </button>
              </div>
            {:else}
              <ResultView taskId={activeTaskId} agentName={activeTaskAgentName} />
            {/if}
          {:else if detailTab === 'roundtable'}
            <RoundTable {agents} />
          {:else}
            <AgentAnalytics agent={activeAgent} />
          {/if}
        </div>
      </div>

    </div>
  </div>

  {#if showAddAgent}
    <AddAgentDialog onclose={() => { showAddAgent = false; }} />
  {/if}

  {#if showComposer && agents.length > 0}
    <!-- Composer modal — task creation is a transient action, not a permanent
         pane. Also the future home of the WP-10 sharing UI. -->
    <div
      class="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-40 p-4"
      onclick={(e) => { if (e.target === e.currentTarget) showComposer = false; }}
      onkeydown={(e) => { if (e.key === 'Escape') showComposer = false; }}
      role="presentation"
    >
      <div class="w-full max-w-lg max-h-[88vh] overflow-y-auto">
        <TaskComposer {agents} bind:selectedAgentId={activeAgentId} onTaskSubmitted={onComposerSubmitted} />
        <button
          onclick={() => (showComposer = false)}
          class="mt-2 w-full text-xs text-slate-400 hover:text-slate-200 transition-colors"
        >
          Cancel
        </button>
      </div>
    </div>
  {/if}

  {#if showDebug}
    <DebugPanel onclose={() => { showDebug = false; }} />
  {/if}
{/if}
