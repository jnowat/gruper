<script lang="ts">
  import '../app.css';
  import { onMount } from 'svelte';
  import { logStore, installConsoleBridge } from '$lib/stores/logs.js';

  let { children } = $props();

  // Start the unified debug log as early as possible: backfill the Rust ring
  // buffer, attach the live 'log-entry' stream, and route console.* into the
  // same buffer. Runs once for the whole app (client-only — ssr is disabled).
  onMount(() => {
    installConsoleBridge();
    logStore.start();
  });
</script>

{@render children()}
