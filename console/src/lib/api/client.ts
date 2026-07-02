import type { Agent, AgentRegistrationRequest, Task, TaskSubmitRequest } from '$lib/types.js';

/**
 * Thin REST client for the Gruper Orchestrator API.
 * All calls are authenticated via Bearer JWT stored in the auth store.
 * Only the endpoints used by WP-05 are implemented here; share-token and
 * metrics endpoints are added in later work packets.
 */
export class OrchestratorClient {
  constructor(
    private readonly baseUrl: string,
    private readonly token: string,
  ) {}

  private async _fetch<T>(path: string, init: RequestInit = {}): Promise<T> {
    const res = await fetch(`${this.baseUrl}${path}`, {
      ...init,
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${this.token}`,
        ...(init.headers ?? {}),
      },
    });
    if (!res.ok) {
      // Error messages from here surface directly in the UI, so extract the
      // human-readable detail instead of dumping "422 {json…}" at the user.
      const text = await res.text().catch(() => '');
      let message = '';
      try {
        const body = JSON.parse(text) as { detail?: unknown };
        if (typeof body.detail === 'string') {
          message = body.detail;
        } else if (Array.isArray(body.detail)) {
          const first = body.detail[0] as { msg?: string } | undefined;
          message = first?.msg ?? '';
        }
      } catch {
        message = text;
      }
      throw new Error(message || res.statusText || `Request failed (${res.status})`);
    }
    if (res.status === 204) return undefined as T;
    return res.json() as Promise<T>;
  }

  getHealth(): Promise<{ status: string; version: string; db: string }> {
    return this._fetch('/v1/health');
  }

  listAgents(): Promise<Agent[]> {
    return this._fetch<Agent[]>('/v1/agents');
  }

  registerAgent(body: AgentRegistrationRequest): Promise<Agent> {
    return this._fetch<Agent>('/v1/agents', {
      method: 'POST',
      body: JSON.stringify(body),
    });
  }

  renameAgent(id: string, name: string): Promise<Agent> {
    return this.updateAgent(id, { name });
  }

  /** Update an agent's display name and/or specialty (owner only). */
  updateAgent(id: string, body: { name?: string; role?: string }): Promise<Agent> {
    return this._fetch<Agent>(`/v1/agents/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    });
  }

  /**
   * Remove an agent for real (server-side soft delete): it vanishes from
   * every listing, its queued/in-flight work is failed, a live connection is
   * kicked, and its runtime process exits when its re-register is rejected.
   */
  deleteAgent(id: string): Promise<void> {
    return this._fetch<void>(`/v1/agents/${id}`, { method: 'DELETE' });
  }

  listTasks(): Promise<Task[]> {
    return this._fetch<Task[]>('/v1/tasks');
  }

  /** Delete one task; for a pending task this is a full cancel. */
  deleteTask(id: string): Promise<void> {
    return this._fetch<void>(`/v1/tasks/${id}`, { method: 'DELETE' });
  }

  /**
   * Bulk-delete tasks server-side. 'failed' = failed/timed-out/unreachable;
   * 'all' = everything not actively being worked on.
   */
  deleteTasks(scope: 'failed' | 'all'): Promise<{ deleted: number }> {
    return this._fetch<{ deleted: number }>(`/v1/tasks?scope=${scope}`, { method: 'DELETE' });
  }

  getTask(id: string): Promise<Task> {
    return this._fetch<Task>(`/v1/tasks/${id}`);
  }

  submitTask(body: TaskSubmitRequest): Promise<Task> {
    return this._fetch<Task>('/v1/tasks', {
      method: 'POST',
      body: JSON.stringify(body),
    });
  }
}
