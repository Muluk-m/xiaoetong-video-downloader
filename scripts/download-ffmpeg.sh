#!/usr/bin/env bash
# 下载 ffmpeg 静态二进制到 gui/src-tauri/binaries/
# 用法:
#   bash scripts/download-ffmpeg.sh          # 下载当前架构
#   bash scripts/download-ffmpeg.sh --all    # 下载 arm64 + x86_64

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BINARIES_DIR="$PROJECT_ROOT/gui/src-tauri/binaries"

# ffmpeg 静态构建下载源 (evermeet.cx 提供 macOS 静态构建)
FFMPEG_VERSION="7.1"
BASE_URL="https://evermeet.cx/ffmpeg"

mkdir -p "$BINARIES_DIR"

download_ffmpeg() {
    local arch="$1"
    local target_triple

    case "$arch" in
        arm64)  target_triple="aarch64-apple-darwin" ;;
        x86_64) target_triple="x86_64-apple-darwin" ;;
        *)
            echo "Error: unsupported architecture: $arch"
            exit 1
            ;;
    esac

    local output_path="$BINARIES_DIR/ffmpeg-$target_triple"

    if [ -f "$output_path" ]; then
        echo "Already exists: $output_path"
        return 0
    fi

    echo "Downloading ffmpeg for $arch ($target_triple)..."

    # 下载 zip 到临时目录
    local tmp_dir
    tmp_dir="$(mktemp -d)"
    trap "rm -rf '$tmp_dir'" EXIT

    local zip_file="$tmp_dir/ffmpeg.zip"

    # evermeet.cx 提供的是通用二进制 (universal)
    curl -L --fail --progress-bar \
        -o "$zip_file" \
        "$BASE_URL/ffmpeg-${FFMPEG_VERSION}.zip" \
    || {
        echo "Error: failed to download ffmpeg from $BASE_URL"
        echo "You can manually download ffmpeg and place it at: $output_path"
        exit 1
    }

    # 解压
    unzip -o -q "$zip_file" -d "$tmp_dir"

    # 移动到目标路径
    mv "$tmp_dir/ffmpeg" "$output_path"
    chmod +x "$output_path"

    echo "Downloaded: $output_path"
    file "$output_path"
}

if [ "${1:-}" = "--all" ]; then
    echo "Downloading ffmpeg for all architectures..."
    download_ffmpeg "arm64"
    # 对于 evermeet.cx 的通用二进制，两个架构用同一个文件
    cp "$BINARIES_DIR/ffmpeg-aarch64-apple-darwin" "$BINARIES_DIR/ffmpeg-x86_64-apple-darwin"
    echo ""
    echo "Done! Both architectures ready."
else
    # 检测当前架构
    ARCH="$(uname -m)"
    echo "Detected architecture: $ARCH"
    download_ffmpeg "$ARCH"
    echo ""
    echo "Done!"
fi

echo ""
echo "Files in $BINARIES_DIR:"
ls -lh "$BINARIES_DIR/"
