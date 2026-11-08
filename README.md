# GPU Finder X

> **v1.0.0 · 首个公开版本**  
> 一个跑在 Mac 上的 GPU 行情与租卡工具：本地 Python 后端 + 原生状态栏 App + Web Dashboard。

实时汇总 **AutoDL、矩池云、优云智算、恒源云** 的 GPU 库存、价格与租卡入口，覆盖 40+ 常用显卡。

![状态栏面板](docs/panel-x.png)
![Dashboard](docs/dashboard-x.png)

## 功能

- **四平台实时行情**：库存、地区、按量价格、平台状态一屏对比；
- **40+ 显卡型号**：4090 / 4090D / 48G、5090 / 5090D、A100、H100、L40S、A6000 等；
- **筛选与预设**：消费级、训练卡、大显存、推理卡、¥3/时以下、按显存/价格排序；
- **Mac 状态栏**：点开即刷新，概览卡片可在 Dashboard 设置里自选；
- **一键租卡**：优云智算、AutoDL、恒源云、矩池云（实验性），创建后自动取 SSH；
- **本地优先**：后端只监听 `127.0.0.1`，凭据不上传，不依赖第三方 Python 包。

## 支持平台

| 平台 | 行情 | 一键租卡 | 说明 |
| --- | --- | --- | --- |
| AutoDL | ✅ | ✅ | 按机器 CUDA 自动选镜像，支持定时关机 |
| 矩池云 | ✅ | ✅ 实验性 | 基础 Pytorch 镜像；1区 / 16区；17区第三方卷暂不支持 |
| 优云智算 | ✅ | ✅ | 官方 API，容量/价格校验、SSH、释放 |
| 恒源云 | ✅ | ✅ | 市场镜像、SSH、释放；定时关机实验性 |

## 安装

要求：

- macOS 13+；
- **Python 3.9+**（当前 App 未内嵌解释器）；
- 默认构建 Universal（arm64 + x86_64）。

```bash
git clone https://github.com/Jcode-jiang/GPU-Finder.git
cd GPU-Finder

# 只开 Dashboard
python3 -m gpufinder serve --open

# 构建并安装状态栏 App
./macos/build.sh --install
open "/Applications/GPU Finder X.app"
```

> 当前是 **ad-hoc 签名、未公证** 的公开版本。首次打开若被 Gatekeeper 拦截，请右键 App →「打开」。正式稳定版需要 Developer ID 签名和公证，见 [docs/RELEASE.md](docs/RELEASE.md)。

## 使用

Dashboard 默认地址：<http://127.0.0.1:8765>

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

## 一键租卡

1. 打开菜单栏 App → 齿轮 → 填写各平台凭据；
2. 打开「启用一键租卡」，设置价格上限、最多同时运行实例数、自动关机；
3. 在行情行点「租」，确认报价后创建；
4. 实例 Running 后复制 SSH 命令/密码；
5. 使用完点「释放」，以平台控制台最终状态为准。

凭据获取方式和平台差异见 [docs/CONFIGURATION.md](docs/CONFIGURATION.md) 与 [docs/RENT.md](docs/RENT.md)。

## 安全边界

- 写 API 必须携带本地会话令牌，并校验 Host / Origin / Content-Type；
- 创建前重新校验真实机器、库存、价格和设置上限；
- 创建操作有平台级互斥和 `request_id` 幂等，付费 POST 不自动重试；
- 释放超时/接口异常显示「未确认」，不伪报成功；
- 环境变量注入的凭据不会回写配置文件；
- 所有费用由各平台账户收取，自动关机 ≠ 自动释放。

## 已知限制

- 当前为 ad-hoc 签名、未公证，不适合直接面向普通用户做 stable 分发；
- 需要外部 Python 3.9+；
- 矩池云 17区第三方资源池需要云盘/卷，当前明确不支持；
- 平台接口为非官方/公开接口，可能变更或临时无库存；
- 暂无 Apple Keychain、演示视频和完整真实平台回归视频。

## 文档

- [安装/卸载](docs/INSTALL.md)
- [配置与凭据](docs/CONFIGURATION.md)
- [平台与接口](docs/PROVIDERS.md)
- [租卡说明](docs/RENT.md)
- [真实租赁冒烟记录](docs/SMOKE.md)
- [隐私说明](docs/PRIVACY.md)
- [发布检查清单](docs/RELEASE.md)
- [开发说明](docs/DEVELOPMENT.md)

## License

MIT，见 [LICENSE](LICENSE)。
