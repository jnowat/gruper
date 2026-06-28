# Gruper Core v0.4.5 → Distributed Task Input Schema Mapping

**Milestone:** `gd-0.1` — Wire Contracts & Schema Freeze

This document is the formal bridge between Gruper core's per-agent configuration
model and the distributed task input schema. It ensures that the same Ollama
parameters, role templates, and conversation conventions that work in `Gruper.html`
are preserved — without change — when tasks are executed remotely by the distributed
agent runtime.

---

## 1. Ollama API Call Shape

Gruper core calls `/api/chat` on the local Ollama endpoint. The exact request body:

```json
{
  "model": "<model-tag>",
  "messages": [
    { "role": "system", "content": "<system prompt from role template>" },
    { "role": "user",   "content": "<task prompt + memory context>" }
  ],
  "stream": false,
  "options": {
    "temperature":    0.7,
    "top_p":          0.9,
    "top_k":          40,
    "repeat_penalty": 1.1,
    "num_predict":    2048,
    "num_ctx":        4096,
    "seed":           null,
    "stop":           []
  }
}
```

> **Note on `num_ctx`:** Gruper core has `num_ctx` commented out in the API call
> (`// num_ctx: options.contextLength ?? 4096`) but stores `contextLength` in agent
> config and exposes it in the UI. The distributed runtime **does** pass `num_ctx`
> explicitly, using the value from `model_preferences.context_length`.

The distributed agent runtime replicates this call verbatim against the remote
agent's local Ollama. No new Ollama parameters are introduced at `gd-0.1`.

---

## 2. Per-Agent Config Parameter Mapping

### 2.1 Inference Parameters

| Gruper Core JS Field | Core UI Label | Ollama API Field | Distributed Schema Field | Range | Core Default |
|---------------------|--------------|-----------------|-------------------------|-------|-------------|
| `temperature` | Temperature | `temperature` | `model_preferences.temperature` | 0–1 | 0.7 |
| `topP` | Top-P | `top_p` | `model_preferences.top_p` | 0–1 | 0.9 |
| `topK` | Top-K | `top_k` | `model_preferences.top_k` | 1–100 | 40 |
| `repeatPenalty` | Repeat Penalty | `repeat_penalty` | `model_preferences.repeat_penalty` | 0.5–2 | 1.1 |
| `maxTokens` | Max Tokens | `num_predict` | `model_preferences.max_tokens` | 128–8192 | 2048 |
| `contextLength` | Context Length | `num_ctx` | `model_preferences.context_length` | 512–131072 | 4096 |
| `seed` | Seed | `seed` | `model_preferences.seed` | integer \| null | null |
| `stopSequences` | Stop Sequences | `stop` | `model_preferences.stop_sequences` | string[] | [] |

**Mapping rule:** The agent runtime reads `model_preferences` from the task input
and constructs the Ollama `options` object using the field mapping above. Fields
absent from `model_preferences` fall back to the agent's local defaults (configured
at registration time via capability metadata).

### 2.2 Model Selection

| Gruper Core JS Field | Ollama API Field | Distributed Schema Field | Notes |
|---------------------|-----------------|-------------------------|-------|
| `model` (string) | `model` (top-level) | `model_preferences.name` | Preferred model tag. Agent uses closest match from its `capabilities.models` list if exact tag unavailable. |

**Fallback behavior:** If the requested model is not available on the target agent,
the runtime uses the highest-ranked model in `capabilities.models` that satisfies
the task's minimum parameter requirements. This is logged as an audit event.

### 2.3 Role Templates

Gruper core defines 12 role templates. Each template sets default inference
parameters and a system prompt. The distributed schema extends this with a
`role_template` enum on the task input.

| Gruper Core Template ID | Distributed `role_template` Value | Core Default Parameters |
|------------------------|----------------------------------|------------------------|
| `analyst` | `analyst` | temp=0.3, top_p=0.9, top_k=40, repeat=1.1 |
| `creative` | `creative` | temp=0.9, top_p=0.95, top_k=50, repeat=1.0 |
| `critic` | `critic` | temp=0.4, top_p=0.85, top_k=40, repeat=1.2 |
| `synthesizer` | `synthesizer` | temp=0.6, top_p=0.9, top_k=45, repeat=1.1 |
| `expert` | `expert` | temp=0.2, top_p=0.85, top_k=35, repeat=1.1 |
| `devil_advocate` | `devil_advocate` | temp=0.7, top_p=0.9, top_k=45, repeat=1.0 |
| `philosopher` | `philosopher` | temp=0.8, top_p=0.9, top_k=50, repeat=1.05 |
| `economist` | `economist` | temp=0.3, top_p=0.85, top_k=30, repeat=1.1 |
| `ethicist` | `ethicist` | temp=0.6, top_p=0.9, top_k=40, repeat=1.0 |
| `scientist` | `scientist` | temp=0.4, top_p=0.85, top_k=40, repeat=1.1 |
| `psychologist` | `psychologist` | temp=0.7, top_p=0.9, top_k=45, repeat=1.05 |
| `engineer` | `engineer` | temp=0.5, top_p=0.9, top_k=40, repeat=1.1 |
| (none) | `custom` | Caller supplies full `model_preferences`; no defaults applied |

**Precedence:** `model_preferences` fields in the task input override the role
template defaults. A submitter can set `role_template: "analyst"` to get the
analyst system prompt while overriding just `temperature: 0.5`.

---

## 3. Message Construction

Gruper core builds the `messages` array from memory context and the current task
prompt. The distributed runtime follows the same construction:

```
messages = [
  { role: "system",    content: <system prompt from role_template or task.input.system_prompt> },
  { role: "user",      content: <memory context (if any)> },   // optional
  { role: "assistant", content: <prior round response> },       // optional, repeats
  { role: "user",      content: task.input.prompt }
]
```

For single-shot tasks (no memory context), the array is simply:
```
[
  { role: "system", content: <system prompt> },
  { role: "user",   content: task.input.prompt }
]
```

The `context` field in `TaskInput` carries structured input data (files, prior
results, research inputs) that the runtime serializes and appends to the user
message before dispatch.

---

## 4. Circuit-Breaker Continuity

Gruper core's circuit-breaker pattern:
- **Threshold:** 3 consecutive API failures → agent auto-disables
- **Retry delays:** `[2000, 4000, 8000, 16000]` ms (2 s / 4 s / 8 s / 16 s)
- **Recovery:** manual reset via UI

The distributed agent runtime mirrors this for its Ollama connection:
- 3 consecutive Ollama failures → agent marks itself `degraded`, sends `status: "degraded"` in the next heartbeat
- Orchestrator stops routing to the agent until an operator acknowledges
- Ollama retries use the same `[2000, 4000, 8000, 16000]` ms backoff
- WSS reconnects to the orchestrator use the same backoff on an independent circuit

---

## 5. Task State Schema

The task input and result schemas are designed to accommodate the OQ-1 decision
(custom ReAct loop) while remaining upgradeable to a LangGraph-style graph engine:

```
TaskInput {
  prompt          // The goal / task description (ReAct: the initial human message)
  system_prompt   // Override system prompt (ReAct: the system turn)
  role_template   // Gruper core template (sets system prompt + param defaults)
  model_preferences // Inference params (maps to Ollama options)
  input_files     // Attached files (ReAct: available as tool results)
  context         // Structured context (ReAct: environment state / memory)
}

TaskResult {
  output          // Final response text (ReAct: the final answer)
  artifacts       // Output files / generated assets
  model_used      // Actual model tag used
  tokens_used     // Total tokens consumed
  duration_ms     // Wall-clock execution time
}
```

The `context` field is intentionally `object` with `additionalProperties: true`
to avoid locking the state machine format at `gd-0.1`. If a LangGraph replacement
is adopted, the graph state is carried in `context` without changing the task wire
schema.

---

## 6. Timeout Mapping

| Gruper Core Timeout Preset | Value (ms) | Distributed `timeout_s` |
|---------------------------|-----------|------------------------|
| Fast | 180,000 | 180 |
| Balanced | 300,000 | 300 |
| Patient | 600,000 | 600 |
| Very Patient | 900,000 | 900 |
| Custom (60–3600 s) | 60,000–3,600,000 | 60–3600 |
| Extended batch (distributed only) | — | up to 86400 |

The distributed schema uses seconds (`timeout_s`) rather than milliseconds for clarity. The upper bound is extended to 86400 s (24 h) for overnight batch tasks — a range not present in Gruper core, which caps at 3600 s.
