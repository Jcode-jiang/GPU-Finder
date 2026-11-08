#!/bin/bash
# 构建 GPU Finder X.app（macOS 状态栏应用）
# 用法: ./macos/build.sh [--install]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_NAME="GPU Finder X"
APP="$ROOT/dist/$APP_NAME.app"
BUILD="$ROOT/build"
MODULE_CACHE="$BUILD/.swift-cache"
PYTHON="${PYTHON:-$(command -v python3)}"
if ! "$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
  echo "错误：需要 Python 3.9+；当前: $($PYTHON --version 2>&1)" >&2
  exit 1
fi

echo "▸ 准备目录"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/python" "$MODULE_CACHE"

echo "▸ 生成图标"
"$PYTHON" "$ROOT/scripts/make_icon.py" || true

echo "▸ 编译 Swift（Python 后端源码随包分发）"
if [ -n "${TARGET:-}" ]; then
  ARCHS="$TARGET"
  UNIVERSAL=0
else
  ARCHS="${ARCHS:-arm64 x86_64}"
  UNIVERSAL=1
fi
BINARIES=()
for ARCH in $ARCHS; do
  TARGET_TRIPLE="${ARCH}-apple-macosx13.0"
  OUT="$BUILD/GPUFinder-$ARCH"
  swiftc -O -swift-version 5 -parse-as-library \
    -target "$TARGET_TRIPLE" \
    -module-cache-path "$MODULE_CACHE/$ARCH" \
    -framework AppKit -framework SwiftUI -framework Combine \
    -o "$OUT" \
    "$ROOT/macos/GPSSUI.swift" "$ROOT/macos/GPSApp.swift"
  BINARIES+=("$OUT")
done
if [ "${#BINARIES[@]}" -gt 1 ]; then
  lipo -create "${BINARIES[@]}" -output "$APP/Contents/MacOS/GPUFinder"
else
  cp "${BINARIES[0]}" "$APP/Contents/MacOS/GPUFinder"
fi

echo "▸ 复制 Info.plist 与资源"
cp "$ROOT/macos/Info.plist" "$APP/Contents/Info.plist"
if [ -f "$BUILD/icon/AppIcon.icns" ]; then
  cp "$BUILD/icon/AppIcon.icns" "$APP/Contents/Resources/AppIcon.icns"
fi

echo "▸ 打包 Python 后端"
rsync -a --exclude '__pycache__' "$ROOT/gpufinder" "$APP/Contents/Resources/python/"
# 确保服务端能找到 web 静态文件与依赖
find "$APP/Contents/Resources/python" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true

IDENTITY="${CODESIGN_IDENTITY:--}"
if [ "$IDENTITY" = "-" ]; then
  echo "▸ 代码签名（ad-hoc；未公证，仅适合本机/开发）"
  codesign --force --deep --sign - "$APP" >/dev/null 2>&1 || {
    echo "  代码签名失败，尝试无签名继续"; }
else
  echo "▸ 代码签名（Developer ID: $IDENTITY）"
  codesign --force --deep --options runtime --timestamp --sign "$IDENTITY" "$APP"
fi

echo "▸ 完成: $APP"
du -sh "$APP" | awk '{print "  体积: "$1}'

if [ "${1:-}" = "--install" ]; then
  echo "▸ 安装到 /Applications"
  rm -rf "/Applications/$APP_NAME.app"
  cp -R "$APP" "/Applications/$APP_NAME.app"
  echo "  已安装: /Applications/$APP_NAME.app"
  echo "  open \"/Applications/$APP_NAME.app\""
fi
