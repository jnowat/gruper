import { writable } from 'svelte/store';
import type { Task, TaskCompleteEvent, TaskProgressEvent } from '$lib/types.js';

export interface ProgressLine {
  ts: number;
  text: string;
  step?: string | null;
  tokens?: number | null;
}

export interface TasksState {
  tasks: Task[];
  /** Live progress lines per task_id — for the result view streaming display. */
  progress: Record<string, ProgressLine[]>;
}

function createTasksStore() {
  const store = writable<TasksState>({ tasks: [], progress: {} });

  return {
    subscribe: store.subscribe,

    setTasks(tasks: Task[]) {
      store.update((s) => ({ ...s, tasks }));
    },

    prependTask(task: Task) {
      store.update((s) => ({ ...s, tasks: [task, ...s.tasks] }));
    },

    applyProgress(event: TaskProgressEvent) {
      store.update((s) => {
        const line: ProgressLine = {
          ts: event.payload.elapsed_ms,
          text: event.payload.partial_output ?? event.payload.step ?? '',
          step: event.payload.step,
          tokens: event.payload.tokens_so_far,
        };
        const existing = s.progress[event.payload.task_id] ?? [];
        return {
          ...s,
          progress: { ...s.progress, [event.payload.task_id]: [...existing, line] },
        };
      });
    },

    applyComplete(event: TaskCompleteEvent) {
      store.update((s) => {
        const tasks = s.tasks.map((t) =>
          t.id === event.payload.task_id
            ? {
                ...t,
                status: event.payload.final_status,
                completed_at: new Date().toISOString(),
              }
            : t,
        );
        return { ...s, tasks };
      });
    },

    reset() {
      store.set({ tasks: [], progress: {} });
    },

    /**
     * Client-side only — there is no backend DELETE endpoint for tasks, so
     * "clearing" here just drops them from this session's view. A fresh
     * REST reload or WS reconnect would bring persisted tasks back; this is
     * for tidying up a long-running session's list, not real deletion.
     */
    clearFailed() {
      store.update((s) => ({
        ...s,
        tasks: s.tasks.filter((t) => t.status !== 'failed' && t.status !== 'timed_out' && t.status !== 'dead_letter'),
      }));
    },

    clearAll() {
      store.update((s) => ({ ...s, tasks: [] }));
    },
  };
}

export const tasksStore = createTasksStore();
