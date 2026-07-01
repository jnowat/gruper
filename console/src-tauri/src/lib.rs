//! WP-32: the Console manages a local orchestrator "sidecar" process so a
//! desktop user never has to start it by hand. On launch, the Rust side:
//!   1. checks whether something is already answering /v1/health on the
//!      default port (an existing sidecar from another launch, a
//!      manually-started orchestrator, or the server-tier docker-compose
//!      stack) — and if so, uses it instead of spawning a duplicate;
//!   2. otherwise spawns the bundled `gruper-orchestrator` sidecar binary
//!      (see tauri.conf.json's `bundle.externalBin` and
//!      orchestrator/packaging/) and polls its health endpoint;
//!   3. emits an `orchestrator-status` event, AND records the same payload
//!      in `LastStatus` state (queryable via the `get_orchestrator_status`
//!      command), so the frontend can auto-fill / auto-connect the Connect
//!      dialog instead of asking the user to type a URL (see
//!      console/src/lib/stores/orchestrator.ts). Both are needed: a plain
//!      Tauri event fired before the frontend's `listen()` call has
//!      attached is simply dropped, not queued — confirmed by testing, this
//!      genuinely happens (the sidecar's health check can resolve before
//!      the webview finishes loading its JS bundle). The queryable command
//!      lets a late-attaching frontend catch up on whatever it missed.
//!
//! `tauri-plugin-single-instance` is registered first so a second Console
//! launch focuses the existing window instead of spawning a second sidecar
//! and racing for the same port.
//!
//! The sidecar (and, since the "Add Local Agent" flow, each spawned
//! `gruper-agent` sidecar too) is launched with an explicit `.current_dir()`
//! pointed at the Tauri app-data directory rather than whatever the OS
//! happened to set as the process's working directory. This matters because
//! the orchestrator/agent write relative-path state next to their CWD
//! (`orchestrator.db`, `.gruper_jwt_secret`, `agent.db` — see
//! orchestrator/config.py and agent-runtime/config.py) and a Windows
//! installer launch's CWD is commonly `C:\Program Files\...`, which is not
//! writable by a non-admin user — an unhandled write failure there is a
//! real crash risk, not a hypothetical one.
//!
//! `detect_ollama_models` exists because the obvious approach — calling
//! `fetch("http://localhost:11434/api/tags")` directly from the frontend —
//! does NOT work reliably from inside the Tauri webview, even when Ollama is
//! genuinely running with models installed. Confirmed on real Windows
//! hardware: Chromium/WebView2 enforces Private Network Access (PNA) for any
//! request from a page's origin into a more-private address space; Tauri's
//! app origin (`https://tauri.localhost` on Windows, `tauri://localhost`
//! elsewhere) does not get automatically classified as "local" the way a
//! page served by a plain `python -m http.server` on `localhost` does, so
//! the browser sends a preflight requiring an
//! `Access-Control-Allow-Private-Network: true` response header — which
//! Ollama's server never sends — and silently fails the request with a
//! generic network error indistinguishable from "Ollama isn't running" at
//! the JS layer. This is a known class of Tauri/Chromium issue, not
//! speculation. The fix is to make the request from Rust instead: a plain
//! `tokio::net::TcpStream` is not a browser page and is not subject to CORS,
//! PNA, or mixed-content rules at all, so it reaches a real local Ollama
//! reliably. `AddAgentDialog.svelte` calls this command when running under
//! Tauri and falls back to a plain `fetch()` only for the non-Tauri
//! browser-dev-tab case (where the same PNA rule does not apply, since a
//! Vite dev server is itself served from `localhost`).

use std::collections::{HashMap, VecDeque};
use std::path::PathBuf;
use std::sync::{Mutex, OnceLock};
use std::time::Duration;

use regex::Regex;
use tauri::{AppHandle, Emitter, Manager};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

const ORCHESTRATOR_HOST: &str = "127.0.0.1";
const ORCHESTRATOR_PORT: u16 = 8080;
const ORCHESTRATOR_URL: &str = "http://127.0.0.1:8080";
const HEALTH_POLL_TIMEOUT_S: u64 = 15;

// ─── Unified debug log sink (Desktop Hardening) ──────────────────────────────
//
// One bounded, in-memory ring buffer is the single sink for the whole stack. It
// is fed by (1) the Rust/Tauri tier directly (`rust_log`), (2) structured JSON
// lines parsed out of the orchestrator/agent sidecar stdout
// (`ingest_sidecar_line`), and (3) the Svelte frontend via the `push_log`
// command. The frontend reads a snapshot with `get_logs` (backfill, since a
// Tauri event fired before the listener attaches is dropped — the same hazard
// solved for `orchestrator-status`) and streams new entries via the `log-entry`
// event, then filters / copies / exports them in DebugPanel.svelte. Secrets are
// redacted HERE, before an entry is ever stored — defense in depth with the
// Python emit-site redaction in {orchestrator,agent-runtime}/structured_log.py.

const LOG_BUFFER_CAP: usize = 5000;
const LOG_SENTINEL: u8 = 0x1e; // ASCII Record Separator; see structured_log.py

#[derive(Clone, serde::Serialize, serde::Deserialize)]
struct LogEntry {
    ts: String,
    level: String,
    category: String,
    tier: String,
    #[serde(default)]
    agent_id: Option<String>,
    #[serde(default)]
    task_id: Option<String>,
    msg: String,
    #[serde(default = "empty_json_object")]
    fields: serde_json::Value,
}

fn empty_json_object() -> serde_json::Value {
    serde_json::json!({})
}

struct LogBuffer(Mutex<VecDeque<LogEntry>>);

/// ISO-8601 UTC timestamp without pulling in chrono, via Howard Hinnant's
/// days-from-civil algorithm. Matches the shape the Python tier emits so the
/// frontend can sort/display every tier's entries uniformly.
fn iso_now() -> String {
    use std::time::{SystemTime, UNIX_EPOCH};
    let dur = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default();
    let secs = dur.as_secs() as i64;
    let millis = dur.subsec_millis();
    let days = secs.div_euclid(86_400);
    let rem = secs.rem_euclid(86_400);
    let (hour, min, sec) = (rem / 3600, (rem % 3600) / 60, rem % 60);
    let z = days + 719_468;
    let era = (if z >= 0 { z } else { z - 146_096 }) / 146_097;
    let doe = z - era * 146_097;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let y = if m <= 2 { y + 1 } else { y };
    format!("{y:04}-{m:02}-{d:02}T{hour:02}:{min:02}:{sec:02}.{millis:03}Z")
}

fn redact_str(input: &str) -> String {
    static JWT: OnceLock<Regex> = OnceLock::new();
    static TOKEN_QS: OnceLock<Regex> = OnceLock::new();
    static BEARER: OnceLock<Regex> = OnceLock::new();
    let jwt = JWT.get_or_init(|| {
        Regex::new(r"eyJ[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}").unwrap()
    });
    let token_qs =
        TOKEN_QS.get_or_init(|| Regex::new(r#"(?i)([?&](?:token|jwt)=)[^&\s"']+"#).unwrap());
    let bearer = BEARER.get_or_init(|| Regex::new(r"(?i)(bearer\s+)[A-Za-z0-9._\-]+").unwrap());
    let s = jwt.replace_all(input, "<jwt:redacted>").into_owned();
    let s = token_qs.replace_all(&s, "${1}<redacted>").into_owned();
    bearer.replace_all(&s, "${1}<redacted>").into_owned()
}

fn is_secret_key(key: &str) -> bool {
    static KEY: OnceLock<Regex> = OnceLock::new();
    KEY.get_or_init(|| {
        Regex::new(r"(?i)(pub_?key|x25519|token_string|secret|password|priv(_?key)?|signature|jwt)")
            .unwrap()
    })
    .is_match(key)
}

fn redact_value(value: &mut serde_json::Value) {
    match value {
        serde_json::Value::String(s) => *s = redact_str(s),
        serde_json::Value::Array(arr) => arr.iter_mut().for_each(redact_value),
        serde_json::Value::Object(map) => {
            for (k, v) in map.iter_mut() {
                if is_secret_key(k) {
                    *v = serde_json::Value::String("<redacted>".into());
                } else {
                    redact_value(v);
                }
            }
        }
        _ => {}
    }
}

fn log_push(app: &AppHandle, mut entry: LogEntry, emit: bool) {
    entry.msg = redact_str(&entry.msg);
    redact_value(&mut entry.fields);
    if let Some(state) = app.try_state::<LogBuffer>() {
        let mut buf = state.0.lock().unwrap();
        while buf.len() >= LOG_BUFFER_CAP {
            buf.pop_front();
        }
        buf.push_back(entry.clone());
    }
    if emit {
        let _ = app.emit("log-entry", &entry);
    }
}

/// Emit a log line from the Rust/Tauri tier itself (spawn decisions, health
/// checks, crash-grace outcomes). Still prints to stderr so `cargo tauri dev`
/// output is unchanged, and also lands in the unified buffer + live stream.
fn rust_log(
    app: &AppHandle,
    level: &str,
    category: &str,
    agent_id: Option<String>,
    msg: impl Into<String>,
) {
    let msg = msg.into();
    match &agent_id {
        Some(id) => eprintln!("[{category}:{id}] {msg}"),
        None => eprintln!("[{category}] {msg}"),
    }
    log_push(
        app,
        LogEntry {
            ts: iso_now(),
            level: level.into(),
            category: category.into(),
            tier: "rust".into(),
            agent_id,
            task_id: None,
            msg,
            fields: empty_json_object(),
        },
        true,
    );
}

/// Ingest one line of sidecar output. A sentinel-prefixed line is parsed as a
/// structured LogEntry (preserving its level/category/task_id); anything else
/// (a traceback, uvicorn's banner, a stray print) is wrapped verbatim as a raw
/// 'sidecar' entry so nothing is ever lost.
fn ingest_sidecar_line(app: &AppHandle, tier: &str, agent_id: &Option<String>, raw: &[u8]) {
    let mut bytes = raw;
    while matches!(bytes.last(), Some(b'\n') | Some(b'\r')) {
        bytes = &bytes[..bytes.len() - 1];
    }
    if bytes.first() == Some(&LOG_SENTINEL) {
        if let Ok(mut e) = serde_json::from_slice::<LogEntry>(&bytes[1..]) {
            if e.ts.is_empty() {
                e.ts = iso_now();
            }
            if e.tier.is_empty() {
                e.tier = tier.to_string();
            }
            if e.agent_id.is_none() {
                e.agent_id = agent_id.clone();
            }
            log_push(app, e, true);
            return;
        }
    }
    let text = String::from_utf8_lossy(bytes).trim().to_string();
    if text.is_empty() {
        return;
    }
    match agent_id {
        Some(id) => eprintln!("[{tier}:{id}] {text}"),
        None => eprintln!("[{tier}] {text}"),
    }
    log_push(
        app,
        LogEntry {
            ts: iso_now(),
            level: "info".into(),
            category: "sidecar".into(),
            tier: tier.into(),
            agent_id: agent_id.clone(),
            task_id: None,
            msg: text,
            fields: empty_json_object(),
        },
        true,
    );
}

/// Snapshot the whole ring buffer (frontend backfill on DebugPanel open).
#[tauri::command]
fn get_logs(state: tauri::State<LogBuffer>) -> Vec<LogEntry> {
    state.0.lock().unwrap().iter().cloned().collect()
}

/// Clear the ring buffer (the DebugPanel "Clear" button).
#[tauri::command]
fn clear_logs(state: tauri::State<LogBuffer>) {
    state.0.lock().unwrap().clear();
}

/// Frontend-originated log line. Stored (redacted) but NOT re-emitted: the
/// calling window already appended it locally, so echoing `log-entry` back
/// would duplicate it.
#[tauri::command]
fn push_log(app: AppHandle, entry: LogEntry) {
    log_push(&app, entry, false);
}

/// Holds every sidecar child process this Console instance spawned, so they
/// can all be killed on exit. `orchestrator` is `None` if we connected to an
/// already-running orchestrator instead of spawning one — in that case,
/// exiting the Console must NOT kill it (it isn't ours to kill: some other
/// launch, or a manually-run server tier). `agents` holds one entry per
/// locally-spawned agent sidecar, keyed by agent id (see spawn_local_agent).
struct SidecarState {
    orchestrator: Mutex<Option<CommandChild>>,
    agents: Mutex<HashMap<String, CommandChild>>,
}

/// Resolves (and creates, if missing) the directory the Console's spawned
/// sidecars should use as their working directory, so their relative-path
/// state (SQLite files, JWT secret, offline queues) lands somewhere the
/// current user can always write to, regardless of how the Console itself
/// was launched or where it was installed.
fn resolve_sidecar_data_dir(app: &AppHandle) -> Result<PathBuf, String> {
    let dir = app
        .path()
        .app_data_dir()
        .map_err(|e| format!("could not resolve app data directory: {e}"))?;
    std::fs::create_dir_all(&dir)
        .map_err(|e| format!("could not create app data directory {}: {e}", dir.display()))?;
    Ok(dir)
}

/// The last `orchestrator-status` payload emitted, so a frontend that
/// attaches its `listen()` call AFTER the event already fired can still
/// retrieve current status instead of getting stuck on "checking…" forever.
/// This is not a hypothetical: it was observed in testing — the sidecar's
/// health check can resolve before the webview has finished loading and
/// registering its listener, and a plain Tauri event emitted into a void
/// with no listener yet attached is simply lost, not queued.
struct LastStatus(Mutex<serde_json::Value>);

#[tauri::command]
fn get_orchestrator_status(state: tauri::State<LastStatus>) -> serde_json::Value {
    state.0.lock().unwrap().clone()
}

fn emit_status(app: &AppHandle, payload: serde_json::Value) {
    if let Some(state) = app.try_state::<LastStatus>() {
        *state.0.lock().unwrap() = payload.clone();
    }
    let _ = app.emit("orchestrator-status", payload);
}

pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_store::Builder::default().build())
        .manage(SidecarState {
            orchestrator: Mutex::new(None),
            agents: Mutex::new(HashMap::new()),
        })
        .manage(LastStatus(Mutex::new(
            serde_json::json!({ "status": "checking", "url": null, "error": null }),
        )))
        .manage(LogBuffer(Mutex::new(VecDeque::with_capacity(256))))
        .invoke_handler(tauri::generate_handler![
            get_orchestrator_status,
            spawn_local_agent,
            detect_ollama_models,
            stop_local_agent,
            get_logs,
            clear_logs,
            push_log
        ])
        .setup(|app| {
            let handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                manage_orchestrator(handle).await;
            });
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                kill_sidecar_if_owned(window);
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building Gruper Console");

    // Two independent shutdown paths kill the sidecar, deliberately
    // redundant: WindowEvent::Destroyed above (fires on a normal window
    // close) and RunEvent::ExitRequested/Exit here (fires on app.exit(),
    // Cmd+Q, and other app-level exits that don't always route through a
    // single window's Destroyed event). Neither path — nor any userspace
    // code at all — can run on a FORCEFUL kill (SIGKILL, or Task Manager's
    // "End Task" on Windows, which sends TerminateProcess): that's what
    // orchestrator/packaging/entry.py's parent-PID watchdog is for (see its
    // module docstring) — confirmed necessary by testing, not assumed.
    app.run(|app_handle, event| {
        if matches!(
            event,
            tauri::RunEvent::ExitRequested { .. } | tauri::RunEvent::Exit
        ) {
            if let Some(state) = app_handle.try_state::<SidecarState>() {
                kill_all_sidecars(&state);
            }
        }
    });
}

fn kill_all_sidecars(state: &SidecarState) {
    if let Some(child) = state.orchestrator.lock().unwrap().take() {
        let _ = child.kill();
    }
    for (_, child) in state.agents.lock().unwrap().drain() {
        let _ = child.kill();
    }
}

fn kill_sidecar_if_owned<R: tauri::Runtime>(manager: &impl Manager<R>) {
    // Best-effort: processes may have already exited on their own. A desktop
    // orchestrator/agent we spawned should not outlive the Console
    // window/app that owns it.
    kill_all_sidecars(&manager.state::<SidecarState>());
}

/// Minimum-viable agent management: stops an agent this Console spawned
/// locally (see `spawn_local_agent`). There is deliberately no
/// orchestrator-side delete here — the orchestrator has no DELETE
/// /v1/agents/{id} endpoint (out of scope for this pass) — so the frontend
/// marks the fleet row `offline` itself after this succeeds; the
/// orchestrator will independently reach the same conclusion once it
/// notices the agent's WebSocket connection drop, so the two converge.
/// Returns an error (not a crash) for an agent this Console isn't tracking
/// — e.g. a remote/manually-run agent, or one already stopped — since that
/// is an expected, common case (not every fleet entry is locally-spawned),
/// and the frontend shows that as a plain message rather than "removal
/// failed."
#[tauri::command]
fn stop_local_agent(app: AppHandle, agent_id: String) -> Result<(), String> {
    let child = app
        .try_state::<SidecarState>()
        .and_then(|state| state.agents.lock().unwrap().remove(&agent_id));

    match child {
        Some(child) => child
            .kill()
            .map_err(|e| format!("agent process could not be stopped: {e}")),
        None => Err(
            "this agent isn't managed by this Console (it wasn't spawned locally, or has already stopped)"
                .to_string(),
        ),
    }
}

async fn manage_orchestrator(app: AppHandle) {
    if check_health().await {
        rust_log(
            &app,
            "info",
            "sidecar",
            None,
            format!("found an orchestrator already answering /v1/health at {ORCHESTRATOR_URL}; using it"),
        );
        emit_status(
            &app,
            serde_json::json!({ "status": "existing", "url": ORCHESTRATOR_URL, "error": null }),
        );
        return;
    }

    let data_dir = match resolve_sidecar_data_dir(&app) {
        Ok(dir) => dir,
        Err(e) => {
            emit_status(
                &app,
                serde_json::json!({
                    "status": "failed",
                    "url": null,
                    "error": format!("could not prepare a writable directory for the local orchestrator: {e}"),
                }),
            );
            return;
        }
    };

    let sidecar = match app.shell().sidecar("gruper-orchestrator") {
        Ok(cmd) => cmd,
        Err(e) => {
            emit_status(
                &app,
                serde_json::json!({
                    "status": "failed",
                    "url": null,
                    "error": format!("orchestrator sidecar binary not available: {e}"),
                }),
            );
            return;
        }
    };
    // See orchestrator/packaging/entry.py: this makes the sidecar self-
    // terminate if it's re-parented (i.e. this Console process is gone by
    // any means, including a forceful kill that no cleanup code here could
    // ever observe).
    let sidecar = sidecar
        .env("GRUPER_EXIT_WITH_PARENT", "1")
        // See the module docstring: the orchestrator persists orchestrator.db
        // and .gruper_jwt_secret relative to its CWD, which must be a
        // directory this user can actually write to — not whatever CWD the
        // OS handed the Console (Program Files on a Windows installer
        // launch, for example).
        .current_dir(&data_dir);

    let (mut rx, child) = match sidecar.spawn() {
        Ok(pair) => pair,
        Err(e) => {
            emit_status(
                &app,
                serde_json::json!({
                    "status": "failed",
                    "url": null,
                    "error": format!("failed to start the local orchestrator: {e}"),
                }),
            );
            return;
        }
    };

    if let Some(state) = app.try_state::<SidecarState>() {
        *state.orchestrator.lock().unwrap() = Some(child);
    }
    rust_log(
        &app,
        "info",
        "sidecar",
        None,
        "spawned bundled orchestrator sidecar; waiting for it to become healthy",
    );

    // Drain the sidecar's stdout/stderr into the Console's unified debug log —
    // the orchestrator logs its own startup/migration/request activity as
    // structured JSON lines (see orchestrator/structured_log.py), which is
    // invaluable for diagnosing a "failed to start" report from a user.
    let app_logs = app.clone();
    tauri::async_runtime::spawn(async move {
        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(line) | CommandEvent::Stderr(line) => {
                    ingest_sidecar_line(&app_logs, "orchestrator", &None, &line);
                }
                CommandEvent::Error(err) => {
                    rust_log(
                        &app_logs,
                        "error",
                        "sidecar",
                        None,
                        format!("orchestrator sidecar error: {err}"),
                    );
                }
                CommandEvent::Terminated(payload) => {
                    rust_log(
                        &app_logs,
                        "warn",
                        "sidecar",
                        None,
                        format!("orchestrator sidecar exited: {payload:?}"),
                    );
                    break;
                }
                _ => {}
            }
        }
    });

    let deadline = tokio::time::Instant::now() + Duration::from_secs(HEALTH_POLL_TIMEOUT_S);
    let mut ready = false;
    while tokio::time::Instant::now() < deadline {
        if check_health().await {
            ready = true;
            break;
        }
        tokio::time::sleep(Duration::from_millis(200)).await;
    }

    if ready {
        rust_log(&app, "info", "sidecar", None, "local orchestrator is healthy");
    } else {
        rust_log(
            &app,
            "error",
            "sidecar",
            None,
            format!("orchestrator did not become healthy within {HEALTH_POLL_TIMEOUT_S}s"),
        );
    }
    emit_status(
        &app,
        serde_json::json!({
            "status": if ready { "ready" } else { "failed" },
            "url": ORCHESTRATOR_URL,
            "error": if ready { serde_json::Value::Null } else {
                serde_json::Value::String(
                    format!("orchestrator did not become healthy within {HEALTH_POLL_TIMEOUT_S}s")
                )
            },
        }),
    );
}

/// "Add Local Agent" (minimum viable agent onboarding): the frontend has
/// already generated an agent identity and registered it with the
/// orchestrator via `POST /v1/agents` (see AddAgentDialog.svelte) — this
/// command does the other half, spawning the bundled `gruper-agent` sidecar
/// so the newly-registered agent actually comes online and can run tasks,
/// without the user ever touching a config file or a terminal.
///
/// `orchestrator_url` is the same http(s) URL the Console itself is
/// connected to; it's converted to the agent's expected ws(s) endpoint here
/// so the frontend doesn't need to know that detail. The JWT is the
/// console's own token — valid for this because gd-0.1's tokens are
/// per-owner, not per-agent (see orchestrator/ws/agent_ws.py), and the
/// spawned agent is owned by the same user as the Console that spawned it,
/// which matches this feature's explicit single-machine/single-owner scope.
/// How long to watch a freshly-spawned agent sidecar for an immediate crash
/// (missing DLL, antivirus quarantine of the freshly-extracted onefile
/// payload, bad working directory) before declaring the spawn successful.
/// Long enough to catch a near-instant process exit; short enough not to
/// make every "Add Local Agent" click feel like it hung.
const AGENT_SPAWN_GRACE_MS: u64 = 800;

#[tauri::command]
async fn spawn_local_agent(
    app: AppHandle,
    agent_id: String,
    jwt_token: String,
    orchestrator_url: String,
    ollama_url: Option<String>,
    capabilities_json: Option<String>,
) -> Result<(), String> {
    let data_dir = resolve_sidecar_data_dir(&app)?;
    // Each local agent gets its own working directory so their SQLite offline
    // queues (agent.db, see agent-runtime/config.py) don't collide.
    let agent_dir = data_dir.join("agents").join(&agent_id);
    std::fs::create_dir_all(&agent_dir)
        .map_err(|e| format!("could not create agent data directory {}: {e}", agent_dir.display()))?;

    let ws_url = orchestrator_url
        .replacen("https://", "wss://", 1)
        .replacen("http://", "ws://", 1);
    let ws_url = format!("{}/v1/agents/ws", ws_url.trim_end_matches('/'));

    let sidecar = app
        .shell()
        .sidecar("gruper-agent")
        .map_err(|e| format!("agent sidecar binary not available: {e}"))?
        .env("AGENT_ID", &agent_id)
        .env("JWT_TOKEN", &jwt_token)
        .env("ORCHESTRATOR_URL", &ws_url)
        // See agent-runtime/main.py: mirrors the orchestrator sidecar's
        // orphan watchdog so a forcefully-killed Console doesn't leave this
        // process running forever.
        .env("GRUPER_EXIT_WITH_PARENT", "1")
        .current_dir(&agent_dir);
    let sidecar = if let Some(url) = ollama_url {
        sidecar.env("OLLAMA_URL", url)
    } else {
        sidecar
    };
    // Without this, the agent process falls back to its own hardcoded
    // default model (see agent-runtime/ws_client.py::_model_and_options)
    // instead of whatever model the "Add Local Agent" dialog actually
    // detected — a real model was chosen in the UI but never made it to the
    // process that runs tasks.
    let sidecar = if let Some(caps) = capabilities_json {
        sidecar.env("CAPABILITIES", caps)
    } else {
        sidecar
    };

    let (mut rx, child) = sidecar
        .spawn()
        .map_err(|e| format!("failed to start local agent {agent_id}: {e}"))?;

    // Grace period: give the process a moment to crash immediately so a
    // failure is reported synchronously to the caller (and shown in the
    // dialog) instead of leaving the frontend to time out waiting for an
    // agent that will never come online.
    let mut last_output: Option<String> = None;
    let mut crashed: Option<String> = None;
    let grace = tokio::time::sleep(Duration::from_millis(AGENT_SPAWN_GRACE_MS));
    tokio::pin!(grace);
    loop {
        tokio::select! {
            _ = &mut grace => break,
            event = rx.recv() => {
                match event {
                    Some(CommandEvent::Stdout(line)) | Some(CommandEvent::Stderr(line)) => {
                        ingest_sidecar_line(&app, "agent", &Some(agent_id.clone()), &line);
                        let text = String::from_utf8_lossy(&line).trim().to_string();
                        if !text.is_empty() {
                            last_output = Some(text);
                        }
                    }
                    Some(CommandEvent::Error(err)) => {
                        crashed = Some(err);
                        break;
                    }
                    Some(CommandEvent::Terminated(payload)) => {
                        crashed = Some(format!(
                            "process exited immediately (code {:?}){}",
                            payload.code,
                            last_output
                                .as_ref()
                                .map(|l| format!(" — last output: {l}"))
                                .unwrap_or_default()
                        ));
                        break;
                    }
                    None => break,
                    _ => {}
                }
            }
        }
    }

    if let Some(reason) = crashed {
        return Err(format!("agent sidecar failed to start: {reason}"));
    }

    if let Some(state) = app.try_state::<SidecarState>() {
        state
            .agents
            .lock()
            .unwrap()
            .insert(agent_id.clone(), child);
    }
    rust_log(
        &app,
        "info",
        "sidecar",
        Some(agent_id.clone()),
        "agent sidecar started; waiting for it to register and come online",
    );

    // Drain stdout/stderr into the Console's unified debug log for the rest of
    // the process's life, same as the orchestrator sidecar — invaluable for
    // diagnosing why a freshly-added agent never shows up as online. Also
    // emit a Tauri event on a later crash/exit so the frontend (still
    // waiting for the agent to appear in the fleet) can report a real
    // failure instead of just quietly timing out.
    let app_for_task = app.clone();
    tauri::async_runtime::spawn(async move {
        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(line) | CommandEvent::Stderr(line) => {
                    ingest_sidecar_line(&app_for_task, "agent", &Some(agent_id.clone()), &line);
                }
                CommandEvent::Error(err) => {
                    rust_log(
                        &app_for_task,
                        "error",
                        "sidecar",
                        Some(agent_id.clone()),
                        format!("agent sidecar error: {err}"),
                    );
                    let _ = app_for_task.emit(
                        "agent-sidecar-exited",
                        serde_json::json!({ "agent_id": agent_id, "error": err }),
                    );
                }
                CommandEvent::Terminated(payload) => {
                    rust_log(
                        &app_for_task,
                        "warn",
                        "sidecar",
                        Some(agent_id.clone()),
                        format!("agent sidecar exited: {payload:?}"),
                    );
                    if let Some(state) = app_for_task.try_state::<SidecarState>() {
                        state.agents.lock().unwrap().remove(&agent_id);
                    }
                    let _ = app_for_task.emit(
                        "agent-sidecar-exited",
                        serde_json::json!({ "agent_id": agent_id, "code": payload.code }),
                    );
                    break;
                }
                _ => {}
            }
        }
    });

    Ok(())
}

/// Hand-rolled HTTP/1.0 GET over a raw TCP socket rather than pulling in an
/// HTTP client crate (reqwest et al.) just to poll one localhost endpoint —
/// keeps the dependency footprint and binary size down for a single-purpose
/// health check.
async fn check_health() -> bool {
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    use tokio::net::TcpStream;
    use tokio::time::timeout;

    let addr = format!("{ORCHESTRATOR_HOST}:{ORCHESTRATOR_PORT}");
    let mut stream = match timeout(Duration::from_millis(500), TcpStream::connect(&addr)).await {
        Ok(Ok(s)) => s,
        _ => return false,
    };

    let req = format!(
        "GET /v1/health HTTP/1.0\r\nHost: {ORCHESTRATOR_HOST}\r\nConnection: close\r\n\r\n"
    );
    if stream.write_all(req.as_bytes()).await.is_err() {
        return false;
    }

    let mut buf = Vec::new();
    if timeout(Duration::from_millis(1000), stream.read_to_end(&mut buf))
        .await
        .is_err()
    {
        return false;
    }

    let text = String::from_utf8_lossy(&buf);
    text.starts_with("HTTP/1.0 200") || text.starts_with("HTTP/1.1 200")
}

/// Result of probing an Ollama instance for installed models. Distinguishes
/// "couldn't even connect" (`reachable: false`) from "connected, but
/// something about the response was off" (`reachable: true`, `error` set,
/// `models` empty) from the happy path — the frontend needs all three to
/// show the user an accurate, actionable message instead of one generic
/// "not reachable" for every failure mode.
#[derive(serde::Serialize)]
struct OllamaProbeResult {
    reachable: bool,
    models: Vec<String>,
    error: Option<String>,
}

/// Splits `http://host[:port][/path]` into its parts without pulling in a
/// full URL-parsing crate for this single call site. Ollama's own server is
/// plain HTTP only (no TLS support), so that's all this needs to handle;
/// anything else is rejected with a clear message rather than silently
/// mishandled.
fn parse_http_url(url: &str) -> Result<(String, u16), String> {
    let rest = url.trim().strip_prefix("http://").ok_or_else(|| {
        "Ollama's URL must start with http:// (Ollama does not serve HTTPS)".to_string()
    })?;
    let authority = match rest.find('/') {
        Some(i) => &rest[..i],
        None => rest,
    };
    if authority.is_empty() {
        return Err(format!("'{url}' is not a valid URL"));
    }
    match authority.rsplit_once(':') {
        Some((host, port_str)) if !host.is_empty() => {
            let port = port_str
                .parse::<u16>()
                .map_err(|_| format!("'{port_str}' is not a valid port in '{url}'"))?;
            Ok((host.to_string(), port))
        }
        _ => Ok((authority.to_string(), 80)),
    }
}

/// Best-effort chunked-transfer-encoding decoder. Not used on the normal
/// path — see the comment below on why the HTTP/1.0 request line generally
/// avoids this — but kept as defense in depth rather than assuming it never
/// happens. Malformed/truncated chunk data returns whatever was decoded so
/// far rather than failing outright.
fn dechunk(body: &[u8]) -> Vec<u8> {
    let mut out = Vec::new();
    let mut rest = body;
    loop {
        let Some(nl) = rest.windows(2).position(|w| w == b"\r\n") else {
            break;
        };
        let size_str = String::from_utf8_lossy(&rest[..nl]);
        let size_str = size_str.split(';').next().unwrap_or("").trim();
        let Ok(size) = usize::from_str_radix(size_str, 16) else {
            break;
        };
        if size == 0 {
            break;
        }
        let chunk_start = nl + 2;
        let chunk_end = (chunk_start + size).min(rest.len());
        out.extend_from_slice(&rest[chunk_start..chunk_end]);
        if chunk_end + 2 > rest.len() {
            break;
        }
        rest = &rest[chunk_end + 2..];
    }
    out
}

/// Probes an Ollama instance for installed models by talking raw HTTP/1.0
/// over a `tokio::net::TcpStream` — deliberately NOT `fetch()` from the
/// frontend. See this module's top-level doc comment for why: the webview's
/// own network stack blocks this exact request via Private Network Access,
/// even when Ollama is genuinely running with models installed, which is
/// what a real Windows test run surfaced. A Rust-side socket is not a
/// browser page and isn't subject to that restriction at all.
#[tauri::command]
async fn detect_ollama_models(url: String) -> Result<OllamaProbeResult, String> {
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    use tokio::net::TcpStream;
    use tokio::time::timeout;

    let (host, port) = parse_http_url(&url)?;
    let addr = format!("{host}:{port}");

    let mut stream = match timeout(Duration::from_millis(2500), TcpStream::connect(&addr)).await {
        Ok(Ok(s)) => s,
        Ok(Err(e)) => {
            return Ok(OllamaProbeResult {
                reachable: false,
                models: vec![],
                error: Some(format!("could not connect to {url}: {e}")),
            })
        }
        Err(_) => {
            return Ok(OllamaProbeResult {
                reachable: false,
                models: vec![],
                error: Some(format!("timed out connecting to {url}")),
            })
        }
    };

    // HTTP/1.0, not 1.1: a well-behaved server (Ollama included — it's a
    // plain Go net/http server) will not switch to chunked transfer
    // encoding for a client that identifies as HTTP/1.0, since chunked
    // encoding is an HTTP/1.1-only feature. That sidesteps needing a fully
    // general chunked decoder on the happy path (dechunk() above still
    // exists as a defensive fallback, not the primary path).
    let req =
        format!("GET /api/tags HTTP/1.0\r\nHost: {host}\r\nConnection: close\r\n\r\n");
    if let Err(e) = stream.write_all(req.as_bytes()).await {
        return Ok(OllamaProbeResult {
            reachable: false,
            models: vec![],
            error: Some(format!("could not send request to {url}: {e}")),
        });
    }

    let mut buf = Vec::new();
    if timeout(Duration::from_millis(5000), stream.read_to_end(&mut buf))
        .await
        .is_err()
    {
        return Ok(OllamaProbeResult {
            reachable: false,
            models: vec![],
            error: Some(format!("timed out reading a response from {url}")),
        });
    }

    let sep = b"\r\n\r\n";
    let split_at = buf.windows(sep.len()).position(|w| w == sep);
    let (head_bytes, body_bytes): (&[u8], &[u8]) = match split_at {
        Some(pos) => (&buf[..pos], &buf[pos + sep.len()..]),
        None => (&buf[..], &[]),
    };
    let head = String::from_utf8_lossy(head_bytes);

    let status_line = head.lines().next().unwrap_or("");
    if !(status_line.starts_with("HTTP/1.0 200") || status_line.starts_with("HTTP/1.1 200")) {
        return Ok(OllamaProbeResult {
            reachable: true,
            models: vec![],
            error: Some(format!(
                "Ollama responded unexpectedly ({})",
                if status_line.is_empty() { "empty response" } else { status_line }
            )),
        });
    }

    let is_chunked = head.to_ascii_lowercase().contains("transfer-encoding: chunked");
    let body_owned;
    let body: &[u8] = if is_chunked {
        body_owned = dechunk(body_bytes);
        &body_owned
    } else {
        body_bytes
    };

    let parsed: serde_json::Value = match serde_json::from_slice(body) {
        Ok(v) => v,
        Err(e) => {
            return Ok(OllamaProbeResult {
                reachable: true,
                models: vec![],
                error: Some(format!("could not parse Ollama's response as JSON: {e}")),
            })
        }
    };

    let models: Vec<String> = parsed
        .get("models")
        .and_then(|m| m.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|m| m.get("name").and_then(|n| n.as_str()).map(String::from))
                .collect()
        })
        .unwrap_or_default();

    Ok(OllamaProbeResult {
        reachable: true,
        models,
        error: None,
    })
}

#[cfg(test)]
mod ollama_probe_tests {
    use super::*;
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    use tokio::net::TcpListener;

    #[test]
    fn parse_http_url_with_port() {
        assert_eq!(
            parse_http_url("http://localhost:11434").unwrap(),
            ("localhost".to_string(), 11434)
        );
        assert_eq!(
            parse_http_url("http://127.0.0.1:11434/api/tags").unwrap(),
            ("127.0.0.1".to_string(), 11434)
        );
    }

    #[test]
    fn parse_http_url_without_port_defaults_to_80() {
        assert_eq!(
            parse_http_url("http://localhost").unwrap(),
            ("localhost".to_string(), 80)
        );
    }

    #[test]
    fn parse_http_url_rejects_https() {
        assert!(parse_http_url("https://localhost:11434").is_err());
    }

    #[test]
    fn parse_http_url_rejects_garbage() {
        assert!(parse_http_url("not a url").is_err());
        assert!(parse_http_url("http://").is_err());
    }

    #[test]
    fn dechunk_decodes_simple_chunked_body() {
        let chunked = b"4\r\ntest\r\n5\r\nhello\r\n0\r\n\r\n";
        assert_eq!(dechunk(chunked), b"testhello".to_vec());
    }

    /// End-to-end against a real TCP listener standing in for Ollama —
    /// exercises the exact code path that broke in the field (connect,
    /// send, read to EOF, split head/body, parse JSON), just against a
    /// loopback socket instead of a real `ollama serve`.
    async fn respond_and_get_probe(response: &'static [u8]) -> OllamaProbeResult {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();

        let server = tokio::spawn(async move {
            let (mut sock, _) = listener.accept().await.unwrap();
            let mut req_buf = [0u8; 1024];
            let _ = sock.read(&mut req_buf).await;
            sock.write_all(response).await.unwrap();
            sock.shutdown().await.ok();
        });

        let result = detect_ollama_models(format!("http://127.0.0.1:{port}"))
            .await
            .unwrap();
        server.await.unwrap();
        result
    }

    #[tokio::test]
    async fn detects_models_from_a_real_response() {
        let response = b"HTTP/1.0 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n{\"models\":[{\"name\":\"llama3.1:8b\"},{\"name\":\"mistral:7b\"}]}";
        let result = respond_and_get_probe(response).await;
        assert!(result.reachable);
        assert_eq!(result.models, vec!["llama3.1:8b", "mistral:7b"]);
        assert!(result.error.is_none());
    }

    #[tokio::test]
    async fn reports_reachable_with_no_models() {
        let response =
            b"HTTP/1.0 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n{\"models\":[]}";
        let result = respond_and_get_probe(response).await;
        assert!(result.reachable);
        assert!(result.models.is_empty());
    }

    #[tokio::test]
    async fn reports_unreachable_when_nothing_is_listening() {
        // Port 1 is a reserved low port essentially guaranteed to have
        // nothing bound to it in any test environment.
        let result = detect_ollama_models("http://127.0.0.1:1".to_string())
            .await
            .unwrap();
        assert!(!result.reachable);
        assert!(result.error.is_some());
    }

    #[tokio::test]
    async fn handles_chunked_transfer_encoding_defensively() {
        // Chunk size is the hex byte length of the JSON payload below (25 = 0x19) —
        // verified with Python's len() rather than hand-counted, since a wrong
        // count here would test nothing (an earlier draft got this wrong and the
        // resulting failure was a bug in the test data, not in dechunk()).
        let response = b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n19\r\n{\"models\":[{\"name\":\"x\"}]}\r\n0\r\n\r\n";
        let result = respond_and_get_probe(response).await;
        assert!(result.reachable);
        assert_eq!(result.models, vec!["x"]);
    }
}
