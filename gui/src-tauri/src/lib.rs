use serde::Serialize;
use std::collections::VecDeque;
use std::io::{BufRead, BufReader};
use std::net::TcpStream;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use tauri::Manager;

const MAX_LOG_ENTRIES: usize = 500;
const BACKEND_PORT: u16 = 19528;
const HEALTH_CHECK_TIMEOUT_SECS: u64 = 30;

// ============ State types ============

#[derive(Debug, Clone, Serialize, PartialEq)]
#[serde(rename_all = "snake_case")]
enum BackendStatus {
    Starting,
    Running,
    Failed,
    NotFound,
}

#[derive(Debug, Clone, Serialize)]
struct LogEntry {
    timestamp: u64,
    stream: String, // "stdout" | "stderr"
    message: String,
}

struct AppStateInner {
    child: Option<Child>,
    status: BackendStatus,
    logs: VecDeque<LogEntry>,
    startup_error: Option<String>,
}

struct AppState(Arc<Mutex<AppStateInner>>);

// ============ Sidecar / project resolution ============

fn resolve_sidecar_path(name: &str) -> Option<String> {
    let target_triple = if cfg!(target_arch = "aarch64") {
        "aarch64-apple-darwin"
    } else if cfg!(target_arch = "x86_64") {
        "x86_64-apple-darwin"
    } else {
        ""
    };

    let exe_dir = std::env::current_exe().ok()?.parent()?.to_path_buf();

    if !target_triple.is_empty() {
        let named = exe_dir.join(format!("{name}-{target_triple}"));
        if named.exists() {
            return Some(named.to_string_lossy().into_owned());
        }
    }

    let plain = exe_dir.join(name);
    if plain.exists() {
        return Some(plain.to_string_lossy().into_owned());
    }

    None
}

fn find_project_root() -> Option<PathBuf> {
    let candidates = vec![
        std::env::current_dir()
            .ok()
            .and_then(|p| p.parent().map(|x| x.to_path_buf())),
        std::env::current_dir()
            .ok()
            .and_then(|p| p.parent().and_then(|x| x.parent()).map(|x| x.to_path_buf())),
        std::env::current_dir().ok(),
        option_env!("CARGO_MANIFEST_DIR")
            .map(|s| {
                PathBuf::from(s)
                    .parent()
                    .and_then(|p| p.parent())
                    .map(|p| p.to_path_buf())
            })
            .flatten(),
    ];

    for candidate in candidates.into_iter().flatten() {
        if candidate.join("backend/server.py").exists() {
            return Some(candidate);
        }
    }
    None
}

fn now_millis() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64
}

fn push_log(state: &Arc<Mutex<AppStateInner>>, stream: &str, message: String) {
    if let Ok(mut guard) = state.lock() {
        if guard.logs.len() >= MAX_LOG_ENTRIES {
            guard.logs.pop_front();
        }
        guard.logs.push_back(LogEntry {
            timestamp: now_millis(),
            stream: stream.to_string(),
            message,
        });
    }
}

// ============ Backend spawning ============

/// Spawn the backend process, set up stdout/stderr reader threads and health check.
/// Returns the Arc state (already updated).
fn spawn_backend(state: &Arc<Mutex<AppStateInner>>, ffmpeg_path: &str) {
    // Clear previous state
    {
        let mut guard = state.lock().unwrap();
        // Kill old child if any
        if let Some(ref mut child) = guard.child {
            let _ = child.kill();
            let _ = child.wait();
        }
        guard.child = None;
        guard.status = BackendStatus::Starting;
        guard.logs.clear();
        guard.startup_error = None;
    }

    push_log(state, "stdout", format!("FFMPEG_PATH: {}", ffmpeg_path));

    let mut child_result: Result<Child, String> = Err("No backend found".to_string());

    // Try bundled backend first
    if let Some(backend_path) = resolve_sidecar_path("backend-server") {
        push_log(
            state,
            "stdout",
            format!("Starting bundled backend: {}", backend_path),
        );
        match Command::new(&backend_path)
            .env("FFMPEG_PATH", ffmpeg_path)
            .env("PYTHONUNBUFFERED", "1")
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
        {
            Ok(c) => {
                push_log(state, "stdout", "Bundled backend started successfully".into());
                child_result = Ok(c);
            }
            Err(e) => {
                let msg = format!("Failed to start bundled backend: {}", e);
                push_log(state, "stderr", msg.clone());
                child_result = Err(msg);
            }
        }
    } else {
        // Dev mode: fall back to Python
        push_log(
            state,
            "stdout",
            "No bundled backend found, falling back to Python dev mode".into(),
        );

        if let Some(root) = find_project_root() {
            let backend_script = root.join("backend/server.py");
            push_log(
                state,
                "stdout",
                format!("Project root: {:?}", root),
            );
            push_log(
                state,
                "stdout",
                format!("Backend script: {:?}", backend_script),
            );

            let python_paths = vec![
                root.join(".venv/bin/python3"),
                root.join(".venv/bin/python"),
                PathBuf::from("python3"),
                PathBuf::from("python"),
            ];

            for python_path in &python_paths {
                match Command::new(python_path)
                    .arg(&backend_script)
                    .current_dir(&root)
                    .env("PYO3_USE_ABI3_FORWARD_COMPATIBILITY", "1")
                    .env("FFMPEG_PATH", ffmpeg_path)
                    .env("PYTHONUNBUFFERED", "1")
                    .stdout(Stdio::piped())
                    .stderr(Stdio::piped())
                    .spawn()
                {
                    Ok(c) => {
                        push_log(
                            state,
                            "stdout",
                            format!("Python backend started with: {:?}", python_path),
                        );
                        child_result = Ok(c);
                        break;
                    }
                    Err(e) => {
                        push_log(
                            state,
                            "stderr",
                            format!("Failed to start with {:?}: {}", python_path, e),
                        );
                    }
                }
            }
        } else {
            let msg = "Could not find project root (backend/server.py not found)".to_string();
            push_log(state, "stderr", msg.clone());
            child_result = Err(msg);
        }
    }

    match child_result {
        Ok(mut child) => {
            // Take stdout/stderr before moving child
            let stdout = child.stdout.take();
            let stderr = child.stderr.take();

            {
                let mut guard = state.lock().unwrap();
                guard.child = Some(child);
            }

            // Spawn stdout reader thread
            if let Some(stdout) = stdout {
                let state_clone = Arc::clone(state);
                std::thread::spawn(move || {
                    let reader = BufReader::new(stdout);
                    for line in reader.lines() {
                        match line {
                            Ok(text) => push_log(&state_clone, "stdout", text),
                            Err(_) => break,
                        }
                    }
                });
            }

            // Spawn stderr reader thread
            if let Some(stderr) = stderr {
                let state_clone = Arc::clone(state);
                std::thread::spawn(move || {
                    let reader = BufReader::new(stderr);
                    for line in reader.lines() {
                        match line {
                            Ok(text) => push_log(&state_clone, "stderr", text),
                            Err(_) => break,
                        }
                    }
                });
            }

            // Spawn health check thread
            let state_clone = Arc::clone(state);
            std::thread::spawn(move || {
                let addr = format!("127.0.0.1:{}", BACKEND_PORT);
                let start = std::time::Instant::now();
                loop {
                    // Check if process has exited unexpectedly
                    {
                        let mut guard = state_clone.lock().unwrap();
                        if let Some(ref mut child) = guard.child {
                            match child.try_wait() {
                                Ok(Some(exit_status)) => {
                                    let msg = format!(
                                        "Backend process exited with status: {}",
                                        exit_status
                                    );
                                    guard.status = BackendStatus::Failed;
                                    guard.startup_error = Some(msg);
                                    return;
                                }
                                Ok(None) => {} // still running
                                Err(e) => {
                                    guard.status = BackendStatus::Failed;
                                    guard.startup_error =
                                        Some(format!("Failed to check process status: {}", e));
                                    return;
                                }
                            }
                        }
                    }

                    if TcpStream::connect_timeout(
                        &addr.parse().unwrap(),
                        Duration::from_secs(1),
                    )
                    .is_ok()
                    {
                        {
                            let mut guard = state_clone.lock().unwrap();
                            guard.status = BackendStatus::Running;
                        }
                        push_log(
                            &state_clone,
                            "stdout",
                            "Health check passed, backend is running".into(),
                        );
                        return;
                    }

                    if start.elapsed().as_secs() >= HEALTH_CHECK_TIMEOUT_SECS {
                        let mut guard = state_clone.lock().unwrap();
                        guard.status = BackendStatus::Failed;
                        guard.startup_error = Some(format!(
                            "Backend failed to start within {} seconds",
                            HEALTH_CHECK_TIMEOUT_SECS
                        ));
                        return;
                    }

                    std::thread::sleep(Duration::from_secs(1));
                }
            });
        }
        Err(msg) => {
            let mut guard = state.lock().unwrap();
            guard.status = BackendStatus::NotFound;
            guard.startup_error = Some(msg);
        }
    }
}

// ============ Tauri commands ============

#[tauri::command]
fn get_api_port() -> u16 {
    BACKEND_PORT
}

#[derive(Serialize)]
struct StatusResponse {
    status: BackendStatus,
    error: Option<String>,
}

#[tauri::command]
fn get_backend_status(state: tauri::State<'_, AppState>) -> StatusResponse {
    let guard = state.0.lock().unwrap();
    StatusResponse {
        status: guard.status.clone(),
        error: guard.startup_error.clone(),
    }
}

#[derive(Serialize)]
struct LogsResponse {
    total: usize,
    logs: Vec<LogEntry>,
}

#[tauri::command]
fn get_backend_logs(state: tauri::State<'_, AppState>, since: Option<u64>) -> LogsResponse {
    let guard = state.0.lock().unwrap();
    let since_ts = since.unwrap_or(0);
    let filtered: Vec<LogEntry> = guard
        .logs
        .iter()
        .filter(|entry| entry.timestamp > since_ts)
        .cloned()
        .collect();
    LogsResponse {
        total: guard.logs.len(),
        logs: filtered,
    }
}

#[tauri::command]
fn restart_backend(state: tauri::State<'_, AppState>) -> StatusResponse {
    let ffmpeg_path = resolve_sidecar_path("ffmpeg").unwrap_or_else(|| "ffmpeg".to_string());
    spawn_backend(&state.0, &ffmpeg_path);
    let guard = state.0.lock().unwrap();
    StatusResponse {
        status: guard.status.clone(),
        error: guard.startup_error.clone(),
    }
}

// ============ App entry ============

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![
            get_api_port,
            get_backend_status,
            get_backend_logs,
            restart_backend,
        ])
        .setup(|app| {
            let state = Arc::new(Mutex::new(AppStateInner {
                child: None,
                status: BackendStatus::Starting,
                logs: VecDeque::new(),
                startup_error: None,
            }));

            let ffmpeg_path =
                resolve_sidecar_path("ffmpeg").unwrap_or_else(|| "ffmpeg".to_string());

            spawn_backend(&state, &ffmpeg_path);

            app.manage(AppState(Arc::clone(&state)));
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                if let Some(state) = window.try_state::<AppState>() {
                    if let Ok(mut guard) = state.0.lock() {
                        if let Some(ref mut child) = guard.child {
                            let _ = child.kill();
                        }
                    }
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
