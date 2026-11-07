"""恒源云（gpushare）一键租卡。"""

from __future__ import annotations

import time
from typing import Any

from .config import Config
from .http import HttpClient, HttpError
from .gpu import normalize_gpu

API = "https://api.gpushare.com/app"
WEB = "https://gpushare.com/"


class GpushareRentError(Exception):
    pass


class GpushareRenter:
    def __init__(self, config: Config, http: HttpClient | None = None) -> None:
        self.config = config
        self.http = http or HttpClient(timeout=35, retries=1)
        self._image_cache: tuple[float, str, str, float] | None = None

    def _headers(self) -> dict[str, str]:
        token = self.config.credential("gpushare_token")
        if not token:
            raise GpushareRentError("请先在设置里填写恒源云 token")
        return {"Authorization": f"Bearer {token}", "Origin": "https://gpushare.com", "Referer": WEB}

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            resp = self.http.get(API + path, params=params, headers=self._headers())
            data = resp.json()
        except (HttpError, ValueError) as exc:
            raise GpushareRentError(f"恒源云请求失败：{exc}") from exc
        if data.get("status") != 0:
            raise GpushareRentError(f"恒源云：{data.get('msg') or '未知错误'}")
        return data

    def _put(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            resp = self.http.put_json(API + path, payload, headers=self._headers())
            data = resp.json()
        except (HttpError, ValueError) as exc:
            raise GpushareRentError(f"恒源云请求失败：{exc}") from exc
        if data.get("status") != 0:
            raise GpushareRentError(f"恒源云：{data.get('msg') or '未知错误'}")
        return data

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            resp = self.http.post_json(API + path, payload, headers=self._headers())
            data = resp.json()
        except (HttpError, ValueError) as exc:
            raise GpushareRentError(f"恒源云请求失败：{exc}") from exc
        if data.get("status") != 0:
            raise GpushareRentError(f"恒源云：{data.get('msg') or '未知错误'}")
        return data

    @property
    def settings(self) -> dict[str, Any]:
        return dict(self.config.rent or {})

    # ------------------------------------------------------------------ 镜像
    def default_image(self, max_cuda: float = 0) -> tuple[str, str]:
        if self._image_cache and time.time() - self._image_cache[0] < 1800 and self._image_cache[3] >= max_cuda:
            return self._image_cache[1], self._image_cache[2]
        data = self._get("/api/image/category", {"vmType": "docker"}).get("data") or {}
        frameworks = data.get("framework") or {}
        torch = frameworks.get("PyTorch") or {}
        if not torch:
            raise GpushareRentError("恒源云没有可用的 PyTorch 镜像")

        def num(text: Any) -> float:
            try:
                parts = str(text).split("(")[0].split(".")
                return float(".".join(parts[:2]))
            except ValueError:
                return 0.0

        for ver in sorted(torch, key=num, reverse=True):
            cudas = torch[ver] or {}
            for cuda in sorted(cudas, key=num, reverse=True):
                pys = cudas[cuda] or []
                if not pys:
                    continue
                if max_cuda and num(cuda) > max_cuda:
                    continue
                py = str(pys[0])
                info = self._get(
                    "/api/image/select",
                    {"framework": "PyTorch", "frameworkVer": ver, "runtimeVer": py,
                     "toolkitVer": cuda, "vmType": "docker"},
                ).get("data") or {}
                image_id = str(info.get("imageId") or "")
                if image_id:
                    name = f"PyTorch {ver} / Python {py} / CUDA {cuda}"
                    self._image_cache = (time.time(), image_id, name, max_cuda)
                    return image_id, name
        raise GpushareRentError("恒源云镜像解析失败")

    # ------------------------------------------------------------------ 机器
    def _machines(self) -> list[dict[str, Any]]:
        data = self._get(
            "/api/market/machine/list",
            {"models": "-1", "gpuName": "", "priceOrder": "asc", "ps": "200",
             "minGpuNum": "0", "maxGpuNum": "24", "vmType": "docker", "pn": "1"},
        ).get("data") or {}
        return data.get("list") or []

    def quote(self, gpu_type: str, region: str, price: float | None = None) -> dict[str, Any]:
        candidates = []
        for m in self._machines():
            base = m.get("baseInfo") or {}
            gpu = normalize_gpu(" ".join(str(x) for x in (base.get("gpuName"), m.get("gpuName")) if x))
            if not gpu or gpu[0] != gpu_type:
                continue
            if str(m.get("regionName") or "") != region:
                continue
            idle = int(m.get("gpuNum") or 0) - int(m.get("gpuUsed") or 0)
            if idle <= 0 or not m.get("isOnline") or int(m.get("status") or 0) != 1:
                continue
            payg = next((s for s in (m.get("skuList") or []) if s.get("skuName") == "payg" and s.get("enable") == 1), None)
            if not payg:
                continue
            p = float(payg.get("price") or 0)
            if price is not None and abs(p - price) > 0.001:
                continue
            candidates.append((m, p, idle))
        if not candidates:
            raise GpushareRentError(f"{region} 当前没有可租的 {gpu_type}")
        candidates.sort(key=lambda x: (x[1], -x[2]))
        machine, p, idle = candidates[0]
        max_price = float(self.settings.get("max_hourly_price") or 5)
        if p > max_price:
            raise GpushareRentError(f"价格 ¥{p}/时 超过设置上限 ¥{max_price:.2f}/时")
        toolkit = machine.get("gpuToolkitVersion") or (machine.get("baseInfo") or {}).get("gpuToolkitVersion") or "12.0"
        try:
            max_cuda = float(str(toolkit).split(".")[0])
        except ValueError:
            max_cuda = 12.0
        image_id, image_name = self.default_image(max_cuda)
        base = machine.get("baseInfo") or {}
        gpu_num = max(1, int(machine.get("gpuNum") or 1))
        try:
            cpu = round(int(base.get("cpuCoreNum") or 0) / gpu_num)
        except (TypeError, ValueError):
            cpu = 0
        try:
            mem_gb = round(int(base.get("memoryTotal") or 0) / gpu_num / (1024**3))
        except (TypeError, ValueError):
            mem_gb = 0
        return {
            "platform": "gpushare",
            "machine_id": str(machine.get("machineId") or ""),
            "gpu_type": gpu_type,
            "region": region,
            "zone": "",
            "zone_name": region,
            "cpu": cpu,
            "mem_gb": mem_gb,
            "image_id": image_id,
            "image_name": image_name,
            "disk_gb": 50,
            "price": p,
            "capacity": True,
            "auto_stop_minutes": 0,
            "max_hourly_price": max_price,
            "enabled": bool(self.settings.get("enabled")),
        }

    # ------------------------------------------------------------------ 创建 / 实例
    def create(self, machine_id: str, image_id: str, name: str = "", confirm: str = "") -> dict[str, Any]:
        if confirm != "RENT":
            raise GpushareRentError("需要二次确认（confirm=RENT）")
        if not self.settings.get("enabled"):
            raise GpushareRentError("租卡功能未启用，请先在设置中打开并保存")
        data = self._post(
            "/api/instance/create",
            {"models": -1, "machineId": machine_id, "skuName": "payg", "unit": 1,
             "imageId": image_id, "autoRenew": False},
        ).get("data") or {}
        instance_id = str(data.get("instanceId") or "")
        if not instance_id:
            raise GpushareRentError("创建成功但没有返回实例 ID")
        return self.instance(instance_id)

    def instances(self) -> list[dict[str, Any]]:
        data = self._get("/api/instance/list", {"pn": 1, "ps": 50}).get("data") or {}
        return [self._map(r) for r in (data.get("list") or [])]

    def instance(self, instance_id: str) -> dict[str, Any]:
        for raw in self.instances():
            if raw["uhost_id"] == instance_id:
                return raw
        raise GpushareRentError("实例还没有出现在列表中，请稍后刷新")

    def _map(self, raw: dict[str, Any]) -> dict[str, Any]:
        tools = {t.get("key"): t for t in (raw.get("toolsAttrs") or [])}
        ssh = tools.get("ssh") or {}
        cmd = str(ssh.get("cmd") or "")
        password = str(ssh.get("passwd") or "")
        host = ""
        if cmd.startswith("ssh "):
            parts = cmd.split()
            host = parts[-1].split("@")[-1] if parts else ""
        machine = raw.get("machine") or {}
        return {
            "platform": "gpushare",
            "uhost_id": str(raw.get("instanceId") or ""),
            "region": str(machine.get("regionId") or ""),
            "zone": str(machine.get("machineId") or ""),
            "zone_name": str(machine.get("regionId") or ""),
            "gpu_type": str(machine.get("gpuName") or ""),
            "gpu": str(machine.get("gpuName") or ""),
            "cpu": machine.get("cpuCoreNum"),
            "mem_gb": round((int(machine.get("memoryTotal") or 0)) / (1024**3)) or None,
            "price": float(raw.get("price")) if raw.get("price") else None,
            "image_name": str(raw.get("imageId") or ""),
            "name": str(raw.get("instanceId") or ""),
            "state": str(raw.get("status") or ""),
            "ip": host,
            "ssh_command": cmd,
            "password": password,
            "released": int(raw.get("deleted") or 0) == 1,
            "auto_stop_at": raw.get("scheduleStopTime"),
            "error": "",
            "warning": "",
            "ssh": {"command": cmd, "password": password, "ip": host, "user": str(ssh.get("username") or "root")},
        }

    def terminate(self, instance_id: str) -> dict[str, Any]:
        try:
            info = self.instance(instance_id)
        except GpushareRentError:
            info = {}
        state = str(info.get("state") or "")
        if state not in ("stop", "stopped", "shutdown"):
            self._put("/api/instance/manage", {"instanceId": instance_id, "skuName": "payg", "actionName": "stop"})
            deadline = time.time() + 180
            while time.time() < deadline:
                time.sleep(4)
                try:
                    state = str(self.instance(instance_id).get("state") or "")
                except GpushareRentError:
                    state = "gone"
                if state in ("stop", "stopped", "shutdown", "gone"):
                    break
        if state == "gone":
            return self._released(instance_id)
        self._put("/api/instance/manage", {"instanceId": instance_id, "skuName": "payg", "actionName": "release"})
        deadline = time.time() + 180
        while time.time() < deadline:
            time.sleep(4)
            try:
                self.instance(instance_id)
            except GpushareRentError:
                return self._released(instance_id)
        return self._released(instance_id)

    @staticmethod
    def _released(instance_id: str) -> dict[str, Any]:
        return {
            "platform": "gpushare", "uhost_id": instance_id, "state": "released", "released": True,
            "region": "", "zone": "", "zone_name": "", "gpu_type": "", "gpu": "",
            "cpu": None, "mem_gb": None, "price": None, "image_name": "", "name": instance_id,
            "ip": "", "ssh_command": "", "password": "", "auto_stop_at": None,
            "error": "", "warning": "", "ssh": {"command": "", "password": "", "ip": "", "user": "root"},
        }
