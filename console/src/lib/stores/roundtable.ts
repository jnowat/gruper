// Round Table state + orchestration, OUTSIDE the component. Two reasons:
//
//  1. The transcript used to live in RoundTable.svelte's local $state, so
//     clicking any other tab unmounted the component and silently destroyed
//     the whole conversation (with the in-flight loop still writing into a
//     dead component). Here it survives tab switches for the session.
//  2. The discussion reads as a chat, not a batch job: the user opens with a
//     message, every participating agent responds in turn (streaming), and the
//     user can interject at any point — each interjection becomes a turn the
//     agents then react to.
//
// Each agent turn is still an ordinary orchestrator task under the hood,
// tagged with input.context.source = 'round_table' so the History list can
// tell these machine-built turns apart from questions the user typed.

import { get, writable } from 'svelte/store';
import { authStore } from '$lib/stores/auth.js';
import { fleetStore } from '$lib/stores/fleet.js';
import { tasksStore } from '$lib/stores/tasks.js';
import { logStore } from '$lib/stores/logs.js';
import { OrchestratorClient } from '$lib/api/client.js';
import { agentModel, agentRole } from '$lib/agentDisplay.js';
import { roleInfo, rolePersona } from '$lib/roles.js';
import type { Agent } from '$lib/types.js';

export interface DiscussionTurn {
  kind: 'user' | 'agent';
  agentId: string | null;
  name: string;
  /** Role id (agent turns only). */
  role: string | null;
  model: string | null;
  text: string;
  status: 'thinking' | 'streaming' | 'done' | 'failed';
}

export interface RoundTableState {
  transcript: DiscussionTurn[];
  /** Selected participant agent ids. */
  participants: Set<string>;
  /** Whether participants were auto-seeded once from the online fleet. */
  seeded: boolean;
  running: boolean;
  error: string | null;
}

const TERMINAL = ['complete', 'failed', 'timed_out', 'dead_letter'];
// A turn's task is submitted with timeout_s = TURN_TIMEOUT_S; the client-side
// deadline is deliberately LONGER, so the orchestrator's own timeout (which is
// authoritative and reaches a terminal status) always wins — a slow local
// model never has its still-running answer abandoned by the UI.
const TURN_TIMEOUT_S = 300;
const TURN_DEADLINE_MS = (TURN_TIMEOUT_S + 60) * 1000;
// A turn that is still 'pending' after this long was never picked up at all
// (dispatch is synchronous when the agent is connected) — the agent looked
// online but isn't taking work. Fail the turn fast and move on instead of
// stalling the whole table for minutes; the abandoned task is cancelled so it
// doesn't linger as a zombie either.
const PENDING_GRACE_MS = 12_000;
// Poll briskly at first (fail-fast needs it), then back off — a fixed 800 ms
// forever floods the debug log with GET /v1/tasks lines during long answers.
const POLL_FAST_MS = 800;
const POLL_SLOW_MS = 2_500;
const POLL_SLOWDOWN_AFTER_MS = 15_000;

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

function createRoundTableStore() {
  const store = writable<RoundTableState>({
    transcript: [],
    participants: new Set(),
    seeded: false,
    running: false,
    error: null,
  });

  // Set by stop(); checked between turns and on every poll so a running
  // discussion can always be cut short. The underlying task keeps running
  // server-side (there is no abort channel until WP-08) — only the UI stops
  // waiting for it.
  let stopRequested = false;

  function patchTurn(idx: number, patch: Partial<DiscussionTurn>) {
    store.update((s) => {
      const transcript = [...s.transcript];
      transcript[idx] = { ...transcript[idx], ...patch };
      return { ...s, transcript };
    });
  }

  /** A failed turn says WHY — "couldn't respond" hid three very different
      problems (never dispatched / model error / too slow) behind one string. */
  function turnFailureText(
    name: string,
    status: string,
    error: { code?: string; message?: string } | null,
  ): string {
    if (status === 'timed_out') return `${name} ran out of time before finishing.`;
    if (status === 'dead_letter') return `${name} kept losing its connection, so its turn was skipped.`;
    if (error?.code === 'ollama_error') {
      return `${name} couldn't reach its model (Ollama) — is Ollama still running?`;
    }
    if (error?.code === 'agent_removed') return `${name} was removed mid-discussion.`;
    return `${name} hit a problem${error?.message ? `: ${error.message}` : ' and couldn’t respond.'}`;
  }

  function buildSystemPrompt(a: Agent): string {
    const persona = rolePersona(agentRole(a)) ?? 'You are a thoughtful assistant.';
    return (
      `${persona}\n\n` +
      `You are taking part in a live round-table discussion with a human and other AI assistants. ` +
      `Speak as "${a.name}". Keep each contribution short and conversational — a few sentences. ` +
      `Build on the discussion; don't repeat what others already said.`
    );
  }

  function buildPrompt(a: Agent, transcript: DiscussionTurn[]): string {
    const lines: string[] = ['The discussion so far:', ''];
    for (const t of transcript) {
      if (t.kind === 'user') {
        lines.push(`The human: ${t.text}`);
      } else if (t.status === 'done') {
        const label = roleInfo(t.role)?.label ?? t.role ?? '';
        lines.push(`${t.name}${label ? ` (${label})` : ''}: ${t.text}`);
      }
    }
    lines.push('', `It's your turn, ${a.name}. Add your perspective.`);
    return lines.join('\n');
  }

  async function runTurn(client: OrchestratorClient, a: Agent, idx: number): Promise<void> {
    try {
      const task = await client.submitTask({
        assigned_agent_id: a.id,
        data_class: 'internal',
        input: {
          prompt: buildPrompt(a, get(store).transcript),
          role_template: agentRole(a) ?? 'analyst',
          system_prompt: buildSystemPrompt(a),
          context: { source: 'round_table' },
        },
        timeout_s: TURN_TIMEOUT_S,
      });
      const taskId = task.id;
      try {
        const started = Date.now();
        const deadline = started + TURN_DEADLINE_MS;
        while (Date.now() < deadline) {
          if (stopRequested) {
            const partial = get(store).transcript[idx].text;
            patchTurn(idx, {
              text: partial ? `${partial} …` : `${a.name} was stopped before answering.`,
              status: partial ? 'done' : 'failed',
            });
            return;
          }
          // Live streaming: the console WS routes this task's progress into
          // tasksStore.progress (keyed by task id), so concatenate it as it grows.
          const prog = get(tasksStore).progress[taskId];
          if (prog?.length) {
            patchTurn(idx, { text: prog.map((l) => l.text).join(''), status: 'streaming' });
          }
          // Authoritative terminal check + full result.
          const t = await client.getTask(taskId);
          if (TERMINAL.includes(t.status)) {
            if (t.status === 'complete') {
              const out = (t.result?.output as string) ?? get(store).transcript[idx].text ?? '';
              patchTurn(idx, {
                text: out || '(no reply)',
                model: (t.result?.model_used as string) ?? get(store).transcript[idx].model,
                status: 'done',
              });
            } else {
              logStore.frontend('warn', 'ui', `round table turn ${t.status}: ${t.error?.message ?? ''}`, {
                task_id: taskId,
                agent_id: a.id,
              });
              patchTurn(idx, { text: turnFailureText(a.name, t.status, t.error), status: 'failed' });
            }
            return;
          }
          // Fail fast on a turn that was never even picked up.
          if (t.status === 'pending' && Date.now() - started > PENDING_GRACE_MS) {
            logStore.frontend('warn', 'ui', 'round table turn never dispatched — cancelling', {
              task_id: taskId,
              agent_id: a.id,
            });
            try {
              await client.deleteTask(taskId);
            } catch {
              // best-effort cleanup; the turn fails either way
            }
            patchTurn(idx, {
              text: `${a.name} isn't picking up work — it may have stopped running. Check its dot in the sidebar.`,
              status: 'failed',
            });
            return;
          }
          await sleep(Date.now() - started > POLL_SLOWDOWN_AFTER_MS ? POLL_SLOW_MS : POLL_FAST_MS);
        }
        logStore.frontend('warn', 'ui', 'round table turn timed out waiting for a response', {
          agent_id: a.id,
        });
        patchTurn(idx, { text: `${a.name} ran out of time before finishing.`, status: 'failed' });
      } finally {
        // The streamed chunks live in tasksStore.progress; once the turn is
        // settled the transcript holds the text, so free the buffer — a long
        // multi-agent session would otherwise grow it without bound.
        tasksStore.clearProgress(taskId);
      }
    } catch (err) {
      logStore.frontend('warn', 'ui', `round table turn error: ${err instanceof Error ? err.message : String(err)}`, {
        agent_id: a.id,
      });
      patchTurn(idx, { text: `${a.name} couldn't respond this time.`, status: 'failed' });
    }
  }

  /**
   * Every selected, ONLINE participant answers once, in order. Offline agents
   * are skipped even if their id is still in the participant set — the UI
   * shows them as away from the table, so they must not get turns (a queued
   * turn would stall the round for minutes and answer into the void).
   */
  async function runAgents(agents: Agent[]): Promise<void> {
    const auth = get(authStore);
    if (!auth.token) {
      store.update((st) => ({ ...st, error: 'Not connected.' }));
      return;
    }
    const client = new OrchestratorClient(auth.orchestratorUrl, auth.token);

    // Pre-flight: re-fetch the fleet over REST before seating anyone. The
    // authoritative statuses catch agents that look "ready" from a stale
    // snapshot but are actually gone — the exact state that used to send a
    // whole round of turns into the void.
    let roster = agents;
    try {
      roster = await client.listAgents();
      fleetStore.setSnapshot(roster);
    } catch {
      // Offline check still runs against the passed-in list.
    }

    const s = get(store);
    const participants = roster.filter((a) => s.participants.has(a.id) && a.status !== 'offline');
    if (participants.length === 0) {
      store.update((st) => ({
        ...st,
        error: 'No one at the table is reachable right now — check the status dots in the sidebar.',
      }));
      return;
    }

    stopRequested = false;
    store.update((st) => ({ ...st, running: true, error: null }));
    try {
      for (const a of participants) {
        if (stopRequested) break;
        let idx = -1;
        store.update((st) => {
          idx = st.transcript.length;
          return {
            ...st,
            transcript: [
              ...st.transcript,
              {
                kind: 'agent' as const,
                agentId: a.id,
                name: a.name,
                role: agentRole(a),
                model: agentModel(a),
                text: '',
                status: 'thinking' as const,
              },
            ],
          };
        });
        await runTurn(client, a, idx);
      }
    } finally {
      store.update((st) => ({ ...st, running: false }));
    }
  }

  return {
    subscribe: store.subscribe,

    /** Default the participant set to all online agents, once. */
    seedParticipants(agents: Agent[]) {
      // Checked outside store.update: a no-op update still notifies every
      // subscriber, and this is called from an $effect on every fleet change —
      // spurious notifications would re-trigger transcript auto-scroll.
      const s = get(store);
      if (s.seeded || agents.length === 0) return;
      store.update((st) => ({
        ...st,
        seeded: true,
        participants: new Set(agents.filter((a) => a.status !== 'offline').map((a) => a.id)),
      }));
    },

    toggleParticipant(id: string) {
      store.update((s) => {
        const participants = new Set(s.participants);
        if (participants.has(id)) participants.delete(id);
        else participants.add(id);
        return { ...s, participants };
      });
    },

    /**
     * The user says something (the opening topic, or an interjection); every
     * selected agent then responds in turn, streaming. Sending WHILE agents
     * are talking is allowed: the message joins the transcript immediately,
     * and every agent whose turn hasn't started yet sees it (buildPrompt reads
     * the live transcript at the start of each turn).
     */
    async send(message: string, agents: Agent[]): Promise<void> {
      const text = message.trim();
      if (!text) return;
      const wasRunning = get(store).running;
      store.update((s) => ({
        ...s,
        transcript: [
          ...s.transcript,
          { kind: 'user', agentId: null, name: 'You', role: null, model: null, text, status: 'done' },
        ],
      }));
      logStore.frontend('info', 'ui', `round table: user message, ${get(store).participants.size} participant(s)`);
      if (!wasRunning) await runAgents(agents);
    },

    /** The agents keep going without a new user message. */
    async continueDiscussion(agents: Agent[]): Promise<void> {
      if (get(store).running || get(store).transcript.length === 0) return;
      logStore.frontend('info', 'ui', 'round table: continue discussion');
      await runAgents(agents);
    },

    /** Cut a running discussion short (takes effect within one poll tick). */
    stop() {
      if (!get(store).running) return;
      stopRequested = true;
      logStore.frontend('info', 'ui', 'round table: stopped by user');
    },

    reset() {
      if (get(store).running) return; // never yank the transcript out from under a live turn
      store.update((s) => ({
        ...s,
        transcript: [],
        running: false,
        error: null,
      }));
    },
  };
}

export const roundTableStore = createRoundTableStore();
