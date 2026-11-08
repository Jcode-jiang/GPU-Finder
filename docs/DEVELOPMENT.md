# 开发与构建

## 环境

- Python 3.9+（macOS 自带的 `/usr/bin/python3` 是 3.9，可直接用）
- macOS 13+（构建状态栏 App）
- Xcode Command Line Tools：`xcode-select --install`
- 无第三方 Python 依赖

## 运行

```bash
python3 -m gpufinder serve --open          # Dashboard
python3 -m gpufinder list --gpu 4090 -a    # CLI
python3 -m gpufinder doctor                # 自检
```

## 测试

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q gpufinder
python3 scripts/check_no_secrets.py
```

测试全部离线：型号归一化、矩池云 RSC 解析、UCloud 签名、AutoDL / 恒源云字段、
快照 summary、HTTP API 与静态资源。

## 构建 App

```bash
./macos/build.sh              # dist/GPU Finder.app
./macos/build.sh --install    # 安装到 /Applications
```

构建脚本会：

1. 调用 `scripts/make_icon.py` 生成图标；
2. 用 `swiftc` 编译两个 Swift 文件；
3. 把 `gpufinder/` 源码复制进 `Contents/Resources/python`；
4. ad-hoc 签名。

App 是 `LSUIElement` 应用，只常驻菜单栏。`Info.plist` 里开了本地网络 ATS 例外，
因为 Dashboard 只监听 `127.0.0.1`。

## 截图 / 验收

仓库里的 `scripts/` 提供离屏渲染工具：

```bash
# Dashboard 截图（WKWebView）
swiftc -O -swift-version 5 -target arm64-apple-macosx13.0 \
  -framework Cocoa -framework WebKit -o /tmp/snapshot scripts/snapshot.swift
/tmp/snapshot http://127.0.0.1:8765 /tmp/dashboard.png 1400 1180 light

# 状态栏面板截图
swiftc -O -swift-version 5 -parse-as-library -target arm64-apple-macosx13.0 \
  -module-cache-path build/.swift-cache \
  -framework AppKit -framework SwiftUI -framework Combine \
  -o /tmp/panel_snapshot macos/GPSSUI.swift scripts/panel_snapshot.swift
/tmp/panel_snapshot http://127.0.0.1:8765 /tmp/panel.png light all
```

> `scripts/panel_snapshot.swift` 里的实例 IP 使用文档保留地址 `203.0.113.10`，不是真实机器。

## CI

`.github/workflows/ci.yml` 会：

- 在 Ubuntu / macOS 上跑 Python 3.9、3.11、3.13 的单元测试；
- 运行 `compileall` 与 `scripts/check_no_secrets.py`；
- 在 macOS runner 上构建状态栏 App（可选 artifact）。

## 发布

1. 更新 `CHANGELOG.md` 与 `pyproject.toml` 版本号；
2. `make test`；
3. `./macos/build.sh`；
4. 打包 `dist/GPU Finder.app` 为 zip，附到 GitHub Release；
5. 不要提交 `dist/`、`build/`、真实配置或截图中的账号信息。

## 目录说明

```text
gpufinder/gpu_catalog.py 显卡目录（40+ 型号）
gpufinder/presets.py     常用预设
gpufinder/providers/   平台适配器（autodl/matpool/compshare/gpushare）
gpufinder/rent_*.py    各平台租卡（写操作）
gpufinder/server.py    本地 HTTP API + 静态资源
gpufinder/web/         Dashboard（无构建步骤）
macos/                 SwiftUI 状态栏 App
scripts/               图标、截图、页面探测
tests/                 离线单元测试
docs/                  文档与截图
```


## 静态检查与发布

```bash
python3 -m ruff check gpufinder tests scripts
python3 -m unittest discover -s tests
./macos/build.sh              # 默认 Universal
./scripts/package_release.sh  # 生成 zip + SHA-256
```

正式签名/公证与发布检查见 `docs/RELEASE.md`。
