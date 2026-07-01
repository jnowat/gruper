<script lang="ts">
  import type { Agent } from '$lib/types.js';

  let {
    agent,
    selected = false,
    onclick,
    onRemove,
  }: {
    agent: Agent;
    selected?: boolean;
    onclick?: () => void;
    onRemove?: () => void;
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
</script>

<!--
  Not a single <button> wrapping everything (as before onRemove existed) —
  nesting a "remove" button inside the card's own button would be invalid
  HTML (buttons can't nest) and would need stopPropagation gymnastics to
  keep a click on remove from also selecting the card. A group container
  with two sibling buttons avoids both problems.
-->
<div
  class="group w-full glass-card p-3 transition-all duration-150 {selected ? 'border-blue-500/60 bg-blue-500/10' : ''}"
>
  <div class="flex items-start gap-2">
    <button class="flex-1 min-w-0 text-left flex items-start gap-2" onclick={onclick}>
      <!-- Status dot -->
      <span class="mt-1 flex-shrink-0 w-2 h-2 rounded-full {STATUS_DOTS[agent.status] ?? 'bg-slate-500'}"></span>

      <div class="min-w-0 flex-1">
        <div class="flex items-center justify-between gap-1">
          <span class="text-sm font-medium text-white truncate">{agent.name}</span>
          <span class="text-xs text-slate-400 status-{agent.status} flex-shrink-0">{agent.status}</span>
        </div>

        {#if agent.capabilities?.models?.length}
          <p class="text-xs text-slate-500 truncate mt-0.5">
            {agent.capabilities.models.slice(0, 2).join(', ')}
            {#if agent.capabilities.models.length > 2}
              +{agent.capabilities.models.length - 2}
            {/if}
          </p>
        {/if}

        <p class="text-xs text-slate-600 mt-0.5">seen {lastSeenLabel}</p>
      </div>
    </button>

    {#if onRemove}
      <button
        onclick={onRemove}
        title="Stop this agent (if it's managed by this Console) and mark it offline"
        class="flex-shrink-0 text-slate-600 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-opacity text-xs px-1"
      >
        ✕
      </button>
    {/if}
  </div>
</div>
