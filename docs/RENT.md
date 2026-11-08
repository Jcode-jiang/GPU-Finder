# 一键租卡说明

## 支持矩阵

| 平台 | 行情 | 报价 | 创建 | SSH | 关机/释放 | 定时关机 |
| --- | --- | --- | --- | --- | --- | --- |
| 优云智算 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| AutoDL | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 恒源云 | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ 实验性 |
| 矩池云 | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |

矩池云创建需要 JWT + `x-matpool-user-id` 两个凭据；未提供时只显示行情。


## 设置项范围

| 设置 | 生效平台 |
| --- | --- |
| 启用一键租卡 / 价格上限 / 最多同时运行实例 | 所有平台 |
| 账户余额 | 四平台分别读取：优云智算 GetBalance / AutoDL wallet / 恒源云 account summary / 矩池云 user/account |
| 优云智算镜像 / 系统盘 / 自动关机 | 优云智算 |
| AutoDL 镜像（可选，留空自动） | AutoDL |
| 恒源云镜像 / 自动关机（实验性） | 恒源云 |
| 矩池云镜像偏好 | 矩池云 |
| 自动关机 | AutoDL + 优云智算 + 恒源云（实验性） |
| 镜像自动选择 | 优云智算 / AutoDL / 恒源云 / 矩池云 |

## 通用安全边界

1. 必须在设置里打开「启用一键租卡」；
2. 每次创建都要在弹窗里勾选确认；
3. 价格超过 `max_hourly_price` 直接拒绝；
4. 默认按量计费，创建后按设置申请定时关机；**定时关机失败会明确警告**，且关机不等于释放，磁盘等资源可能继续计费；
5. 释放时先关机，再删除/释放实例；
6. SSH 密码不写入磁盘，需要时从平台接口重新获取。

## 优云智算

- 报价调用 `CheckCompShareResourceCapacity` 做真实容量校验；
- 创建成功后从 `DescribeCompShareInstance` 取 SSH；
- 释放：`StopCompShareInstance` → `TerminateCompShareInstance`。

## AutoDL

- 报价时从市场接口挑一台**空闲且实例/存储配额未满**的机器；
- 镜像按机器 `highest_cuda_version` 过滤，避免 CUDA 13 镜像在只支持 12.x 的机器上启动失败；
- 创建前按 machine_id 重新校验型号、地区、空闲卡、payg 价格与上限；失败不会自动换机重试；
- 创建后用 `instance/timed/shutdown` 设置定时关机；
- 释放：先 `power_off`，等状态变为 `shutdown`，再 `instance/release`；
- 如果启动失败（`shutdown_by_starting_error`），会自动释放并报错。

## 恒源云

- 机器来自 `/api/market/machine/list`，只挑 `payg` 且空闲的机器；
- 镜像从 `/api/image/category` + `/api/image/select` 解析，按机器 CUDA 上限过滤；
- 创建：`POST /api/instance/create`；
- SSH：`/api/instance/list` 的 `toolsAttrs`（`key=ssh`）；
- 释放：先 `actionName=stop`，等状态为 `stop`，再 `actionName=release`；
- 定时关机：已接入 `POST /api/instance/set/schedule_stop`，标记为实验性；失败会在创建结果里给出 warning。
- 释放超时不会显示成功，会返回「结果未确认」，需要到控制台核实。

## 矩池云（实验性）

- 设置里需要填 **JWT** 与 **用户 ID**：
  - Network → 任意请求 → `authorization: Bearer <JWT>`；
  - 同一请求头 `x-matpool-user-id`。
- 报价：重新抓取 `host-market`，按 GPU 型号/区域/价格找有 `max_available_units` 的资源池；
- 镜像：`GET /api/images?resource_pool_id=...`，选 PyTorch 且 CUDA ≤ 12.8 的镜像；
- 创建：`POST /api/node`，body 包含 `resource_pool_id`、`hardware_qty`、`image_id`、`mount_infos`；
- 实例：`GET /api/nodes`，SSH 来自 `node.ports` 与 `sshAuths`；
- 释放：`DELETE /api/node`，body `{"id": ...}`；只有确认节点消失或状态为 released 才算成功，stopped 不算释放。
- 创建响应缺少节点 ID 时，使用“创建前快照 + 唯一新节点”匹配；无法确认时返回待确认，绝不拿旧节点冒充。
- 注意：平台可能返回 `53 insufficient resource` 或 `187 auth cert`；前者是库存/容量问题，后者是凭据缺失。

## 失败处理

| 错误 | 含义 | 建议 |
| --- | --- | --- |
| `余额不足` / `Lack of balance` | 账户余额不够 | 充值后重试 |
| `该主机已租满` | 实例配额满 | 换一台/换地区 |
| `存储库存已满` | 机器磁盘配额满 | 换一台 |
| `状态不符` | 实例状态不允许该操作 | 先关机再释放 |
| `check jwt token failed` | 矩池云 token 格式/会话不对 | 重新登录获取 |
| `user not passed auth cert` | 矩池云缺少用户 ID 或登录态失效 | 在设置里补全 JWT 与 `x-matpool-user-id` |

## 手工验证流程

1. 在 Dashboard 启用租卡，设置价格上限（例如 ¥5/时）与自动关机 60 分钟；
2. 点最低价有货的「租」，确认报价与镜像；
3. 勾选确认创建；
4. 实例 Running 后复制 SSH 命令与密码，执行 `nvidia-smi`；
5. 点「释放实例」，确认平台控制台里实例已消失、余额停止扣费。
