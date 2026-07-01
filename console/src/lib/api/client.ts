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
      const text = await res.text().catch(() => res.statusText);
      throw new Error(`${res.status} ${text}`);
    }
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
    return this._fetch<Agent>(`/v1/agents/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ name }),
    });
  }

  listTasks(): Promise<Task[]> {
    return this._fetch<Task[]>('/v1/tasks');
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
