<!--
  Round Table — a group chat with your agents. The user opens with a message,
  every selected agent responds in turn (streaming live), and the user can
  interject at any time — or just let them keep going. State lives in
  roundTableStore, so switching tabs never loses the conversation.

  No "Round N" machinery, no model tags in the flow (they're in the hover
  tooltip), no raw errors as speech — a failed turn reads as a quiet note.
-->
<script lang="ts">
  import { roundTableStore } from '$lib/stores/roundtable.js';
  import { agentModel, agentRole } from '$lib/agentDisplay.js';
  import { roleInfo } from '$lib/roles.js';
  import AgentAvatar from '$lib/components/AgentAvatar.svelte';
  import type { Agent } from '$lib/types.js';

  let { agents = [] }: { agents?: Agent[] } = $props();

  const rt = $derived($roundTableStore);
  const started = $derived(rt.transcript.length > 0);
  // Only online selected agents are truly "at the table" — the store skips
  // offline ones when running turns, so the count and the turns always agree.
  const participants = $derived(
    agents.filter((a) => rt.participants.has(a.id) && a.status !== 'offline'),
  );

  let draft = $state('');

  // Default: everyone online takes part (once, until the user adjusts it).
  $effect(() => {
    roundTableStore.seedParticipants(agents);
  });

  function send() {
    const text = draft.trim();
    if (!text || participants.length === 0) return;
    draft = '';
    void roundTableStore.send(text, agents);
  }

  function onDraftKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      send();
    }
  }

  // Auto-scroll the transcript as it grows / streams — but only when the user
  // is already near the bottom, so scrolling up to re-read an earlier turn
  // isn't hijacked by every incoming chunk.
  let scroller = $state<HTMLDivElement | null>(null);
  $effect(() => {
    void rt.transcript;
    if (!scroller) return;
    const nearBottom = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 160;
    if (nearBottom) scroller.scrollTop = scroller.scrollHeight;
  });

  function agentTooltip(turn: { agentId: string | null; role: string | null; model: string | null }): string {
    const info = roleInfo(turn.role);
    return [info ? `${info.label} — ${info.tagline}` : null, turn.model ? `Model: ${turn.model}` : null]
      .filter(Boolean)
      .join('\n');
  }
</script>

<div class="space-y-3 max-w-3xl h-full flex flex-col">
  <div class="glass-card p-4 space-y-3 flex-shrink-0">
    <div class="flex items-center justify-between">
      <h2 class="text-sm font-semibold text-white">Round Table</h2>
      {#if started}
        <button
          onclick={() => roundTableStore.reset()}
          disabled={rt.running}
          class="text-xs text-slate-500 hover:text-red-400 disabled:opacity-40 transition-colors"
        >Start over</button>
      {/if}
    </div>
    {#if !started}
      <p class="text-xs text-slate-500">
        A group discussion: everyone you pick responds in turn, each seeing what came before.
        Anything you send joins the conversation — agents who haven't spoken yet will see it.
      </p>
    {/if}

    <div>
      <p class="text-xs text-slate-400 mb-1.5">Who's at the table ({participants.length})</p>
      {#if agents.length === 0}
        <p class="text-xs text-slate-500">No agents yet — add one from the sidebar first.</p>
      {:else}
        <div class="flex flex-wrap gap-1.5">
          {#each agents as a (a.id)}
            {@const info = roleInfo(agentRole(a))}
            <button
              type="button"
              onclick={() => roundTableStore.toggleParticipant(a.id)}
              disabled={rt.running || a.status === 'offline'}
              class="flex items-center gap-1.5 text-xs pl-1 pr-2 py-1 rounded-lg border transition-colors disabled:opacity-50 {rt.participants.has(a.id) && a.status !== 'offline'
                ? 'border-blue-500/50 bg-blue-500/10 text-blue-100'
                : 'border-white/10 text-slate-400 hover:bg-white/5'}"
              title={a.status === 'offline'
                ? `${a.name} is offline and can't join right now`
                : info ? `${info.label} — ${info.tagline}\nModel: ${agentModel(a)}` : `Model: ${agentModel(a)}`}
            >
              <AgentAvatar id={a.id} name={a.name} size={18} />
              {a.name}
              {#if info}<span class="text-slate-500">{info.icon}</span>{/if}
              {#if a.status === 'offline'}<span class="text-slate-600">(offline)</span>{/if}
            </button>
          {/each}
        </div>
      {/if}
    </div>

    {#if rt.error}
      <div class="bg-red-500/10 border border-red-500/30 text-red-400 text-xs rounded-lg p-2">{rt.error}</div>
    {/if}
  </div>

  <!-- Transcript -->
  {#if started}
    <div bind:this={scroller} class="space-y-2 flex-1 min-h-0 overflow-y-auto pr-1">
      {#each rt.transcript as turn, i (i)}
        {#if turn.kind === 'user'}
          <div class="flex justify-end">
            <div class="max-w-[85%] bg-blue-600/20 border border-blue-500/30 rounded-xl rounded-br-sm px-3 py-2">
              <p class="text-sm text-slate-100" style="white-space: pre-wrap; word-break: break-word;">{turn.text}</p>
            </div>
          </div>
        {:else}
          <div class="glass-card p-3 transition-colors {turn.status === 'thinking' || turn.status === 'streaming' ? 'border-blue-500/40 bg-blue-500/5' : ''}">
            <div class="flex items-center gap-2 mb-1.5" title={agentTooltip(turn)}>
              {#if turn.agentId}<AgentAvatar id={turn.agentId} name={turn.name} size={22} />{/if}
              <span class="text-xs font-medium text-white">{turn.name}</span>
              {#if roleInfo(turn.role)}
                <span class="text-xs text-blue-300">{roleInfo(turn.role)?.icon} {roleInfo(turn.role)?.label}</span>
              {/if}
              {#if turn.status === 'thinking' || turn.status === 'streaming'}
                <span class="text-xs text-amber-400 progress-pulse">responding…</span>
              {/if}
            </div>
            {#if turn.status === 'thinking'}
              <div class="flex items-center gap-2 text-sm text-amber-400 progress-pulse">
                <span class="w-2 h-2 rounded-full bg-amber-400 inline-block"></span>
                thinking…
              </div>
            {:else if turn.status === 'failed'}
              <p class="text-sm text-slate-500 italic">{turn.text}</p>
            {:else}
              <p class="text-sm text-slate-200" style="white-space: pre-wrap; word-break: break-word;">{turn.text}{#if turn.status === 'streaming'}<span class="text-amber-400 progress-pulse">▌</span>{/if}</p>
            {/if}
          </div>
        {/if}
      {/each}
    </div>
  {/if}

  <!-- Say something / keep it going -->
  <div class="glass-card p-3 space-y-2 flex-shrink-0">
    <textarea
      bind:value={draft}
      onkeydown={onDraftKeydown}
      rows={started ? 2 : 3}
      placeholder={started
        ? 'Add to the discussion… (Enter to send)'
        : 'What should they discuss? e.g. Should I buy or rent my next home?'}
      class="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white placeholder:text-slate-500 focus:outline-none focus:border-blue-500 resize-none"
    ></textarea>
    <div class="flex items-center gap-2">
      <button
        onclick={send}
        disabled={!draft.trim() || participants.length === 0}
        class="bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed text-white rounded-lg px-4 py-1.5 text-sm font-medium transition-colors"
      >
        {started ? 'Send' : 'Start the discussion'}
      </button>
      {#if rt.running}
        <span class="text-xs text-amber-400 progress-pulse">They're talking…</span>
        <button
          onclick={() => roundTableStore.stop()}
          class="text-xs text-slate-400 hover:text-red-400 transition-colors"
          title="Stop after the current sentence — the conversation stays"
        >
          Stop
        </button>
      {:else if started}
        <button
          onclick={() => void roundTableStore.continueDiscussion(agents)}
          disabled={participants.length === 0}
          class="text-xs text-slate-400 hover:text-slate-200 disabled:opacity-40 transition-colors"
          title="Everyone at the table responds again, without a new message from you"
        >
          Let them keep going →
        </button>
      {/if}
      {#if participants.length === 0 && agents.length > 0}
        <span class="text-xs text-amber-400">Pick at least one agent above.</span>
      {/if}
    </div>
  </div>
</div>
