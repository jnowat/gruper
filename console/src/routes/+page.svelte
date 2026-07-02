<!--
  Gruper Console — main page.
  Master/detail layout: Agents sidebar | History list | wide detail pane
  (answer / round table / analytics). The wide pane is where answers are READ;
  asking is a modal ("+ Ask"); a slide-over Debug panel exposes the unified log.

  Language rule for this file: no internal nouns in anything user-visible.
  "Orchestrator", "fleet", "task", "dispatched", "dead_letter" and raw UUIDs
  stay in code and the Debug panel; the user sees agents, questions, answers,
  and plain status words (shared vocabulary in $lib/taskDisplay.ts).
-->
<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { get } from 'svelte/store';
  import { authStore } from '$lib/stores/auth.js';
  import { fleetStore } from '$lib/stores/fleet.js';
  import { tasksStore } from '$lib/stores/tasks.js';
  import { orchestratorStore } from '$lib/stores/orchestrator.js';
  import { wsStatus } from '$lib/stores/wsStatus.js';
  import { logStore } from '$lib/stores/logs.js';
  import { OrchestratorClient } from '$lib/api/client.js';
  import { ConsoleWS } from '$lib/ws/console_ws.js';
  import { taskStatusColour, taskStatusLabel } from '$lib/taskDisplay.js';
  import { agentRole } from '$lib/agentDisplay.js';
  import ConnectDialog from '$lib/components/ConnectDialog.svelte';
  import AddAgentDialog from '$lib/components/AddAgentDialog.svelte';
  import AgentCard from '$lib/components/AgentCard.svelte';
  import AgentAvatar from '$lib/components/AgentAvatar.svelte';
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

  // Round Table turns are machine-built tasks (tagged via input.context) — the
  // History list shows only questions the user actually asked. The transcript
  // itself lives in the Round Table tab.
  const visibleTasks = $derived(
    tasks.filter((t) => (t.input?.context as Record<string, unknown> | null)?.source !== 'round_table'),
  );

  // Name of the agent a task/row was sent to, for clearer Agents↔History linkage.
  function agentNameFor(agentId: string | undefined): string | null {
    if (!agentId) return null;
    return agents.find((a) => a.id === agentId)?.name ?? null;
  }
  const activeTask = $derived(tasks.find((t) => t.id === activeTaskId) ?? null);
  const activeTaskAgentName = $derived(agentNameFor(activeTask?.assigned_agent_id));
  const activeTaskAgent = $derived(
    agents.find((a) => a.id === activeTask?.assigned_agent_id) ?? null,
  );

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
        // Default-select from the VISIBLE fleet (the raw REST list still
        // contains locally-hidden agents).
        if (!activeAgentId) {
          activeAgentId = get(fleetStore)[0]?.id ?? null;
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
    // Selection feeds the Analytics tab and the composer default — it should
    // not yank the user away from whatever tab they're reading.
    activeAgentId = id;
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
   * "Remove" an agent (see ROADMAP.md WP-32.1): stop the locally-spawned
   * process if it's running, then hide the entry (persisted locally). There is
   * no orchestrator DELETE endpoint for agents, so the row survives server-side
   * — but it no longer clutters the sidebar, which is what the user meant by ✕.
   */
  async function removeAgent(id: string) {
    agentActionError = null;
    const agent = agents.find((a) => a.id === id);
    if (agent && agent.status !== 'offline') {
      if (!hasTauri) {
        agentActionError = 'Stopping a running agent requires the desktop app.';
        return;
      }
      try {
        const { invoke } = await import('@tauri-apps/api/core');
        await invoke('stop_local_agent', { agentId: id });
        fleetStore.setOffline(id);
      } catch (err) {
        // Most common cause: the agent wasn't started by this Console (manual
        // runtime, another machine), so this process can't stop it — and
        // hiding a still-running agent would be a lie (it would pop back on
        // its next heartbeat anyway). Say so plainly; raw detail goes to the
        // debug log.
        const raw = err instanceof Error ? err.message : String(err);
        logStore.frontend('warn', 'ui', `stop_local_agent failed: ${raw}`, { agent_id: id });
        agentActionError = `${agent.name} wasn't started by this app, so it can't be stopped from here. Stop it where it runs — it can be removed once it goes offline.`;
        return;
      }
    }
    fleetStore.hide(id);
    if (activeAgentId === id) activeAgentId = agents.find((a) => a.id !== id)?.id ?? null;
    logStore.frontend('info', 'ui', 'agent removed from sidebar (stopped + hidden locally)', { agent_id: id });
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

  async function changeAgentRole(id: string, role: string) {
    agentActionError = null;
    const token = authStore.getToken();
    if (!token) return;
    try {
      const client = new OrchestratorClient(authStore.getOrchestratorUrl(), token);
      await client.updateAgent(id, { role });
      fleetStore.setRole(id, role);
      logStore.frontend('info', 'ui', `changed agent specialty to "${role}"`, { agent_id: id });
    } catch (err) {
      agentActionError = err instanceof Error ? err.message : String(err);
    }
  }

  // One health indicator instead of two jargon dots ("orchestrator local",
  // "live 3/4"). The live WS is what actually matters once connected; the
  // technical detail lives in the tooltip and the Debug panel.
  const health = $derived.by(() => {
    if (wsState === 'live') {
      return {
        dot: 'bg-green-500',
        label:
          agents.length === 0
            ? 'connected'
            : `${onlineCount} of ${agents.length} agent${agents.length === 1 ? '' : 's'} online`,
      };
    }
    if (wsState === 'connecting' || wsState === 'reconnecting') {
      return { dot: 'bg-amber-400 animate-pulse', label: 'reconnecting…' };
    }
    return { dot: 'bg-slate-600', label: 'not connected' };
  });
  // Plain words in the tooltip too — the raw union values ("existing",
  // "closed") are internal state names, not writing.
  const WS_WORDS: Record<string, string> = {
    live: 'connected', connecting: 'connecting…', reconnecting: 'reconnecting…', closed: 'not connected',
  };
  const ENGINE_WORDS: Record<string, string> = {
    ready: 'running', existing: 'running', checking: 'starting…', failed: "couldn't start", unavailable: 'not managed by this app',
  };
  const healthTooltip = $derived(
    `Live updates: ${WS_WORDS[wsState] ?? wsState}\nEngine: ${ENGINE_WORDS[orch.status] ?? orch.status}${orch.error ? ` — ${orch.error}` : ''}`,
  );
</script>

{#if !auth.token}
  <ConnectDialog />
{:else}
  <div class="h-screen flex flex-col bg-slate-900 text-slate-100 overflow-hidden">

    <!-- Top bar -->
    <header class="flex-shrink-0 px-4 py-2 border-b border-white/5 flex items-center justify-between">
      <div class="flex items-center gap-3">
        <span class="text-sm font-semibold text-white" title="Gruper Console · gd-0.2 (pre-release)">Gruper Console</span>
      </div>
      <div class="flex items-center gap-4">
        <div class="flex items-center gap-1.5" title={healthTooltip}>
          <span class="w-2 h-2 rounded-full {health.dot}"></span>
          <span class="text-xs text-slate-500">{health.label}</span>
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

      <!-- Left: Agents sidebar -->
      <aside class="w-60 flex-shrink-0 border-r border-white/5 flex flex-col overflow-hidden">
        <div class="px-3 py-2 flex items-center justify-between">
          <span class="text-xs font-medium text-slate-400 uppercase tracking-wider">Agents</span>
          <div class="flex items-center gap-2">
            {#if loadingData}
              <span class="text-xs text-blue-400 progress-pulse">loading…</span>
            {/if}
            <button
              onclick={() => { showAddAgent = true; }}
              class="text-xs text-blue-400 hover:text-blue-300 transition-colors {agents.length === 0 && !loadingData ? 'animate-pulse font-semibold' : ''}"
              title="Add an agent"
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
              onChangeRole={(role) => changeAgentRole(agent.id, role)}
            />
          {/each}
          {#if agents.length === 0 && !loadingData}
            <div class="text-center py-6 px-2 space-y-2">
              <p class="text-xs text-slate-400">No agents yet.</p>
              <p class="text-xs text-slate-600">
                An agent is a private AI helper that runs on this computer.
                Click <span class="text-blue-400 font-medium">+ Add</span> to create your first one.
              </p>
            </div>
          {/if}
        </div>
      </aside>

      <!-- Middle: History master list -->
      <div class="w-72 flex-shrink-0 flex flex-col border-r border-white/5 overflow-hidden">
        <div class="px-3 py-2 border-b border-white/5 flex items-center justify-between gap-2">
          <span class="text-xs font-medium text-slate-400 uppercase tracking-wider">History</span>
          <button
            onclick={openComposer}
            disabled={agents.length === 0}
            title={agents.length > 0 ? 'Ask a question' : 'Add an agent first'}
            class="text-xs text-blue-400 hover:text-blue-300 disabled:text-slate-600 disabled:cursor-not-allowed transition-colors"
          >
            + Ask
          </button>
        </div>
        {#if visibleTasks.length > 0}
          <div class="px-3 py-1 flex items-center gap-3 border-b border-white/5">
            {#if visibleTasks.some((t) => t.status === 'failed' || t.status === 'timed_out' || t.status === 'dead_letter')}
              <button
                onclick={() => tasksStore.clearFailed()}
                class="text-xs text-slate-500 hover:text-amber-400 transition-colors"
                title="Remove failed questions from this list"
              >
                Clear failed
              </button>
            {/if}
            <button
              onclick={() => { activeTaskId = null; tasksStore.clearAll(); }}
              class="text-xs text-slate-500 hover:text-red-400 transition-colors"
              title="Empty this list. Answers stay saved and come back the next time you open the app."
            >
              Clear all
            </button>
          </div>
        {/if}
        <div class="flex-1 overflow-y-auto p-2 space-y-1">
          {#each visibleTasks as task (task.id)}
            <button
              onclick={() => selectTask(task.id)}
              class="w-full text-left glass-card px-3 py-2 transition-all {activeTaskId === task.id ? 'border-blue-500/60' : ''}"
            >
              <div class="flex items-center justify-between gap-2">
                <span class="text-xs text-white truncate flex-1">
                  {task.input?.prompt?.slice(0, 60) ?? '—'}
                </span>
                <span class="text-xs flex-shrink-0 {taskStatusColour(task.status)}">{taskStatusLabel(task.status)}</span>
              </div>
              <p class="text-xs text-slate-600 mt-0.5 truncate flex items-center gap-1">
                {#if task.assigned_agent_id && agentNameFor(task.assigned_agent_id)}
                  <AgentAvatar id={task.assigned_agent_id} name={agentNameFor(task.assigned_agent_id) ?? ''} size={12} />
                  {agentNameFor(task.assigned_agent_id)}
                {:else}
                  <span class="text-slate-700">an agent that's been removed</span>
                {/if}
              </p>
            </button>
          {:else}
            <div class="text-center py-6 px-2 space-y-2">
              <p class="text-xs text-slate-600">Nothing asked yet.</p>
              {#if agents.length > 0}
                <button onclick={openComposer} class="text-xs text-blue-400 hover:text-blue-300">
                  + Ask a question
                </button>
              {/if}
            </div>
          {/each}
        </div>
      </div>

      <!-- Right: wide detail pane (answer / round table / analytics) -->
      <div class="flex-1 flex flex-col min-w-0 overflow-hidden">
        <div class="flex border-b border-white/5">
          {#each [
            { key: 'result' as const, label: 'Answer' },
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
            {#if !activeTaskId && (agents.length === 0 || visibleTasks.length === 0)}
              <!-- First-run checklist: three steps that check themselves off. -->
              <div class="glass-card p-8 space-y-5 max-w-md mx-auto mt-8">
                <p class="text-white text-sm font-medium text-center">Welcome to Gruper</p>
                <ol class="space-y-4">
                  <li class="flex items-start gap-3">
                    <span class="flex-shrink-0 w-5 h-5 rounded-full flex items-center justify-center text-xs {agents.length > 0 ? 'bg-emerald-500/20 text-emerald-400' : 'bg-blue-500/20 text-blue-300'}">
                      {agents.length > 0 ? '✓' : '1'}
                    </span>
                    <div class="min-w-0">
                      <p class="text-sm {agents.length > 0 ? 'text-slate-500 line-through' : 'text-slate-200'}">Add an agent</p>
                      {#if agents.length === 0}
                        <p class="text-xs text-slate-500 mt-0.5">A private AI helper that runs on this computer.</p>
                        <button
                          onclick={() => { showAddAgent = true; }}
                          class="mt-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg px-3 py-1.5 text-xs font-medium transition-colors"
                        >
                          + Add your first agent
                        </button>
                      {/if}
                    </div>
                  </li>
                  <li class="flex items-start gap-3">
                    <span class="flex-shrink-0 w-5 h-5 rounded-full flex items-center justify-center text-xs {agents.length > 0 ? 'bg-blue-500/20 text-blue-300' : 'bg-white/5 text-slate-600'}">2</span>
                    <div class="min-w-0">
                      <p class="text-sm {agents.length > 0 ? 'text-slate-200' : 'text-slate-600'}">Ask it a question</p>
                      {#if agents.length > 0}
                        <p class="text-xs text-slate-500 mt-0.5">The answer streams in right here.</p>
                        <button
                          onclick={openComposer}
                          class="mt-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg px-3 py-1.5 text-xs font-medium transition-colors"
                        >
                          Ask a question
                        </button>
                      {/if}
                    </div>
                  </li>
                  <li class="flex items-start gap-3">
                    <span class="flex-shrink-0 w-5 h-5 rounded-full flex items-center justify-center text-xs bg-white/5 text-slate-600">3</span>
                    <div class="min-w-0">
                      <p class="text-sm text-slate-600">Get a second opinion</p>
                      <p class="text-xs text-slate-600 mt-0.5">
                        Add more agents with different specialties, then let them discuss in the
                        <button class="text-blue-400 hover:text-blue-300" onclick={() => { detailTab = 'roundtable'; }}>Round Table</button> tab.
                      </p>
                    </div>
                  </li>
                </ol>
              </div>
            {:else if !activeTaskId}
              <div class="glass-card p-8 text-center space-y-3 max-w-md mx-auto mt-8">
                <p class="text-white text-sm font-medium">No question selected</p>
                <p class="text-xs text-slate-400">Pick one from History, or ask something new.</p>
                <button
                  onclick={openComposer}
                  class="bg-blue-600 hover:bg-blue-500 text-white rounded-lg px-4 py-2 text-sm font-medium transition-colors"
                >
                  Ask a question
                </button>
              </div>
            {:else}
              <ResultView
                taskId={activeTaskId}
                agentId={activeTask?.assigned_agent_id ?? null}
                agentName={activeTaskAgentName}
                agentRoleId={activeTaskAgent ? agentRole(activeTaskAgent) : null}
                onResubmitted={(id) => { activeTaskId = id; }}
              />
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
    <!-- Asking is a transient action, not a permanent pane. Closing the modal
         (even by a stray backdrop click) is safe: the draft survives in the
         composer's module state and is restored on reopen. -->
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
          Close
        </button>
      </div>
    </div>
  {/if}

  {#if showDebug}
    <DebugPanel onclose={() => { showDebug = false; }} />
  {/if}
{/if}
