<!--
  ResultView — renders a task's live progress and final result. Fills the wide
  master/detail pane (see +page.svelte), not the old cramped right rail.

  - Round-based streaming progress from task_progress events
  - Final output rendered with the real marked + DOMPurify pipeline (untrusted
    model text sanitized before {@html}), with a plaintext fallback so a render
    failure degrades to visible text rather than a blank result
  - Copy-result button; fetch-error state distinct from "no output"
-->
<script lang="ts">
  import { marked } from 'marked';
  import DOMPurify from 'dompurify';
  import { tasksStore, type ProgressLine } from '$lib/stores/tasks.js';
  import { authStore } from '$lib/stores/auth.js';
  import { OrchestratorClient } from '$lib/api/client.js';
  import type { Task } from '$lib/types.js';

  let { taskId }: { taskId: string | null } = $props();

  let task = $state<Task | null>(null);
  let progressLines = $state<ProgressLine[]>([]);
  let fetchingResult = $state(false);
  let resultText = $state<string | null>(null);
  let fetchError = $state<string | null>(null);
  let resultModel = $state<string | null>(null);
  let resultDuration = $state<number | null>(null);
  let copied = $state(false);

  // Reactive: when taskId changes, look up the task in the store and reset the
  // fetched-result state so the next terminal task fetches fresh.
  $effect(() => {
    if (!taskId) {
      task = null;
      progressLines = [];
      resultText = null;
      fetchError = null;
      resultModel = null;
      resultDuration = null;
      return;
    }
    // Reset per-task fetched state on switch.
    resultText = null;
    fetchError = null;
    resultModel = null;
    resultDuration = null;
    const unsubTask = tasksStore.subscribe((s) => {
      task = s.tasks.find((t) => t.id === taskId) ?? null;
      progressLines = s.progress[taskId] ?? [];
    });
    return unsubTask;
  });

  async function fetchResult(id: string): Promise<void> {
    fetchingResult = true;
    fetchError = null;
    const { token, orchestratorUrl } = $authStore;
    if (!token) {
      fetchingResult = false;
      return;
    }
    try {
      const full = await new OrchestratorClient(orchestratorUrl, token).getTask(id);
      const result = full.result as Record<string, unknown> | null;
      resultText = (result?.output as string) ?? '';
      resultModel = (result?.model_used as string) ?? null;
      resultDuration = (result?.duration_ms as number) ?? null;
    } catch (err) {
      // Distinct from "no output": a network blip must not masquerade as an
      // empty answer. The user gets a Retry.
      fetchError = err instanceof Error ? err.message : String(err);
    } finally {
      fetchingResult = false;
    }
  }

  $effect(() => {
    if (task && task.status === 'complete' && resultText === null && !fetchingResult && !fetchError) {
      fetchResult(task.id);
    }
  });

  // Real markdown, sanitized. marked + DOMPurify are the project's existing deps
  // and are statically bundled (no runtime import that a strict CSP could reject
  // into a blank result). Untrusted model output rendered with {@html} is a
  // genuine XSS surface — DOMPurify closes it.
  function renderMarkdown(text: string): string {
    try {
      const html = marked.parse(text, { async: false, gfm: true, breaks: true }) as string;
      return DOMPurify.sanitize(html);
    } catch {
      return text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/\n/g, '<br>');
    }
  }

  async function copyResult(): Promise<void> {
    if (!resultText) return;
    try {
      await navigator.clipboard.writeText(resultText);
      copied = true;
      setTimeout(() => (copied = false), 1500);
    } catch {
      // ignore — clipboard may be unavailable in some webview contexts
    }
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
    Select a task to view its result — or start a new one.
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
        <p class="text-sm text-white mt-0.5">{task.input?.prompt ?? '—'}</p>
      </div>
      <span class="text-xs {STATUS_COLOUR[task.status] ?? 'text-slate-400'} flex-shrink-0 font-medium">
        {task.status}
      </span>
    </div>

    <div class="text-xs text-slate-500 flex gap-4 flex-wrap">
      <span>Priority: {task.priority}</span>
      <span>Data class: {task.data_class}</span>
      <span>Timeout: {task.timeout_s}s</span>
      {#if task.created_at}
        <span>Created: {new Date(task.created_at).toLocaleTimeString()}</span>
      {/if}
    </div>

    <!-- Streaming progress -->
    {#if progressLines.length > 0}
      <div>
        <p class="text-xs text-slate-400 mb-2 font-medium">Progress</p>
        <div class="space-y-1 max-h-[40vh] overflow-y-auto">
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

    <!-- Final result -->
    {#if task.status === 'complete'}
      <div>
        <div class="flex items-center justify-between mb-2">
          <p class="text-xs text-slate-400 font-medium">
            Result
            {#if resultModel ?? task.result?.model_used}
              <span class="text-slate-500">· {resultModel ?? task.result?.model_used}</span>
            {/if}
            {#if (resultDuration ?? task.result?.duration_ms) != null}
              <span class="text-slate-500">· {((resultDuration ?? task.result?.duration_ms ?? 0) / 1000).toFixed(1)}s</span>
            {/if}
          </p>
          {#if resultText}
            <button
              onclick={copyResult}
              class="text-xs px-2 py-0.5 rounded bg-white/5 border border-white/10 text-slate-300 hover:bg-white/10 transition-colors"
            >
              {copied ? 'Copied ✓' : 'Copy'}
            </button>
          {/if}
        </div>

        {#if fetchingResult}
          <div class="text-slate-500 text-sm">Fetching full result…</div>
        {:else if fetchError}
          <div class="bg-red-500/10 border border-red-500/30 rounded-lg p-3 text-sm">
            <p class="text-red-400">Couldn't load the result: {fetchError}</p>
            <button
              onclick={() => task && fetchResult(task.id)}
              class="mt-2 text-xs px-2 py-1 rounded bg-white/5 border border-white/10 text-slate-300 hover:bg-white/10"
            >
              Retry
            </button>
          </div>
        {:else if resultText}
          <div class="message-bubble markdown-body" role="article">
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
