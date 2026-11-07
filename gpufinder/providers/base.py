"""Provider 基类与共享工具。"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from ..config import Config
from ..http import HttpClient
from ..models import Offer, ProviderResult, now_iso
from ..gpu import normalize_gpu


@dataclass
class FetchContext:
    config: Config
    http: HttpClient
    timeout: float = 20.0


class ProviderError(Exception):
    """抓取失败，服务层会使用参考数据/上次缓存兜底。"""


class AuthRequired(ProviderError):
    """需要登录态才能访问，但未配置凭据。"""


class Provider:
    id: str = ""
    name: str = ""
    homepage: str = ""
    accent: str = "#5B8DEF"
    auth_required: bool = False
    credential_keys: tuple[str, ...] = ()
    description: str = ""
    empty_message: str = ""

    def credentials_configured(self, config: Config) -> bool:
        if not self.credential_keys:
            return True
        return any(config.credential(k) for k in self.credential_keys)

    def fetch(self, ctx: FetchContext) -> list[Offer]:
        raise NotImplementedError

    # ------------------------------------------------------------------ 便捷方法
    def offer(
        self,
        *,
        gpu_text: str,
        region: str,
        price: float | None,
        url: str,
        source: str = "api",
        source_label: str = "",
        available: bool | None = None,
        stock: int | None = None,
        capacity: int | None = None,
        billing: str = "按量计费",
        notes: str = "",
        specs: dict[str, Any] | None = None,
        status: str = "live",
        source_url: str = "",
    ) -> Offer | None:
        norm = normalize_gpu(gpu_text)
        if norm is None:
            return None
        display, family, vram = norm
        return Offer(
            platform=self.id,
            platform_name=self.name,
            gpu=display,
            family=family,
            vram_gb=vram,
            region=region,
            price=round(price, 4) if price is not None else None,
            billing=billing,
            available=available,
            stock=stock,
            capacity=capacity,
            status=status,
            source=source,
            source_label=source_label,
            source_url=source_url,
            url=url or self.homepage,
            notes=notes,
            specs=specs or {},
        )

    def run(self, ctx: FetchContext) -> ProviderResult:
        started = time.perf_counter()
        result = ProviderResult(
            provider_id=self.id,
            provider_name=self.name,
            homepage=self.homepage,
            accent=self.accent,
            auth_required=self.auth_required,
            credentials_configured=self.credentials_configured(ctx.config),
            started_at=now_iso(),
        )
        try:
            offers = self.fetch(ctx)
            result.offers = sorted(
                offers, key=lambda o: (o.family, o.price if o.price is not None else 1e9, o.region)
            )
            result.ok = True
            result.mode = "live"
            if not offers and self.empty_message:
                result.message = self.empty_message
        except AuthRequired as exc:
            result.ok = False
            result.mode = "auth"
            result.message = str(exc)
        except ProviderError as exc:
            result.ok = False
            result.mode = "error"
            result.message = str(exc)
        except Exception as exc:  # noqa: BLE001 - 任何解析异常都不应拖垮其它平台
            result.ok = False
            result.mode = "error"
            result.message = f"{type(exc).__name__}: {exc}"
        result.latency_ms = int((time.perf_counter() - started) * 1000)
        return result
