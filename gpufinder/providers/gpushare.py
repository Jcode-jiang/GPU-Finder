"""恒源云（gpushare.com）算力市场适配器。

公开接口 ``GET https://api.gpushare.com/app/api/market/machine/list``
需要登录态 ``Authorization: Bearer <token>``；返回每台机器的 GPU 总数/已用数、
在线状态、地区与各 SKU（含按小时价格）。

token 获取：登录 gpushare.com 后，浏览器 Cookie 中的 ``gpu_share_token``
（开发者工具 → Application → Cookies → https://www.gpushare.com）。
前端实际使用的请求头是 ``Authorization: Bearer <gpu_share_token>``。
"""

from __future__ import annotations

from typing import Any

from ..gpu import normalize_gpu
from ..http import HttpError
from ..models import Offer
from .base import AuthRequired, FetchContext, Provider, ProviderError

API_URL = "https://api.gpushare.com/app/api/market/machine/list"
SITE_URL = "https://gpushare.com"
MARKET_URL = "https://gpushare.com/store"

BASE_PARAMS: dict[str, str] = {
    "models": "-1",
    "gpuName": "",
    "priceOrder": "asc",
    "ps": "50",
    "minGpuNum": "1",
    "maxGpuNum": "24",
    "vmType": "docker",
    "tag": "",
}


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bearer(token: str) -> str:
    token = token.strip()
    if token.lower().startswith("bearer "):
        return token
    return f"Bearer {token}"


def extract_machines(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    data = payload.get("data")
    if isinstance(data, dict):
        rows = data.get("list") or data.get("records") or []
        if isinstance(rows, list):
            return [r for r in rows if isinstance(r, dict)], _int(data.get("total")) or len(rows)
    if isinstance(payload.get("list"), list):
        return payload["list"], len(payload["list"])
    return [], 0


_HOURLY_HINTS = ("按量", "时租", "小时", "hour", "payg", "on-demand", "ondemand")


def _best_sku(machine: dict[str, Any]) -> tuple[str, float | None]:
    """优先取按小时计费的 SKU，避免把包月单价当成时租。"""
    candidates: list[tuple[str, float, bool]] = []
    for sku in machine.get("skuList") or []:
        if not isinstance(sku, dict):
            continue
        if sku.get("enable") not in (1, "1", True, None):
            continue
        if sku.get("status") not in (1, "1", True, None):
            continue
        price = _float(sku.get("price"))
        if price is None or price <= 0:
            continue
        name = str(sku.get("skuName") or "")
        hourly = any(h in name.lower() for h in _HOURLY_HINTS)
        candidates.append((name, price, hourly))
    if not candidates:
        return "", None
    hourly = [c for c in candidates if c[2]]
    pool = hourly or candidates
    name, price, _ = min(pool, key=lambda c: c[1])
    return name, price


def parse_machines(machines: list[dict[str, Any]]) -> list[Offer]:
    buckets: dict[tuple[str, str, float | None, str], dict[str, Any]] = {}
    for m in machines:
        base = m.get("baseInfo") or {}
        gpu_text = " ".join(
            str(x)
            for x in (base.get("gpuName"), m.get("gpuName"), base.get("gpuMemory"))
            if x
        )
        gpu = normalize_gpu(gpu_text)
        if gpu is None:
            continue
        display, family, vram = gpu
        gpu_num = _int(m.get("gpuNum"))
        gpu_used = _int(m.get("gpuUsed"))
        idle = max(0, gpu_num - gpu_used)
        online = bool(m.get("isOnline"))
        active = _int(m.get("status")) == 1
        sku_name, price = _best_sku(m)
        region = str(m.get("regionName") or "恒源云")
        key = (display, region, price, sku_name)
        b = buckets.setdefault(
            key,
            {"family": family, "vram": vram, "idle": 0, "total": 0, "online": False, "active": False},
        )
        b["idle"] += idle if (online and active) else 0
        b["total"] += gpu_num
        b["online"] = b["online"] or online
        b["active"] = b["active"] or active

    offers: list[Offer] = []
    for (display, region, price, sku), b in buckets.items():
        idle = int(b["idle"])
        notes = []
        if sku:
            notes.append(f"SKU: {sku}")
        if not b["online"]:
            notes.append("机器离线")
        offers.append(
            Offer(
                platform="gpushare",
                platform_name="恒源云",
                gpu=display,
                family=b["family"],
                vram_gb=b["vram"],
                region=region,
                price=round(price, 4) if price is not None else None,
                billing="按量计费",
                available=idle > 0 and bool(b["online"]),
                stock=idle,
                capacity=int(b["total"]) or None,
                status="live",
                source="api",
                source_label="官网市场接口（登录态）",
                source_url=MARKET_URL,
                url=MARKET_URL,
                notes="；".join(notes),
                rent={
                    "platform": "gpushare",
                    "gpu_type": display,
                    "region": region,
                    "price": round(price, 4) if price is not None else None,
                },
            )
        )
    return offers


class GpushareProvider(Provider):
    id = "gpushare"
    name = "恒源云"
    homepage = SITE_URL
    accent = "#F59E0B"
    auth_required = True
    credential_keys = ("gpushare_token",)
    empty_message = "官网实时：当前没有 RTX 4090 / 5090 在售（恒源云公开市场仅 6 台机器）"
    description = "官方市场接口（需登录 token）"

    def _fetch_page(self, ctx: FetchContext, token: str, page: int) -> dict[str, Any]:
        params = dict(BASE_PARAMS)
        params["pn"] = str(page)
        try:
            resp = ctx.http.get(
                API_URL,
                params=params,
                headers={
                    "Authorization": _bearer(token),
                    "Origin": SITE_URL,
                    "Referer": SITE_URL + "/",
                },
                timeout=ctx.timeout,
            )
        except HttpError as exc:
            raise ProviderError(f"恒源云请求失败: {exc}") from exc
        if resp.status in (401, 403):
            raise AuthRequired("恒源云 token 无效或已过期，请重新获取")
        try:
            data = resp.json()
        except ValueError as exc:
            raise ProviderError(f"恒源云返回非 JSON（HTTP {resp.status}）") from exc
        status = data.get("status")
        if status not in (0, "0", None):
            msg = str(data.get("msg") or data.get("message") or "")
            if "auth" in msg.lower() or str(status) in ("401", "403"):
                raise AuthRequired(f"恒源云需要登录: {msg}")
            raise ProviderError(f"恒源云接口异常: status={status} {msg}")
        return data

    def fetch(self, ctx: FetchContext) -> list[Offer]:
        token = ctx.config.credential("gpushare_token")
        if not token:
            raise AuthRequired(
                "恒源云算力市场需要登录 token：登录 gpushare.com 后从浏览器 Cookie 复制 gpu_share_token 填入设置"
            )
        machines: list[dict[str, Any]] = []
        total = 0
        for page in range(1, 5):
            data = self._fetch_page(ctx, token, page)
            rows, total = extract_machines(data)
            machines.extend(rows)
            if len(machines) >= total or not rows:
                break
        return parse_machines(machines)
