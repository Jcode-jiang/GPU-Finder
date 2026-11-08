"""恒源云（gpushare）一键租卡。"""

from __future__ import annotations

import math
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
        self._image_list_cache: tuple[float, list[dict[str, Any]]] | None = None

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
        if not isinstance(data, dict):
            raise GpushareRentError("恒源云返回了非对象响应")
        if data.get("status") != 0:
            raise GpushareRentError(f"恒源云：{data.get('msg') or '未知错误'}")
        return data

    def _put(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            resp = self.http.put_json(API + path, payload, headers=self._headers())
            data = resp.json()
        except (HttpError, ValueError) as exc:
            raise GpushareRentError(f"恒源云请求失败：{exc}") from exc
        if not isinstance(data, dict):
            raise GpushareRentError("恒源云返回了非对象响应")
        if data.get("status") != 0:
            raise GpushareRentError(f"恒源云：{data.get('msg') or '未知错误'}")
        return data

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            resp = self.http.post_json(API + path, payload, headers=self._headers())
            data = resp.json()
        except (HttpError, ValueError) as exc:
            raise GpushareRentError(f"恒源云请求失败：{exc}") from exc
        if not isinstance(data, dict):
            raise GpushareRentError("恒源云返回了非对象响应")
        if data.get("status") != 0:
            raise GpushareRentError(f"恒源云：{data.get('msg') or '未知错误'}")
        return data

    @property
    def settings(self) -> dict[str, Any]:
        return dict(self.config.rent or {})

    def active_count(self) -> int:
        return sum(1 for item in self.instances() if not item.get("released"))

    def balance(self) -> float:
        data = self._get("/api/account/summary").get("data")
        if not isinstance(data, dict):
            raise GpushareRentError("恒源云余额响应格式异常")
        return round(float(data.get("totalBalance") or 0), 2)

    # ------------------------------------------------------------------ 镜像
    def images(self) -> list[dict[str, Any]]:
        """列出官方 PyTorch 镜像（id / 名称 / CUDA），用于设置页。"""
        if self._image_list_cache and time.time() - self._image_list_cache[0] < 1800:
            return self._image_list_cache[1]
        data = self._get("/api/image/category", {"vmType": "docker"}).get("data") or {}
        torch = (data.get("framework") or {}).get("PyTorch") or {}

        def num(text: Any) -> float:
            try:
                parts = str(text).split("(")[0].split(".")
                return float(".".join(parts[:2]))
            except ValueError:
                return 0.0

        out: list[dict[str, Any]] = []
        for ver in sorted(torch, key=num, reverse=True):
            cudas = torch[ver] or {}
            for cuda in sorted(cudas, key=num, reverse=True):
                for py in (cudas[cuda] or []):
                    info = self._get(
                        "/api/image/select",
                        {"framework": "PyTorch", "frameworkVer": ver, "runtimeVer": str(py),
                         "toolkitVer": cuda, "vmType": "docker"},
                    ).get("data") or {}
                    image_id = str(info.get("imageId") or "")
                    if not image_id:
                        continue
                    out.append({
                        "id": image_id,
                        "name": f"PyTorch {ver} / Python {py} / CUDA {cuda}",
                        "cuda": num(cuda),
                    })
        self._image_list_cache = (time.time(), out)
        return out

    def default_image(self, max_cuda: float = 0) -> tuple[str, str]:
        configured = str(self.settings.get("gpushare_image_id") or "").strip()
        if configured:
            try:
                for img in self.images():
                    if img["id"] != configured:
                        continue
                    if not max_cuda or float(img.get("cuda") or 0) <= max_cuda:
                        return img["id"], img["name"]
                    break
            except GpushareRentError:
                pass
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
            if not math.isfinite(p) or p <= 0:
                continue
            if price is not None and abs(p - price) > 0.001:
                continue
            candidates.append((m, p, idle))
        if not candidates:
            raise GpushareRentError(f"{region} 当前没有可租的 {gpu_type}")
        candidates.sort(key=lambda x: (x[1], -x[2]))
        machine, p, idle = candidates[0]
        max_price = float(self.settings.get("max_hourly_price") or 5)
        if not math.isfinite(max_price) or max_price <= 0:
            raise GpushareRentError("价格上限配置无效")
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
            "auto_stop_minutes": int(self.settings.get("gpushare_auto_stop_minutes") or self.settings.get("auto_stop_minutes") or 0),
            "max_hourly_price": max_price,
            "enabled": bool(self.settings.get("enabled")),
        }

    def _validated_machine(self, machine_id: str, gpu_type: str, region: str,
                           price: float | None) -> dict[str, Any]:
        if not machine_id or not gpu_type or not region:
            raise GpushareRentError("创建参数不完整：缺少 machine_id / gpu_type / region")
        for machine in self._machines():
            if str(machine.get("machineId") or "") != str(machine_id):
                continue
            base = machine.get("baseInfo") or {}
            gpu = normalize_gpu(" ".join(str(x) for x in (base.get("gpuName"), machine.get("gpuName")) if x))
            if not gpu or gpu[0] != gpu_type:
                raise GpushareRentError("机器型号与报价不一致，请重新报价")
            if str(machine.get("regionName") or "") != region:
                raise GpushareRentError("机器所属地区已变化，请重新报价")
            idle = int(machine.get("gpuNum") or 0) - int(machine.get("gpuUsed") or 0)
            if idle <= 0 or not machine.get("isOnline") or int(machine.get("status") or 0) != 1:
                raise GpushareRentError("机器当前无空闲卡，请刷新后重试")
            payg = next((s for s in (machine.get("skuList") or [])
                         if s.get("skuName") == "payg" and s.get("enable") == 1), None)
            if not payg:
                raise GpushareRentError("机器没有可用的按量计费 SKU，已拒绝创建")
            current = float(payg.get("price") or 0)
            if not math.isfinite(current) or current <= 0:
                raise GpushareRentError("无法获取有效价格，已拒绝创建")
            if price is not None:
                try:
                    expected = float(price)
                except (TypeError, ValueError) as exc:
                    raise GpushareRentError("报价参数无效，已拒绝创建") from exc
                if not math.isfinite(expected) or abs(current - expected) > 0.001:
                    raise GpushareRentError(
                        f"报价已从 ¥{expected:.2f}/时 变为 ¥{current:.2f}/时，已拒绝创建"
                    )
            limit = float(self.settings.get("max_hourly_price") or 5)
            if not math.isfinite(limit) or limit <= 0:
                raise GpushareRentError("价格上限配置无效，已拒绝创建")
            if current > limit:
                raise GpushareRentError(f"价格 ¥{current:.2f}/时 超过设置上限 ¥{limit:.2f}/时")
            return machine
        raise GpushareRentError("目标机器已下架或不存在，请重新报价")

    # ------------------------------------------------------------------ 创建 / 实例
    def create(self, machine_id: str, image_id: str, name: str = "", confirm: str = "",
               gpu_type: str = "", region: str = "", price: float | None = None) -> dict[str, Any]:
        if confirm != "RENT":
            raise GpushareRentError("需要二次确认（confirm=RENT）")
        if not self.settings.get("enabled"):
            raise GpushareRentError("租卡功能未启用，请先在设置中打开并保存")
        if not image_id:
            raise GpushareRentError("缺少镜像 ID，已拒绝创建")
        self._validated_machine(machine_id, gpu_type, region, price)
        data = self._post(
            "/api/instance/create",
            {"models": -1, "machineId": machine_id, "skuName": "payg", "unit": 1,
             "imageId": image_id, "autoRenew": False},
        ).get("data") or {}
        instance_id = str(data.get("instanceId") or "")
        if not instance_id:
            raise GpushareRentError("创建成功但没有返回实例 ID")
        warning = ""
        minutes = int(self.settings.get("gpushare_auto_stop_minutes") or self.settings.get("auto_stop_minutes") or 0)
        if minutes > 0:
            try:
                self.set_auto_stop(instance_id, minutes)
            except GpushareRentError as exc:
                warning = f"定时关机设置失败：{exc}"
        info = self.instance(instance_id)
        info["warning"] = warning
        return info

    def set_auto_stop(self, instance_id: str, minutes: int) -> None:
        ts = int((time.time() + minutes * 60) * 1000)
        self._put("/api/instance/set/schedule_stop",
                  {"instanceId": instance_id, "timeStamp": ts, "enable": True})

    def instances(self) -> list[dict[str, Any]]:
        data = self._get("/api/instance/list", {"pn": 1, "ps": 50}).get("data")
        if not isinstance(data, dict):
            raise GpushareRentError("恒源云实例响应格式异常")
        return [self._map(r) for r in (data.get("list") or []) if isinstance(r, dict)]

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

    def _find(self, instance_id: str) -> dict[str, Any] | None:
        """只在实例列表请求成功时返回 None；请求失败会抛异常，不能当作已释放。"""
        for item in self.instances():
            if item["uhost_id"] == instance_id:
                return item
        return None

    def terminate(self, instance_id: str) -> dict[str, Any]:
        try:
            info = self._find(instance_id)
        except GpushareRentError as exc:
            raise GpushareRentError(f"无法确认实例当前状态，释放未执行：{exc}") from exc
        if info is None or info.get("released") is True:
            return self._released(instance_id)
        state = str(info.get("state") or "")
        if state not in ("stop", "stopped", "shutdown"):
            self._put("/api/instance/manage", {"instanceId": instance_id, "skuName": "payg", "actionName": "stop"})
            deadline = time.time() + 180
            stopped = False
            while time.time() < deadline:
                time.sleep(4)
                try:
                    current = self._find(instance_id)
                except GpushareRentError:
                    continue
                if current is None or current.get("released") is True:
                    return self._released(instance_id)
                if str(current.get("state") or "") in ("stop", "stopped", "shutdown"):
                    stopped = True
                    break
            if not stopped:
                raise GpushareRentError("等待实例关机超时，未执行释放；请到恒源云控制台确认状态")
        self._put("/api/instance/manage", {"instanceId": instance_id, "skuName": "payg", "actionName": "release"})
        deadline = time.time() + 180
        while time.time() < deadline:
            time.sleep(4)
            try:
                current = self._find(instance_id)
            except GpushareRentError:
                continue
            if current is None or current.get("released") is True or str(current.get("state") or "") in ("released", "deleted"):
                return self._released(instance_id)
        raise GpushareRentError("释放请求已发送，但 180 秒内未确认实例消失；结果未确认，请到恒源云控制台核实")

    @staticmethod
    def _released(instance_id: str) -> dict[str, Any]:
        return {
            "platform": "gpushare", "uhost_id": instance_id, "state": "released", "released": True,
            "region": "", "zone": "", "zone_name": "", "gpu_type": "", "gpu": "",
            "cpu": None, "mem_gb": None, "price": None, "image_name": "", "name": instance_id,
            "ip": "", "ssh_command": "", "password": "", "auto_stop_at": None,
            "error": "", "warning": "", "ssh": {"command": "", "password": "", "ip": "", "user": "root"},
        }
