# Gruper User Manual

**Version:** 0.4.5 — Streamlined UX
**Application:** `Gruper.html` (single-file, open in any modern browser)

---

## Table of Contents

1. [Introduction](#1-introduction)
2. [Requirements](#2-requirements)
3. [Installation & First Run](#3-installation--first-run)
4. [Interface Overview](#4-interface-overview)
5. [Configuring Agents](#5-configuring-agents)
6. [Starting a Conversation](#6-starting-a-conversation)
7. [During a Conversation](#7-during-a-conversation)
8. [Keyboard Shortcuts](#8-keyboard-shortcuts)
9. [Agent Templates Reference](#9-agent-templates-reference)
10. [Advanced Agent Parameters](#10-advanced-agent-parameters)
11. [Timeout Settings](#11-timeout-settings)
12. [Memory & Consensus Settings](#12-memory--consensus-settings)
13. [Text Scaling](#13-text-scaling)
14. [Analytics Dashboard](#14-analytics-dashboard)
15. [Debug Log](#15-debug-log)
16. [Conversation Tabs](#16-conversation-tabs)
17. [Import & Export](#17-import--export)
18. [Troubleshooting](#18-troubleshooting)
19. [Frequently Asked Questions](#19-frequently-asked-questions)

---

## 1. Introduction

Gruper runs up to 6 AI agents simultaneously, each powered by a local LLM via [Ollama](https://ollama.ai/) or [LocalAI](https://localai.io/). Agents debate, analyze, and collaborate on any topic you provide. You can configure each agent's personality, model, and generation parameters independently.

**Key design principle:** Gruper is a single HTML file with no installation, no build step, and no backend of its own. All state is stored in your browser's `localStorage`. Your conversations never leave your machine unless you explicitly export them.

---

## 2. Requirements

| Requirement | Details |
|---|---|
| Browser | Chrome 90+, Firefox 88+, Safari 15+, or Edge 90+ |
| JavaScript | Must be enabled (the entire application is JS-driven) |
| LLM backend | [Ollama](https://ollama.ai/) or [LocalAI](https://localai.io/) running locally (or on a reachable server) |
| Network | Local network access to your LLM backend only — no internet required for the app itself |
| CDN access | Internet access is needed once per session to load Chart.js and DOMPurify from jsDelivr |

**Minimum hardware:** Whatever is required to run your chosen LLM model. Gruper itself is lightweight.

---

## 3. Installation & First Run

### Step 1 — Get Gruper

Clone the repository or download `Gruper.html` directly:

```bash
git clone https://github.com/jnowat/gruper.git
cd gruper
```

Or simply [download `Gruper.html`](https://raw.githubusercontent.com/jnowat/gruper/main/Gruper.html) and save it anywhere on your machine.

### Step 2 — Start your LLM backend

**Ollama (recommended):**
```bash
ollama serve
# In a separate terminal, pull a model if you haven't yet:
ollama pull llama3.2
```

**LocalAI:**
```bash
# Follow LocalAI's documentation for your setup
local-ai --models-path ./models --address 0.0.0.0:8080
```

### Step 3 — Open Gruper

```bash
open Gruper.html        # macOS
firefox Gruper.html     # Linux
start Gruper.html       # Windows
```

Or double-click `Gruper.html` in your file manager.

### Step 4 — Enter your backend URL

- The default URL is `http://localhost:11434` (Ollama's default).
- Change it to match your backend if needed. Common alternatives:
  - `http://localhost:8080` (LocalAI)
  - `http://192.168.1.x:11434` (Ollama on another machine on LAN)
- Click **"Test Connection"** to verify. The status badge at the top will turn green when connected.

### Step 5 — Fetch available models

After a successful connection, click **"Refresh Models"** to populate model dropdowns for each agent.

---

## 4. Interface Overview

```
┌─────────────────────────────────────────────────────────────────┐
│  Header: Version badge • Connection status • Text scale • Theme │
├──────────────────┬──────────────────────────────────────────────┤
│                  │                                              │
│  Sidebar         │  Main Panel                                  │
│  (Agents 1–6)    │  ┌──────────────────────────────────────┐   │
│                  │  │  Task input                          │   │
│  Each agent:     │  │  Conversation controls               │   │
│  • Enable toggle │  └──────────────────────────────────────┘   │
│  • Model picker  │                                              │
│  • Template      │  Conversation messages appear here           │
│  • Personality   │  (one card per agent per round)              │
│  • Advanced →    │                                              │
│                  │  Round summary badge after each round        │
│  [Collapse ◀]    │                                              │
├──────────────────┴──────────────────────────────────────────────┤
│  Footer: Analytics • Export • Debug • Version badge             │
└─────────────────────────────────────────────────────────────────┘
```

**Sidebar toggle:** Click the `◀` / `▶` button or press `Ctrl+B` to show/hide the sidebar.

**Conversation tabs:** Add tabs with `+` or `Ctrl+T`. Each tab holds an independent conversation.

---

## 5. Configuring Agents

### Enabling an agent

Each of the 6 agent slots has an enable/disable toggle. Only enabled agents participate in conversations. You need at least 1 enabled agent to start a conversation; 2+ produce meaningful multi-agent debate.

### Selecting a model

After fetching models (see Step 5 in First Run), select a model from the dropdown for each agent. Each agent can use a different model — mixing models (e.g., one analytical model, one creative model) often produces richer conversations.

### Choosing a template

Select from 12 built-in templates (see [Section 9](#9-agent-templates-reference)) or choose "Custom" to write your own personality prompt from scratch.

### Writing a personality

The personality text box accepts plain text. Describe how this agent should think and respond. Keep it concise (1–3 sentences) for best results — longer personalities tend to dilute the agent's focus.

**Example:**
> You are a skeptical economist. Question optimistic assumptions, surface hidden costs, and always ask "compared to what alternative?"

### Advanced parameters

Click **"Advanced"** on any agent card to expand per-agent generation parameters (see [Section 10](#10-advanced-agent-parameters)).

---

## 6. Starting a Conversation

### Writing a task

Enter your question or task in the main text area. Tasks can be:
- **Questions:** "What are the tradeoffs of microservices vs. monoliths for a 5-person startup?"
- **Problems:** "Our user retention drops 40% after day 7. Analyze root causes and propose experiments."
- **Debates:** "Argue the case for and against universal basic income."
- **Analyses:** "Review this business plan: [paste text here]"

For best results: be specific, provide context, and state what kind of output you want (analysis, action plan, debate, etc.).

### Conversation settings (above the Start button)

| Setting | Description |
|---|---|
| **Max Rounds** | Maximum number of back-and-forth rounds (1–50). Each round = one response per enabled agent. |
| **Memory** | When enabled, agents receive a summary of previous rounds as context. |
| **Memory Depth** | Number of previous rounds to include in context (1–20). |
| **Consensus** | When enabled, conversation stops automatically if agents reach agreement. |
| **Consensus Threshold** | Agreement level required to trigger early stop (0–1 scale). |

### Starting

Click **"Start Conversation"** or press `Ctrl+Enter`. Agents respond sequentially in the order they are enabled (Agent 1 first, then 2, etc.).

---

## 7. During a Conversation

### Skeleton loading

While an agent is generating a response, a skeleton placeholder appears showing:
- The agent's name and model
- Current attempt number (if retrying)
- Estimated wait time (based on historical response times for that model)
- "Overdue" status if the request exceeds the estimated time

### Pause, resume, and stop

| Button | Keyboard | Effect |
|---|---|---|
| Pause | `Ctrl+P` | Finish the current agent's response, then pause before the next agent starts |
| Resume | `Ctrl+P` | Continue from where paused |
| Stop | `Ctrl+.` | Halt the conversation immediately (current agent response is discarded) |
| Reset | `Ctrl+R` | Clear the conversation and return to the task input |

### Round summary badge

After all enabled agents respond in a round, a compact badge appears:
```
📊 Round 3 complete • 4 agents responded
```

### Consensus detection

If consensus detection is enabled and the threshold is met, the conversation stops and shows:
- A green completion banner at the top of the conversation
- A toast notification
- An export flag marking the conversation as consensus-reached

### Human-in-the-Loop

If the conversation is paused, you can add a human message before resuming. This lets you steer the conversation mid-way.

---

## 8. Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| `Ctrl+Enter` | Start conversation |
| `Ctrl+P` | Pause / Resume |
| `Ctrl+.` | Stop conversation |
| `Ctrl+R` | Reset conversation |
| `Ctrl+E` | Export conversation |
| `Ctrl+A` | Open analytics dashboard |
| `Ctrl+D` | Toggle debug log |
| `Ctrl+T` | New conversation tab |
| `Ctrl+Shift+D` | Toggle dark/light mode |
| `Ctrl+B` | Toggle sidebar |
| `Cmd+K` / `Ctrl+K` | Open command palette |

The **command palette** (`Cmd+K`) provides a searchable list of all actions. It is the fastest way to access any feature without remembering keyboard shortcuts.

---

## 9. Agent Templates Reference

Templates set a starting personality prompt. You can modify the text after selecting a template.

| Template | Style | Best for |
|---|---|---|
| **Analyst** | Data-driven, logical | Factual assessment, evidence review |
| **Creative** | Imaginative, unconventional | Brainstorming, novel approaches |
| **Critic** | Skeptical, finds flaws | Risk assessment, red-teaming |
| **Synthesizer** | Integrative, diplomatic | Finding common ground, summary |
| **Expert** | Authoritative, precise | Domain-specific deep dives |
| **Devil's Advocate** | Contrarian, challenges assumptions | Stress-testing ideas |
| **Philosopher** | Principled, explores implications | Ethics, meaning, first principles |
| **Economist** | Incentive-focused, cost-aware | Business decisions, resource allocation |
| **Ethicist** | Fairness-focused, equity-aware | Moral dimensions, societal impact |
| **Scientist** | Empirical, hypothesis-driven | Research questions, experimental design |
| **Psychologist** | Behavioral, motivational | Human factors, bias identification |
| **Engineer** | Practical, technical, optimization | Implementation, trade-offs, systems |

**Recommended combinations:**
- **Analysis task:** Analyst + Critic + Synthesizer
- **Creative problem:** Creative + Engineer + Devil's Advocate
- **Ethical decision:** Ethicist + Economist + Philosopher
- **Technical design:** Engineer + Scientist + Critic

---

## 10. Advanced Agent Parameters

Expand "Advanced" on any agent card to access:

| Parameter | Range | Default | Effect |
|---|---|---|---|
| **Temperature** | 0.0–1.0 | 0.7 | Higher = more creative/random. Lower = more focused/deterministic. |
| **Top-P** | 0.0–1.0 | 0.9 | Nucleus sampling. Lower values restrict vocabulary to highest-probability tokens. |
| **Top-K** | 1–100 | 40 | Limits token selection to the K most likely next tokens. |
| **Repeat Penalty** | 0.5–2.0 | 1.1 | Higher values penalize repeating recent tokens. Helps prevent loops. |
| **Max Tokens** | 128–8192 | 2048 | Maximum length of each response. |
| **Context Length** | 512–16384 | 4096 | How much text the model can "see" at once (prompt + response). |
| **Seed** | Optional integer | (random) | Set to a fixed number for reproducible responses. |
| **Stop Sequences** | Comma-separated strings | (none) | The model stops generating when it outputs any of these strings. |
| **Timeout Override** | 60–3600 seconds | (global) | Override the global timeout for this specific agent only. |

**Tips:**
- For reasoning/analysis tasks, lower temperature (0.3–0.5) produces more consistent responses.
- For creative tasks, higher temperature (0.7–0.9) produces more varied responses.
- If an agent produces repetitive responses, increase Repeat Penalty to 1.2–1.3.
- For very large models on slow hardware, set a generous Timeout Override (600–1800s).

---

## 11. Timeout Settings

Gruper has two timeout layers:

### Global timeout

Set in the header controls. Presets:
- **Fast** (180s) — for small models on fast hardware
- **Balanced** (300s) — default for most setups
- **Patient** (600s) — for medium models
- **Very Patient** (900s) — for large models or slow hardware
- **Custom** — any value from 60s to 3600s

### Per-agent timeout override

Set in Advanced parameters per agent. Overrides the global timeout for that agent only. Useful when you have one slow model alongside faster agents.

### What happens on timeout

The agent's request fails with an error card. Gruper will retry automatically (up to 4 times with exponential backoff: 2s → 4s → 8s → 16s). After 3 consecutive failures, the agent's circuit breaker activates and the agent is disabled for the rest of that conversation. A toast notification informs you.

---

## 12. Memory & Consensus Settings

### Memory

When memory is enabled, each agent receives a context window containing summaries of previous rounds alongside the original task. This allows agents to build on each other's ideas and maintain thread continuity over many rounds.

- **Depth:** How many previous rounds to include (1–20). Higher depth improves continuity but increases prompt length and response time.
- **Performance note:** Memory significantly increases the tokens sent per request. For models with small context windows, keep depth at 1–3.

### Consensus detection

Gruper monitors each response for agreement signals using keyword-based detection. When the **Consensus Threshold** (0–1) proportion of agents show agreement in the same round, the conversation ends automatically.

- A **Consensus Reached** banner appears in the conversation.
- A **toast notification** confirms the outcome.
- Exported conversations include a `consensusReached: true` flag.

**Threshold guide:**
- `0.5` — majority agreement (works well for 4+ agents)
- `0.67` — two-thirds agreement (good default)
- `1.0` — unanimous (strictest — all agents must agree)

---

## 13. Text Scaling

Adjust the global font size using the text scale control in the header (80%–140%). The default is 100%; Gruper auto-suggests 90% on screens narrower than 1000px.

Text scaling changes all UI text proportionally and is persisted across sessions via `localStorage`.

---

## 14. Analytics Dashboard

Open analytics with `Ctrl+A` or the analytics button in the footer. The dashboard shows charts and metrics for the current conversation session.

### Charts

| Chart | Description |
|---|---|
| **Response time trend** | Line chart — response time per round per agent |
| **Per-agent performance** | Bar chart — average response time per agent (gray bar = no successful responses) |
| **Success rate** | Pie chart — proportion of successful vs. failed API calls |

### Metrics

Displayed below the charts:
- Total rounds completed
- Total messages sent/received
- Overall success rate
- Model usage breakdown

### Export

Click **Export CSV** or **Export JSON** to save the analytics data. Useful for analyzing model performance across sessions.

The dashboard auto-refreshes when a conversation ends.

---

## 15. Debug Log

Toggle the debug log with `Ctrl+D` or the debug button in the footer.

### Features

- **Live filtering:** Type in the search box to filter log entries in real-time (case-insensitive)
- **Auto-scroll:** Toggle auto-scroll to follow the latest entries or scroll freely to review history
- **Drag to resize:** Drag the top edge of the debug pane to adjust its height; size is persisted
- **Entry highlighting:** New entries flash yellow briefly when they appear

### Log levels

| Level | Color | Meaning |
|---|---|---|
| DEBUG | Gray | Detailed internal state changes |
| INFO | Blue | Normal operation events |
| WARNING | Yellow | Non-fatal issues (retry attempts, degraded behavior) |
| ERROR | Red | Failed operations (API errors, timeouts) |
| SUCCESS | Green | Completed operations |

Debug log entries include timestamps and are searchable. The log does not persist across page reloads.

---

## 16. Conversation Tabs

Gruper supports multiple independent conversations via tabs.

- **New tab:** Click `+` in the tab bar or press `Ctrl+T`
- **Switch tabs:** Click any tab
- **Close tab:** Click `×` on a tab (conversation data is lost — export first if needed)

Each tab has its own independent state: task, agents in use, conversation history, and settings. Tab state is persisted in `localStorage` between sessions.

**Note:** All tabs share the same agent configuration in the sidebar. Agent enable/disable, model, and personality settings affect all tabs.

---

## 17. Import & Export

### Export conversation

Press `Ctrl+E` or click **Export** in the footer. This downloads a JSON file containing:
- Task text
- All conversation rounds (agent name, model, response text, timestamps, metadata)
- Settings used (max rounds, memory depth, consensus settings)
- Analytics data (response times, success rates)
- `consensusReached` flag if applicable

### Import conversation

Click **Import** and select a previously exported JSON file. The conversation is loaded into the current tab, replacing any existing conversation (you will be prompted to confirm).

### Export agent configuration

From the sidebar, click **Export Config** to save your current agent configuration (names, models, personalities, parameters) as a JSON file. Import it later with **Import Config**.

This is useful for saving different sets of agents for different use cases (e.g., a "technical review" set vs. a "creative brainstorm" set).

---

## 18. Troubleshooting

### Connection refused / cannot reach backend

- Make sure Ollama or LocalAI is running: `ollama serve` / `local-ai ...`
- Check the endpoint URL matches your backend's address and port
- If using a remote server, verify CORS is configured to allow requests from `file://` origins
- Try the **IP preset switcher** for common configurations

### Models not appearing in dropdown

- Click **Refresh Models** after the connection succeeds
- Verify your backend has models installed: `ollama list`
- Ensure the backend's model API is responding: `curl http://localhost:11434/api/tags`

### Agent times out repeatedly

- Increase the global timeout (try "Very Patient" at 900s for large models)
- Set a per-agent timeout override in Advanced parameters
- Check system resource usage — the model may be competing for CPU/RAM
- Try a smaller or quantized version of the model

### Agent circuit breaker activated

An agent is disabled mid-conversation if it fails 3 times consecutively. To re-enable:
- Click the agent's enable toggle off, then back on
- Reset the conversation (`Ctrl+R`) to start fresh

### Conversation state seems corrupted or stuck

Press `Ctrl+R` to reset the conversation. If the problem persists across reloads, open the browser console and run:
```javascript
localStorage.removeItem('multiAgentApp');
location.reload();
```
This clears all persisted state. Your conversations will be lost — export important ones first.

### Storage quota warning appears

Gruper saves state to `localStorage`. If you see a "Storage quota exceeded" warning, your browser's localStorage limit has been reached. Gruper will attempt to free space by removing cached data and retry automatically. If the warning persists, export and delete old conversation tabs.

### XSS protection / content looks sanitized

Gruper uses DOMPurify to render LLM responses as safe HTML. The following HTML elements are allowed: `p`, `br`, `strong`, `em`, `code`, `ul`, `ol`, `li`. All other HTML is stripped. This is intentional — it prevents an LLM from injecting malicious scripts into the page.

### Dark mode not saving

Dark mode preference is stored in `localStorage`. If it resets on each reload, check your browser's storage permissions for the file. Some browsers restrict `localStorage` for `file://` URLs in privacy mode.

---

## 19. Frequently Asked Questions

**Q: Does Gruper send my conversations anywhere?**
A: No. All data stays in your browser and in your local LLM backend. The only external network requests are:
1. Loading Chart.js and DOMPurify from jsDelivr CDN (once per page load)
2. Loading the Inter font from Google Fonts CDN (once per page load)
3. API calls to your configured LLM backend (localhost or LAN)

**Q: Can I use Gruper offline?**
A: Partially. The application logic is fully offline-capable. However, Chart.js and DOMPurify are loaded from CDN — if those fail to load (e.g., no internet), analytics charts won't render and message display falls back to plain text (still safe, just less styled). Font rendering falls back to system fonts.

**Q: How many agents should I use?**
A: 2–4 agents is the sweet spot for most tasks. With 2 agents you get focused debate; with 4 you get broader perspective coverage. 5–6 agents increases conversation time and token cost without proportionally more insight, unless you need coverage of 5+ distinct viewpoints simultaneously.

**Q: Can I use different models for different agents?**
A: Yes — this is one of Gruper's most powerful features. Mixing a fast small model (e.g., phi3:mini) for quick reactions with a slower large model (e.g., llama3.1:70b) for deep analysis often produces better conversations than using identical models.

**Q: What does the security shield icon mean?**
A: It indicates that Gruper's XSS protection is active: DOMPurify sanitizes all LLM-generated HTML, prompt injection patterns are filtered on startup, and only a safe whitelist of HTML tags is rendered. Hover over it to see details.

**Q: Why does the app use inline JavaScript and no framework?**
A: Gruper is intentionally a single-file, dependency-minimal application. Vanilla JS (ES6+) with no framework means no `node_modules`, no build step, and no runtime abstraction layer — just open the file and it works. The tradeoff is a larger single file and some patterns (like inline `onclick` handlers) that would look different in a framework context.

**Q: How do I update Gruper?**
A: Download the latest `Gruper.html` from the repository and replace your local copy. Your conversations and settings are stored in `localStorage` under the key `multiAgentApp` and will persist across file updates.

**Q: Can I run multiple Gruper instances at once?**
A: Yes, but they share `localStorage`. Opening two tabs with the same `Gruper.html` means they share state — saving in one tab may overwrite the other's state. Use conversation tabs within a single Gruper instance instead.

---

## 20. Privacy & Data Storage

All data stays local:

- **No network requests** except to your local Ollama/LocalAI endpoint and the jsDelivr CDN (for Chart.js and DOMPurify on first load)
- **No telemetry, no analytics, no cloud**
- Conversation history is stored in `localStorage` under the key `multiAgentApp`
- To clear all data: open browser DevTools → Application → Local Storage → delete the key, or use the Reset controls within Gruper

External libraries (Chart.js and DOMPurify) are loaded from jsDelivr CDN on first open. If you need fully offline use, save their files locally and update the `<script>` tags in `Gruper.html`.

---

*For issues, questions, or feature requests, open an issue at [github.com/jnowat/gruper/issues](https://github.com/jnowat/gruper/issues).*

*See also: [README.md](README.md) for quick start · [CHANGELOG.md](CHANGELOG.md) for version history · [ROADMAP.md](ROADMAP.md) for planned work*
