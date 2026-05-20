#!/usr/bin/env bash
# 下载 ffmpeg 静态二进制到 gui/src-tauri/binaries/
# 用法:
#   bash scripts/download-ffmpeg.sh          # 下载当前架构
#   bash scripts/download-ffmpeg.sh --all    # 下载 arm64 + x86_64

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BINARIES_DIR="$PROJECT_ROOT/gui/src-tauri/binaries"

# ffmpeg 静态构建下载源:
# - arm64: osxexperts.net 提供 Apple Silicon 静态构建
# - x86_64: evermeet.cx 提供 Intel 静态构建
# 历史教训: evermeet.cx 的 zip 实际只含 x86_64 二进制, 不能当 universal 用
FFMPEG_ARM64_URL="https://www.osxexperts.net/ffmpeg711arm.zip"
FFMPEG_X86_64_URL="https://evermeet.cx/ffmpeg/ffmpeg-7.1.zip"

mkdir -p "$BINARIES_DIR"

download_ffmpeg() {
    local arch="$1"
    local target_triple
    local url
    local expected_lipo_arch

    case "$arch" in
        arm64)
            target_triple="aarch64-apple-darwin"
            url="$FFMPEG_ARM64_URL"
            expected_lipo_arch="arm64"
            ;;
        x86_64)
            target_triple="x86_64-apple-darwin"
            url="$FFMPEG_X86_64_URL"
            expected_lipo_arch="x86_64"
            ;;
        *)
            echo "Error: unsupported architecture: $arch"
            exit 1
            ;;
    esac

    local output_path="$BINARIES_DIR/ffmpeg-$target_triple"

    if [ -f "$output_path" ]; then
        # 已存在时校验架构, 不匹配则重新下载
        if lipo -info "$output_path" 2>/dev/null | grep -q "$expected_lipo_arch"; then
            echo "Already exists (arch ok): $output_path"
            return 0
        fi
        echo "Existing $output_path is wrong arch, redownloading..."
        rm -f "$output_path"
    fi

    echo "Downloading ffmpeg for $arch ($target_triple) from $url ..."

    local tmp_dir
    tmp_dir="$(mktemp -d)"
    trap "rm -rf '$tmp_dir'" EXIT

    local zip_file="$tmp_dir/ffmpeg.zip"

    curl -L --fail --progress-bar \
        --retry 5 --retry-delay 2 --retry-all-errors \
        --connect-timeout 30 --speed-time 30 --speed-limit 1024 \
        -o "$zip_file" "$url" || {
        echo "Error: failed to download ffmpeg from $url"
        echo "You can manually download ffmpeg and place it at: $output_path"
        exit 1
    }

    unzip -o -q "$zip_file" -d "$tmp_dir"

    # 找到解压后的 ffmpeg 可执行文件 (可能在子目录里)
    local extracted
    extracted="$(find "$tmp_dir" -type f -name ffmpeg -perm +111 | head -n1)"
    if [ -z "$extracted" ]; then
        extracted="$(find "$tmp_dir" -type f -name ffmpeg | head -n1)"
    fi
    if [ -z "$extracted" ]; then
        echo "Error: ffmpeg binary not found inside $url archive"
        exit 1
    fi

    mv "$extracted" "$output_path"
    chmod +x "$output_path"

    # 架构校验: 防止再次出现 x86_64 冒充 aarch64
    if ! lipo -info "$output_path" | grep -q "$expected_lipo_arch"; then
        echo "Error: downloaded ffmpeg arch mismatch (expected $expected_lipo_arch):"
        lipo -info "$output_path"
        exit 1
    fi

    echo "Downloaded: $output_path"
    file "$output_path"
    lipo -info "$output_path"
}

if [ "${1:-}" = "--all" ]; then
    echo "Downloading ffmpeg for arm64 + x86_64..."
    download_ffmpeg "arm64"
    download_ffmpeg "x86_64"
    echo ""
    echo "Done! Both architectures ready."
else
    ARCH="$(uname -m)"
    echo "Detected architecture: $ARCH"
    download_ffmpeg "$ARCH"
    echo ""
    echo "Done!"
fi

echo ""
echo "Files in $BINARIES_DIR:"
ls -lh "$BINARIES_DIR/"
