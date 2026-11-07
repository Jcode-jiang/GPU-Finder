# Changelog

所有重要变更都记录在这里。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## [1.0.0] - 2026-11-07

### Added

- 四个平台的实时行情：AutoDL、矩池云、优云智算、恒源云，统一 4090 / 5090 型号归一化；
- 本地 Web Dashboard：深色/浅色、平台筛选、型号筛选、只看有货、设置抽屉、实例列表；
- macOS 状态栏 App：`NSStatusItem` + `NSPopover`，点开即刷新，显示最低有货价；
- CLI：`list` / `refresh` / `serve` / `providers` / `doctor` / `config` / `login` / `export`；
- 一键租卡：
  - 优云智算：官方 API，容量校验、创建、SSH、关机/释放；
  - AutoDL：官方市场接口，自动选主机、按机器 CUDA 上限选镜像、定时关机、释放；
  - 恒源云：官方市场接口，自动选兼容镜像、创建、SSH、关机/释放；
  - 矩池云（实验性）：JWT + 用户 ID，选资源池、创建、SSH、释放；
- 零第三方 Python 依赖，配置与凭据保存在本机 `0600` 文件；
- 离线解析测试、GitHub Actions CI、Issue / PR 模板。

### Known limitations

- 矩池云租卡需要 JWT + `x-matpool-user-id`，平台改版可能失效；
- 恒源云暂不支持定时关机；
- 平台接口可能随官网改版失效，行情与租卡互不影响。
