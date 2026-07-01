<script lang="ts">
  import { authStore, getOrCreatePubkey } from '$lib/stores/auth.js';
  import { orchestratorStore } from '$lib/stores/orchestrator.js';

  let orchestratorUrl = $state($authStore.orchestratorUrl ?? 'http://localhost:8080');
  // WP-32: no more "run this Python command" — a stable client identity is
  // generated once and reused on every launch (see getOrCreatePubkey).
  let pubkey = $state(getOrCreatePubkey());
  let displayName = $state('');
  let error = $state<string | null>(null);
  let loading = $state(false);
  let showAdvanced = $state(false);
  // Only auto-connect once, and only if the user hasn't already started
  // editing the form by hand — a failed auto-connect attempt shouldn't keep
  // retrying and stomping on something the user is actively typing.
  let autoConnectAttempted = $state(false);
  let userEdited = $state(false);

  const sidecar = $derived($orchestratorStore);

  $effect(() => {
    if (sidecar.status !== 'ready' && sidecar.status !== 'existing') return;
    if (userEdited || autoConnectAttempted) return;
    autoConnectAttempted = true;
    orchestratorUrl = sidecar.url ?? orchestratorUrl;
    handleConnect();
  });

  async function handleConnect() {
    error = null;
    loading = true;
    try {
      await authStore.login(orchestratorUrl, pubkey.trim(), displayName.trim() || undefined);
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    } finally {
      loading = false;
    }
  }
</script>

<div class="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50">
  <div class="glass-card p-8 w-full max-w-md mx-4 space-y-6">
    <div>
      <h1 class="text-xl font-semibold text-white">Gruper Console</h1>
      <p class="text-sm text-slate-400 mt-1">Connect to an orchestrator to manage your agent fleet.</p>
    </div>

    {#if sidecar.status === 'checking'}
      <div class="bg-blue-500/10 border border-blue-500/30 text-blue-300 text-sm rounded-lg p-3">
        Starting local orchestrator…
      </div>
    {:else if sidecar.status === 'ready' || sidecar.status === 'existing'}
      <div class="bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 text-sm rounded-lg p-3">
        Local orchestrator {sidecar.status === 'ready' ? 'started' : 'found'} at {sidecar.url} — connecting…
      </div>
    {:else if sidecar.status === 'failed'}
      <div class="bg-amber-500/10 border border-amber-500/30 text-amber-300 text-sm rounded-lg p-3">
        Couldn't start the local orchestrator{sidecar.error ? `: ${sidecar.error}` : '.'} You can still connect to
        a remote or manually-started orchestrator below.
      </div>
    {/if}

    <form class="space-y-4" onsubmit={(e) => { e.preventDefault(); handleConnect(); }}>
      <div>
        <label class="block text-xs text-slate-400 mb-1" for="orch-url">Orchestrator URL</label>
        <input
          id="orch-url"
          type="url"
          bind:value={orchestratorUrl}
          oninput={() => { userEdited = true; }}
          placeholder="http://localhost:8080"
          class="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white placeholder:text-slate-500 focus:outline-none focus:border-blue-500"
          required
        />
      </div>

      <div>
        <label class="block text-xs text-slate-400 mb-1" for="display-name">Display Name (optional)</label>
        <input
          id="display-name"
          type="text"
          bind:value={displayName}
          oninput={() => { userEdited = true; }}
          placeholder="e.g. Alice"
          class="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white placeholder:text-slate-500 focus:outline-none focus:border-blue-500"
        />
      </div>

      <div>
        <button
          type="button"
          onclick={() => { showAdvanced = !showAdvanced; }}
          class="text-xs text-slate-500 hover:text-slate-300 transition-colors"
        >
          {showAdvanced ? '▾' : '▸'} Advanced: client identity
        </button>
        {#if showAdvanced}
          <div class="mt-2">
            <label class="block text-xs text-slate-400 mb-1" for="pubkey">Public Key (base64url)</label>
            <input
              id="pubkey"
              type="text"
              bind:value={pubkey}
              oninput={() => { userEdited = true; }}
              class="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white placeholder:text-slate-500 focus:outline-none focus:border-blue-500 font-mono"
              required
              minlength={43}
              maxlength={88}
            />
            <p class="text-xs text-slate-500 mt-1">
              Auto-generated on first launch and reused every time so you always connect as the same
              identity. Only edit this if you're deliberately reusing an identity from another install.
            </p>
          </div>
        {/if}
      </div>

      {#if error}
        <div class="bg-red-500/10 border border-red-500/30 text-red-400 text-sm rounded-lg p-3">
          {error}
        </div>
      {/if}

      <button
        type="submit"
        disabled={loading}
        class="w-full bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white rounded-lg px-4 py-2 text-sm font-medium transition-colors"
      >
        {loading ? 'Connecting…' : 'Connect'}
      </button>
    </form>

    <p class="text-xs text-slate-500 text-center">
      Gruper Console — gd-0.2 walking skeleton · pre-v1
    </p>
  </div>
</div>
