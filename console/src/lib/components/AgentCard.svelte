<script lang="ts">
  import type { Agent } from '$lib/types.js';
  import { agentColor, agentInitials, agentModel, agentRole } from '$lib/agentDisplay.js';

  let {
    agent,
    selected = false,
    onclick,
    onRemove,
    onRename,
  }: {
    agent: Agent;
    selected?: boolean;
    onclick?: () => void;
    onRemove?: () => void;
    onRename?: (name: string) => void;
  } = $props();

  const STATUS_DOTS: Record<string, string> = {
    idle:     'bg-green-500',
    busy:     'bg-amber-500',
    offline:  'bg-slate-500',
    degraded: 'bg-red-500',
    draining: 'bg-amber-400 opacity-70',
  };

  const lastSeenLabel = $derived.by(() => {
    if (!agent.last_seen) return 'never';
    const diff = Math.floor((Date.now() - new Date(agent.last_seen).getTime()) / 1000);
    if (diff < 60) return `${diff}s ago`;
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    return `${Math.floor(diff / 3600)}h ago`;
  });

  const models = $derived(agent.capabilities?.models ?? []);
  const model = $derived(agentModel(agent));
  const role = $derived(agentRole(agent));
  const color = $derived(agentColor(agent.id));
  const initials = $derived(agentInitials(agent.name));

  let editing = $state(false);
  let draft = $state('');
  function startEdit() {
    draft = agent.name;
    editing = true;
  }
  function commit() {
    const name = draft.trim();
    editing = false;
    if (name && name !== agent.name) onRename?.(name);
  }
</script>

<!--
  Sibling buttons in a group container (not a wrapping <button>) so the card can
  hold its own action buttons (rename, remove) without invalid nested buttons.
-->
<div
  class="group w-full glass-card p-2.5 transition-all duration-150 {selected ? 'border-blue-500/60 bg-blue-500/10' : ''}"
>
  <div class="flex items-start gap-2">
    <!-- Colour+initials avatar — the fastest way to tell agents apart. -->
    <span
      class="mt-0.5 flex-shrink-0 w-7 h-7 rounded-md flex items-center justify-center text-xs font-semibold text-white relative"
      style="background-color: {color}"
      title={agent.status}
    >
      {initials}
      <span class="absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 rounded-full border border-slate-900 {STATUS_DOTS[agent.status] ?? 'bg-slate-500'}"></span>
    </span>

    <div class="min-w-0 flex-1">
      {#if editing}
        <!-- svelte-ignore a11y_autofocus -->
        <input
          bind:value={draft}
          onblur={commit}
          onkeydown={(e) => { if (e.key === 'Enter') commit(); else if (e.key === 'Escape') editing = false; }}
          autofocus
          class="w-full bg-white/10 border border-blue-500/50 rounded px-1.5 py-0.5 text-sm text-white focus:outline-none"
        />
      {:else}
        <div class="flex items-center gap-1">
          <button class="min-w-0 text-left flex-1" onclick={onclick}>
            <span class="text-sm font-medium text-white truncate block">{agent.name}</span>
          </button>
          {#if onRename}
            <button
              onclick={startEdit}
              title="Rename this agent"
              class="flex-shrink-0 text-slate-600 hover:text-blue-400 opacity-0 group-hover:opacity-100 transition-opacity text-xs"
            >✎</button>
          {/if}
          {#if onRemove}
            <button
              onclick={onRemove}
              title="Stop this agent (if managed by this Console) and mark it offline"
              class="flex-shrink-0 text-slate-600 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-opacity text-xs"
            >✕</button>
          {/if}
        </div>
      {/if}

      <button class="w-full text-left" onclick={onclick}>
        <p class="text-xs mt-0.5 truncate">
          {#if role}<span class="text-blue-300 font-medium">{role}</span>{/if}
          {#if role && model}<span class="text-slate-600"> · </span>{/if}
          {#if model}<span class="font-mono text-slate-500">{model}</span>{#if models.length > 1}<span class="text-slate-600"> +{models.length - 1}</span>{/if}{/if}
          {#if !model && !role}<span class="text-slate-600">no model</span>{/if}
        </p>
        <p class="text-xs text-slate-600 mt-0.5">
          <span class="status-{agent.status}">{agent.status}</span> · seen {lastSeenLabel}
        </p>
      </button>
    </div>
  </div>
</div>
