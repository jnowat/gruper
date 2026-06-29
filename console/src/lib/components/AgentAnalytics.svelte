<!--
  AgentAnalytics — per-agent Chart.js analytics panel.
  Uses the same visual language as Gruper core: response-time line chart,
  tooltip format, and CSV/JSON export conventions.
  Chart.js v4.x (same version as Gruper core, pinned in package.json).
-->
<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { tasksStore } from '$lib/stores/tasks.js';
  import type { Agent } from '$lib/types.js';
  import type { Chart as ChartType } from 'chart.js';

  let { agent }: { agent: Agent | null } = $props();

  let canvasEl = $state<HTMLCanvasElement | undefined>(undefined);
  let chart: ChartType | null = null;

  interface DataPoint { label: string; duration: number; status: string }

  const agentTasks = $derived.by(() => {
    if (!agent) return [] as DataPoint[];
    return $tasksStore.tasks
      .filter((t) => t.assigned_agent_id === agent.id && t.status === 'complete' && t.result?.duration_ms)
      .slice(-30) // last 30 completed tasks, matching Gruper core's analytics window
      .map((t) => ({
        label: new Date(t.completed_at ?? t.created_at).toLocaleTimeString(),
        duration: (t.result!.duration_ms as number) / 1000,
        status: t.status,
      }));
  });

  // Stats derived from tasks, matching Gruper core's analytics dashboard metrics
  const stats = $derived.by(() => {
    const durations = agentTasks.map((d) => d.duration);
    if (!durations.length) return { avg: 0, min: 0, max: 0, count: 0 };
    return {
      avg: durations.reduce((a, b) => a + b, 0) / durations.length,
      min: Math.min(...durations),
      max: Math.max(...durations),
      count: durations.length,
    };
  });

  async function buildChart() {
    if (!canvasEl) return;
    const { Chart, LineController, LineElement, PointElement, LinearScale,
            CategoryScale, Tooltip, Legend } = await import('chart.js');
    Chart.register(LineController, LineElement, PointElement, LinearScale,
                   CategoryScale, Tooltip, Legend);

    chart?.destroy();
    chart = new Chart(canvasEl, {
      type: 'line',
      data: {
        labels: agentTasks.map((d) => d.label),
        datasets: [{
          label: 'Response time (s)',
          data: agentTasks.map((d) => d.duration),
          borderColor: '#3b82f6',
          backgroundColor: 'rgba(59,130,246,0.1)',
          borderWidth: 1.5,
          pointRadius: 3,
          pointHoverRadius: 5,
          tension: 0.3,
          fill: true,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 200 },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: 'rgba(15,23,42,0.9)',
            titleColor: '#94a3b8',
            bodyColor: '#e2e8f0',
            borderColor: 'rgba(255,255,255,0.1)',
            borderWidth: 1,
            padding: 8,
            callbacks: {
              label: (ctx) => ` ${(ctx.parsed.y as number).toFixed(2)}s`,
            },
          },
        },
        scales: {
          x: { ticks: { color: '#64748b', maxTicksLimit: 8 }, grid: { color: 'rgba(255,255,255,0.05)' } },
          y: { ticks: { color: '#64748b' }, grid: { color: 'rgba(255,255,255,0.05)' },
               beginAtZero: true, title: { display: true, text: 'seconds', color: '#64748b', font: { size: 10 } } },
        },
      },
    });
  }

  $effect(() => {
    void agentTasks; // reactivity trigger
    if (canvasEl) void buildChart();
  });

  onMount(() => { if (canvasEl) void buildChart(); });
  onDestroy(() => chart?.destroy());

  function exportJSON() {
    if (!agentTasks.length) return;
    const blob = new Blob([JSON.stringify(agentTasks, null, 2)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `${agent?.name ?? 'agent'}-analytics.json`;
    a.click();
  }

  function exportCSV() {
    if (!agentTasks.length) return;
    const rows = ['time,duration_s,status', ...agentTasks.map((d) => `${d.label},${d.duration},${d.status}`)];
    const blob = new Blob([rows.join('\n')], { type: 'text/csv' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `${agent?.name ?? 'agent'}-analytics.csv`;
    a.click();
  }
</script>

<div class="glass-card p-4 space-y-4 h-full flex flex-col">
  <div class="flex items-center justify-between">
    <h2 class="text-sm font-semibold text-white">
      Analytics
      {#if agent}<span class="text-slate-400 font-normal">— {agent.name}</span>{/if}
    </h2>
    {#if agentTasks.length}
      <div class="flex gap-2">
        <button onclick={exportJSON}
          class="text-xs text-slate-400 hover:text-white transition-colors">JSON</button>
        <button onclick={exportCSV}
          class="text-xs text-slate-400 hover:text-white transition-colors">CSV</button>
      </div>
    {/if}
  </div>

  <!-- Summary stats — same metrics as Gruper core's analytics dashboard -->
  <div class="grid grid-cols-4 gap-2 text-center">
    {#each [
      { label: 'Tasks', value: stats.count },
      { label: 'Avg (s)', value: stats.avg.toFixed(1) },
      { label: 'Min (s)', value: stats.min.toFixed(1) },
      { label: 'Max (s)', value: stats.max.toFixed(1) },
    ] as stat}
      <div class="bg-white/5 rounded-lg p-2">
        <p class="text-lg font-semibold text-white">{stat.value}</p>
        <p class="text-xs text-slate-500">{stat.label}</p>
      </div>
    {/each}
  </div>

  <!-- Response-time line chart -->
  <div class="flex-1 min-h-0 relative">
    {#if agentTasks.length}
      <canvas bind:this={canvasEl} class="w-full h-full"></canvas>
    {:else}
      <div class="flex items-center justify-center h-full text-slate-500 text-sm">
        No completed tasks yet for this agent.
      </div>
    {/if}
  </div>
</div>
