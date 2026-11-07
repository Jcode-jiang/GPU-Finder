#!/bin/bash
# 构建 GPU Finder.app（macOS 状态栏应用）
# 用法: ./macos/build.sh [--install]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_NAME="GPU Finder"
APP="$ROOT/dist/$APP_NAME.app"
BUILD="$ROOT/build"
MODULE_CACHE="$BUILD/.swift-cache"
PYTHON="${PYTHON:-$(command -v python3)}"

echo "▸ 准备目录"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/python" "$MODULE_CACHE"

echo "▸ 生成图标"
"$PYTHON" "$ROOT/scripts/make_icon.py" || true

echo "▸ 编译 Swift（$($PYTHON -c 'print("python")') 后端将随包分发）"
TARGET="${TARGET:-$(uname -m)-apple-macosx13.0}"
swiftc -O -swift-version 5 -parse-as-library \
  -target "$TARGET" \
  -module-cache-path "$MODULE_CACHE" \
  -framework AppKit -framework SwiftUI -framework Combine \
  -o "$APP/Contents/MacOS/GPUFinder" \
  "$ROOT/macos/GPSSUI.swift" "$ROOT/macos/GPSApp.swift"

echo "▸ 复制 Info.plist 与资源"
cp "$ROOT/macos/Info.plist" "$APP/Contents/Info.plist"
if [ -f "$BUILD/icon/AppIcon.icns" ]; then
  cp "$BUILD/icon/AppIcon.icns" "$APP/Contents/Resources/AppIcon.icns"
fi

echo "▸ 打包 Python 后端"
rsync -a --exclude '__pycache__' "$ROOT/gpufinder" "$APP/Contents/Resources/python/"
# 确保服务端能找到 web 静态文件与依赖
find "$APP/Contents/Resources/python" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true

echo "▸ 代码签名（ad-hoc）"
codesign --force --deep --sign - "$APP" >/dev/null 2>&1 || {
  echo "  代码签名失败，尝试无签名继续"; }

echo "▸ 完成: $APP"
du -sh "$APP" | awk '{print "  体积: "$1}'

if [ "${1:-}" = "--install" ]; then
  echo "▸ 安装到 /Applications"
  rm -rf "/Applications/$APP_NAME.app"
  cp -R "$APP" "/Applications/$APP_NAME.app"
  echo "  已安装: /Applications/$APP_NAME.app"
  echo "  open \"/Applications/$APP_NAME.app\""
fi
