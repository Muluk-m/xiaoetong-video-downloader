use std::path::PathBuf;
use std::process::{Child, Command};
use std::sync::Mutex;
use tauri::Manager;

struct PythonServer(Mutex<Option<Child>>);

/// 查找项目根目录（包含 backend/server.py 的目录）
fn find_project_root() -> Option<PathBuf> {
    // 开发模式下，cwd 通常是 gui/src-tauri 或 gui/
    // 我们需要找到包含 backend/server.py 的上层目录
    let candidates = vec![
        // 从 gui/ 目录启动
        std::env::current_dir().ok().and_then(|p| p.parent().map(|x| x.to_path_buf())),
        // 从 gui/src-tauri/ 目录启动
        std::env::current_dir().ok().and_then(|p| p.parent().and_then(|x| x.parent()).map(|x| x.to_path_buf())),
        // 从项目根目录启动
        std::env::current_dir().ok(),
        // 通过 CARGO_MANIFEST_DIR（编译时）
        option_env!("CARGO_MANIFEST_DIR").map(|s| PathBuf::from(s).parent().and_then(|p| p.parent()).map(|p| p.to_path_buf())).flatten(),
    ];

    for candidate in candidates.into_iter().flatten() {
        if candidate.join("backend/server.py").exists() {
            return Some(candidate);
        }
    }
    None
}

/// 解析 bundled ffmpeg 路径
/// 查找优先级：{exe_dir}/ffmpeg-{target_triple} → {exe_dir}/ffmpeg → 系统 "ffmpeg"
fn resolve_ffmpeg_path() -> String {
    let target_triple = if cfg!(target_arch = "aarch64") {
        "aarch64-apple-darwin"
    } else if cfg!(target_arch = "x86_64") {
        "x86_64-apple-darwin"
    } else {
        ""
    };

    if let Ok(exe_path) = std::env::current_exe() {
        if let Some(exe_dir) = exe_path.parent() {
            // 优先查找带 target triple 的版本
            if !target_triple.is_empty() {
                let named = exe_dir.join(format!("ffmpeg-{target_triple}"));
                if named.exists() {
                    println!("FFMPEG_PATH: {}", named.display());
                    return named.to_string_lossy().into_owned();
                }
            }
            // 再查找不带后缀的版本
            let plain = exe_dir.join("ffmpeg");
            if plain.exists() {
                println!("FFMPEG_PATH: {}", plain.display());
                return plain.to_string_lossy().into_owned();
            }
        }
    }

    // 回退到系统 PATH
    println!("FFMPEG_PATH: ffmpeg (system)");
    "ffmpeg".to_string()
}

#[tauri::command]
fn get_api_port() -> u16 {
    19528
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![get_api_port])
        .setup(|_app| {
            let project_root = find_project_root();

            if project_root.is_none() {
                eprintln!("WARNING: Could not find project root (backend/server.py not found)");
                return Ok(());
            }

            let root = project_root.unwrap();
            let backend_script = root.join("backend/server.py");

            println!("Project root: {:?}", root);
            println!("Backend script: {:?}", backend_script);

            let ffmpeg_path = resolve_ffmpeg_path();

            // 尝试多个 Python 路径
            let python_paths = vec![
                root.join(".venv/bin/python3"),
                root.join(".venv/bin/python"),
                PathBuf::from("python3"),
                PathBuf::from("python"),
            ];

            let mut child: Option<Child> = None;

            for python_path in &python_paths {
                match Command::new(python_path)
                    .arg(&backend_script)
                    .current_dir(&root)
                    .env("PYO3_USE_ABI3_FORWARD_COMPATIBILITY", "1")
                    .env("FFMPEG_PATH", &ffmpeg_path)
                    .spawn()
                {
                    Ok(c) => {
                        println!("Python backend started with: {:?}", python_path);
                        child = Some(c);
                        break;
                    }
                    Err(e) => {
                        println!("Failed to start with {:?}: {}", python_path, e);
                    }
                }
            }

            if child.is_none() {
                eprintln!("WARNING: Failed to start Python backend with any Python interpreter");
            }

            _app.manage(PythonServer(Mutex::new(child)));
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                if let Some(state) = window.try_state::<PythonServer>() {
                    if let Ok(mut guard) = state.0.lock() {
                        if let Some(ref mut child) = *guard {
                            let _ = child.kill();
                            println!("Python backend stopped");
                        }
                    }
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
