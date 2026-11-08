#!/bin/bash
# 生成带版本/架构的 App zip 与 SHA-256；不负责上传 GitHub。
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP="$ROOT/dist/GPU Finder X.app"
INFO="$APP/Contents/Info.plist"
[ -d "$APP" ] || { echo "找不到 $APP；请先运行 ./macos/build.sh" >&2; exit 1; }
VERSION="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$INFO")"
ARCH="$(lipo -archs "$APP/Contents/MacOS/GPUFinder" 2>/dev/null | tr ' ' '-' || uname -m)"
ARCH="${ARCH:-$(uname -m)}"
OUT="$ROOT/dist/GPU-Finder-X-${VERSION}-${ARCH}.zip"
ditto -c -k --keepParent "$APP" "$OUT"
shasum -a 256 "$OUT" | tee "$OUT.sha256"
echo "▸ 产物: $OUT"
echo "▸ 校验: cat $OUT.sha256"
