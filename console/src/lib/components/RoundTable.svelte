<!--
  Round Table — a multi-agent conversation (like the original gruper.html). Pick
  a topic and which agents take part; each answers in turn, seeing the discussion
  so far, so later agents build on earlier ones. Each turn's reply STREAMS in
  live (via the task's progress events already flowing into tasksStore), so it
  reads like a real conversation rather than a batch of tasks. "Another round"
  continues the same transcript.
-->
<script lang="ts">
  import { get } from 'svelte/store';
  import { authStore } from '$lib/stores/auth.js';
  import { tasksStore } from '$lib/stores/tasks.js';
  import { logStore } from '$lib/stores/logs.js';
  import { OrchestratorClient } from '$lib/api/client.js';
  import { agentModel, agentRole } from '$lib/agentDisplay.js';
  import AgentAvatar from '$lib/components/AgentAvatar.svelte';
  import type { Agent } from '$lib/types.js';

  let { agents = [] }: { agents?: Agent[] } = $props();

  let topic = $state('');
  let selected = $state<Set<string>>(new Set());
  let running = $state(false);
  let error = $state<string | null>(null);
  let round = $state(0);

  interface Turn {
    agentId: string;
    agentName: string;
    role: string;
    model: string;
    round: number;
    text: string;
    status: 'thinking' | 'streaming' | 'done' | 'failed';
  }
  let transcript = $state<Turn[]>([]);

  const TERMINAL = ['complete', 'failed', 'timed_out', 'dead_letter'];
  const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

  // Default: select all online agents once the fleet is known.
  let seeded = false;
  $effect(() => {
    if (!seeded && agents.length > 0) {
      seeded = true;
      selected = new Set(agents.filter((a) => a.status !== 'offline').map((a) => a.id));
    }
  });

  const participants = $derived(agents.filter((a) => selected.has(a.id)));

  function toggle(id: string) {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    selected = next;
  }

  function buildPrompt(a: Agent): string {
    const prior = transcript.filter((t) => t.status === 'done');
    const lines = [`Topic: ${topic.trim()}`, ''];
    if (prior.length > 0) {
      lines.push('Discussion so far:');
      for (const t of prior) lines.push(`${t.agentName} (${t.role}): ${t.text}`);
      lines.push('');
    }
    lines.push(
      `You are the ${agentRole(a) ?? 'analyst'}. ${prior.length ? 'Add your perspective to the discussion' : 'Open the discussion'}. Be concise (a few sentences), and don't repeat what others already said.`,
    );
    return lines.join('\n');
  }

  // Auto-scroll the transcript as it grows / streams.
  let scroller = $state<HTMLDivElement | null>(null);
  $effect(() => {
    void transcript;
    if (scroller) scroller.scrollTop = scroller.scrollHeight;
  });

  async function runTurn(client: OrchestratorClient, a: Agent, idx: number): Promise<void> {
    try {
      const task = await client.submitTask({
        assigned_agent_id: a.id,
        data_class: 'internal',
        input: { prompt: buildPrompt(a), role_template: agentRole(a) ?? 'analyst' },
        timeout_s: 300,
      });
      const taskId = task.id;
      const deadline = Date.now() + 180_000;
      while (Date.now() < deadline) {
        // Live streaming: the console WS routes this task's progress into
        // tasksStore.progress (keyed by task id), so concatenate it as it grows.
        const prog = get(tasksStore).progress[taskId];
        if (prog?.length) {
          transcript[idx] = { ...transcript[idx], text: prog.map((l) => l.text).join(''), status: 'streaming' };
          transcript = [...transcript];
        }
        // Authoritative terminal check + full result.
        const t = await client.getTask(taskId);
        if (TERMINAL.includes(t.status)) {
          if (t.status === 'complete') {
            const out = (t.result?.output as string) ?? transcript[idx].text ?? '';
            transcript[idx] = {
              ...transcript[idx],
              text: out || '(no output)',
              model: (t.result?.model_used as string) ?? transcript[idx].model,
              status: 'done',
            };
          } else {
            transcript[idx] = { ...transcript[idx], text: t.error?.message ?? `task ${t.status}`, status: 'failed' };
          }
          transcript = [...transcript];
          return;
        }
        await sleep(800);
      }
      transcript[idx] = { ...transcript[idx], text: transcript[idx].text || 'timed out waiting for a response', status: 'failed' };
      transcript = [...transcript];
    } catch (err) {
      transcript[idx] = { ...transcript[idx], text: err instanceof Error ? err.message : String(err), status: 'failed' };
      transcript = [...transcript];
    }
  }

  async function runRound() {
    if (running || !topic.trim() || participants.length === 0) return;
    const auth = $authStore;
    if (!auth.token) {
      error = 'Not connected to an orchestrator.';
      return;
    }
    error = null;
    running = true;
    round += 1;
    const thisRound = round;
    const client = new OrchestratorClient(auth.orchestratorUrl, auth.token);
    logStore.frontend('info', 'ui', `round table: round ${thisRound} with ${participants.length} agent(s)`);

    try {
      for (const a of participants) {
        transcript = [
          ...transcript,
          { agentId: a.id, agentName: a.name, role: agentRole(a) ?? 'analyst', model: agentModel(a), round: thisRound, text: '', status: 'thinking' },
        ];
        await runTurn(client, a, transcript.length - 1);
      }
    } finally {
      running = false;
    }
  }

  function reset() {
    transcript = [];
    round = 0;
    error = null;
  }
</script>

<div class="space-y-4 max-w-3xl">
  <div class="glass-card p-4 space-y-3">
    <div class="flex items-center justify-between">
      <h2 class="text-sm font-semibold text-white">Round Table</h2>
      {#if transcript.length > 0}
        <button onclick={reset} disabled={running} class="text-xs text-slate-500 hover:text-red-400 disabled:opacity-40 transition-colors">Clear</button>
      {/if}
    </div>
    <p class="text-xs text-slate-500">
      A shared conversation: each selected agent answers in turn, seeing what the others said first.
    </p>

    <div>
      <label class="block text-xs text-slate-400 mb-1" for="rt-topic">Topic / question</label>
      <textarea
        id="rt-topic"
        bind:value={topic}
        rows={3}
        placeholder="e.g. What are the biggest risks in shipping cross-network agent sharing?"
        class="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white placeholder:text-slate-500 focus:outline-none focus:border-blue-500 resize-none"
      ></textarea>
    </div>

    <div>
      <p class="text-xs text-slate-400 mb-1.5">Participants ({participants.length})</p>
      {#if agents.length === 0}
        <p class="text-xs text-slate-500">No agents yet — add one from the Fleet sidebar first.</p>
      {:else}
        <div class="flex flex-wrap gap-1.5">
          {#each agents as a (a.id)}
            <button
              type="button"
              onclick={() => toggle(a.id)}
              disabled={running}
              class="flex items-center gap-1.5 text-xs pl-1 pr-2 py-1 rounded-lg border transition-colors disabled:opacity-50 {selected.has(a.id)
                ? 'border-blue-500/50 bg-blue-500/10 text-blue-100'
                : 'border-white/10 text-slate-400 hover:bg-white/5'}"
              title={`${agentModel(a)} · ${agentRole(a) ?? 'analyst'}${a.status === 'offline' ? ' · offline' : ''}`}
            >
              <AgentAvatar id={a.id} name={a.name} size={18} />
              {a.name}
              {#if a.status === 'offline'}<span class="text-slate-600">(offline)</span>{/if}
            </button>
          {/each}
        </div>
      {/if}
    </div>

    {#if error}
      <div class="bg-red-500/10 border border-red-500/30 text-red-400 text-xs rounded-lg p-2">{error}</div>
    {/if}

    <div class="flex items-center gap-2">
      <button
        onclick={runRound}
        disabled={running || !topic.trim() || participants.length === 0}
        class="bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed text-white rounded-lg px-4 py-2 text-sm font-medium transition-colors"
      >
        {#if running}Running round {round}…{:else if round === 0}Start round{:else}Another round{/if}
      </button>
      {#if round > 0 && !running}
        <span class="text-xs text-slate-500">{round} round{round === 1 ? '' : 's'} so far</span>
      {/if}
    </div>
  </div>

  <!-- Transcript -->
  {#if transcript.length > 0}
    <div bind:this={scroller} class="space-y-2 max-h-[55vh] overflow-y-auto pr-1">
      {#each transcript as turn, i (i)}
        {#if i === 0 || transcript[i - 1].round !== turn.round}
          <div class="flex items-center gap-2 pt-1">
            <span class="text-xs text-slate-600">Round {turn.round}</span>
            <span class="flex-1 border-t border-white/5"></span>
          </div>
        {/if}
        <div class="glass-card p-3 transition-colors {turn.status === 'thinking' || turn.status === 'streaming' ? 'border-blue-500/40 bg-blue-500/5' : ''}">
          <div class="flex items-center gap-2 mb-1.5">
            <AgentAvatar id={turn.agentId} name={turn.agentName} size={22} />
            <span class="text-xs font-medium text-white">{turn.agentName}</span>
            <span class="text-xs text-blue-300">{turn.role}</span>
            {#if turn.status === 'thinking' || turn.status === 'streaming'}
              <span class="text-xs text-amber-400 progress-pulse">responding…</span>
            {/if}
            <span class="flex-1"></span>
            <span class="text-xs text-slate-600 font-mono">{turn.model}</span>
          </div>
          {#if turn.status === 'thinking'}
            <div class="flex items-center gap-2 text-sm text-amber-400 progress-pulse">
              <span class="w-2 h-2 rounded-full bg-amber-400 inline-block"></span>
              thinking…
            </div>
          {:else}
            <p class="text-sm {turn.status === 'failed' ? 'text-red-400' : 'text-slate-200'}" style="white-space: pre-wrap; word-break: break-word;">{turn.text}{#if turn.status === 'streaming'}<span class="text-amber-400 progress-pulse">▌</span>{/if}</p>
          {/if}
        </div>
      {/each}
    </div>
  {/if}
</div>
