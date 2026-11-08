# 安装、启动、卸载

## 要求

- macOS 13+；
- Python 3.9+（当前 App 不内嵌解释器；推荐 Homebrew 或 python.org 安装）；
- 首次启动需要允许本地网络访问（如果系统弹出提示）。

## 安装

1. 下载 `GPU-Finder-X-<版本>-<架构>.zip` 和对应 `.sha256`；
2. 校验：
   ```bash
   shasum -a 256 -c GPU-Finder-X-*.zip.sha256
   ```
3. 解压后把 `GPU Finder X.app` 拖到 `/Applications`；
4. 默认构建是 **Universal**（arm64 + x86_64），但使用 **ad-hoc 签名、未公证**：
   - 首次打开若被 Gatekeeper 拦截，右键 → 打开；
   - 正式分发包应使用 Developer ID 签名并公证，见 `docs/RELEASE.md`。

## 启动检查

1. 点菜单栏图标，确认出现 GPU 报价；
2. 打开 Dashboard，确认平台状态为「实时」或明确的错误；
3. 打开设置，确认余额/凭据状态正确；
4. 退出 App，确认后台 Python 进程结束：
   ```bash
   pgrep -fl "gpufinder.*serve"
   ```

## 卸载

```bash
# 1. 退出 App
osascript -e 'quit app "GPU Finder X"' 2>/dev/null || true

# 2. 删除应用
rm -rf "/Applications/GPU Finder X.app"

# 3. 删除配置、实例缓存、会话令牌
rm -rf ~/.config/gpufinder ~/Library/Caches/gpufinder
```

项目当前不使用 macOS Keychain；删除上述目录即可清除本地平台凭据和会话令牌。
GitHub Release/仓库不包含任何个人配置。
