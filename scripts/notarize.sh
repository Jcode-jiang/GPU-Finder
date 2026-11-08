#!/bin/bash
# Developer ID 签名 + Apple 公证 + stapler。
# 用法：
#   CODESIGN_IDENTITY="Developer ID Application: ..." \
#   NOTARY_PROFILE="gpufinder-notary" ./scripts/notarize.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP="${1:-$ROOT/dist/GPU Finder X.app}"
IDENTITY="${CODESIGN_IDENTITY:?请设置 CODESIGN_IDENTITY（Developer ID Application）}"
PROFILE="${NOTARY_PROFILE:?请设置 NOTARY_PROFILE（notarytool keychain profile）}"

if [ ! -d "$APP" ]; then
  echo "找不到 App: $APP；请先运行 ./macos/build.sh" >&2
  exit 1
fi

echo "▸ Developer ID 签名"
codesign --force --deep --options runtime --timestamp --sign "$IDENTITY" "$APP"
codesign --verify --deep --strict --verbose=2 "$APP"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
ZIP="$TMP/notarize.zip"
ditto -c -k --keepParent "$APP" "$ZIP"

echo "▸ 提交 Apple 公证"
xcrun notarytool submit "$ZIP" --keychain-profile "$PROFILE" --wait
xcrun stapler staple "$APP"
xcrun stapler validate "$APP"
spctl -a -vv "$APP"

echo "▸ 公证与 Gatekeeper 验证完成"
