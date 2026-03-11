use std::path::PathBuf;

fn main() {
    // 确保 binaries/ 目录和 sidecar 占位文件存在，避免 tauri-build 报错
    // 真正的二进制需要通过对应的构建脚本生成
    let target_triple = std::env::var("TAURI_ENV_TARGET_TRIPLE")
        .unwrap_or_else(|_| "aarch64-apple-darwin".to_string());

    let binaries_dir = PathBuf::from("binaries");
    std::fs::create_dir_all(&binaries_dir).ok();

    let binaries = [
        ("ffmpeg", "make download-ffmpeg"),
        ("backend-server", "make build-backend"),
    ];

    for (name, hint) in binaries {
        let path = binaries_dir.join(format!("{name}-{target_triple}"));
        if !path.exists() {
            // 创建占位脚本，输出提示信息
            std::fs::write(
                &path,
                format!("#!/bin/sh\necho '{name} not bundled. Run: {hint}' >&2\nexit 1\n"),
            )
            .ok();

            // 设置可执行权限
            #[cfg(unix)]
            {
                use std::os::unix::fs::PermissionsExt;
                std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o755)).ok();
            }

            println!(
                "cargo:warning={name} binary not found at {}. Run '{hint}' to build it.",
                path.display()
            );
        }
    }

    tauri_build::build()
}
