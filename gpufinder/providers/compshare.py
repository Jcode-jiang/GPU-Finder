"""优云智算（compshare.cn）官方 API 适配器。

使用 UCloud 风格的公开 API（``https://api.compshare.cn``），需要控制台的
AccessKey ID / AccessKey Secret（公钥 / 私钥）：

* ``DescribeCompShareSupportZone``：地域 / 可用区
* ``DescribeAvailableCompShareInstanceTypes``：各机型**实时在售 / 售罄状态**
* ``GetCompShareInstancePrice``：指定配置的**实时价格**（按量 / 抢占）

签名算法（UCloud 官方文档）：把所有请求参数按参数名升序拼接
``key + value``，末尾拼上 PrivateKey，做 SHA1 取十六进制。
"""

from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from ..gpu import normalize_gpu
from ..http import HttpError
from ..models import Offer
from .base import AuthRequired, FetchContext, Provider, ProviderError

API_URL = "https://api.compshare.cn"
CONSOLE_URL = "https://console.compshare.cn/light-gpu/resources/create"

# 官方文档列出的「云主机」可用区（IsPod=false），API 不可用时兜底
HOST_ZONES_FALLBACK: list[tuple[str, str, str]] = [
    ("cn-wlcb", "cn-wlcb-01", "华北二A"),
    ("cn-sh2", "cn-sh2-02", "上海二B"),
]

CHARGE_LABELS = {
    "Postpay": "按量计费",
    "Spot": "抢占式",
}


def encode_value(value: Any) -> str:
    """UCloud 规则：bool 小写，整数值浮点去掉小数。"""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else str(value)
    return str(value)


def flatten_params(params: dict[str, Any]) -> dict[str, str]:
    """UCloud 嵌套参数编码：Disks -> Disks.0.IsBoot=true ..."""
    out: dict[str, str] = {}
    for key, value in params.items():
        if isinstance(value, dict):
            for sub_key, sub_val in flatten_params(value).items():
                out[f"{key}.{sub_key}"] = sub_val
        elif isinstance(value, (list, tuple)):
            for idx, item in enumerate(value):
                if isinstance(item, dict):
                    for sub_key, sub_val in flatten_params(item).items():
                        out[f"{key}.{idx}.{sub_key}"] = sub_val
                else:
                    out[f"{key}.{idx}"] = encode_value(item)
        else:
            out[key] = encode_value(value)
    return out


def sign_params(params: dict[str, Any], private_key: str) -> str:
    flat = flatten_params(params)
    raw = "".join(name + flat[name] for name in sorted(flat)) + private_key
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


class CompshareAPI:
    def __init__(self, ctx: FetchContext, public_key: str, private_key: str) -> None:
        self.ctx = ctx
        self.public_key = public_key.strip()
        self.private_key = private_key.strip()

    def call(self, action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        fields: dict[str, Any] = {"Action": action, "PublicKey": self.public_key}
        for key, value in (params or {}).items():
            if value is None:
                continue
            fields[key] = value
        flat = flatten_params(fields)
        flat["Signature"] = sign_params(fields, self.private_key)

        try:
            resp = self.ctx.http.post_form(API_URL, flat, timeout=self.ctx.timeout)
        except HttpError as exc:
            raise ProviderError(f"优云智算 API 请求失败: {exc}") from exc
        try:
            data = resp.json()
        except ValueError as exc:
            raise ProviderError(f"优云智算 API 返回非 JSON（HTTP {resp.status}）") from exc

        ret = data.get("RetCode")
        if ret not in (0, "0", None):
            message = str(data.get("Message") or "")
            if any(k in message for k in ("签名", "Signature", "公钥", "PublicKey", "PrivateKey")):
                raise AuthRequired(f"优云智算 API 鉴权失败：{message}")
            raise ProviderError(f"优云智算 API 错误 {ret}: {message}")
        return data

    # ------------------------------------------------------------------ 接口
    def zones(self) -> list[tuple[str, str, str]]:
        try:
            data = self.call("DescribeCompShareSupportZone")
        except ProviderError:
            return HOST_ZONES_FALLBACK
        zones: list[tuple[str, str, str]] = []
        for info in data.get("ZoneInfo") or []:
            if info.get("IsPod"):
                continue
            region = str(info.get("Region") or "")
            zone = str(info.get("Zone") or "")
            desc = str(info.get("Describe") or zone)
            if region and zone:
                zones.append((region, zone, desc))
        return zones or HOST_ZONES_FALLBACK

    def images(self, region: str, zone: str, image_type: str = "System") -> list[dict[str, Any]]:
        data = self.call(
            "DescribeCompShareImages",
            {"Region": region, "Zone": zone, "ImageType": image_type, "Limit": 100},
        )
        return [r for r in (data.get("ImageSet") or []) if isinstance(r, dict)]

    def default_image(self, region: str, zone: str) -> str:
        """选一个带 NVIDIA 驱动的 Ubuntu 系统镜像，作为库存检查 / 租卡的默认镜像。"""
        cache_key = (region, zone)
        cached = getattr(self, "_image_cache", None)
        if cached is None:
            cached = self._image_cache = {}
        if cache_key in cached:
            return cached[cache_key]
        image_id = ""
        try:
            images = self.images(region, zone, "System")
            preferred = [
                "Ubuntu-nvidia 22.04",
                "Ubuntu 22.04 64位",
                "Ubuntu 22.04",
                "Ubuntu 24.04 64位",
            ]
            by_name = {str(i.get("Name") or ""): i for i in images if i.get("Status") == "Available"}
            for name in preferred:
                if name in by_name:
                    image_id = str(by_name[name].get("CompShareImageId") or "")
                    break
            if not image_id:
                for name, item in by_name.items():
                    if "ubuntu" in name.lower():
                        image_id = str(item.get("CompShareImageId") or "")
                        break
        except (ProviderError, AuthRequired):
            image_id = ""
        cached[cache_key] = image_id
        return image_id

    def capacity(
        self,
        region: str,
        zone: str,
        gpu_type: str,
        image_id: str,
        cpu: int,
        mem_gb: int,
        disk_gb: int = 100,
        charge: str = "Postpay",
    ) -> bool | None:
        """调用官方容量检查接口，确认该组合当前真的有库存。"""
        if not image_id:
            return None
        try:
            data = self.call(
                "CheckCompShareResourceCapacity",
                {
                    "Region": region,
                    "Zone": zone,
                    "GpuType": gpu_type,
                    "MachineType": "G",
                    "MinimalCpuPlatform": "Auto",
                    "CompShareImageId": image_id,
                    "ChargeType": charge,
                    "Disks": [{"IsBoot": True, "Type": "CLOUD_SSD", "Size": disk_gb}],
                },
            )
        except (ProviderError, AuthRequired):
            return None
        for spec in data.get("Specs") or []:
            try:
                if int(spec.get("Gpu") or 0) == 1 and int(spec.get("Cpu") or 0) == cpu and int(spec.get("Mem") or 0) == mem_gb:
                    return bool(spec.get("ResourceEnough"))
            except (TypeError, ValueError):
                continue
        spec1 = next((s for s in (data.get("Specs") or []) if str(s.get("Gpu")) == "1"), None)
        if spec1 is not None:
            return bool(spec1.get("ResourceEnough"))
        return None

    def available_types(self, region: str, zone: str) -> list[dict[str, Any]]:
        data = self.call(
            "DescribeAvailableCompShareInstanceTypes",
            {"Region": region, "Zone": zone},
        )
        rows = data.get("AvailableInstanceTypes") or []
        return [r for r in rows if isinstance(r, dict)]

    def price(
        self, region: str, zone: str, gpu_type: str, cpu: int, memory_mb: int
    ) -> dict[str, float]:
        out: dict[str, float] = {}
        for charge in ("Postpay", "Spot"):
            try:
                data = self.call(
                    "GetCompShareInstancePrice",
                    {
                        "Region": region,
                        "Zone": zone,
                        "GpuType": gpu_type,
                        "Gpu": 1,
                        "Cpu": cpu,
                        "Memory": memory_mb,
                        "ChargeType": charge,
                    },
                )
            except (ProviderError, AuthRequired):
                continue
            for detail in data.get("PriceDetails") or []:
                if detail.get("ChargeType") == charge and detail.get("Instance") is not None:
                    try:
                        out[charge] = float(detail["Instance"])
                    except (TypeError, ValueError):
                        pass
        return out


def pick_single_gpu_config(item: dict[str, Any]) -> tuple[int, int] | None:
    """从 MachineSizes 中选 1 卡的最低 CPU/内存组合，返回 (cpu, memory_gb)。"""
    best: tuple[int, int] | None = None
    for size in item.get("MachineSizes") or []:
        if not isinstance(size, dict):
            continue
        try:
            if int(size.get("Gpu") or 0) != 1:
                continue
        except (TypeError, ValueError):
            continue
        for combo in size.get("Collection") or []:
            if not isinstance(combo, dict):
                continue
            try:
                cpu = int(combo.get("Cpu") or 0)
            except (TypeError, ValueError):
                continue
            mems = [int(m) for m in (combo.get("Memory") or []) if str(m).isdigit()]
            if not cpu or not mems:
                continue
            candidate = (cpu, min(mems))
            if best is None or (candidate[0], candidate[1]) < (best[0], best[1]):
                best = candidate
    return best


class CompshareProvider(Provider):
    id = "compshare"
    name = "优云智算"
    homepage = "https://www.compshare.cn"
    accent = "#7C5CFF"
    auth_required = True
    credential_keys = ("compshare_public_key", "compshare_private_key")
    empty_message = "官网实时：当前没有 RTX 4090 / 5090 在售"
    description = "官方 API：实时在售 / 售罄状态 + 实时价格"

    def credentials_configured(self, config: Any) -> bool:  # noqa: ANN401
        return bool(config.credential("compshare_public_key") and config.credential("compshare_private_key"))

    def fetch(self, ctx: FetchContext) -> list[Offer]:
        public_key = ctx.config.credential("compshare_public_key")
        private_key = ctx.config.credential("compshare_private_key")
        if not public_key or not private_key:
            raise AuthRequired(
                "优云智算实时库存需要官方 API 密钥：控制台 → 账户中心 → API 密钥，"
                "填入 AccessKey ID / Secret 后即可显示实时在售状态"
            )

        api = CompshareAPI(ctx, public_key, private_key)
        zones = api.zones()
        offers: list[Offer] = []
        zone_ok = False

        for region, zone, zone_name in zones:
            try:
                types = api.available_types(region, zone)
                zone_ok = True
            except AuthRequired:
                raise
            except ProviderError:
                continue

            targets: list[tuple[dict[str, Any], str, str, int, int, int]] = []
            for item in types:
                name = str(item.get("Name") or "")
                norm = normalize_gpu(name)
                if norm is None:
                    continue
                display, family, vram = norm
                config = pick_single_gpu_config(item)
                if config is None:
                    continue
                cpu, mem_gb = config
                targets.append((item, display, family, vram, cpu, mem_gb))

            if not targets:
                continue

            image_id = api.default_image(region, zone)

            # 价格 + 官方容量检查并发
            def _probe(target: tuple[dict[str, Any], str, str, int, int, int]) -> tuple[dict[str, float], bool | None]:
                item, display, family, vram, cpu, mem_gb = target
                try:
                    prices = api.price(region, zone, str(item.get("Name")), cpu, mem_gb * 1024)
                except (ProviderError, AuthRequired):
                    prices = {}
                enough = api.capacity(region, zone, str(item.get("Name")), image_id, cpu, mem_gb)
                return prices, enough

            with ThreadPoolExecutor(max_workers=4) as pool:
                probes = list(pool.map(_probe, targets))

            for (item, display, family, vram, cpu, mem_gb), (price_map, capacity_ok) in zip(targets, probes):
                status = str(item.get("Status") or "")
                if capacity_ok is not None:
                    available = capacity_ok
                else:
                    available = True if status == "Normal" else (False if status == "SoldOut" else None)
                postpay = price_map.get("Postpay")
                spot = price_map.get("Spot")
                notes = [f"{cpu}C · {mem_gb}G 内存"]
                if spot is not None:
                    notes.append(f"抢占价 ¥{spot:.2f}/时")
                if status == "SoldOut":
                    notes.append("官网售罄")
                elif capacity_ok is False:
                    notes.append("当前库存不足")
                offers.append(
                    Offer(
                        platform=self.id,
                        platform_name=self.name,
                        gpu=display,
                        family=family,
                        vram_gb=vram,
                        region=zone_name,
                        price=round(postpay, 4) if postpay is not None else None,
                        billing="按量计费",
                        available=available,
                        stock=None,
                        capacity=None,
                        status="live",
                        source="api",
                        source_label="优云智算官方 API（实时）",
                        source_url=API_URL,
                        url=CONSOLE_URL,
                        notes="；".join(notes),
                        specs={
                            "config": f"{cpu}C · {mem_gb}G 内存",
                            "gpu_type": str(item.get("Name") or ""),
                            "cpu": cpu,
                            "mem_gb": mem_gb,
                            "region_id": region,
                            "zone_id": zone,
                            "zone_name": zone_name,
                        },
                        rent={
                            "platform": "compshare",
                            "gpu_type": str(item.get("Name") or ""),
                            "cpu": cpu,
                            "mem_gb": mem_gb,
                            "region": region,
                            "zone": zone,
                            "zone_name": zone_name,
                        },
                    )
                )

        if not offers and not zone_ok:
            raise ProviderError("优云智算 API 所有可用区均请求失败")
        return offers
