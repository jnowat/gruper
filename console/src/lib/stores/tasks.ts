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
  };
}

export const tasksStore = createTasksStore();
