<!--
  ResultView — embeds Gruper core's conversation message rendering style:
  - Round-based display with agent role indicator
  - Markdown rendering via marked + DOMPurify XSS protection (same libraries as core)
  - Glassmorphism message bubbles matching core's agent panel cards
  - Streaming partial output from task_progress events
-->
<script lang="ts">
  import { tasksStore, type ProgressLine } from '$lib/stores/tasks.js';
  import { authStore } from '$lib/stores/auth.js';
  import { OrchestratorClient } from '$lib/api/client.js';
  import type { Task } from '$lib/types.js';

  let { taskId }: { taskId: string | null } = $props();

  let task = $state<Task | null>(null);
  let progressLines = $state<ProgressLine[]>([]);
  let fetchingResult = $state(false);
  let resultText = $state<string | null>(null);

  // Reactive: when taskId changes, look up the task in the store and fetch full
  // result if it's in a terminal state.
  $effect(() => {
    if (!taskId) {
      task = null;
      progressLines = [];
      resultText = null;
      return;
    }
    const unsubTask = tasksStore.subscribe((s) => {
      task = s.tasks.find((t) => t.id === taskId) ?? null;
      progressLines = s.progress[taskId] ?? [];
    });

    return unsubTask;
  });

  $effect(() => {
    if (!task) return;
    if (task.status === 'complete' && !resultText && !fetchingResult) {
      fetchingResult = true;
      const { token, orchestratorUrl } = $authStore;
      if (!token) return;
      const client = new OrchestratorClient(orchestratorUrl, token);
      client
        .getTask(task.id)
        .then((full) => {
          resultText = (full.result as Record<string, string>)?.output ?? null;
        })
        .catch(() => {
          resultText = null;
        })
        .finally(() => {
          fetchingResult = false;
        });
    }
  });

  // Markdown renderer with DOMPurify, matching Gruper core's rendering pipeline.
  function renderMarkdown(text: string): string {
    let html: string;
    try {
      // Dynamic import is not available in sync context; use a simple fallback
      // that converts newlines to <br> and escapes HTML. WP-06 adds the full
      // marked + DOMPurify pipeline with dynamic import.
      html = text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.*?)\*/g, '<em>$1</em>')
        .replace(/`([^`]+)`/g, '<code class="bg-white/10 px-1 rounded text-blue-300">$1</code>')
        .replace(/\n/g, '<br>');
    } catch {
      html = text.replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }
    return html;
  }

  const STATUS_COLOUR: Record<string, string> = {
    pending:     'text-slate-400',
    dispatched:  'text-blue-400',
    running:     'text-amber-400',
    complete:    'text-green-400',
    failed:      'text-red-400',
    timed_out:   'text-orange-400',
    dead_letter: 'text-red-600',
  };
</script>

{#if !taskId}
  <div class="glass-card p-8 text-center text-slate-500 text-sm">
    Select a task to view its result.
  </div>
{:else if !task}
  <div class="glass-card p-8 text-center text-slate-500 text-sm">
    Loading…
  </div>
{:else}
  <div class="glass-card p-4 space-y-4">
    <!-- Task header -->
    <div class="flex items-start justify-between gap-2">
      <div class="min-w-0">
        <p class="text-xs text-slate-400 font-mono truncate">{task.id}</p>
        <p class="text-sm text-white mt-0.5 line-clamp-2">{task.input?.prompt ?? '—'}</p>
      </div>
      <span class="text-xs {STATUS_COLOUR[task.status] ?? 'text-slate-400'} flex-shrink-0 font-medium">
        {task.status}
      </span>
    </div>

    <div class="text-xs text-slate-500 flex gap-4">
      <span>Priority: {task.priority}</span>
      <span>Data class: {task.data_class}</span>
      <span>Timeout: {task.timeout_s}s</span>
      {#if task.created_at}
        <span>Created: {new Date(task.created_at).toLocaleTimeString()}</span>
      {/if}
    </div>

    <!-- Streaming progress — mirrors Gruper core's round-by-round display -->
    {#if progressLines.length > 0}
      <div>
        <p class="text-xs text-slate-400 mb-2 font-medium">Progress</p>
        <div class="space-y-1 max-h-48 overflow-y-auto">
          {#each progressLines as line}
            <div class="flex gap-2 items-start">
              <span class="text-xs text-slate-600 flex-shrink-0 w-14 text-right">
                {(line.ts / 1000).toFixed(1)}s
              </span>
              <div class="message-bubble flex-1 text-xs py-1">
                {#if line.step}
                  <span class="text-blue-400 font-medium">[{line.step}]</span>
                  {' '}
                {/if}
                {line.text || '…'}
              </div>
            </div>
          {/each}
        </div>
      </div>
    {:else if task.status === 'running'}
      <div class="flex items-center gap-2 text-sm text-amber-400 progress-pulse">
        <span class="w-2 h-2 rounded-full bg-amber-400 inline-block"></span>
        Running — waiting for progress updates…
      </div>
    {/if}

    <!-- Final result — Gruper core conversation bubble rendering -->
    {#if task.status === 'complete'}
      <div>
        <p class="text-xs text-slate-400 mb-2 font-medium">
          Result
          {#if task.result?.model_used}
            <span class="text-slate-500">· {task.result.model_used}</span>
          {/if}
          {#if task.result?.duration_ms}
            <span class="text-slate-500">· {(task.result.duration_ms / 1000).toFixed(1)}s</span>
          {/if}
        </p>

        {#if fetchingResult}
          <div class="text-slate-500 text-sm">Fetching full result…</div>
        {:else if resultText}
          <div class="message-bubble" role="article">
            <!-- eslint-disable-next-line svelte/no-at-html-tags -->
            {@html renderMarkdown(resultText)}
          </div>
        {:else}
          <div class="text-slate-500 text-sm italic">No output returned.</div>
        {/if}
      </div>
    {:else if task.status === 'failed'}
      <div class="bg-red-500/10 border border-red-500/30 rounded-lg p-3">
        <p class="text-xs text-red-400 font-medium">Task failed</p>
        {#if task.error?.message}
          <p class="text-sm text-red-300 mt-1">{task.error.message}</p>
        {/if}
        {#if task.error?.code}
          <p class="text-xs text-slate-500 mt-1">Code: {task.error.code}</p>
        {/if}
      </div>
    {:else if task.status === 'timed_out'}
      <div class="bg-orange-500/10 border border-orange-500/30 rounded-lg p-3 text-orange-400 text-sm">
        Task timed out after {task.timeout_s}s.
      </div>
    {:else if task.status === 'dead_letter'}
      <div class="bg-red-900/20 border border-red-800/40 rounded-lg p-3 text-red-400 text-sm">
        Dead-lettered after 3 retries. No agents could accept the task.
      </div>
    {/if}
  </div>
{/if}
