<!--
  Gruper Console — main page
  Three-pane layout: fleet sidebar | task area | analytics
  Orchestrates the ConsoleWS connection and bridges stores to components.
-->
<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { authStore } from '$lib/stores/auth.js';
  import { fleetStore } from '$lib/stores/fleet.js';
  import { tasksStore } from '$lib/stores/tasks.js';
  import { OrchestratorClient } from '$lib/api/client.js';
  import { ConsoleWS } from '$lib/ws/console_ws.js';
  import ConnectDialog from '$lib/components/ConnectDialog.svelte';
  import AddAgentDialog from '$lib/components/AddAgentDialog.svelte';
  import AgentCard from '$lib/components/AgentCard.svelte';
  import TaskComposer from '$lib/components/TaskComposer.svelte';
  import ResultView from '$lib/components/ResultView.svelte';
  import AgentAnalytics from '$lib/components/AgentAnalytics.svelte';

  let ws: ConsoleWS | null = null;
  let activeAgentId = $state<string | null>(null);
  let activeTaskId = $state<string | null>(null);
  let rightTab = $state<'compose' | 'analytics'>('compose');
  let loadingData = $state(false);
  let showAddAgent = $state(false);

  const auth = $derived($authStore);
  const agents = $derived($fleetStore);
  const tasks = $derived($tasksStore.tasks);
  const activeAgent = $derived(agents.find((a) => a.id === activeAgentId) ?? null);

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

    // REST initial load: fetch agents and tasks (WS snapshot supplements this).
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

  function selectAgent(id: string) {
    activeAgentId = id;
    // Default to the compose tab when switching agents.
    rightTab = 'compose';
  }

  function onTaskSubmitted(taskId: string) {
    activeTaskId = taskId;
  }
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
        <span class="text-xs text-slate-500">
          {agents.filter((a) => a.status !== 'offline').length}/{agents.length} agents online
        </span>
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
              class="text-xs text-blue-400 hover:text-blue-300 transition-colors"
              title="Add Local Agent"
            >
              + Add
            </button>
          </div>
        </div>

        <div class="flex-1 overflow-y-auto px-2 pb-2 space-y-1">
          {#each agents as agent (agent.id)}
            <AgentCard
              {agent}
              selected={agent.id === activeAgentId}
              onclick={() => selectAgent(agent.id)}
            />
          {/each}
          {#if agents.length === 0 && !loadingData}
            <p class="text-xs text-slate-600 text-center py-4">
              No agents registered.<br />Click "+ Add" above to start one.
            </p>
          {/if}
        </div>
      </aside>

      <!-- Center: Task queue -->
      <div class="flex-1 flex flex-col min-w-0 border-r border-white/5 overflow-hidden">
        <div class="px-3 py-2 border-b border-white/5">
          <span class="text-xs font-medium text-slate-400 uppercase tracking-wider">Tasks</span>
        </div>
        <div class="flex-1 overflow-y-auto p-2 space-y-1">
          {#each tasks as task (task.id)}
            <button
              onclick={() => { activeTaskId = task.id; }}
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
              <p class="text-xs text-slate-600 mt-0.5 font-mono">{task.id.slice(0, 8)}…</p>
            </button>
          {:else}
            <p class="text-xs text-slate-600 text-center py-4">
              No tasks submitted yet.
            </p>
          {/each}
        </div>
      </div>

      <!-- Right: Compose / Result / Analytics -->
      <div class="w-[28rem] flex-shrink-0 flex flex-col overflow-hidden">
        <!-- Tab bar -->
        <div class="flex border-b border-white/5">
          {#each [
            { key: 'compose' as const, label: 'Compose' },
            { key: 'analytics' as const, label: 'Analytics' },
          ] as tab}
            <button
              onclick={() => { rightTab = tab.key; }}
              class="flex-1 text-xs py-2 transition-colors {rightTab === tab.key
                ? 'text-white border-b border-blue-500'
                : 'text-slate-500 hover:text-slate-300'}"
            >
              {tab.label}
            </button>
          {/each}
        </div>

        <div class="flex-1 overflow-y-auto p-3 space-y-3">
          {#if rightTab === 'compose'}
            <TaskComposer agent={activeAgent} onTaskSubmitted={onTaskSubmitted} />
            {#if activeTaskId}
              <ResultView taskId={activeTaskId} />
            {/if}
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
{/if}
