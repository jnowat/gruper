<!--
  ResultView — a task's live progress and final result, filling the wide detail
  pane.

  - Progress is collapsible and auto-collapses once the task finishes, so the
    result is what you see (the progress panel was "overbearing").
  - Header shows model, wall time, tokens, and tokens/sec (real Ollama
    eval_count / eval_duration surfaced by the agent runtime).
  - Markdown via marked + DOMPurify, with LaTeX/math protected from markdown
    mangling and rendered by KaTeX (falling back to clean escaped text) — fixes
    "$^4\text{He}$" getting bolded instead of rendered.
-->
<script lang="ts">
  import { marked } from 'marked';
  import DOMPurify from 'dompurify';
  import katex from 'katex';
  import 'katex/dist/katex.min.css';
  import { tasksStore, type ProgressLine } from '$lib/stores/tasks.js';
  import { authStore } from '$lib/stores/auth.js';
  import { OrchestratorClient } from '$lib/api/client.js';
  import type { Task } from '$lib/types.js';

  let { taskId, agentName = null }: { taskId: string | null; agentName?: string | null } = $props();

  const TERMINAL = new Set(['complete', 'failed', 'timed_out', 'dead_letter']);

  let task = $state<Task | null>(null);
  let progressLines = $state<ProgressLine[]>([]);
  let fetchingResult = $state(false);
  let resultText = $state<string | null>(null);
  let fetchError = $state<string | null>(null);
  let resultModel = $state<string | null>(null);
  let resultDuration = $state<number | null>(null);
  let resultTokens = $state<number | null>(null);
  let resultTps = $state<number | null>(null);
  let copied = $state(false);
  // null = follow the default (expanded while running, collapsed when done);
  // true/false = the user's explicit choice for this task.
  let userToggledProgress = $state<boolean | null>(null);

  const isTerminal = $derived(task ? TERMINAL.has(task.status) : false);
  const showProgress = $derived(userToggledProgress ?? !isTerminal);

  $effect(() => {
    if (!taskId) {
      task = null;
      progressLines = [];
      resetResult();
      return;
    }
    resetResult();
    userToggledProgress = null;
    const unsubTask = tasksStore.subscribe((s) => {
      task = s.tasks.find((t) => t.id === taskId) ?? null;
      progressLines = s.progress[taskId] ?? [];
    });
    return unsubTask;
  });

  function resetResult() {
    resultText = null;
    fetchError = null;
    resultModel = null;
    resultDuration = null;
    resultTokens = null;
    resultTps = null;
  }

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
      resultTokens = (result?.tokens_used as number) ?? null;
      resultTps = (result?.tokens_per_sec as number) ?? null;
    } catch (err) {
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

  // ── Markdown + math ─────────────────────────────────────────────────────────
  type MathItem = { tex: string; display: boolean };
  // A distinctive ASCII sentinel that markdown + DOMPurify leave untouched
  // and that won't collide with real content, so restoring math can't clobber
  // stray digits in the rendered output.
  const M_OPEN = '@@GRUPERMATH';
  const M_CLOSE = '@@';

  function looksLikeMath(s: string): boolean {
    return /[\\^_{}]/.test(s) || /\\?(frac|sqrt|sum|int|alpha|beta|gamma|theta|text|mathrm|cdot|times|approx|leq|geq|infty)/.test(s);
  }

  function extractMath(text: string, store: MathItem[]): string {
    const push = (tex: string, display: boolean) => {
      const idx = store.length;
      store.push({ tex: tex.trim(), display });
      return `${M_OPEN}${idx}${M_CLOSE}`;
    };
    let out = text.replace(/\$\$([\s\S]+?)\$\$/g, (_m, t) => push(t, true));
    out = out.replace(/\\\[([\s\S]+?)\\\]/g, (_m, t) => push(t, true));
    out = out.replace(/\\\(([\s\S]+?)\\\)/g, (_m, t) => push(t, false));
    // Inline $...$ — conservative: single line and must look like math, so
    // prose with "$5 and $10" is left alone.
    out = out.replace(/\$([^$\n]+?)\$/g, (whole, t) => (looksLikeMath(t) ? push(t, false) : whole));
    return out;
  }

  function renderMathItem(item: MathItem): string {
    try {
      return katex.renderToString(item.tex, {
        displayMode: item.display,
        throwOnError: false,
        output: 'html',
      });
    } catch {
      const esc = item.tex.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
      const wrap = item.display ? `$$${esc}$$` : `$${esc}$`;
      return `<code class="math-fallback">${wrap}</code>`;
    }
  }

  function escapePlain(text: string): string {
    return text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/\n/g, '<br>');
  }

  function renderMarkdown(text: string): string {
    const math: MathItem[] = [];
    const protectedText = extractMath(text, math);
    let html: string;
    try {
      html = marked.parse(protectedText, { async: false, gfm: true, breaks: true }) as string;
      html = DOMPurify.sanitize(html);
    } catch {
      html = escapePlain(protectedText);
    }
    // Restore math AFTER sanitize: KaTeX output is trusted, fixed-structure
    // markup (throwOnError:false, trust:false by default), inserted verbatim.
    const re = new RegExp(`${M_OPEN}(\\d+)${M_CLOSE}`, 'g');
    return html.replace(re, (_m, i) => {
      const item = math[Number(i)];
      return item ? renderMathItem(item) : '';
    });
  }

  async function copyResult(): Promise<void> {
    if (!resultText) return;
    try {
      await navigator.clipboard.writeText(resultText);
      copied = true;
      setTimeout(() => (copied = false), 1500);
    } catch {
      // clipboard may be unavailable in some webview contexts
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
        <p class="text-xs text-slate-400 font-mono truncate">
          {task.id}{#if agentName}<span class="text-slate-500"> · → {agentName}</span>{/if}
        </p>
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

    <!-- Streaming progress (collapsible) -->
    {#if progressLines.length > 0 || task.status === 'running'}
      <div>
        <button
          type="button"
          onclick={() => (userToggledProgress = !showProgress)}
          class="flex items-center gap-1 text-xs text-slate-400 hover:text-slate-200 mb-2 font-medium"
        >
          <span class="inline-block w-3">{showProgress ? '▾' : '▸'}</span>
          Progress{#if progressLines.length}<span class="text-slate-600"> ({progressLines.length})</span>{/if}
        </button>
        {#if showProgress}
          {#if progressLines.length > 0}
            <div class="space-y-1 max-h-[32vh] overflow-y-auto">
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
          {:else}
            <div class="flex items-center gap-2 text-sm text-amber-400 progress-pulse">
              <span class="w-2 h-2 rounded-full bg-amber-400 inline-block"></span>
              Running — waiting for progress updates…
            </div>
          {/if}
        {/if}
      </div>
    {/if}

    <!-- Final result -->
    {#if task.status === 'complete'}
      <div>
        <div class="flex items-center justify-between mb-2 gap-2">
          <p class="text-xs text-slate-400 font-medium min-w-0 truncate">
            Result
            {#if resultModel ?? task.result?.model_used}
              <span class="text-slate-500">· {resultModel ?? task.result?.model_used}</span>
            {/if}
            {#if (resultDuration ?? task.result?.duration_ms) != null}
              <span class="text-slate-500">· {((resultDuration ?? task.result?.duration_ms ?? 0) / 1000).toFixed(1)}s</span>
            {/if}
            {#if (resultTokens ?? task.result?.tokens_used) != null}
              <span class="text-slate-500">· {resultTokens ?? task.result?.tokens_used} tok</span>
            {/if}
            {#if (resultTps ?? task.result?.tokens_per_sec) != null}
              <span class="text-slate-500">· {resultTps ?? task.result?.tokens_per_sec} tok/s</span>
            {/if}
          </p>
          {#if resultText}
            <button
              onclick={copyResult}
              class="flex-shrink-0 text-xs px-2 py-0.5 rounded bg-white/5 border border-white/10 text-slate-300 hover:bg-white/10 transition-colors"
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
