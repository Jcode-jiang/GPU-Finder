"""核心数据模型：GPU 报价、平台抓取结果、快照。

所有模型都可以安全地序列化为 JSON，Web Dashboard、CLI 与 macOS App
共用同一份 schema（``schema: 1``）。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any


SCHEMA_VERSION = 1


def now_iso() -> str:
    """本地时区的 ISO-8601 时间（精确到秒）。"""
    from datetime import datetime

    return datetime.now().astimezone().isoformat(timespec="seconds")


def _clean(d: dict[str, Any]) -> dict[str, Any]:
    """去掉 None 与空字符串，保持 JSON 精简。"""
    out: dict[str, Any] = {}
    for k, v in d.items():
        if v is None or v == "" or v == [] or v == {}:
            continue
        out[k] = v
    return out


@dataclass
class Offer:
    """一条「某平台某型号某地区」的实时/参考报价。"""

    platform: str
    platform_name: str
    gpu: str                 # 展示型号，例如 RTX 4090 / RTX 4090D
    family: str              # rtx4090 / rtx5090
    region: str
    price: float | None      # 元 / 卡 · 小时
    currency: str = "CNY"
    billing: str = "按量计费"
    available: bool | None = None
    stock: int | None = None       # 可租卡数
    capacity: int | None = None    # 该池总卡数
    vram_gb: int | None = None
    status: str = "live"      # live | reference | unknown
    source: str = "api"       # api | scrape | reference
    source_label: str = ""
    source_url: str = ""
    url: str = ""             # 下单/详情页
    fetched_at: str = field(default_factory=now_iso)
    notes: str = ""
    specs: dict[str, Any] = field(default_factory=dict)
    rent: dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return f"{self.platform}:{self.family}:{self.region}:{self.gpu}"

    @property
    def price_label(self) -> str:
        if self.price is None:
            return "价格未知"
        symbol = "$" if (self.currency or "").upper() == "USD" else "¥"
        return f"{symbol}{self.price:g}/时"

    @property
    def stock_label(self) -> str:
        if self.available is False:
            return "无货"
        if self.available is None:
            return "库存未知"
        if self.stock is None:
            return "有货"
        return f"有货 {self.stock} 卡"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["id"] = self.id
        d["price_label"] = self.price_label
        d["stock_label"] = self.stock_label
        d["available"] = self.available
        return _clean(d)


@dataclass
class ProviderResult:
    """单个平台一次抓取的产出。"""

    provider_id: str
    provider_name: str
    offers: list[Offer] = field(default_factory=list)
    mode: str = "live"        # live | reference | auth | error
    ok: bool = True
    message: str = ""
    latency_ms: int = 0
    homepage: str = ""
    accent: str = "#5B8DEF"
    auth_required: bool = False
    credentials_configured: bool = False
    started_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.provider_id,
            "name": self.provider_name,
            "ok": self.ok,
            "mode": self.mode,
            "message": self.message,
            "latency_ms": self.latency_ms,
            "offer_count": len(self.offers),
            "available_count": sum(1 for o in self.offers if o.available),
            "homepage": self.homepage,
            "accent": self.accent,
            "auth_required": self.auth_required,
            "credentials_configured": self.credentials_configured,
            "started_at": self.started_at,
        }


@dataclass
class Snapshot:
    """一次完整刷新的结果，供 API / CLI / App 消费。"""

    offers: list[Offer] = field(default_factory=list)
    providers: list[ProviderResult] = field(default_factory=list)
    generated_at: str = field(default_factory=now_iso)
    generated_ts: float = field(default_factory=time.time)
    duration_ms: int = 0
    stale: bool = False
    error: str = ""

    @property
    def families(self) -> dict[str, list[Offer]]:
        out: dict[str, list[Offer]] = {}
        for o in self.offers:
            out.setdefault(o.family, []).append(o)
        return out

    def summary(self) -> dict[str, Any]:
        by_family: dict[str, Any] = {}
        for fam, offers in self.families.items():
            avail = [o for o in offers if o.available]
            priced_all = [o for o in offers if o.price is not None]
            priced_avail = [o for o in avail if o.price is not None]
            pool = priced_avail or priced_all
            # 跨币种不能直接比较：优先人民币，其次才是美元
            cny = [o for o in pool if (o.currency or "CNY").upper() == "CNY"]
            usd = [o for o in pool if (o.currency or "").upper() == "USD"]
            cheapest = min(cny or usd, key=lambda o: o.price) if (cny or usd) else None
            by_family[fam] = _clean(
                {
                    "count": len(offers),
                    "available": len(avail),
                    "min_price": cheapest.price if cheapest else None,
                    "currency": cheapest.currency if cheapest else None,
                    "cheapest_platform": cheapest.platform_name if cheapest else None,
                    "cheapest_region": cheapest.region if cheapest else None,
                }
            )
        return {
            "offers": len(self.offers),
            "available": sum(1 for o in self.offers if o.available),
            "platforms_ok": sum(1 for p in self.providers if p.ok),
            "platforms_total": len(self.providers),
            "by_family": by_family,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA_VERSION,
            "id": uuid.uuid4().hex[:12],
            "generated_at": self.generated_at,
            "generated_ts": self.generated_ts,
            "duration_ms": self.duration_ms,
            "stale": self.stale,
            "error": self.error,
            "summary": self.summary(),
            "platforms": [p.to_dict() for p in self.providers],
            "offers": [
                {**o.to_dict(), "id": f"{o.platform}:{o.family}:{idx}"}
                for idx, o in enumerate(self.offers)
            ],
        }
