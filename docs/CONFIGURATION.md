# 配置说明

## 配置文件位置

| 内容 | 路径 |
| --- | --- |
| 主配置 | `~/.config/gpufinder/config.json` |
| 最近快照 | `~/Library/Caches/gpufinder/last_snapshot.json` |
| 价格历史 | `~/Library/Caches/gpufinder/history.jsonl` |
| 租卡实例元数据 | `~/Library/Caches/gpufinder/instances.json` |

设置 `GPUFINDER_HOME` 可以把上述目录换到别处（测试或便携使用）：

```bash
GPUFINDER_HOME=/tmp/gpufinder-home python3 -m gpufinder list
```

配置文件权限应为 `0600`。如果权限不对，可以手动修正：

```bash
chmod 600 ~/.config/gpufinder/config.json
```

## 配置示例

```json
{
  "port": 8765,
  "refresh_interval": 300,
  "request_timeout": 20,
  "credentials": {
    "autodl_token": "",
    "gpushare_token": "",
    "compshare_public_key": "",
    "compshare_private_key": "",
    "matpool_token": "",
    "matpool_user_id": ""
  },
  "rent": {
    "enabled": false,
    "image_id": "",
    "disk_gb": 100,
    "auto_stop_minutes": 60,
    "max_hourly_price": 5,
    "name_prefix": "gpufinder"
  }
}
```

仓库里的 [`config.example.json`](../config.example.json) 只包含空值，**不要提交真实配置**。

## 字段

### 基础

| 字段 | 默认 | 说明 |
| --- | --- | --- |
| `port` | `8765` | Dashboard / App 后端端口；被占用时启动会换端口 |
| `refresh_interval` | `300` | 后台自动刷新间隔（秒） |
| `overview_families` | `[]` | 概览卡片显示的显卡家族（最多 3 个，空 = 自动） |
| `request_timeout` | `20` | 单次 HTTP 请求超时（秒） |

### 凭据

| 字段 | 平台 | 获取方式 |
| --- | --- | --- |
| `autodl_token` | AutoDL | 登录后 Local Storage 的 `token` |
| `gpushare_token` | 恒源云 | 浏览器 Cookie `gpu_share_token` |
| `compshare_public_key` | 优云智算 | API 密钥的 AccessKey ID |
| `compshare_private_key` | 优云智算 | API 密钥的 AccessKey Secret |
| `matpool_token` | 矩池云 | 请求头 `authorization` 里 Bearer 后的 JWT |
| `matpool_user_id` | 矩池云 | 请求头 `x-matpool-user-id` |

也支持环境变量，优先级高于配置文件：

```text
GPUFINDER_AUTODL_TOKEN
GPUFINDER_GPUSHARE_TOKEN
GPUFINDER_COMPSHARE_PUBLIC_KEY
GPUFINDER_COMPSHARE_PRIVATE_KEY
GPUFINDER_MATPOOL_TOKEN
GPUFINDER_MATPOOL_USER_ID
```

### 租卡

| 字段 | 默认 | 说明 |
| --- | --- | --- |
| `enabled` | `false` | 是否允许创建实例；关闭时只能看行情 |
| `image_id` | `""` | 优云智算默认镜像；留空自动选 PyTorch |
| `autodl_image_id` | `""` | AutoDL 镜像 UUID；留空按机器 CUDA 自动选 |
| `gpushare_image_id` | `""` | 恒源云镜像 ID；留空按机器 CUDA 自动选 |
| `gpushare_auto_stop_minutes` | `60` | 恒源云定时关机分钟数；`0` 关闭 |
| `matpool_image_policy` | `"auto"` | 矩池云镜像偏好：`auto` / `latest` |
| `disk_gb` | `100` | 优云智算系统盘大小 |
| `auto_stop_minutes` | `60` | 创建后定时关机分钟数；`0` 表示不设置 |
| `max_hourly_price` | `5` | 价格上限（元/卡/小时），超过直接拒绝 |
| `name_prefix` | `gpufinder` | 实例名前缀 |

## 命令行修改

```bash
./gpufinder.sh config --show
./gpufinder.sh config --set port=8800
./gpufinder.sh config --set refresh_interval=120

./gpufinder.sh config --token autodl <TOKEN>
./gpufinder.sh config --token gpushare <TOKEN>
./gpufinder.sh config --apikey compshare <ACCESS_KEY_ID> <ACCESS_KEY_SECRET>
```

也可以直接编辑 JSON；保存后重启 `gpufinder serve` 或状态栏 App 生效。

## 显卡目录与预设

- 型号目录：`gpufinder/gpu_catalog.py`，新增型号只改这一个文件；
- 预设：`gpufinder/presets.py`，Dashboard 顶部的「全部显卡 / 训练卡 / 大显存…」都由它生成；
- 查看：`GET /api/catalog` 或 `GET /api/presets`。

## 安全建议

- 不要把 `config.json` 提交到 Git；
- 不要把 token / Cookie 发到 Issue、截图或日志；
- 租卡完成后及时释放实例；
- 使用独立、限额的 API 密钥。
