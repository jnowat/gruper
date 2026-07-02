<!--
  One agent in the sidebar. Designed to be scanned, not studied:
    line 1 — name (the identity)
    line 2 — specialty in plain words ("🔍 Critic — pokes holes…")
    line 3 — model (quiet, mono) + humanized status
  Raw enum statuses, "seen Xs ago", and the full model list live in the hover
  tooltip instead of the card. Name and specialty are both editable in place —
  the pencil is always faintly visible (not hover-only), and double-clicking
  the name also starts a rename. Removing asks first, inline.
-->
<script lang="ts">
  import type { Agent } from '$lib/types.js';
  import { agentColor, agentInitials, agentModel, agentRole } from '$lib/agentDisplay.js';
  import { agentStatusLabel } from '$lib/taskDisplay.js';
  import { ROLES, roleInfo } from '$lib/roles.js';

  let {
    agent,
    selected = false,
    onclick,
    onRemove,
    onRename,
    onChangeRole,
  }: {
    agent: Agent;
    selected?: boolean;
    onclick?: () => void;
    onRemove?: () => void;
    onRename?: (name: string) => void;
    onChangeRole?: (role: string) => void;
  } = $props();

  const STATUS_DOTS: Record<string, string> = {
    idle:     'bg-green-500',
    busy:     'bg-amber-500',
    offline:  'bg-slate-500',
    degraded: 'bg-red-500',
    draining: 'bg-amber-400 opacity-70',
  };

  const lastSeenLabel = $derived.by(() => {
    if (!agent.last_seen) return 'not connected yet';
    const diff = Math.floor((Date.now() - new Date(agent.last_seen).getTime()) / 1000);
    if (diff < 60) return `active ${diff}s ago`;
    if (diff < 3600) return `active ${Math.floor(diff / 60)}m ago`;
    return `active ${Math.floor(diff / 3600)}h ago`;
  });

  const models = $derived(agent.capabilities?.models ?? []);
  const model = $derived(agentModel(agent));
  const roleId = $derived(agentRole(agent));
  const role = $derived(roleInfo(roleId));
  const color = $derived(agentColor(agent.id));
  const initials = $derived(agentInitials(agent.name));
  const statusLabel = $derived(agentStatusLabel(agent.status));

  const tooltip = $derived(
    [
      `${agent.name} — ${statusLabel}`,
      model ? `Model: ${model}${models.length > 1 ? ` (+${models.length - 1} more installed)` : ''}` : null,
      lastSeenLabel,
    ]
      .filter(Boolean)
      .join('\n'),
  );

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

  // The editor commits on blur (not only on change): for an agent with no
  // specialty, picking the option the select already shows fires no change
  // event, so change-only committing could never set it.
  let editingRole = $state(false);
  let roleEditCancelled = false;
  function commitRole(id: string) {
    editingRole = false;
    if (roleEditCancelled) return;
    if (id && id !== agentRole(agent)) onChangeRole?.(id);
  }

  let confirmingRemove = $state(false);
</script>

<!--
  Sibling buttons in a group container (not a wrapping <button>) so the card can
  hold its own action buttons (rename, remove) without invalid nested buttons.
-->
<div
  class="group w-full glass-card p-2.5 transition-all duration-150 {selected ? 'border-blue-500/60 bg-blue-500/10' : ''}"
  title={tooltip}
>
  <div class="flex items-start gap-2">
    <!-- Colour+initials avatar — the fastest way to tell agents apart. -->
    <button
      onclick={onclick}
      class="mt-0.5 flex-shrink-0 w-7 h-7 rounded-md flex items-center justify-center text-xs font-semibold text-white relative"
      style="background-color: {color}"
    >
      {initials}
      <span class="absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 rounded-full border border-slate-900 {STATUS_DOTS[agent.status] ?? 'bg-slate-500'}" title={statusLabel}></span>
    </button>

    <div class="min-w-0 flex-1">
      {#if editing}
        <!-- svelte-ignore a11y_autofocus -->
        <input
          bind:value={draft}
          onblur={commit}
          onkeydown={(e) => { if (e.key === 'Enter' && !e.isComposing) commit(); else if (e.key === 'Escape') editing = false; }}
          autofocus
          class="w-full bg-white/10 border border-blue-500/50 rounded px-1.5 py-0.5 text-sm text-white focus:outline-none"
        />
      {:else}
        <div class="flex items-center gap-1">
          <button
            class="min-w-0 text-left flex-1"
            onclick={onclick}
            ondblclick={() => { if (onRename) startEdit(); }}
          >
            <span class="text-sm font-medium text-white truncate block">{agent.name}</span>
          </button>
          {#if onRename}
            <button
              onclick={startEdit}
              title="Rename"
              class="flex-shrink-0 text-slate-600 hover:text-blue-400 opacity-40 group-hover:opacity-100 transition-opacity text-xs"
            >✎</button>
          {/if}
          {#if onRemove}
            <button
              onclick={() => { confirmingRemove = true; }}
              title="Remove this agent"
              class="flex-shrink-0 text-slate-600 hover:text-red-400 opacity-40 group-hover:opacity-100 transition-opacity text-xs"
            >✕</button>
          {/if}
        </div>
      {/if}

      {#if editingRole}
        <!-- svelte-ignore a11y_autofocus -->
        <select
          autofocus
          value={roleId ?? 'analyst'}
          onblur={(e) => commitRole((e.currentTarget as HTMLSelectElement).value)}
          onkeydown={(e) => { if (e.key === 'Escape') { roleEditCancelled = true; editingRole = false; } else if (e.key === 'Enter') { commitRole((e.currentTarget as HTMLSelectElement).value); } }}
          class="w-full mt-0.5 bg-white/10 border border-blue-500/50 rounded px-1 py-0.5 text-xs text-white focus:outline-none"
        >
          {#if roleId && !role}
            <!-- A role outside the catalog (e.g. a manually-run agent): keep it listed so the select opens on the truth. -->
            <option value={roleId} class="bg-slate-800 text-white">{roleId}</option>
          {/if}
          {#each ROLES as r (r.id)}
            <option value={r.id} class="bg-slate-800 text-white">{r.icon} {r.label} — {r.tagline}</option>
          {/each}
        </select>
      {:else if onChangeRole}
        <button
          class="w-full text-left text-xs mt-0.5 truncate block hover:text-blue-300 transition-colors {roleId ? 'text-slate-400' : 'text-slate-600'}"
          title="Change specialty"
          onclick={() => { roleEditCancelled = false; editingRole = true; }}
        >
          {#if role}{role.icon} <span class="text-blue-300 font-medium">{role.label}</span> — {role.tagline}{:else if roleId}<span class="text-blue-300 font-medium">{roleId}</span>{:else}Set a specialty…{/if}
        </button>
      {:else}
        <p class="text-xs mt-0.5 truncate {roleId ? 'text-slate-400' : 'text-slate-600'}">
          {#if role}{role.icon} <span class="text-blue-300 font-medium">{role.label}</span> — {role.tagline}{:else if roleId}<span class="text-blue-300 font-medium">{roleId}</span>{:else}No specialty set{/if}
        </p>
      {/if}

      <button class="w-full text-left flex items-center justify-between gap-2 mt-0.5" onclick={onclick}>
        <span class="text-xs font-mono text-slate-600 truncate">{model || ''}</span>
        <span class="text-xs flex-shrink-0 status-{agent.status}">{statusLabel}</span>
      </button>

      {#if confirmingRemove}
        <div class="mt-1.5 flex items-center gap-2 text-xs bg-white/5 rounded px-2 py-1">
          <span class="text-slate-400 flex-1 truncate">
            {agent.status === 'offline' ? 'Remove from list?' : 'Stop and remove?'}
          </span>
          <button
            onclick={() => { confirmingRemove = false; onRemove?.(); }}
            class="text-red-400 hover:text-red-300 font-medium"
          >Remove</button>
          <button
            onclick={() => { confirmingRemove = false; }}
            class="text-slate-500 hover:text-slate-300"
          >Keep</button>
        </div>
      {/if}
    </div>
  </div>
</div>
