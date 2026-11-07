# 安全说明

## 报告问题

请不要在公开 Issue 中提交以下内容：

- AutoDL / 恒源云 / 矩池云的 token、Cookie、JWT；
- 优云智算的 AccessKey ID / Secret；
- SSH 密码、私钥、实例 IP；
- 账号余额、订单号、实名信息截图。

如果发现凭据泄露、越权、租卡流程可能误扣费，请通过仓库所有者的 GitHub 主页邮箱私下联系，
或使用 GitHub Security Advisory 的「Report a vulnerability」。

## 本地凭据

- 配置保存在 `~/.config/gpufinder/config.json`，权限 `0600`；
- 可以通过环境变量注入，避免写文件；
- 本项目不会把凭据上传到任何服务器；Dashboard 只监听 `127.0.0.1`；
- 租卡记录只保存实例 ID 等元数据，**SSH 密码不落盘**。

## 支持范围

- 仅支持 macOS 13+；
- 行情数据来自平台官方接口或公开页面；
- 租卡属于实验性功能，平台接口变更可能导致失败；下单前请确认价格与配置。
