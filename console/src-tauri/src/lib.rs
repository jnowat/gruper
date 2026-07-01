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

use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::Mutex;
use std::time::Duration;

use tauri::{AppHandle, Emitter, Manager};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

const ORCHESTRATOR_HOST: &str = "127.0.0.1";
const ORCHESTRATOR_PORT: u16 = 8080;
const ORCHESTRATOR_URL: &str = "http://127.0.0.1:8080";
const HEALTH_POLL_TIMEOUT_S: u64 = 15;

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
        .invoke_handler(tauri::generate_handler![
            get_orchestrator_status,
            spawn_local_agent
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

async fn manage_orchestrator(app: AppHandle) {
    if check_health().await {
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

    // Drain the sidecar's stdout/stderr into the Console's own log — the
    // orchestrator logs its own startup/migration/request activity, which
    // is invaluable for diagnosing a "failed to start" report from a user.
    tauri::async_runtime::spawn(async move {
        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(line) => {
                    eprintln!("[orchestrator] {}", String::from_utf8_lossy(&line));
                }
                CommandEvent::Stderr(line) => {
                    eprintln!("[orchestrator] {}", String::from_utf8_lossy(&line));
                }
                CommandEvent::Error(err) => {
                    eprintln!("[orchestrator] error: {err}");
                }
                CommandEvent::Terminated(payload) => {
                    eprintln!("[orchestrator] exited: {:?}", payload);
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
#[tauri::command]
async fn spawn_local_agent(
    app: AppHandle,
    agent_id: String,
    jwt_token: String,
    orchestrator_url: String,
    ollama_url: Option<String>,
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

    let (mut rx, child) = sidecar
        .spawn()
        .map_err(|e| format!("failed to start local agent {agent_id}: {e}"))?;

    if let Some(state) = app.try_state::<SidecarState>() {
        state
            .agents
            .lock()
            .unwrap()
            .insert(agent_id.clone(), child);
    }

    // Drain stdout/stderr into the Console's own log, same as the
    // orchestrator sidecar — invaluable for diagnosing why a freshly-added
    // agent never shows up as online.
    tauri::async_runtime::spawn(async move {
        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(line) | CommandEvent::Stderr(line) => {
                    eprintln!("[agent:{agent_id}] {}", String::from_utf8_lossy(&line));
                }
                CommandEvent::Error(err) => {
                    eprintln!("[agent:{agent_id}] error: {err}");
                }
                CommandEvent::Terminated(payload) => {
                    eprintln!("[agent:{agent_id}] exited: {:?}", payload);
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
