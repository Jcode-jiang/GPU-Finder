# GPU Finder X

**Mac 上的 GPU 行情与租卡工作台。**  
本地 Python 后端 · 原生状态栏 App · Web Dashboard · CLI。

<p>
  <img src="https://img.shields.io/badge/version-1.0.0-blue" alt="version">
  <img src="https://img.shields.io/badge/status-beta-orange" alt="status">
  <img src="https://img.shields.io/badge/macOS-13%2B-black" alt="macOS">
  <img src="https://img.shields.io/badge/Python-3.9%2B-yellow" alt="Python">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="license">
</p>

GPU Finder X 把 **AutoDL、矩池云、优云智算、恒源云** 的 GPU 库存、价格和租卡入口集中到一个本地工具里。  
不用在四个控制台之间来回切换，也不用把账号凭据交给额外的聚合服务。

> **v1.0.0 是首个公开版本，属于 Beta。**  
> 当前为 ad-hoc 签名、未公证；App 需要本机安装 Python 3.9+。详见[已知限制](#已知限制)。

![状态栏面板](docs/panel-x.png)

![Dashboard](docs/dashboard-x.png)

## 为什么做

- GPU 租赁平台分散，价格和库存变化快；
- 同一张卡在不同平台、不同地区价差很大；
- 从比价到创建、拿 SSH、释放，流程链路长；
- 不希望把 token 交给额外的聚合服务。

GPU Finder X 的目标很简单：**在本机完成比价、租卡和释放，凭据只保存在本机。**

## 功能

- **四平台实时行情**：库存、地区、按量价格、平台状态一屏对比；
- **40+ 常用显卡**：4090 / 4090D / 4090 48G、5090 / 5090D、A100、H100、L40S、A6000 等；
- **预设与筛选**：消费级、训练卡、大显存、推理卡、¥3/时以下，按显存/价格排序；
- **三种入口**：Mac 状态栏、Web Dashboard、CLI，共用同一套数据和租卡配置；
- **概览可自选**：设置里选择最多 3 个显卡家族，Dashboard 显示 3 张、状态栏显示前 2 张；
- **一键租卡**：优云智算、AutoDL、恒源云、矩池云（实验性），创建后获取 SSH；
- **安全边界**：创建前复核真实价格/库存，创建互斥 + 幂等，释放结果验证；
- **零第三方 Python 依赖**：只用标准库，不联网安装依赖。

## 支持平台

| 平台 | 行情 | 一键租卡 | 说明 |
| --- | --- | --- | --- |
| **AutoDL** | ✅ | ✅ | 按机器 CUDA 自动选镜像，支持定时关机 |
| **矩池云** | ✅ | ✅ 实验性 | 基础 Pytorch 镜像；1 区 / 16 区；17 区第三方卷暂不支持 |
| **优云智算** | ✅ | ✅ | 官方 API，容量/价格校验、SSH、释放 |
| **恒源云** | ✅ | ✅ | 市场镜像、SSH、释放；定时关机实验性 |

## 安装

### 要求

- macOS 13+；
- **Python 3.9+**（当前 App 未内嵌解释器）；
- 默认构建 **Universal**（arm64 + x86_64）。

### 使用发布包

从 [Releases](https://github.com/Jcode-jiang/GPU-Finder/releases) 下载：

```text
GPU-Finder-X-1.0.0-x86_64-arm64.zip
```

解压后把 `GPU Finder X.app` 拖到 `/Applications`。  
当前构建使用 **ad-hoc 签名、未公证**：首次打开若被 Gatekeeper 拦截，请右键 App →「打开」。

### 从源码构建

```bash
git clone https://github.com/Jcode-jiang/GPU-Finder.git
cd GPU-Finder

# 只开 Dashboard
python3 -m gpufinder serve --open

# 构建并安装状态栏 App
./macos/build.sh --install
open "/Applications/GPU Finder X.app"
```

签名、公证和发布流程见 [docs/RELEASE.md](docs/RELEASE.md)。

## 使用

Dashboard 默认地址：<http://127.0.0.1:8765>

### CLI

```bash
./gpufinder.sh list --gpu 4090 -a          # 4090 有货
./gpufinder.sh list --preset training -a   # 训练卡
./gpufinder.sh list --preset budget        # ¥3/时以下
./gpufinder.sh export --format csv -o gpu.csv
```

安装为全局命令：

```bash
python3 -m pip install -e .
```

### 状态栏

点菜单栏图标打开面板：

- 顶部概览卡片来自 Dashboard 设置；
- 点刷新会重新抓取四个平台；
- 点行情行右侧「租」进入报价和创建流程。

## 一键租卡

1. 打开菜单栏 App → 齿轮 → 填写各平台凭据；
2. 打开「启用一键租卡」，设置价格上限、最多同时运行实例数、自动关机；
3. 在行情行点「租」，确认报价后创建；
4. 实例 Running 后复制 SSH 命令/密码；
5. 使用完点「释放」，以平台控制台最终状态为准。

凭据获取方式和平台差异见 [docs/CONFIGURATION.md](docs/CONFIGURATION.md) 与 [docs/RENT.md](docs/RENT.md)。

## 安全与隐私

- 后端只监听 `127.0.0.1`；写 API 需要本地会话令牌，并校验 Host / Origin / Content-Type；
- 创建前重新校验真实机器、库存、价格和设置上限；
- 创建操作有平台级互斥和 `request_id` 幂等，付费 POST 不自动重试；
- 释放超时/接口异常显示「未确认」，不伪报成功；
- 环境变量注入的凭据不会回写配置文件；
- 所有费用由各平台账户收取；**自动关机 ≠ 自动释放**；
- 项目没有自有服务器，行情和租卡请求只发送到对应平台。

配置、缓存和卸载方式见 [docs/PRIVACY.md](docs/PRIVACY.md)。

## 已知限制

- 当前为 **ad-hoc 签名、未公证**，不适合直接面向普通用户做 stable 分发；
- 需要外部 **Python 3.9+**；
- 矩池云 17 区第三方资源池需要云盘/卷，当前明确不支持；
- 平台接口为非官方/公开接口，可能变更或临时无库存；
- 暂无 Apple Keychain、演示视频和完整真实平台回归视频。

## 开发

```bash
python3 -m unittest discover -s tests
python3 -m ruff check gpufinder tests scripts
python3 scripts/check_no_secrets.py
./macos/build.sh
./scripts/package_release.sh
```

项目结构：

```text
gpufinder/            Python 后端、行情 provider、租卡、Web 静态资源
macos/                SwiftUI / AppKit 状态栏 App
scripts/              构建、截图、发布、密钥扫描
tests/                离线测试
docs/                 配置、平台、租卡、安装、发布文档
```

## 文档

- [安装 / 卸载](docs/INSTALL.md)
- [配置与凭据](docs/CONFIGURATION.md)
- [平台与接口](docs/PROVIDERS.md)
- [租卡说明](docs/RENT.md)
- [真实租赁冒烟记录](docs/SMOKE.md)
- [隐私说明](docs/PRIVACY.md)
- [发布检查清单](docs/RELEASE.md)
- [开发说明](docs/DEVELOPMENT.md)

## Contributing

欢迎提交 Issue 和 PR。提交前请先阅读 [CONTRIBUTING.md](CONTRIBUTING.md)；不要提交 token、Cookie、SSH 密码、实例 IP 或账号截图。

## License

MIT，见 [LICENSE](LICENSE)。
