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

use std::sync::Mutex;
use std::time::Duration;

use tauri::{AppHandle, Emitter, Manager};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

const ORCHESTRATOR_HOST: &str = "127.0.0.1";
const ORCHESTRATOR_PORT: u16 = 8080;
const ORCHESTRATOR_URL: &str = "http://127.0.0.1:8080";
const HEALTH_POLL_TIMEOUT_S: u64 = 15;

/// Holds the sidecar child process IF this Console instance spawned one, so
/// it can be killed on exit. `None` if we connected to an already-running
/// orchestrator instead — in that case, exiting the Console must NOT kill it
/// (it isn't ours to kill: some other launch, or a manually-run server tier).
struct SidecarState(Mutex<Option<CommandChild>>);

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
        .manage(SidecarState(Mutex::new(None)))
        .manage(LastStatus(Mutex::new(
            serde_json::json!({ "status": "checking", "url": null, "error": null }),
        )))
        .invoke_handler(tauri::generate_handler![get_orchestrator_status])
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
                if let Some(child) = state.0.lock().unwrap().take() {
                    let _ = child.kill();
                }
            }
        }
    });
}

fn kill_sidecar_if_owned<R: tauri::Runtime>(manager: &impl Manager<R>) {
    let child = manager.state::<SidecarState>().0.lock().unwrap().take();
    if let Some(child) = child {
        // Best-effort: the process may have already exited on its own. A
        // desktop orchestrator we spawned should not outlive the Console
        // window/app that owns it.
        let _ = child.kill();
    }
}

async fn manage_orchestrator(app: AppHandle) {
    if check_health().await {
        emit_status(
            &app,
            serde_json::json!({ "status": "existing", "url": ORCHESTRATOR_URL, "error": null }),
        );
        return;
    }

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
    let sidecar = sidecar.env("GRUPER_EXIT_WITH_PARENT", "1");

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
        *state.0.lock().unwrap() = Some(child);
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
