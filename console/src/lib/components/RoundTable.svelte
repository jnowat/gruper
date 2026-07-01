<!--
  Round Table — a simple multi-agent conversation (like the original
  gruper.html). Pick a topic and which agents take part; each selected agent
  responds in turn, seeing the discussion so far, so later agents build on
  earlier ones. Sequential and single-round per click; "Another round" continues
  the same transcript. Each turn is a normal task dispatched to that agent.
-->
<script lang="ts">
  import { authStore } from '$lib/stores/auth.js';
  import { logStore } from '$lib/stores/logs.js';
  import { OrchestratorClient } from '$lib/api/client.js';
  import type { Agent, Task } from '$lib/types.js';

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
    status: 'thinking' | 'done' | 'failed';
  }
  let transcript = $state<Turn[]>([]);

  const TERMINAL = ['complete', 'failed', 'timed_out', 'dead_letter'];

  // Default: select all online agents the first time the fleet is known.
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

  function roleOf(a: Agent): string {
    return a.capabilities?.roles?.[0] ?? 'analyst';
  }
  function modelOf(a: Agent): string {
    return a.capabilities?.default_model ?? a.capabilities?.models?.[0] ?? '';
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
      `You are the ${roleOf(a)}. ${prior.length ? 'Add your perspective to the discussion' : 'Open the discussion'}. Be concise (a few sentences), and don't repeat what others already said.`,
    );
    return lines.join('\n');
  }

  async function waitForResult(client: OrchestratorClient, id: string, timeoutMs = 120_000): Promise<Task> {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      const t = await client.getTask(id);
      if (TERMINAL.includes(t.status)) return t;
      await new Promise((r) => setTimeout(r, 1500));
    }
    throw new Error('timed out waiting for a response');
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
        const turn: Turn = {
          agentId: a.id,
          agentName: a.name,
          role: roleOf(a),
          model: modelOf(a),
          round: thisRound,
          text: '',
          status: 'thinking',
        };
        transcript = [...transcript, turn];
        const idx = transcript.length - 1;

        try {
          const task = await client.submitTask({
            assigned_agent_id: a.id,
            data_class: 'internal',
            input: { prompt: buildPrompt(a), role_template: roleOf(a) },
            timeout_s: 300,
          });
          const done = await waitForResult(client, task.id);
          if (done.status === 'complete') {
            const out = (done.result?.output as string) ?? '';
            transcript[idx] = { ...turn, text: out || '(no output)', status: 'done' };
          } else {
            transcript[idx] = {
              ...turn,
              text: done.error?.message ?? `task ${done.status}`,
              status: 'failed',
            };
          }
          transcript = [...transcript];
        } catch (err) {
          transcript[idx] = {
            ...turn,
            text: err instanceof Error ? err.message : String(err),
            status: 'failed',
          };
          transcript = [...transcript];
        }
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

  const ROLE_COLOUR: Record<string, string> = {
    thinking: 'text-amber-400',
    done: 'text-slate-200',
    failed: 'text-red-400',
  };
</script>

<div class="space-y-4 max-w-3xl">
  <div class="glass-card p-4 space-y-3">
    <div class="flex items-center justify-between">
      <h2 class="text-sm font-semibold text-white">Round Table</h2>
      {#if transcript.length > 0}
        <button onclick={reset} class="text-xs text-slate-500 hover:text-red-400 transition-colors">Clear</button>
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
      <p class="text-xs text-slate-400 mb-1">Participants ({participants.length})</p>
      {#if agents.length === 0}
        <p class="text-xs text-slate-500">No agents yet — add one from the Fleet sidebar first.</p>
      {:else}
        <div class="flex flex-wrap gap-1.5">
          {#each agents as a (a.id)}
            <button
              type="button"
              onclick={() => toggle(a.id)}
              disabled={running}
              class="text-xs px-2 py-1 rounded-lg border transition-colors disabled:opacity-50 {selected.has(a.id)
                ? 'border-blue-500/50 bg-blue-500/10 text-blue-200'
                : 'border-white/10 text-slate-400 hover:bg-white/5'}"
              title={`${modelOf(a)} · ${roleOf(a)}${a.status === 'offline' ? ' · offline' : ''}`}
            >
              {a.name}
              {#if a.status === 'offline'}<span class="text-slate-600"> (offline)</span>{/if}
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
        {#if running}
          Running round {round}…
        {:else if round === 0}
          Start round
        {:else}
          Another round
        {/if}
      </button>
      {#if round > 0 && !running}
        <span class="text-xs text-slate-500">{round} round{round === 1 ? '' : 's'} so far</span>
      {/if}
    </div>
  </div>

  <!-- Transcript -->
  {#if transcript.length > 0}
    <div class="space-y-2">
      {#each transcript as turn, i (i)}
        <div class="glass-card p-3">
          <div class="flex items-center justify-between mb-1">
            <span class="text-xs font-medium text-white">
              {turn.agentName}
              <span class="text-blue-300"> · {turn.role}</span>
            </span>
            <span class="text-xs text-slate-600 font-mono">R{turn.round} · {turn.model}</span>
          </div>
          {#if turn.status === 'thinking'}
            <div class="flex items-center gap-2 text-sm {ROLE_COLOUR.thinking} progress-pulse">
              <span class="w-2 h-2 rounded-full bg-amber-400 inline-block"></span>
              thinking…
            </div>
          {:else}
            <p class="text-sm {ROLE_COLOUR[turn.status]}" style="white-space: pre-wrap; word-break: break-word;">{turn.text}</p>
          {/if}
        </div>
      {/each}
    </div>
  {/if}
</div>
