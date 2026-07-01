// ── Gruper Distributed — shared TypeScript types ──────────────────────────────
// These mirror the JSON Schema definitions in spec/contracts/models/ and the
// OpenAPI types in spec/contracts/openapi.yaml.

export type AgentStatus = 'idle' | 'busy' | 'offline' | 'degraded' | 'draining';
export type TaskStatus =
  | 'pending'
  | 'dispatched'
  | 'running'
  | 'complete'
  | 'failed'
  | 'timed_out'
  | 'dead_letter';
export type DataClass = 'public' | 'internal' | 'confidential';

export interface AgentCapabilities {
  models: string[];
  roles: string[];
  tools: string[];
  hardware: {
    cpu_cores: number;
    ram_gb: number;
    gpu?: string | null;
    disk_gb?: number;
  };
}

export interface AgentRegistrationRequest {
  name: string;
  pubkey: string;
  capabilities: AgentCapabilities;
  runtime_version: string;
}

export interface Agent {
  id: string;
  name: string;
  status: AgentStatus;
  owner_id: string;
  pubkey: string;
  runtime_version: string;
  capabilities: AgentCapabilities;
  last_seen: string | null;
  created_at: string;
}

export interface ModelPreferences {
  name?: string;
  temperature?: number;
  top_p?: number;
  top_k?: number;
  repeat_penalty?: number;
  max_tokens?: number;
  context_length?: number;
  seed?: number;
}

export interface TaskInput {
  prompt: string;
  role_template?: string;
  model_preferences?: ModelPreferences;
  context?: string | null;
}

export interface TaskSubmitRequest {
  assigned_agent_id: string;
  data_class: DataClass;
  input: TaskInput;
  priority?: number;
  timeout_s?: number;
  correlation_id?: string;
}

export interface Task {
  id: string;
  submitter_id: string;
  assigned_agent_id: string;
  data_class: DataClass;
  input: TaskInput;
  status: TaskStatus;
  priority: number;
  timeout_s: number;
  retry_count: number;
  correlation_id: string | null;
  result: { output?: string; model_used?: string; tokens_used?: number; duration_ms?: number } | null;
  error: { code?: string; message?: string } | null;
  created_at: string;
  dispatched_at: string | null;
  completed_at: string | null;
}

export interface AuthTokenResponse {
  token: string;
  expires_at: string;
  user_id: string;
}

// ── Console WebSocket message types (orchestrator → console) ──────────────────

export interface FleetEvent {
  type: 'fleet_event';
  payload: {
    agent_id: string;
    event: string;
    status: AgentStatus;
    name?: string | null;
    location_tag?: string | null;
    running_task_count: number;
    last_seen?: string | null;
  };
}

export interface FleetSnapshot {
  type: 'fleet_snapshot';
  agents: Agent[];
}

export interface TaskProgressEvent {
  type: 'task_progress';
  payload: {
    task_id: string;
    agent_id: string;
    elapsed_ms: number;
    step?: string | null;
    tokens_so_far?: number | null;
    partial_output?: string | null;
  };
}

export interface TaskCompleteEvent {
  type: 'task_complete';
  payload: {
    task_id: string;
    agent_id: string;
    final_status: 'complete' | 'failed' | 'timed_out' | 'dead_letter';
    duration_ms?: number | null;
    model_used?: string | null;
    error_code?: string | null;
    output_preview?: string | null;
  };
}

export interface QueueDepthEvent {
  type: 'queue_depth';
  payload: {
    total_pending: number;
    total_running: number;
    agents: Array<{ agent_id: string; pending: number; running: number }>;
  };
}

export type ConsoleMessage =
  | FleetEvent
  | FleetSnapshot
  | TaskProgressEvent
  | TaskCompleteEvent
  | QueueDepthEvent;
