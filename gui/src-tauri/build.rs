use std::path::PathBuf;

fn main() {
    // 确保 binaries/ 目录和 ffmpeg 占位文件存在，避免 tauri-build 报错
    // 真正的 ffmpeg 二进制需要通过 scripts/download-ffmpeg.sh 下载
    let target_triple = std::env::var("TAURI_ENV_TARGET_TRIPLE")
        .unwrap_or_else(|_| "aarch64-apple-darwin".to_string());

    let binaries_dir = PathBuf::from("binaries");
    std::fs::create_dir_all(&binaries_dir).ok();

    let ffmpeg_path = binaries_dir.join(format!("ffmpeg-{target_triple}"));
    if !ffmpeg_path.exists() {
        // 创建占位脚本，输出提示信息
        std::fs::write(
            &ffmpeg_path,
            "#!/bin/sh\necho 'ffmpeg not bundled. Run: make download-ffmpeg' >&2\nexit 1\n",
        )
        .ok();

        // 设置可执行权限
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(&ffmpeg_path, std::fs::Permissions::from_mode(0o755)).ok();
        }

        println!(
            "cargo:warning=ffmpeg binary not found at {}. Run 'make download-ffmpeg' to bundle ffmpeg.",
            ffmpeg_path.display()
        );
    }

    tauri_build::build()
}
