# 隐私与本地数据

## 本地保存

| 数据 | 位置 | 说明 |
| --- | --- | --- |
| 平台凭据 | `~/.config/gpufinder/config.json` | 权限 0600；可用环境变量注入，环境变量值不会被回写 |
| 本地 API 会话令牌 | `~/Library/Caches/gpufinder/session.token` | 权限 0600；只用于 Dashboard/App 与本地后端握手 |
| 上次快照/历史 | `~/Library/Caches/gpufinder/` | 行情缓存，不包含 SSH 密码 |
| 优云实例记录 | `~/Library/Caches/gpufinder/instances.json` | 实例 ID 等元数据，SSH 密码字段不落盘 |

项目没有自有服务器；行情和租卡请求只发送到对应平台接口。Apple Keychain 尚未接入，卸载说明见 `docs/INSTALL.md`。

## 删除

```bash
rm -rf ~/.config/gpufinder ~/Library/Caches/gpufinder
```

删除后需要重新填写平台凭据。GitHub 仓库、Release、截图和日志中不包含可用 token 或 SSH 密码。

## 费用

所有费用由 AutoDL / 矩池云 / 优云智算 / 恒源云账户收取。自动关机、停止实例不等于释放；请以平台账单为准。
