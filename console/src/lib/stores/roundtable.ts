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
const POLL_MS = 800;

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
        const deadline = Date.now() + TURN_DEADLINE_MS;
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
              logStore.frontend('warn', 'ui', `round table turn ${t.status}`, {
                task_id: taskId,
                agent_id: a.id,
              });
              patchTurn(idx, { text: `${a.name} couldn't respond this time.`, status: 'failed' });
            }
            return;
          }
          await sleep(POLL_MS);
        }
        logStore.frontend('warn', 'ui', 'round table turn timed out waiting for a response', {
          agent_id: a.id,
        });
        patchTurn(idx, { text: `${a.name} couldn't respond this time.`, status: 'failed' });
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
    const s = get(store);
    const participants = agents.filter((a) => s.participants.has(a.id) && a.status !== 'offline');
    if (participants.length === 0) return;

    const auth = get(authStore);
    if (!auth.token) {
      store.update((st) => ({ ...st, error: 'Not connected.' }));
      return;
    }
    stopRequested = false;
    store.update((st) => ({ ...st, running: true, error: null }));
    const client = new OrchestratorClient(auth.orchestratorUrl, auth.token);
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
