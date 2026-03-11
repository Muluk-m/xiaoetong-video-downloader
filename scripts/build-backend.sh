#!/usr/bin/env bash
# 用 PyInstaller 打包后端为独立可执行文件，输出到 gui/src-tauri/binaries/
# 用法: bash scripts/build-backend.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BINARIES_DIR="$PROJECT_ROOT/gui/src-tauri/binaries"

# 检测当前架构，生成 target triple
ARCH="$(uname -m)"
case "$ARCH" in
    arm64)  TARGET_TRIPLE="aarch64-apple-darwin" ;;
    x86_64) TARGET_TRIPLE="x86_64-apple-darwin" ;;
    *)
        echo "Error: unsupported architecture: $ARCH"
        exit 1
        ;;
esac

echo "Building backend for $ARCH ($TARGET_TRIPLE)..."

# 确保 PyInstaller 已安装
if ! python3 -c "import PyInstaller" 2>/dev/null; then
    echo "Installing PyInstaller..."
    pip3 install pyinstaller
fi

mkdir -p "$BINARIES_DIR"

# 运行 PyInstaller
cd "$PROJECT_ROOT/backend"
python3 -m PyInstaller backend.spec \
    --distpath "$BINARIES_DIR" \
    --workpath "$PROJECT_ROOT/build/pyinstaller" \
    --noconfirm

# PyInstaller onefile 模式直接输出 backend-server，重命名为 Tauri sidecar 格式
BUILT="$BINARIES_DIR/backend-server"
TARGET="$BINARIES_DIR/backend-server-$TARGET_TRIPLE"

if [ -f "$BUILT" ]; then
    mv "$BUILT" "$TARGET"
    chmod +x "$TARGET"
    echo ""
    echo "Built: $TARGET"
    file "$TARGET"
    ls -lh "$TARGET"
else
    echo "Error: PyInstaller output not found at $BUILT"
    exit 1
fi

echo ""
echo "Done! Backend binary ready for Tauri bundling."
