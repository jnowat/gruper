<!--
  ResultView — the answer is the focal point.

  - While the task runs, the streaming reply itself fills the result area (with a
    subtle "answering…" pulse) — there is no separate progress panel competing
    with the answer.
  - On completion the answer renders as markdown under one quiet summary line
    ("Answered in 12.3s · ~41 tok/s"); model name and token counts sit behind a
    small "Details" toggle instead of a pill row that competes with the answer.
  - Failures read as plain sentences with a "Try again" button that resubmits
    the same question to the same agent; error codes hide behind Details.
  - Markdown via marked + DOMPurify; LaTeX/math protected from markdown mangling
    and rendered by KaTeX (clean escaped-text fallback).
  - No raw task UUIDs or inference internals anywhere in the default view.
-->
<script lang="ts">
  import { marked } from 'marked';
  import DOMPurify from 'dompurify';
  import katex from 'katex';
  import 'katex/dist/katex.min.css';
  import { tasksStore, type ProgressLine } from '$lib/stores/tasks.js';
  import { authStore } from '$lib/stores/auth.js';
  import { logStore } from '$lib/stores/logs.js';
  import { OrchestratorClient } from '$lib/api/client.js';
  import { taskStatusColour, taskStatusLabel, RUNNING_TASK_STATUSES } from '$lib/taskDisplay.js';
  import { roleLabel } from '$lib/roles.js';
  import AgentAvatar from '$lib/components/AgentAvatar.svelte';
  import type { Task } from '$lib/types.js';

  let {
    taskId,
    agentId = null,
    agentName = null,
    agentRoleId = null,
    onResubmitted,
  }: {
    taskId: string | null;
    agentId?: string | null;
    agentName?: string | null;
    agentRoleId?: string | null;
    onResubmitted?: (taskId: string) => void;
  } = $props();

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
  let showDetails = $state(false);
  let resubmitting = $state(false);
  let resubmitError = $state<string | null>(null);

  const isRunning = $derived(task ? RUNNING_TASK_STATUSES.has(task.status) : false);
  // The reply as it streams in, one growing block.
  const streamedText = $derived(progressLines.map((l) => l.text).join(''));

  // Metrics prefer the fetched full result, then the task_complete event.
  const mModel = $derived(resultModel ?? task?.result?.model_used ?? null);
  const mDurationMs = $derived(resultDuration ?? task?.result?.duration_ms ?? null);
  const mTokens = $derived(resultTokens ?? task?.result?.tokens_used ?? null);
  // tok/s: use the runtime's real value; otherwise derive from tokens ÷ time so
  // the number is present even when Ollama didn't report eval timings.
  const tps = $derived.by(() => {
    const exact = resultTps ?? task?.result?.tokens_per_sec ?? null;
    if (exact != null) return { value: exact, approx: false };
    if (mTokens && mDurationMs) return { value: Math.round((mTokens / (mDurationMs / 1000)) * 10) / 10, approx: true };
    return null;
  });

  let streamEl = $state<HTMLDivElement | null>(null);
  $effect(() => {
    void streamedText;
    if (streamEl) streamEl.scrollTop = streamEl.scrollHeight;
  });

  $effect(() => {
    if (!taskId) {
      task = null;
      progressLines = [];
      resetResult();
      return;
    }
    resetResult();
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
    showDetails = false;
    resubmitError = null;
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

  /** Resubmit the same question to the same agent (for failed/timed-out tasks). */
  async function tryAgain(): Promise<void> {
    if (!task || resubmitting) return;
    const { token, orchestratorUrl } = $authStore;
    if (!token) return;
    resubmitting = true;
    resubmitError = null;
    try {
      const client = new OrchestratorClient(orchestratorUrl, token);
      const fresh = await client.submitTask({
        assigned_agent_id: task.assigned_agent_id,
        data_class: task.data_class,
        input: task.input,
        timeout_s: task.timeout_s,
      });
      tasksStore.prependTask(fresh);
      logStore.frontend('info', 'ui', 'resubmitted task after failure', {
        task_id: fresh.id,
        agent_id: task.assigned_agent_id,
      });
      onResubmitted?.(fresh.id);
    } catch (err) {
      resubmitError = err instanceof Error ? err.message : String(err);
    } finally {
      resubmitting = false;
    }
  }

  // ── Markdown + math ─────────────────────────────────────────────────────────
  type MathItem = { tex: string; display: boolean };
  const M_OPEN = '@@GRUPERMATH';
  const M_CLOSE = '@@';

  function looksLikeMath(s: string): boolean {
    return (
      /[\\^_{}]/.test(s) ||
      /\\?(frac|sqrt|sum|int|prod|lim|alpha|beta|gamma|delta|theta|lambda|sigma|omega|pi|text|mathrm|mathbf|cdot|cdots|ldots|times|div|pm|mp|approx|neq|leq|geq|infty|partial|nabla|vec|hat|bar|dot|rightarrow|leftarrow|to|forall|exists|in|subset)/.test(s)
    );
  }

  function extractMath(text: string, store: MathItem[]): string {
    const push = (tex: string, display: boolean) => {
      const idx = store.length;
      store.push({ tex: tex.trim(), display });
      return `${M_OPEN}${idx}${M_CLOSE}`;
    };
    let out = text.replace(/\\begin\{([a-zA-Z*]+)\}[\s\S]+?\\end\{\1\}/g, (m) => push(m, true));
    out = out.replace(/\$\$([\s\S]+?)\$\$/g, (_m, t) => push(t, true));
    out = out.replace(/\\\[([\s\S]+?)\\\]/g, (_m, t) => push(t, true));
    out = out.replace(/\\\(([\s\S]+?)\\\)/g, (_m, t) => push(t, false));
    out = out.replace(/\$([^$\n]+?)\$/g, (whole, t) => (looksLikeMath(t) ? push(t, false) : whole));
    return out;
  }

  function renderMathItem(item: MathItem): string {
    try {
      return katex.renderToString(item.tex, { displayMode: item.display, throwOnError: false, output: 'html' });
    } catch {
      const esc = item.tex.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
      const wrap = item.display ? `$$${esc}$$` : `$${esc}$`;
      return `<code class="math-fallback">${wrap}</code>`;
    }
  }

  function escapePlain(text: string): string {
    return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>');
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
</script>

{#if !taskId}
  <div class="glass-card p-8 text-center text-slate-500 text-sm">
    Select a question to see its answer — or ask a new one.
  </div>
{:else if !task}
  <div class="glass-card p-8 text-center text-slate-500 text-sm">Loading…</div>
{:else}
  <div class="glass-card p-4 space-y-3">
    <!-- Header: the question, who's answering, and status -->
    <div class="flex items-start justify-between gap-3">
      <div class="min-w-0">
        <p class="text-sm text-white line-clamp-3">{task.input?.prompt ?? '—'}</p>
        <div class="flex items-center gap-1.5 mt-1.5 text-xs text-slate-500">
          {#if agentId && agentName}
            <AgentAvatar id={agentId} name={agentName} size={18} />
            <span class="text-slate-400">{agentName}</span>
            {#if roleLabel(agentRoleId)}
              <span class="text-slate-600">{roleLabel(agentRoleId)}</span>
            {/if}
            <span>·</span>
          {/if}
          <span class="{taskStatusColour(task.status)} {isRunning ? 'progress-pulse' : ''}">
            {taskStatusLabel(task.status)}
          </span>
        </div>
      </div>
      {#if task.status === 'complete' && resultText}
        <button
          onclick={copyResult}
          class="flex-shrink-0 text-xs px-2 py-0.5 rounded bg-white/5 border border-white/10 text-slate-300 hover:bg-white/10 transition-colors"
        >
          {copied ? 'Copied ✓' : 'Copy'}
        </button>
      {/if}
    </div>

    {#if task.status === 'complete'}
      <!-- One quiet summary line; the numbers live behind "Details". -->
      {#if mDurationMs != null || tps}
        <div class="flex items-center gap-2 text-xs text-slate-500">
          <span>
            Answered{#if mDurationMs != null}&nbsp;in {(mDurationMs / 1000).toFixed(1)}s{/if}{#if tps}&nbsp;· {tps.approx ? '~' : ''}{tps.value} tok/s{/if}
          </span>
          <button
            onclick={() => (showDetails = !showDetails)}
            class="text-slate-600 hover:text-slate-300 transition-colors"
          >
            {showDetails ? 'hide details' : 'details'}
          </button>
        </div>
        {#if showDetails}
          <div class="flex flex-wrap gap-1.5">
            {#if mModel}
              <span class="text-xs font-mono text-slate-300 bg-white/5 border border-white/10 rounded px-2 py-0.5">{mModel}</span>
            {/if}
            {#if mTokens != null}
              <span class="text-xs text-slate-300 bg-white/5 border border-white/10 rounded px-2 py-0.5">{mTokens.toLocaleString()} tokens</span>
            {/if}
            {#if tps}
              <span class="text-xs text-slate-300 bg-white/5 border border-white/10 rounded px-2 py-0.5" title={tps.approx ? 'estimated from tokens ÷ time' : 'reported by the model runtime'}>
                {tps.approx ? '~' : ''}{tps.value} tokens/second{tps.approx ? ' (estimated)' : ''}
              </span>
            {/if}
          </div>
        {/if}
      {/if}

      {#if fetchingResult}
        <div class="text-slate-500 text-sm">Fetching the answer…</div>
      {:else if fetchError}
        <div class="bg-red-500/10 border border-red-500/30 rounded-lg p-3 text-sm">
          <p class="text-red-400">Couldn't load the answer: {fetchError}</p>
          <button onclick={() => task && fetchResult(task.id)} class="mt-2 text-xs px-2 py-1 rounded bg-white/5 border border-white/10 text-slate-300 hover:bg-white/10">Retry</button>
        </div>
      {:else if resultText}
        <div class="message-bubble markdown-body" role="article">
          <!-- eslint-disable-next-line svelte/no-at-html-tags -->
          {@html renderMarkdown(resultText)}
        </div>
      {:else}
        <div class="text-slate-500 text-sm italic">No answer came back.</div>
      {/if}

    {:else if isRunning}
      <!-- The forming answer IS the focal content while running. -->
      {#if streamedText}
        <div bind:this={streamEl} class="message-bubble max-h-[60vh] overflow-y-auto text-sm text-slate-200" style="white-space: pre-wrap; word-break: break-word;">{streamedText}<span class="text-amber-400 progress-pulse">▌</span></div>
      {:else}
        <div class="flex items-center gap-2 text-sm text-amber-400 progress-pulse py-2">
          <span class="w-2 h-2 rounded-full bg-amber-400 inline-block"></span>
          {task.status === 'running' ? 'thinking…' : `waiting for ${agentName ?? 'an agent'}…`}
        </div>
      {/if}

    {:else}
      <!-- Failed / timed out / unreachable: a plain sentence and a way forward. -->
      <div class="bg-red-500/10 border border-red-500/30 rounded-lg p-3 space-y-2">
        {#if task.status === 'failed'}
          <p class="text-sm text-red-300">
            {agentName ?? 'The agent'} couldn't finish this answer.
          </p>
          {#if task.error?.message}<p class="text-xs text-red-400/80">{task.error.message}</p>{/if}
        {:else if task.status === 'timed_out'}
          <p class="text-sm text-orange-300">
            No answer after {task.timeout_s} seconds, so this question was stopped.
          </p>
        {:else}
          <p class="text-sm text-red-300">
            {agentName ?? 'The agent'} kept losing its connection while working on this,
            so the question was given up on. Check that it's online (green dot in the
            sidebar) and that Ollama is running, then try again.
          </p>
        {/if}
        <div class="flex items-center gap-3">
          <button
            onclick={tryAgain}
            disabled={resubmitting}
            class="text-xs px-3 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white font-medium transition-colors"
          >
            {resubmitting ? 'Asking again…' : 'Try again'}
          </button>
          {#if task.error?.code}
            <button
              onclick={() => (showDetails = !showDetails)}
              class="text-xs text-slate-500 hover:text-slate-300 transition-colors"
            >
              {showDetails ? 'hide details' : 'details'}
            </button>
          {/if}
        </div>
        {#if showDetails && task.error?.code}
          <p class="text-xs text-slate-500 font-mono">error code: {task.error.code}</p>
        {/if}
        {#if resubmitError}
          <p class="text-xs text-red-400">Couldn't resubmit: {resubmitError}</p>
        {/if}
      </div>
    {/if}
  </div>
{/if}
