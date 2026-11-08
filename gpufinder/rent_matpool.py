"""矩池云（matpool）一键租卡。"""

from __future__ import annotations

import json
import math
import re
import time
import urllib.parse
from typing import Any

from .config import Config
from .gpu import normalize_gpu
from .http import HttpClient, HttpError
from .providers.matpool import MARKET_URL, parse_host_market, _region_name

API = "https://matpool.com/api"
WEB = "https://matpool.com/"


class MatpoolRentError(Exception):
    pass


class MatpoolRenter:
    def __init__(self, config: Config, http: HttpClient | None = None) -> None:
        self.config = config
        self.http = http or HttpClient(timeout=35, retries=1)
        self._domains: dict[int, str] | None = None

    def _headers(self) -> dict[str, str]:
        token = (self.config.credential("matpool_token") or "").strip()
        user_id = (self.config.credential("matpool_user_id") or "").strip()
        if not token:
            raise MatpoolRentError("请先在设置里填写矩池云 token")
        if token.lower().startswith("bearer "):
            token = token[7:].strip()
        token = urllib.parse.unquote(token)
        if not user_id:
            raise MatpoolRentError("请先在设置里填写矩池云用户 ID（X-Matpool-User-Id）")
        return {
            "Authorization": f"Bearer {token}",
            "X-Matpool-User-Id": user_id,
            "Origin": "https://matpool.com",
            "Referer": "https://matpool.com/host-market/gpu",
            "Accept": "application/json",
        }

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            resp = self.http.get(API + path, params=params, headers=self._headers())
            data = resp.json()
        except (HttpError, ValueError) as exc:
            raise MatpoolRentError(f"矩池云请求失败：{exc}") from exc
        if data.get("code") not in (0, None):
            raise MatpoolRentError(f"矩池云：{data.get('msg') or '未知错误'}")
        return data

    def _send(self, method: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            if method == "POST":
                resp = self.http.post_json(API + path, payload, headers=self._headers())
            elif method == "DELETE":
                resp = self.http.delete_json(API + path, payload, headers=self._headers())
            else:
                resp = self.http.put_json(API + path, payload, headers=self._headers())
            data = resp.json()
        except (HttpError, ValueError) as exc:
            raise MatpoolRentError(f"矩池云请求失败：{exc}") from exc
        if data.get("code") not in (0, None):
            raise MatpoolRentError(f"矩池云：{data.get('msg') or '未知错误'}")
        return data

    def active_count(self) -> int:
        return sum(1 for item in self.instances() if not item.get("released"))

    def balance(self) -> float:
        """矩池云余额（元）。account.balance 单位是分。"""
        data = self._get("/user/account")
        account = data.get("account") or {}
        return round(float(account.get("balance") or 0) / 100, 2)

    def _market(self) -> dict[str, Any]:
        try:
            html = self.http.get(MARKET_URL, headers={"Referer": WEB, "Accept": "text/html"}).text
        except HttpError as exc:
            raise MatpoolRentError(f"矩池云市场请求失败：{exc}") from exc
        data = parse_host_market(html)
        self._domains = {
            int(i.get("domain")): str(i.get("displayName") or "")
            for i in (data.get("domainInfos") or [])
            if str(i.get("domain") or "").isdigit()
        }
        return data

    def quote(self, gpu_type: str, region: str, price: float | None = None) -> dict[str, Any]:
        data = self._market()
        candidates: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for pool in data.get("pools") or []:
            norm = normalize_gpu(str(pool.get("gpu_model") or ""))
            if not norm or norm[0] != gpu_type:
                continue
            domain = int(pool.get("domain") or 0)
            name = _region_name(domain, self._domains or {})
            if name != region:
                continue
            if not pool.get("is_cn_resource", True):
                # 17区等第三方资源池需要额外云盘/卷挂载，当前创建路径不支持。
                continue
            available = int(pool.get("max_available_units") or 0)
            if available <= 0:
                continue
            hardware = ((pool.get("machine") or {}).get("hardware") or {})
            millicent = hardware.get("discountPriceMillicent") or hardware.get("priceMillicent")
            p = round(float(millicent) / 100000.0, 4) if millicent else None
            if price is not None and p is not None and abs(p - price) > 0.001:
                continue
            candidates.append((pool, {"price": p, "available": available}))
        if not candidates:
            raise MatpoolRentError(
                f"{region} 当前没有可租的 {gpu_type}（第三方资源池/云盘区域暂不支持一键租卡）"
            )
        candidates.sort(key=lambda x: (x[1]["price"] or 99, -x[1]["available"]))
        pool, info = candidates[0]
        image_id, image_name = self._default_image(pool)
        machine = ((pool.get("machine") or {}).get("machine") or {})
        return {
            "platform": "matpool",
            "machine_id": str(pool.get("resource_pool_id") or ""),
            "gpu_type": gpu_type,
            "region": region,
            "zone": str(pool.get("domain") or ""),
            "zone_name": region,
            "cpu": len(machine.get("cpuIds") or []) or None,
            "mem_gb": round((machine.get("ramMB") or 0) / 1024) or None,
            "image_id": str(image_id),
            "image_name": image_name,
            "disk_gb": machine.get("diskGB"),
            "price": info["price"],
            "capacity": True,
            "auto_stop_minutes": 0,
            "max_hourly_price": float((self.config.rent or {}).get("max_hourly_price") or 5),
            "enabled": bool((self.config.rent or {}).get("enabled")),
        }

    def _pool_images(self, pool: dict[str, Any]) -> list[dict[str, Any]]:
        return self._get(
            "/images",
            {"resource_pool_id": pool.get("resource_pool_id"), "machine_category": 0, "page": 1, "per_page": 50},
        ).get("images") or []

    def _default_image(self, pool: dict[str, Any]) -> tuple[int, str]:
        images = self._pool_images(pool)

        def cuda(text: str) -> float:
            m = re.search(r"CUDA\s+([0-9]+(?:\.[0-9]+)?)", text or "", re.I)
            try:
                return float(m.group(1)) if m else 0.0
            except ValueError:
                return 0.0

        policy = str((self.config.rent or {}).get("matpool_image_policy") or "auto")
        torch = [
            i for i in images
            if "pytorch" in (str(i.get("alias") or "") + " " + str(i.get("description") or "")).lower()
        ]
        # 优先“Pytorch 2.8.0”这类基础镜像，避免选中 wan-dancer / ComfyUI
        # 等应用镜像；应用镜像可能依赖卷或长时间初始化，导致实例一直 starting。
        base = [
            i for i in torch
            if re.fullmatch(r"pytorch\s+\d+(?:\.\d+)*", str(i.get("alias") or "").strip(), re.I)
        ]
        if base:
            torch = base
        if policy != "latest":
            capped = [i for i in torch if cuda(str(i.get("description") or "")) <= 12.8]
            if capped:
                torch = capped
        if not torch:
            raise MatpoolRentError("矩池云没有可用的 PyTorch 基础镜像")
        torch.sort(key=lambda i: (cuda(str(i.get("description") or "")), i.get("id") or 0), reverse=True)
        img = torch[0]
        return int(img["id"]), str(img.get("alias") or f"image-{img['id']}")

    def _validated_pool(self, resource_pool_id: str, gpu_type: str, region: str,
                        price: float | None) -> dict[str, Any]:
        if not resource_pool_id or not gpu_type or not region:
            raise MatpoolRentError("创建参数不完整：缺少 machine_id / gpu_type / region")
        data = self._market()
        for pool in data.get("pools") or []:
            if str(pool.get("resource_pool_id") or "") != str(resource_pool_id):
                continue
            norm = normalize_gpu(str(pool.get("gpu_model") or ""))
            if not norm or norm[0] != gpu_type:
                raise MatpoolRentError("资源池型号与报价不一致，请重新报价")
            domain = int(pool.get("domain") or 0)
            if _region_name(domain, self._domains or {}) != region:
                raise MatpoolRentError("资源池地区已变化，请重新报价")
            if not pool.get("is_cn_resource", True):
                raise MatpoolRentError("该区域是第三方资源池，需云盘挂载；当前版本暂不支持一键租卡")
            if int(pool.get("max_available_units") or 0) <= 0:
                raise MatpoolRentError("资源池当前无空闲卡，请刷新后重试")
            hardware = ((pool.get("machine") or {}).get("hardware") or {})
            millicent = hardware.get("discountPriceMillicent") or hardware.get("priceMillicent")
            if not millicent:
                raise MatpoolRentError("无法获取有效价格，已拒绝创建")
            current = round(float(millicent) / 100000.0, 4)
            if not math.isfinite(current) or current <= 0:
                raise MatpoolRentError("无法获取有效价格，已拒绝创建")
            if price is not None:
                try:
                    expected = float(price)
                except (TypeError, ValueError) as exc:
                    raise MatpoolRentError("报价参数无效，已拒绝创建") from exc
                if not math.isfinite(expected) or abs(current - expected) > 0.001:
                    raise MatpoolRentError(
                        f"报价已从 ¥{expected:.2f}/时 变为 ¥{current:.2f}/时，已拒绝创建"
                    )
            limit = float((self.config.rent or {}).get("max_hourly_price") or 5)
            if not math.isfinite(limit) or limit <= 0:
                raise MatpoolRentError("价格上限配置无效，已拒绝创建")
            if current > limit:
                raise MatpoolRentError(f"价格 ¥{current:.2f}/时 超过设置上限 ¥{limit:.2f}/时")
            return pool
        raise MatpoolRentError("目标资源池已下架或不存在，请重新报价")

    def create(self, resource_pool_id: str, image_id: str, name: str = "", confirm: str = "",
               gpu_type: str = "", region: str = "", price: float | None = None) -> dict[str, Any]:
        if confirm != "RENT":
            raise MatpoolRentError("需要二次确认（confirm=RENT）")
        if not (self.config.rent or {}).get("enabled"):
            raise MatpoolRentError("租卡功能未启用，请先在设置中打开并保存")
        pool = self._validated_pool(resource_pool_id, gpu_type, region, price)
        if not str(image_id).isdigit():
            raise MatpoolRentError("缺少有效镜像 ID，已拒绝创建")
        image_ids = {str(i.get("id")) for i in self._pool_images(pool)}
        if str(image_id) not in image_ids:
            raise MatpoolRentError("镜像不在该资源池中，请重新报价")
        before_ids = {item["uhost_id"] for item in self.instances()}
        payload = {
            "resource_pool_id": resource_pool_id,
            "machine_category": 0,
            "hardware_qty": 1,
            "auto_password": True,
            "vnc_switcher": True,
            "image_id": int(image_id),
        }
        # 第三方资源池（如 17区）没有自营卷，发送 mount_infos 会报 volume not exist。
        if pool.get("is_cn_resource", True):
            payload["mount_infos"] = json.dumps([{"source": "/", "dest": "/mnt", "readOnly": False}])
        data = self._send("POST", "/node", payload)
        node = data.get("node") or data.get("data") or {}
        node_id = node.get("id") if isinstance(node, dict) else None
        if node_id:
            deadline = time.time() + 30
            while time.time() < deadline:
                try:
                    return self.instance(int(node_id))
                except MatpoolRentError:
                    time.sleep(3)
            raise MatpoolRentError("创建接口返回了实例 ID，但实例尚未出现在列表中，请刷新核对")
        # 没有返回 ID 时，只能通过“创建前快照 + 唯一新节点”确认；
        # 绝不能把用户账户里的第一个旧节点当作刚创建的实例。
        deadline = time.time() + 30
        while time.time() < deadline:
            nodes = self.instances()
            new_nodes = [n for n in nodes if n.get("uhost_id") and n["uhost_id"] not in before_ids]
            if len(new_nodes) == 1:
                return new_nodes[0]
            if len(new_nodes) > 1:
                raise MatpoolRentError("检测到多个新实例，无法确认本次创建结果，请到控制台核对后再操作")
            time.sleep(3)
        raise MatpoolRentError("创建请求已发送，但无法确认实例 ID；请到矩池云控制台核对，切勿重复下单")

    def instances(self) -> list[dict[str, Any]]:
        data = self._get("/nodes", {"page": 1, "per_page": 50})
        if self._domains is None:
            try:
                self._market()
            except MatpoolRentError:
                self._domains = {}
        return [self._map(u) for u in (data.get("userNodes") or [])]

    def instance(self, node_id: int) -> dict[str, Any]:
        for item in self.instances():
            if item["uhost_id"] == str(node_id):
                return item
        raise MatpoolRentError("实例还没有出现在列表中，请稍后刷新")

    def _map(self, user_node: dict[str, Any]) -> dict[str, Any]:
        node = user_node.get("node") or {}
        hardware = node.get("hardware") or {}
        gpu = hardware.get("gpu") or {}
        ports = node.get("ports") or []
        ssh_port = 22
        host = ""
        for port in ports:
            if int(port.get("srcPort") or 0) == 22:
                url = str(port.get("url") or "")
                m = re.match(r"ssh://([^:]+):(\d+)", url)
                if m:
                    host, ssh_port = m.group(1), int(m.group(2))
                break
        auth = ((user_node.get("sshAuths") or [{}])[0].get("BaseOn") or {}).get("Cred") or {}
        password = str(auth.get("password") or "")
        user = str(auth.get("user") or "root")
        cmd = f"ssh -p {ssh_port} {user}@{host}" if host else ""
        status = int(user_node.get("status") or 0)
        state = {0: "creating", 1: "starting", 2: "running", 3: "stopped", 4: "released"}.get(status, str(status))
        price = hardware.get("discountPriceMillicent") or hardware.get("priceMillicent")
        return {
            "platform": "matpool",
            "uhost_id": str(node.get("id") or ""),
            "region": _region_name(int(node.get("domain") or 0), self._domains or {}),
            "zone": str(node.get("domain") or ""),
            "zone_name": _region_name(int(node.get("domain") or 0), self._domains or {}),
            "gpu_type": str(gpu.get("gpuName") or ""),
            "gpu": str(gpu.get("gpuName") or ""),
            "cpu": len((hardware.get("machine") or {}).get("cpuIds") or []) or None,
            "mem_gb": round(((hardware.get("machine") or {}).get("ramMB") or 0) / 1024) or None,
            "price": round(float(price) / 100000.0, 4) if price else None,
            "image_name": str((node.get("image") or {}).get("alias") or ""),
            "name": str(user_node.get("displayID") or node.get("id") or ""),
            "state": state,
            "ip": host,
            "ssh_command": cmd,
            "password": password,
            "released": state == "released",
            "auto_stop_at": None,
            "error": "",
            "warning": "",
            "ssh": {"command": cmd, "password": password, "ip": host, "user": user},
        }

    def terminate(self, node_id: str) -> dict[str, Any]:
        try:
            numeric_id = int(node_id)
        except (TypeError, ValueError) as exc:
            raise MatpoolRentError("无效的实例 ID") from exc
        try:
            current = self.instance(numeric_id)
        except MatpoolRentError as exc:
            # instance() 只会在列表请求成功且确实不存在时抛这句；网络失败必须区分。
            try:
                nodes = self.instances()
            except MatpoolRentError as list_exc:
                raise MatpoolRentError(f"无法确认实例当前状态，释放未执行：{list_exc}") from list_exc
            if not any(n.get("uhost_id") == str(node_id) for n in nodes):
                return self._released(node_id)
            raise MatpoolRentError(f"无法确认实例当前状态，释放未执行：{exc}") from exc
        if current.get("released") is True:
            return current
        self._send("DELETE", "/node", {"id": numeric_id})
        deadline = time.time() + 180
        while time.time() < deadline:
            time.sleep(4)
            try:
                nodes = self.instances()
            except MatpoolRentError:
                continue
            found = next((n for n in nodes if n.get("uhost_id") == str(node_id)), None)
            if found is None:
                return self._released(node_id)
            if found.get("released") is True:
                return found
            # stopped 只是关机，不等于销毁/停止计费，继续等待。
        raise MatpoolRentError("释放请求已发送，但 180 秒内未确认销毁；结果未确认，请到矩池云控制台核实")

    @staticmethod
    def _released(node_id: str) -> dict[str, Any]:
        return {
            "platform": "matpool", "uhost_id": node_id, "state": "released", "released": True,
            "region": "", "zone": "", "zone_name": "", "gpu_type": "", "gpu": "",
            "cpu": None, "mem_gb": None, "price": None, "image_name": "", "name": node_id,
            "ip": "", "ssh_command": "", "password": "", "auto_stop_at": None,
            "error": "", "warning": "",
            "ssh": {"command": "", "password": "", "ip": "", "user": "root"},
        }
