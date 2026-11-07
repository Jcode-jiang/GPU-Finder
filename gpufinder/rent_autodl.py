"""AutoDL 一键租卡（网页登录态 API）。

已验证链路：machine/search → create/payg → instance 列表取 ssh_command/root_password
→ power_off → release。
"""

from __future__ import annotations

import time
from typing import Any

from .config import Config
from .http import HttpClient, HttpError
from .providers.autodl import API_BASE, MARKET_URL, DEFAULT_SEARCH_BODY, extract_list, normalize_item

TARGET_TYPES = ("RTX 4090", "RTX 4090D", "RTX 5090", "RTX 5090 D")
OFFLINE = {3, 4, 5, 6}


class AutoDLRentError(Exception):
    pass


class AutoDLRenter:
    def __init__(self, config: Config, http: HttpClient | None = None) -> None:
        self.config = config
        self.http = http or HttpClient(timeout=35, retries=1)

    def _headers(self) -> dict[str, str]:
        token = self.config.credential("autodl_token")
        if not token:
            raise AutoDLRentError("请先在设置里填写 AutoDL token")
        return {
            "Authorization": token,
            "Origin": "https://www.autodl.com",
            "Referer": MARKET_URL,
            "AppVersion": "2.18.0",
        }

    def _post(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            resp = self.http.post_json(API_BASE + path, payload or {}, headers=self._headers())
            data = resp.json()
        except (HttpError, ValueError) as exc:
            raise AutoDLRentError(f"AutoDL 请求失败：{exc}") from exc
        if data.get("code") != "Success":
            msg = data.get("msg") or data.get("code") or "未知错误"
            raise AutoDLRentError(f"AutoDL：{msg}")
        return data

    # ------------------------------------------------------------------ 镜像 / 机器
    def images(self) -> list[dict[str, Any]]:
        data = self._post("/api/v1/image/get", {}).get("data") or []
        out = []
        for item in data:
            if item.get("is_off"):
                continue
            out.append(
                {
                    "id": item.get("uuid"),
                    "name": f"{item.get('framework_name')} {item.get('framework_version')} "
                            f"{item.get('python_version')} / CUDA {item.get('cuda_version')}",
                    "type": "system",
                    "raw": item,
                }
            )
        return out

    def _default_image(self, max_cuda: float = 0) -> dict[str, Any]:
        configured = (self.rent_settings.get("autodl_image_id") or "").strip()
        imgs = [i for i in self.images() if i["id"]]
        if configured:
            for img in imgs:
                if img["id"] == configured:
                    return img
        # 只要 NVIDIA、x86 的 PyTorch 镜像，排除 MUSA/ROCm/ARM 版本
        def short_num(text: Any) -> float:
            try:
                parts = str(text).split(".")[:2]
                return float(".".join(parts))
            except ValueError:
                return 0.0

        def cuda_num(raw: dict[str, Any]) -> float:
            return short_num(raw.get("cuda_version") or "0")

        def version_num(raw: dict[str, Any]) -> float:
            return short_num(raw.get("framework_version") or "0")

        torch = [
            i for i in imgs
            if "PyTorch" in str(i["name"])
            and str(i["raw"].get("chip_corp") or "").lower() == "nvidia"
            and str(i["raw"].get("cpu_arch") or "x86") == "x86"
            and cuda_num(i["raw"]) >= 11.8
            and (not max_cuda or cuda_num(i["raw"]) <= max_cuda)
        ]
        torch.sort(key=lambda i: (version_num(i["raw"]), cuda_num(i["raw"]), i["raw"].get("rank") or 0), reverse=True)
        if torch:
            return torch[0]
        return imgs[0]

    @property
    def rent_settings(self) -> dict[str, Any]:
        return dict(self.config.rent or {})

    def _machines(self, gpu_type: str) -> list[dict[str, Any]]:
        gpu_type = "RTX 5090 D" if gpu_type == "RTX 5090D" else gpu_type
        body = dict(DEFAULT_SEARCH_BODY)
        body["gpu_type_name"] = [gpu_type]
        body["page_size"] = 500
        body["page_index"] = 1
        data = self._post("/api/v1/machine/search", body)
        rows, _ = extract_list(data)
        out = []
        for raw in rows:
            n = normalize_item(raw)
            if n and n["idle"] > 0 and n["online"]:
                out.append((raw, n))
        return out

    # ------------------------------------------------------------------ 报价
    def quote(self, gpu_type: str, region: str, price: float | None = None) -> dict[str, Any]:
        machines = self._machines(gpu_type)
        candidates = [(r, n) for r, n in machines if n["region"] == region]
        if not candidates:
            raise AutoDLRentError(f"{region} 当前没有可租的 {gpu_type}（接口空闲数可能已被抢走）")
        if price is not None:
            exact = [x for x in candidates if abs((x[1]["price"] or 0) - price) < 0.001]
            if exact:
                candidates = exact
        candidates.sort(key=lambda x: (-x[1]["idle"], x[1]["price"] or 99))
        raw, norm = candidates[0]
        try:
            detail = self._post("/api/v1/machine/detail", {"machine_id": raw.get("machine_id")}).get("data") or {}
            max_cuda = float(str(detail.get("highest_cuda_version") or "12.6").split(".")[0] + "." +
                             (str(detail.get("highest_cuda_version") or "12.6").split(".") + ["0"])[1])
        except (AutoDLRentError, ValueError):
            max_cuda = 12.6
        image = self._default_image(max_cuda)
        settings = self.rent_settings
        max_price = float(settings.get("max_hourly_price") or 5)
        p = norm["price"]
        if p is None or p > max_price:
            raise AutoDLRentError(f"价格 ¥{p}/时 超过设置上限 ¥{max_price:.2f}/时")
        return {
            "platform": "autodl",
            "machine_id": raw.get("machine_id"),
            "gpu_type": gpu_type,
            "region": region,
            "zone": "",
            "zone_name": region,
            "cpu": 22,
            "mem_gb": 90,
            "image_id": image["id"],
            "image_name": image["name"],
            "disk_gb": 0,
            "price": p,
            "spot": None,
            "capacity": True,
            "auto_stop_minutes": int(settings.get("auto_stop_minutes") or 60),
            "max_hourly_price": max_price,
            "enabled": bool(settings.get("enabled")),
        }

    # ------------------------------------------------------------------ 创建
    def create(self, machine_id: str, image_id: str, name: str = "", confirm: str = "",
               gpu_type: str = "", region: str = "", price: float | None = None) -> dict[str, Any]:
        if confirm != "RENT":
            raise AutoDLRentError("需要二次确认（confirm=RENT）")
        settings = self.rent_settings
        if not settings.get("enabled"):
            raise AutoDLRentError("租卡功能未启用，请先在设置中打开并保存")
        payload = {
            "instance_info": {
                "machine_id": machine_id,
                "charge_type": "payg",
                "req_gpu_amount": 1,
                "base_image_uuid": image_id,
                "private_image_uuid": "",
                "reproduction_uuid": "",
                "cg_application_uuid": "",
                "cg_application_info": {"image_name": "", "current_version_id": 0, "current_version": "", "image_id": 0},
                "instance_name": (name or "gpufinder")[:60],
                "expand_data_disk": 0,
                "reproduction_id": 0,
                "copy_data_disk_after_clone": False,
            },
            "price_info": {
                "coupon_id_list": [],
                "machine_id": machine_id,
                "charge_type": "payg",
                "duration": 1,
                "num": 1,
                "expand_data_disk": 0,
            },
        }
        last_error: AutoDLRentError | None = None
        uuid = ""
        try:
            data = self._post("/api/v1/order/instance/create/payg", payload)
            uuid = str(data.get("data") or "")
        except AutoDLRentError as exc:
            last_error = exc
        if not uuid and gpu_type and region:
            # 主机可能“已租满/存储已满”，自动换一台同地区同价位的空闲机器重试
            try:
                candidates = [(r, n) for r, n in self._machines(gpu_type)
                              if n["region"] == region and r.get("machine_id") != machine_id
                              and (price is None or abs((n["price"] or 0) - price) < 0.001)]
                candidates.sort(key=lambda x: -x[1]["idle"])
                for raw, _norm in candidates[:5]:
                    payload["instance_info"]["machine_id"] = raw.get("machine_id")
                    payload["price_info"]["machine_id"] = raw.get("machine_id")
                    try:
                        data = self._post("/api/v1/order/instance/create/payg", payload)
                        uuid = str(data.get("data") or "")
                        if uuid:
                            break
                    except AutoDLRentError as exc:
                        last_error = exc
            except AutoDLRentError:
                pass
        if not uuid:
            raise last_error or AutoDLRentError("创建成功但没有返回实例 ID")
        warning = ""
        minutes = int(settings.get("auto_stop_minutes") or 0)
        if minutes > 0:
            try:
                self.set_auto_stop(uuid, minutes)
            except AutoDLRentError as exc:
                warning = f"定时关机设置失败：{exc}"
        info = self.instance(uuid)
        deadline = time.time() + 120
        while time.time() < deadline:
            state = str(info.get("state") or "")
            if state == "running":
                break
            if state.startswith("shutdown") or state in ("error", "failed"):
                try:
                    self.terminate(uuid)
                except AutoDLRentError:
                    pass
                raise AutoDLRentError(f"实例启动失败（{state}），已尝试释放，请换一台机器或镜像重试")
            time.sleep(3)
            info = self.instance(uuid)
        info["warning"] = warning
        return info

    def set_auto_stop(self, uuid: str, minutes: int) -> None:
        from datetime import datetime, timedelta
        at = (datetime.now() + timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M")
        self._post("/api/v1/instance/timed/shutdown", {"instance_uuid": uuid, "shutdown_at": at})

    def instance(self, uuid: str) -> dict[str, Any]:
        data = self._post("/api/v1/instance", {}).get("data") or {}
        for raw in data.get("list") or []:
            if str(raw.get("uuid")) == uuid:
                return self._map(raw)
        raise AutoDLRentError("实例还没有出现在列表中，请稍后刷新")

    def instances(self) -> list[dict[str, Any]]:
        data = self._post("/api/v1/instance", {}).get("data") or {}
        return [self._map(r) for r in (data.get("list") or [])]

    def _map(self, raw: dict[str, Any]) -> dict[str, Any]:
        ssh = str(raw.get("ssh_command") or "")
        host = ""
        port = 22
        if ssh.startswith("ssh "):
            parts = ssh.split()
            if "-p" in parts:
                try:
                    port = int(parts[parts.index("-p") + 1])
                except (ValueError, IndexError):
                    port = 22
            host = parts[-1].split("@")[-1]
        return {
            "platform": "autodl",
            "uhost_id": str(raw.get("uuid")),
            "region": str(raw.get("region_name") or ""),
            "zone": str(raw.get("region_sign") or ""),
            "zone_name": str(raw.get("region_name") or ""),
            "gpu_type": str(raw.get("snapshot_gpu_alias_name") or ""),
            "gpu": str(raw.get("snapshot_gpu_alias_name") or ""),
            "cpu": raw.get("cpu_limit"),
            "mem_gb": round((raw.get("mem_limit_in_byte") or 0) / (1024**3)) or None,
            "price": (raw.get("payg_price") or 0) / 1000 if raw.get("payg_price") else None,
            "image_name": str(raw.get("image") or ""),
            "name": str(raw.get("uuid")),
            "state": str(raw.get("status") or ""),
            "ip": host,
            "ssh_command": ssh,
            "password": str(raw.get("root_password") or ""),
            "released": str(raw.get("status") or "") in ("released", "deleted"),
            "auto_stop_at": None,
            "error": "",
            "warning": "",
            "ssh": {"command": ssh, "password": str(raw.get("root_password") or ""), "ip": host, "user": "root"},
            "ssh_port": port,
        }

    def terminate(self, uuid: str) -> dict[str, Any]:
        self._post("/api/v1/instance/power_off", {"instance_uuid": uuid})
        deadline = time.time() + 180
        while time.time() < deadline:
            try:
                info = self.instance(uuid)
            except AutoDLRentError:
                info = {}
            state = str(info.get("state") or "")
            if state in ("shutdown", "stopped", "offline"):
                break
            time.sleep(3)
        self._post("/api/v1/instance/release", {"instance_uuid": uuid})
        try:
            return self.instance(uuid)
        except AutoDLRentError:
            return {
                "platform": "autodl", "uhost_id": uuid, "state": "released", "released": True,
                "region": "", "zone": "", "zone_name": "", "gpu_type": "", "gpu": "",
                "cpu": None, "mem_gb": None, "price": None, "image_name": "", "name": uuid,
                "ip": "", "ssh_command": "", "password": "", "auto_stop_at": None,
                "error": "", "warning": "", "ssh": {"command": "", "password": "", "ip": "", "user": "root"},
            }
