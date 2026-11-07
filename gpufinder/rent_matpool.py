"""矩池云（matpool）一键租卡。"""

from __future__ import annotations

import json
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
            raise MatpoolRentError(f"{region} 当前没有可租的 {gpu_type}")
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
            "image_id": image_id,
            "image_name": image_name,
            "disk_gb": machine.get("diskGB"),
            "price": info["price"],
            "capacity": True,
            "auto_stop_minutes": 0,
            "max_hourly_price": float((self.config.rent or {}).get("max_hourly_price") or 5),
            "enabled": bool((self.config.rent or {}).get("enabled")),
        }

    def _default_image(self, pool: dict[str, Any]) -> tuple[int, str]:
        images = self._get(
            "/images",
            {"resource_pool_id": pool.get("resource_pool_id"), "machine_category": 0, "page": 1, "per_page": 50},
        ).get("images") or []

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
        if policy != "latest":
            capped = [i for i in torch if cuda(str(i.get("description") or "")) <= 12.8]
            if capped:
                torch = capped
        if not torch:
            raise MatpoolRentError("矩池云没有可用的 PyTorch 镜像")
        torch.sort(key=lambda i: (cuda(str(i.get("description") or "")), i.get("id") or 0), reverse=True)
        img = torch[0]
        return int(img["id"]), str(img.get("alias") or f"image-{img['id']}")

    def create(self, resource_pool_id: str, image_id: str, name: str = "", confirm: str = "") -> dict[str, Any]:
        if confirm != "RENT":
            raise MatpoolRentError("需要二次确认（confirm=RENT）")
        if not (self.config.rent or {}).get("enabled"):
            raise MatpoolRentError("租卡功能未启用，请先在设置中打开并保存")
        payload = {
            "resource_pool_id": resource_pool_id,
            "machine_category": 0,
            "hardware_qty": 1,
            "auto_password": True,
            "vnc_switcher": True,
            "mount_infos": json.dumps([{"source": "/", "dest": "/mnt", "readOnly": False}]),
            "image_id": int(image_id),
        }
        data = self._send("POST", "/node", payload)
        node = data.get("node") or data.get("data") or {}
        node_id = node.get("id") if isinstance(node, dict) else None
        if not node_id:
            # 有些返回只给 request_id，去列表里找最新的节点
            nodes = self.instances()
            if nodes:
                return nodes[0]
            raise MatpoolRentError("创建成功但没有返回实例 ID")
        return self.instance(int(node_id))

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
        self._send("DELETE", "/node", {"id": int(node_id)})
        deadline = time.time() + 180
        while time.time() < deadline:
            time.sleep(4)
            try:
                info = self.instance(int(node_id))
            except MatpoolRentError:
                info = None
            if info is None or info.get("state") in ("released", "stopped"):
                if info is not None:
                    info["released"] = True
                    return info
                return {
                    "platform": "matpool", "uhost_id": node_id, "state": "released", "released": True,
                    "region": "", "zone": "", "zone_name": "", "gpu_type": "", "gpu": "",
                    "cpu": None, "mem_gb": None, "price": None, "image_name": "", "name": node_id,
                    "ip": "", "ssh_command": "", "password": "", "auto_stop_at": None,
                    "error": "", "warning": "",
                    "ssh": {"command": "", "password": "", "ip": "", "user": "root"},
                }
        raise MatpoolRentError("释放请求已发送，但实例仍在列表中，请稍后刷新")
