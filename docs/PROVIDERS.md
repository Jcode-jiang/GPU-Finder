# 平台适配说明

所有平台都只读取**官方 API 或公开页面**。没有代理、没有第三方代采、没有验证码破解。

## AutoDL

- **行情**：`POST https://api.autodl.com/api/v1/machine/search`
- **鉴权**：`Authorization: <token>`（网页 Local Storage 的 `token`，不是 API Key）
- **品种**：`RTX 4090`、`RTX 4090D`、`RTX 5090`、`RTX 5090 D`
- **分页**：只查目标 GPU 类型，按 500/页拉全，避免只看到前几百台机器
- **库存口径**：
  - `gpu_idle_num` 是接口快照，不是预留；
  - 机器离线 / 实例配额已满时置零；
  - 同一显示地区可能包含多个 `region_sign`（如 west-B / west-C），行情按显示地区聚合。
- **已知问题**：
  - 热门 4090 可能在几秒内被抢走；
  - “有货”不代表一定能创建（配额、存储、镜像兼容性）。

## 矩池云

- **行情**：`https://matpool.com/host-market` 的 Next.js RSC 内嵌 JSON（游客可见）
- **解析**：`parse_host_market` → `parse_pools`
- **库存**：`machine.gpu.available / total`，按 GPU 型号与地区聚合
- **限制**：
  - 页面结构改版可能导致解析失败；
  - 租卡需要 JWT + `x-matpool-user-id`；创建/释放接口已适配，属于实验性功能。

## 优云智算

- **API**：`DescribeAvailableCompShareInstanceTypes`、`GetCompShareInstancePrice`
- **鉴权**：UCloud 签名
  1. 参数按 key 排序；
  2. 拼接 `key + value`（无分隔符）；
  3. 末尾拼接 PrivateKey；
  4. SHA1 → 十六进制小写，放入 `Signature`。
- **嵌套参数**：`Disks.0.Type=CLOUD_SSD` 这种扁平化写法。
- **库存**：官方返回「在售 / 售罄」，不返回具体空闲卡数。
- **租卡**：容量校验、创建、SSH、关机、释放均已适配。

## 恒源云

- **行情**：`GET https://api.gpushare.com/app/api/market/machine/list`
- **鉴权**：`Authorization: Bearer <gpu_share_token>`
- **库存**：`gpuNum - gpuUsed`，按机器 `isOnline` / `status` 过滤
- **SKU**：优先 `payg`、`daily` 等按小时提示
- **租卡**：
  - 镜像从 `/api/image/category` + `/api/image/select` 解析；
  - 按机器 `gpuToolkitVersion` 过滤 CUDA 兼容的 PyTorch 镜像；
  - 实例 SSH 来自 `/api/instance/list` 的 `toolsAttrs`。

## 新增平台

1. 在 `gpufinder/providers/` 新建模块，继承 `Provider`；
2. 实现 `fetch(ctx) -> list[Offer]`，失败抛 `ProviderError`；
3. 在 `gpufinder/providers/__init__.py` 注册；
4. 加离线解析测试（用固定 JSON / HTML fixture，不要请求真实网络）；
5. 更新本文档和 `README.md` 的数据来源表。

`Offer` 的关键字段：

| 字段 | 说明 |
| --- | --- |
| `platform` / `platform_name` | 平台 id 与显示名 |
| `gpu` / `family` / `vram_gb` | 归一化后的型号、家族、显存 |
| `region` | 展示地区 |
| `price` | 元/卡/小时 |
| `available` / `stock` / `capacity` | 是否有货、空闲数、总量 |
| `source` / `source_label` | `api` / `scrape` 与展示文案 |
| `specs` | 驱动、CPU、内存等补充信息 |
| `rent` | 租卡参数（可选） |
