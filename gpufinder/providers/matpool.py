"""矩池云（matpool.com）算力市场适配器。

数据来源：官网 ``https://matpool.com/host-market`` 的 Next.js RSC 内嵌
``initialData``（游客可见分区，公开数据），包含每个资源池的 GPU 型号、
空闲卡数 / 总卡数、按小时价格与硬件规格。

价格字段 ``priceMillicent`` 的单位是「毫分」= 0.00001 元，
例如 220000 -> ¥2.20/卡·小时。
"""

from __future__ import annotations

import json
import re
from typing import Any

from ..gpu import normalize_gpu
from ..http import HttpError
from ..models import Offer
from .base import FetchContext, Provider, ProviderError

MARKET_URL = "https://matpool.com/host-market"
SITE_URL = "https://matpool.com"

_PUSH_RE = re.compile(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)')


def _repair_mojibake(text: str) -> str:
    """修复 RSC 里按字节转义的 UTF-8 中文（\u00e5\u008c\u00ba -> 区）。"""
    if not text:
        return text
    if any("\u0080" <= ch <= "\u00ff" for ch in text):
        try:
            fixed = text.encode("latin-1").decode("utf-8")
            return fixed
        except (UnicodeEncodeError, UnicodeDecodeError):
            return text
    return text


def _extract_json_object(text: str, start: int) -> str:
    """从 ``start`` 处的 ``{`` 开始截取配平的 JSON 对象（正确处理字符串/转义）。"""
    depth = 0
    in_str = False
    esc = False
    for idx in range(start, len(text)):
        ch = text[idx]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : idx + 1]
    raise ProviderError("矩池云页面数据结构不完整")


def parse_host_market(html: str) -> dict[str, Any]:
    """从 host-market 页面 HTML 中解析出 initialData。"""
    chunks: list[str] = []
    for m in _PUSH_RE.finditer(html):
        try:
            chunks.append(json.loads(m.group(1)))
        except ValueError:
            continue
    payload = "".join(chunks)
    if not payload:
        raise ProviderError("矩池云页面未找到内嵌数据（可能改版）")

    key = '"initialData":'
    idx = payload.find(key)
    if idx < 0:
        raise ProviderError("矩池云页面缺少 initialData（可能改为登录可见）")
    brace = payload.find("{", idx + len(key))
    if brace < 0:
        raise ProviderError("矩池云 initialData 解析失败")
    raw = _extract_json_object(payload, brace)
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise ProviderError(f"矩池云 initialData JSON 解析失败: {exc}") from exc
    if not isinstance(data, dict) or "pools" not in data:
        raise ProviderError("矩池云 initialData 结构变化")
    return data


def _region_name(domain: int, domain_map: dict[int, str]) -> str:
    # 实时 market 接口把默认/1区标成 domain 0，而页面展示为「1区」。
    if domain == 0:
        return "1区"
    name = domain_map.get(domain)
    if name:
        return _repair_mojibake(name)
    return f"{domain} 区"


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_pools(data: dict[str, Any]) -> list[Offer]:
    domain_map: dict[int, str] = {}
    for info in data.get("domainInfos") or []:
        try:
            domain = int(info.get("domain"))
        except (TypeError, ValueError):
            continue
        name = info.get("displayName") or ""
        if name:
            domain_map[domain] = name

    provider_name = "矩池云"
    merged: dict[tuple[str, int, float | None], dict[str, Any]] = {}

    for pool in data.get("pools") or []:
        if not isinstance(pool, dict):
            continue
        gpu_raw = str(pool.get("gpu_model") or "")
        norm = normalize_gpu(gpu_raw)
        if norm is None:
            continue
        display, family, vram = norm

        machine = pool.get("machine") or {}
        gpu = machine.get("gpu") or {}
        hardware = machine.get("hardware") or {}
        hw_machine = hardware.get("machine") or {}

        available = _int(gpu.get("available")) or 0
        total = _int(gpu.get("total"))
        price_millicent = _num(hardware.get("discountPriceMillicent"))
        if not price_millicent:
            price_millicent = _num(hardware.get("priceMillicent"))
        price = round(price_millicent / 100000.0, 4) if price_millicent else None

        domain = _int(pool.get("domain")) or 0
        cpu_ids = hw_machine.get("cpuIds") or []
        specs = {
            "cpu_cores": len(cpu_ids) if isinstance(cpu_ids, list) and cpu_ids else None,
            "ram_gb": round((_num(hw_machine.get("ramMB")) or 0) / 1024) or None,
            "disk_gb": _int(hw_machine.get("diskGB")),
            "driver": gpu.get("driver") or pool.get("driver_version") or "",
            "tflops": _num(gpu.get("tflops")),
        }
        specs = {k: v for k, v in specs.items() if v not in (None, "")}

        key = (display, domain, price)
        bucket = merged.setdefault(
            key,
            {
                "family": family,
                "vram": vram,
                "domain": domain,
                "available": 0,
                "total": 0,
                "specs": specs,
                "owner": pool.get("isProprietary"),
            },
        )
        bucket["available"] += available
        bucket["total"] += total or 0
        if not bucket["specs"] and specs:
            bucket["specs"] = specs

    offers: list[Offer] = []
    for (display, domain, price), info in merged.items():
        region = _region_name(domain, domain_map)
        avail = int(info["available"])
        total = int(info["total"])
        offers.append(
            Offer(
                platform="matpool",
                platform_name=provider_name,
                gpu=display,
                family=info["family"],
                vram_gb=info["vram"],
                region=region,
                price=price,
                billing="按分钟计费",
                available=avail > 0,
                stock=avail,
                capacity=total or None,
                status="live",
                source="scrape",
                source_label="官网算力市场（游客可见）",
                source_url=MARKET_URL,
                url=MARKET_URL,
                notes="分钟级计费" + ("，自有机器" if info.get("owner") else ""),
                specs=info["specs"],
                rent={
                    "platform": "matpool",
                    "gpu_type": display,
                    "region": region,
                    "price": price,
                },
            )
        )

    if not offers:
        raise ProviderError("矩池云未返回 4090/5090 资源（可能临时无在售）")
    return offers


class MatpoolProvider(Provider):
    id = "matpool"
    name = "矩池云"
    homepage = SITE_URL
    accent = "#14B8A6"
    description = "官网算力市场公开数据（RSC 内嵌 JSON）"

    def fetch(self, ctx: FetchContext) -> list[Offer]:
        try:
            resp = ctx.http.get(
                MARKET_URL,
                headers={"Referer": SITE_URL + "/", "Accept": "text/html"},
                timeout=ctx.timeout,
            )
        except HttpError as exc:
            raise ProviderError(f"矩池云请求失败: {exc}") from exc
        if resp.status >= 400:
            raise ProviderError(f"矩池云返回 HTTP {resp.status}")
        data = parse_host_market(resp.text)
        return parse_pools(data)
