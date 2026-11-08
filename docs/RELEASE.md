# 发布检查清单

## 阻塞项

- [ ] P0 安全回归通过：`python3 -m unittest discover -s tests`、`scripts/check_no_secrets.py`
- [ ] 四个平台各用低预算账户完成一次真实创建、SSH、释放；记录订单与最终状态
- [ ] 验证价格变化拒绝、重复 `request_id` 只创建一个实例、释放超时显示未确认
- [ ] 验证恒源云定时关机（实验性）失败时有 warning
- [ ] macOS 安装包在**没有源码目录**的机器上启动、获取行情、退出
- [ ] 默认 Universal（arm64 + x86_64）；如只构建单架构，Release 说明必须标注
- [ ] 未公证的 ad-hoc 包必须在 Release 说明中标注；正式分发使用 Developer ID + 公证

## 签名与公证

```bash
CODESIGN_IDENTITY="Developer ID Application: ..." ./macos/build.sh
CODESIGN_IDENTITY="Developer ID Application: ..." \
NOTARY_PROFILE="gpufinder-notary" ./scripts/notarize.sh
```

`NOTARY_PROFILE` 通过 `xcrun notarytool store-credentials` 创建，不要把 Apple ID 密码写入仓库。

## 产物

```bash
./scripts/package_release.sh
```

输出 `dist/GPU-Finder-X-<版本>-<架构>.zip` 和同名 `.sha256`。

## Release 说明必须写清

- 支持 macOS 13+，当前构建架构；
- 需要 Python 3.9+（当前 App 未内嵌解释器）；
- 行情来自非官方/公开接口，可能失效；
- 租卡会真实扣费，自动关机≠自动释放，停止≠停止所有计费；
- 凭据保存在本机 `~/.config/gpufinder/config.json`（0600），可删除；不随仓库/Release 分发。

## GitHub Release

- 附 App zip、SHA-256、CHANGELOG；
- 不附源码中的 `.env`、配置文件或截图中的账户余额；
- 先跑 CI，再创建 tag（版本与 `Info.plist`/`pyproject.toml` 一致）。
