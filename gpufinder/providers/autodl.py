"""AutoDL（autodl.com）算力市场适配器。

AutoDL 的市场机器列表需要登录态：

* 公开接口 ``GET /api/v1/machine/gpu_type``、``/api/v1/region/list`` 可取到
  在售卡型与机房列表；
* 机器库存/价格接口 ``POST /api/v1/machine/search`` 需要
  ``Authorization: <token>``（浏览器 ``localStorage.token``，或
  ``gpufinder login autodl`` 自动换取）。

价格字段 ``payg_price`` 的单位是「厘/小时」，除以 1000 得到元/小时。
"""

from __future__ import annotations

import hashlib
from typing import Any

from ..http import HttpError
from ..models import Offer
from .base import AuthRequired, FetchContext, Provider, ProviderError

API_BASE = "https://api.autodl.com"
WEB_BASE = "https://www.autodl.com"
MARKET_URL = f"{WEB_BASE}/market/list"

# AutoDL 前端把 on_line 属于这些值的主机视为离线，空闲数按 0 处理
OFFLINE_ON_LINE = {3, 4, 5, 6}

DEFAULT_SEARCH_BODY: dict[str, Any] = {
    "charge_type": "payg",
    "region_sign": "",
    "region_sign_list": [],
    "gpu_type_name": [],
    "machine_tag_name": [],
    "gpu_idle_num": 0,
    "mount_net_disk": False,
    "cpu_arch": [],
    "chip_corp": [],
    "instance_disk_size_order": "",
    "date_range": "",
    "date_from": "",
    "date_to": "",
    "page_index": 1,
    "page_size": 100,
    "pay_price_order": "",
    "gpu_idle_type": "",
    "default_order": True,
}


def _auth_headers(token: str) -> dict[str, str]:
    token = token.strip()
    if token.lower().startswith("bearer "):
        return {"Authorization": token}
    return {"Authorization": token}


def _check(resp_json: dict[str, Any], what: str) -> dict[str, Any]:
    code = resp_json.get("code")
    if code == "Success":
        return resp_json
    if code == "AuthorizeFailed":
        raise AuthRequired(
            f"AutoDL {what} 登录态已失效：请重新登录 www.autodl.com 后复制 localStorage.token，"
            "或运行 `gpufinder login autodl` 自动换取新 token"
        )
    raise ProviderError(f"AutoDL {what} 接口异常: {code} {resp_json.get('msg') or ''}".strip())


def extract_list(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    data = payload.get("data")
    if isinstance(data, dict):
        for key in ("list", "machine_list", "machines", "items", "rows"):
            val = data.get(key)
            if isinstance(val, list):
                try:
                    total = int(data.get("result_total") or data.get("total") or len(val))
                except (TypeError, ValueError):
                    total = len(val)
                return val, total
        if isinstance(data.get("data"), list):
            return data["data"], len(data["data"])
    if isinstance(data, list):
        return data, len(data)
    return [], 0


def _first(item: dict[str, Any], keys: tuple[str, ...], default: Any = None) -> Any:
    for key in keys:
        if key in item and item[key] not in (None, ""):
            return item[key]
    return default


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def normalize_item(item: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    gpu_name = _first(item, ("gpu_name",), "") or ""
    if not gpu_name:
        gtype = item.get("gpu_type")
        if isinstance(gtype, str):
            gpu_name = gtype
        elif isinstance(gtype, dict):
            gpu_name = gtype.get("gpu_name") or gtype.get("name") or ""
    if not gpu_name:
        ginfo = item.get("gpu_type_info")
        if isinstance(ginfo, dict):
            gpu_name = ginfo.get("gpu_name") or ginfo.get("name") or ""
    if not gpu_name:
        return None

    gpu_mem = _int(item.get("gpu_memory") or item.get("gpu_memory_size"))
    idle = _int(item.get("gpu_idle_num"))
    total = _int(_first(item, ("gpu_number", "gpu_all_num", "gpu_total_number"), 0))

    on_line = item.get("on_line")
    if isinstance(on_line, int) and on_line in OFFLINE_ON_LINE:
        idle = 0
    max_inst = item.get("max_instance_num")
    binding = item.get("binding_instance_num")
    if isinstance(max_inst, int) and isinstance(binding, int) and (max_inst - binding) <= 0:
        idle = 0

    price_raw = _first(item, ("payg_price", "pay_price"))
    try:
        price = float(price_raw) / 1000.0 if price_raw is not None else None
    except (TypeError, ValueError):
        price = None

    return {
        "gpu_name": str(gpu_name),
        "region": str(_first(item, ("region_name", "region"), "") or ""),
        "region_sign": str(_first(item, ("region_sign",), "") or ""),
        "idle": max(0, idle),
        "total": max(0, total),
        "online": not (isinstance(on_line, int) and on_line in OFFLINE_ON_LINE),
        "price": price,
        "driver": str(item.get("driver_version") or ""),
        "tag": str(item.get("machine_tag_name") or ""),
        "gpu_mem_gb": round(gpu_mem / (1024**3), 1) if gpu_mem else None,
    }


def merge_machines(items: list[dict[str, Any]]) -> list[Offer]:
    from ..gpu import normalize_gpu

    buckets: dict[tuple[str, str, str, float | None], dict[str, Any]] = {}
    for raw in items:
        norm_item = normalize_item(raw)
        if not norm_item:
            continue
        gpu = normalize_gpu(norm_item["gpu_name"])
        if gpu is None:
            continue
        display, family, vram = gpu
        key = (display, norm_item["region"], norm_item["price"])
        b = buckets.setdefault(
            key,
            {
                "family": family,
                "vram": vram,
                "idle": 0,
                "total": 0,
                "online": False,
                "tags": set(),
                "driver": "",
                "gpu_mem": None,
            },
        )
        b["idle"] += norm_item["idle"]
        b["total"] += norm_item["total"]
        b["online"] = b["online"] or norm_item["online"]
        if norm_item["tag"]:
            b["tags"].add(norm_item["tag"])
        b["driver"] = b["driver"] or norm_item["driver"]
        b["gpu_mem"] = b["gpu_mem"] or norm_item["gpu_mem_gb"]

    offers: list[Offer] = []
    for (display, region, price), b in buckets.items():
        idle = int(b["idle"])
        offers.append(
            Offer(
                platform="autodl",
                platform_name="AutoDL",
                gpu=display,
                family=b["family"],
                vram_gb=int(b["gpu_mem"]) if b["gpu_mem"] else b["vram"],
                region=region or "AutoDL",
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
                notes="；".join(sorted(b["tags"])) if b["tags"] else "",
                specs={"driver": b["driver"]} if b["driver"] else {},
                rent={
                    "platform": "autodl",
                    "gpu_type": display,
                    "region": region or "AutoDL",
                    "price": round(price, 4) if price is not None else None,
                },
            )
        )
    return offers


class AutodlProvider(Provider):
    id = "autodl"
    name = "AutoDL"
    homepage = WEB_BASE
    accent = "#4F7CFF"
    auth_required = True
    credential_keys = ("autodl_token",)
    empty_message = "官网实时：当前没有 RTX 4090 / 5090 在售机器"
    description = "官方市场接口（region/gpu_type 公开，机器库存需 token）"

    # ------------------------------------------------------------------ 公共
    def _regions(self, ctx: FetchContext) -> list[str]:
        try:
            resp = ctx.http.get(f"{API_BASE}/api/v1/region/list", timeout=ctx.timeout)
            data = resp.json()
            rows = data.get("data") or []
            return [str(r.get("region_sign")) for r in rows if r.get("region_sign")]
        except (HttpError, ValueError, AttributeError):
            return []

    TARGET_TYPES = ("RTX 4090", "RTX 4090D", "RTX 5090", "RTX 5090 D")
    PAGE_SIZE = 500

    def _search_type(
        self,
        ctx: FetchContext,
        headers: dict[str, str],
        regions: list[str],
        gpu_type: str | None,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page = 1
        while page <= 6:
            body = dict(DEFAULT_SEARCH_BODY)
            body["region_sign_list"] = regions
            body["gpu_type_name"] = [gpu_type] if gpu_type else []
            body["page_index"] = page
            body["page_size"] = self.PAGE_SIZE
            try:
                resp = ctx.http.post_json(
                    f"{API_BASE}/api/v1/machine/search", body, headers=headers, timeout=ctx.timeout
                )
            except HttpError as exc:
                raise ProviderError(f"AutoDL 请求失败: {exc}") from exc
            try:
                data = resp.json()
            except ValueError as exc:
                raise ProviderError(f"AutoDL 返回非 JSON（HTTP {resp.status}）") from exc
            _check(data, "机器列表")
            batch, total = extract_list(data)
            items.extend(batch)
            if len(items) >= total or not batch:
                break
            page += 1
        return items

    def _search(self, ctx: FetchContext, token: str, regions: list[str]) -> list[dict[str, Any]]:
        headers = _auth_headers(token)
        headers["Origin"] = WEB_BASE
        headers["Referer"] = MARKET_URL

        # 只查询 4090 / 5090 系列，分页拉全，避免只看到前几百台机器
        seen: set[str] = set()
        items: list[dict[str, Any]] = []
        try:
            catalog = ctx.http.get(f"{API_BASE}/api/v1/machine/gpu_type", timeout=ctx.timeout).json()
            names = {str(t.get("gpu_name")) for t in (catalog.get("data") or [])}
            types = [t for t in self.TARGET_TYPES if t in names]
            if not types:
                types = list(self.TARGET_TYPES)
        except (HttpError, ValueError):
            types = list(self.TARGET_TYPES)

        for gpu_type in types:
            for row in self._search_type(ctx, headers, regions, gpu_type):
                mid = str(row.get("machine_id") or row.get("uuid") or "")
                if mid and mid in seen:
                    continue
                if mid:
                    seen.add(mid)
                items.append(row)
        return items

    def fetch(self, ctx: FetchContext) -> list[Offer]:
        token = ctx.config.credential("autodl_token")
        if not token:
            raise AuthRequired(
                "AutoDL 算力市场需要登录：请复制 www.autodl.com 登录后 localStorage 的 token"
                "（不是控制台开发者 Token），或运行 `gpufinder login autodl` 自动获取"
            )
        regions = self._regions(ctx)
        if not regions:
            # 地区接口失败时退化为空列表（等价于全部地区）
            regions = []
        items = self._search(ctx, token, regions)
        offers = merge_machines(items)
        if not offers:
            # 登录成功但当前市场没有 4090/5090（季节性售罄）也算成功
            return []
        return offers

    # ------------------------------------------------------------------ 登录
    @staticmethod
    def login(phone: str, password: str, timeout: float = 20.0) -> str:
        """手机号 + 密码换取 token（不保存密码）。"""
        from ..http import HttpClient, HttpError

        client = HttpClient(timeout=timeout, retries=1)
        sha1 = hashlib.sha1(password.encode("utf-8")).hexdigest()
        try:
            r1 = client.post_json(
                f"{API_BASE}/api/v1/new_login",
                {"phone": str(phone), "password": sha1, "phone_area": "+86"},
            ).json()
        except (HttpError, ValueError) as exc:
            raise ProviderError(f"AutoDL 登录请求失败: {exc}") from exc
        if r1.get("code") != "Success":
            raise ProviderError(f"AutoDL 登录失败: {r1.get('msg') or r1.get('code')}")
        ticket = (r1.get("data") or {}).get("ticket")
        if not ticket:
            raise ProviderError("AutoDL 登录未返回 ticket（可能需要图形验证码，请改用 token）")
        try:
            r2 = client.post_json(f"{API_BASE}/api/v1/passport", {"ticket": ticket}).json()
        except (HttpError, ValueError) as exc:
            raise ProviderError(f"AutoDL 换取 token 失败: {exc}") from exc
        token = (r2.get("data") or {}).get("token")
        if not token:
            raise ProviderError(f"AutoDL 未取得 token: {r2.get('msg') or ''}")
        return str(token)
