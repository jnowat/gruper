import { fleetStore } from '$lib/stores/fleet.js';
import { tasksStore } from '$lib/stores/tasks.js';
import type { ConsoleMessage } from '$lib/types.js';

const BACKOFF_MS = [2000, 4000, 8000, 16000]; // mirrors Gruper core's retry discipline

export class ConsoleWS {
  private ws: WebSocket | null = null;
  private _retries = 0;
  private _intentionalClose = false;
  private _reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(
    private readonly baseUrl: string,
    private readonly token: string,
  ) {}

  connect(): void {
    this._intentionalClose = false;
    this._open();
  }

  disconnect(): void {
    this._intentionalClose = true;
    if (this._reconnectTimer) clearTimeout(this._reconnectTimer);
    this.ws?.close(1000, 'console logout');
    this.ws = null;
  }

  private _open(): void {
    // Convert http/https base URL to ws/wss for the console WS endpoint.
    const wsBase = this.baseUrl.replace(/^http/, 'ws');
    const url = `${wsBase}/v1/console/ws?token=${encodeURIComponent(this.token)}`;

    try {
      this.ws = new WebSocket(url);
    } catch (err) {
      console.warn('[ConsoleWS] Failed to open WebSocket:', err);
      this._scheduleReconnect();
      return;
    }

    this.ws.onopen = () => {
      console.info('[ConsoleWS] Connected to', this.baseUrl);
      this._retries = 0;
    };

    this.ws.onmessage = (ev) => {
      try {
        this._dispatch(JSON.parse(ev.data as string) as ConsoleMessage);
      } catch {
        console.warn('[ConsoleWS] Unparseable message ignored');
      }
    };

    this.ws.onclose = (ev) => {
      if (!this._intentionalClose) {
        console.warn('[ConsoleWS] Disconnected (code=%d) — scheduling reconnect', ev.code);
        fleetStore.markAllOffline();
        this._scheduleReconnect();
      }
    };

    this.ws.onerror = () => {
      // onclose fires immediately after onerror; log only.
      console.warn('[ConsoleWS] WebSocket error');
    };
  }

  private _dispatch(msg: ConsoleMessage): void {
    switch (msg.type) {
      case 'fleet_snapshot':
        fleetStore.setSnapshot(msg.agents);
        break;
      case 'fleet_event':
        fleetStore.applyEvent(msg);
        break;
      case 'task_progress':
        tasksStore.applyProgress(msg);
        break;
      case 'task_complete':
        tasksStore.applyComplete(msg);
        break;
      case 'queue_depth':
        // Handled locally in AgentAnalytics via the store snapshot for now.
        break;
      default:
        // Forward-compatible: ignore unknown message types silently.
        break;
    }
  }

  private _scheduleReconnect(): void {
    const delay = BACKOFF_MS[Math.min(this._retries, BACKOFF_MS.length - 1)];
    this._retries++;
    console.info('[ConsoleWS] Reconnecting in %dms (attempt %d)', delay, this._retries);
    this._reconnectTimer = setTimeout(() => {
      if (!this._intentionalClose) this._open();
    }, delay);
  }
}
