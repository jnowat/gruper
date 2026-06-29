<script lang="ts">
  import { authStore } from '$lib/stores/auth.js';

  let orchestratorUrl = $state($authStore.orchestratorUrl ?? 'http://localhost:8080');
  let pubkey = $state('');
  let displayName = $state('');
  let error = $state<string | null>(null);
  let loading = $state(false);

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

    <form class="space-y-4" onsubmit={(e) => { e.preventDefault(); handleConnect(); }}>
      <div>
        <label class="block text-xs text-slate-400 mb-1" for="orch-url">Orchestrator URL</label>
        <input
          id="orch-url"
          type="url"
          bind:value={orchestratorUrl}
          placeholder="http://localhost:8080"
          class="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white placeholder:text-slate-500 focus:outline-none focus:border-blue-500"
          required
        />
      </div>

      <div>
        <label class="block text-xs text-slate-400 mb-1" for="pubkey">Public Key (base64url)</label>
        <input
          id="pubkey"
          type="text"
          bind:value={pubkey}
          placeholder="43-88 character base64url string"
          class="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white placeholder:text-slate-500 focus:outline-none focus:border-blue-500 font-mono"
          required
          minlength={43}
          maxlength={88}
        />
        <p class="text-xs text-slate-500 mt-1">
          Generate: <code class="text-blue-400">python3 -c "import secrets,base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b'=').decode())"</code>
        </p>
      </div>

      <div>
        <label class="block text-xs text-slate-400 mb-1" for="display-name">Display Name (optional)</label>
        <input
          id="display-name"
          type="text"
          bind:value={displayName}
          placeholder="e.g. Alice"
          class="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white placeholder:text-slate-500 focus:outline-none focus:border-blue-500"
        />
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
