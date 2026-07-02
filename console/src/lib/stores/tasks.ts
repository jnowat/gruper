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
        const { final_status, duration_ms, model_used, error_code } = event.payload;
        const tasks = s.tasks.map((t) => {
          if (t.id !== event.payload.task_id) return t;
          // Fold the completion metrics into the task so the UI can show
          // "answered in 12s" immediately, without waiting for the full
          // result re-fetch (which is still needed for the output text).
          const result =
            duration_ms != null || model_used
              ? {
                  ...t.result,
                  ...(duration_ms != null ? { duration_ms } : {}),
                  ...(model_used ? { model_used } : {}),
                }
              : t.result;
          const error = error_code ? { ...t.error, code: error_code } : t.error;
          return {
            ...t,
            status: final_status,
            completed_at: new Date().toISOString(),
            result,
            error,
          };
        });
        return { ...s, tasks };
      });
    },

    /**
     * Drop the streamed-chunk buffer for one task (the Round Table calls this
     * once a turn settles — the transcript keeps the text, so holding every
     * chunk of every past turn would just grow memory for the session).
     */
    clearProgress(taskId: string) {
      store.update((s) => {
        if (!(taskId in s.progress)) return s;
        const progress = { ...s.progress };
        delete progress[taskId];
        return { ...s, progress };
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
