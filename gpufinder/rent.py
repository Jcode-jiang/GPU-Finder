"""一键租卡（优云智算）。

流程与安全边界：
1. 报价：官方容量检查 + 价格，不产生费用；
2. 创建：必须 enabled、价格不超过上限、容量充足，且由用户显式确认；
3. 创建后轮询 Describe 接口，Running 后从官方返回中解出 SSH 命令与密码；
4. 默认设置定时关机；释放时先关机再删除实例。
"""

from __future__ import annotations

import base64
import json
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from .config import Config, state_path
from .http import HttpClient
from .providers.base import AuthRequired, FetchContext, ProviderError
from .providers.compshare import CompshareAPI

RENT_DEFAULTS: dict[str, Any] = {
    "enabled": False,
    "image_id": "",
    "disk_gb": 100,
    "auto_stop_minutes": 60,
    "max_hourly_price": 5.0,
    "name_prefix": "gpufinder",
}

INSTANCE_FILE = "instances.json"


class RentError(Exception):
    pass


@dataclass
class InstanceRecord:
    uhost_id: str
    region: str
    zone: str
    zone_name: str
    gpu_type: str
    gpu: str
    cpu: int
    mem_gb: int
    price: float | None
    image_id: str
    image_name: str
    name: str
    created_at: str
    auto_stop_at: int | None = None
    released: bool = False
    state: str = "Starting"
    ip: str = ""
    ssh_command: str = ""
    password: str = ""
    error: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RentService:
    def __init__(self, config: Config, http: HttpClient | None = None) -> None:
        self.config = config
        self.http = http or HttpClient(timeout=25, retries=1)
        self._lock = threading.Lock()
        self._records: list[InstanceRecord] = []
        self._load()

    # ------------------------------------------------------------------ 配置
    @property
    def rent(self) -> dict[str, Any]:
        current = dict(RENT_DEFAULTS)
        current.update(self.config.rent or {})
        return current

    def update_settings(self, values: dict[str, Any]) -> dict[str, Any]:
        merged = self.rent
        for key, value in values.items():
            if key not in RENT_DEFAULTS:
                continue
            if key in {"enabled"}:
                merged[key] = bool(value)
            elif key in {"disk_gb", "auto_stop_minutes"}:
                merged[key] = int(value)
            elif key == "max_hourly_price":
                merged[key] = float(value)
            else:
                merged[key] = str(value)
        self.config.rent = merged
        self.config.save()
        return merged

    # ------------------------------------------------------------------ 基础
    def _api(self) -> CompshareAPI:
        public_key = self.config.credential("compshare_public_key")
        private_key = self.config.credential("compshare_private_key")
        if not public_key or not private_key:
            raise RentError("请先在设置中填写优云智算 AccessKey ID / Secret")
        ctx = FetchContext(
            config=self.config,
            http=self.http,
            timeout=self.config.request_timeout,
        )
        return CompshareAPI(ctx, public_key, private_key)

    def _image(self, api: CompshareAPI, region: str, zone: str, image_id: str = "") -> tuple[str, str]:
        """返回 (image_id, image_name)，优先用户设置，其次 PyTorch 24.04，最后 Ubuntu。"""
        settings_image = (image_id or self.rent.get("image_id") or "").strip()
        images: list[dict[str, Any]] = []
        for image_type in ("App", "System"):
            try:
                images.extend(api.images(region, zone, image_type))
            except (ProviderError, AuthRequired):
                continue
        by_id = {str(i.get("CompShareImageId")): i for i in images if i.get("Status") == "Available"}
        if settings_image and settings_image in by_id:
            return settings_image, str(by_id[settings_image].get("Name") or "")
        # 默认 PyTorch：优先 24.04，其次可用的 torch 镜像
        preferred = ["PyTorch:24.04-py3", "cuda128_torch280_py312", "pytorch_2.5.0_Py3.12"]
        for wanted in preferred:
            for name, item in by_id.items():
                if str(item.get("Name") or "") == wanted:
                    return name, wanted
        for name, item in by_id.items():
            label = str(item.get("Name") or "")
            if "torch" in label.lower():
                return name, label
        fallback = api.default_image(region, zone)
        if fallback and fallback in by_id:
            return fallback, str(by_id[fallback].get("Name") or "")
        if fallback:
            return fallback, "Ubuntu"
        raise RentError("找不到可用镜像，请刷新或手动选择镜像")

    # ------------------------------------------------------------------ 报价
    def quote(self, gpu_type: str, region: str, zone: str, cpu: int, mem_gb: int) -> dict[str, Any]:
        api = self._api()
        image_id, image_name = self._image(api, region, zone)
        disk_gb = int(self.rent.get("disk_gb") or 100)
        capacity = api.capacity(region, zone, gpu_type, image_id, cpu, mem_gb, disk_gb=disk_gb)
        prices = api.price(region, zone, gpu_type, cpu, mem_gb * 1024)
        settings = self.rent
        postpay = prices.get("Postpay")
        zone_name = zone
        try:
            for r, z, desc in api.zones():
                if z == zone:
                    zone_name = desc
                    break
        except (ProviderError, AuthRequired):
            pass
        return {
            "platform": "compshare",
            "gpu_type": gpu_type,
            "region": region,
            "zone": zone,
            "zone_name": zone_name,
            "cpu": cpu,
            "mem_gb": mem_gb,
            "image_id": image_id,
            "image_name": image_name,
            "disk_gb": disk_gb,
            "price": postpay,
            "spot": prices.get("Spot"),
            "capacity": capacity,
            "auto_stop_minutes": int(settings.get("auto_stop_minutes") or 60),
            "max_hourly_price": float(settings.get("max_hourly_price") or 5),
            "enabled": bool(settings.get("enabled")),
        }

    # ------------------------------------------------------------------ 创建
    def create(
        self,
        *,
        gpu_type: str,
        region: str,
        zone: str,
        cpu: int,
        mem_gb: int,
        image_id: str = "",
        name: str = "",
        confirm: str = "",
    ) -> dict[str, Any]:
        if confirm != "RENT":
            raise RentError("需要二次确认（confirm=RENT）才能创建实例")
        settings = self.rent
        if not settings.get("enabled"):
            raise RentError("租卡功能未启用，请先在设置中打开并保存")
        api = self._api()
        quote = self.quote(gpu_type, region, zone, cpu, mem_gb)
        if quote["capacity"] is False:
            raise RentError("当前规格库存不足，请换区域或刷新后再试")
        price = quote["price"]
        if price is None:
            raise RentError("无法获取该规格价格，已取消创建")
        if price > float(settings.get("max_hourly_price") or 5):
            raise RentError(f"价格 ¥{price:.2f}/时 超过设置上限 ¥{float(settings['max_hourly_price']):.2f}/时")

        image = image_id or quote["image_id"]
        disk_gb = int(settings.get("disk_gb") or 100)
        instance_name = (name or f"{settings.get('name_prefix') or 'gpufinder'}-{int(time.time())}")[:63]

        params = {
            "Region": region,
            "Zone": zone,
            "MachineType": "G",
            "GpuType": gpu_type,
            "Gpu": 1,
            "Cpu": cpu,
            "Memory": mem_gb * 1024,
            "ChargeType": "Postpay",
            "CompShareImageId": image,
            "Name": instance_name,
            "Disks": [{"IsBoot": True, "Type": "CLOUD_SSD", "Size": disk_gb}],
        }
        try:
            resp = api.call("CreateCompShareInstance", params)
        except AuthRequired as exc:
            raise RentError(str(exc)) from exc
        except ProviderError as exc:
            raise RentError(f"创建失败：{exc}") from exc
        ids = resp.get("UHostIds") or []
        if not ids:
            raise RentError(f"创建接口未返回实例 ID：{resp}")
        uhost_id = str(ids[0])

        auto_stop_at = None
        warning = ""
        minutes = int(settings.get("auto_stop_minutes") or 0)
        if minutes > 0:
            auto_stop_at = int(time.time()) + minutes * 60
            try:
                project_id = self._project_id(api)
                api.call(
                    "UpdateCompShareStopScheduler",
                    {
                        "Region": region,
                        "Zone": zone,
                        "ProjectId": project_id,
                        "UHostId": uhost_id,
                        "SchedulerStopTime": auto_stop_at,
                    },
                )
            except (ProviderError, AuthRequired, RentError) as exc:
                warning = f"定时关机设置失败：{exc}"
                auto_stop_at = None

        record = InstanceRecord(
            uhost_id=uhost_id,
            region=region,
            zone=zone,
            zone_name=str(quote.get("zone_name") or zone),
            gpu_type=gpu_type,
            gpu=quote.get("gpu_type") or gpu_type,
            cpu=cpu,
            mem_gb=mem_gb,
            price=price,
            image_id=image,
            image_name=quote.get("image_name") or "",
            name=instance_name,
            created_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            auto_stop_at=auto_stop_at,
        )
        with self._lock:
            self._records.append(record)
            self._save()
        result = record.to_dict()
        result["warning"] = warning
        return result

    def _project_id(self, api: CompshareAPI) -> str:
        data = api.call("GetProjectList")
        for item in data.get("ProjectSet") or []:
            if item.get("IsDefault") and item.get("ProjectId"):
                return str(item["ProjectId"])
        for item in data.get("ProjectSet") or []:
            if item.get("ProjectId"):
                return str(item["ProjectId"])
        raise RentError("无法获取 ProjectId")

    # ------------------------------------------------------------------ 查询
    def _describe(self, api: CompshareAPI, ids: list[str]) -> list[dict[str, Any]]:
        if not ids:
            return []
        data = api.call("DescribeCompShareInstance", {"UHostIds": ids, "Limit": min(100, len(ids))})
        return [r for r in (data.get("UHostSet") or []) if isinstance(r, dict)]

    def _apply(self, record: InstanceRecord, info: dict[str, Any]) -> None:
        record.state = str(info.get("State") or record.state)
        record.ip = _public_ip(info)
        record.ssh_command = str(info.get("SshLoginCommand") or "")
        password = str(info.get("Password") or "")
        if password:
            try:
                record.password = base64.b64decode(password).decode("utf-8", "replace")
            except Exception:  # noqa: BLE001
                record.password = password
        if record.state == "Running" and record.ip and not record.ssh_command:
            record.ssh_command = f"ssh root@{record.ip}"
        meta = record.meta or {}
        meta["instance_price"] = info.get("InstancePrice")
        meta["disk_price"] = info.get("DiskPrice")
        meta["image_name"] = info.get("CompShareImageName") or record.image_name
        meta["scheduler_stop_time"] = info.get("SchedulerStopTime")
        meta["release_time"] = info.get("ReleaseTime")
        record.meta = meta

    def list_instances(self, refresh: bool = True) -> list[dict[str, Any]]:
        with self._lock:
            records = list(self._records)
        active = [r for r in records if not r.released]
        if refresh and active:
            try:
                api = self._api()
                infos = self._describe(api, [r.uhost_id for r in active])
                by_id = {str(i.get("UHostId")): i for i in infos}
                for record in active:
                    info = by_id.get(record.uhost_id)
                    if info:
                        self._apply(record, info)
                with self._lock:
                    self._save()
            except (ProviderError, AuthRequired, RentError):
                pass
        return [self._public(r) for r in records]

    def refresh_one(self, uhost_id: str) -> dict[str, Any]:
        with self._lock:
            record = next((r for r in self._records if r.uhost_id == uhost_id), None)
        if not record:
            raise RentError("实例不存在")
        api = self._api()
        infos = self._describe(api, [uhost_id])
        if infos:
            self._apply(record, infos[0])
            with self._lock:
                self._save()
        return self._public(record)

    def _public(self, record: InstanceRecord) -> dict[str, Any]:
        data = record.to_dict()
        data["hourly_price"] = record.price
        data["ssh"] = {
            "command": record.ssh_command,
            "password": record.password,
            "ip": record.ip,
            "user": "root",
        }
        return data

    # ------------------------------------------------------------------ 释放
    def stop(self, uhost_id: str) -> dict[str, Any]:
        with self._lock:
            record = next((r for r in self._records if r.uhost_id == uhost_id), None)
        if not record:
            raise RentError("实例不存在")
        api = self._api()
        try:
            api.call(
                "StopCompShareInstance",
                {"Region": record.region, "Zone": record.zone, "UHostId": uhost_id},
            )
        except (ProviderError, AuthRequired) as exc:
            raise RentError(f"关机失败：{exc}") from exc
        record.state = "Stopping"
        with self._lock:
            self._save()
        return self._public(record)

    def terminate(self, uhost_id: str, wait_stopped: bool = True) -> dict[str, Any]:
        with self._lock:
            record = next((r for r in self._records if r.uhost_id == uhost_id), None)
        if not record:
            raise RentError("实例不存在")
        api = self._api()
        deadline = time.time() + 180
        while True:
            try:
                infos = self._describe(api, [uhost_id])
            except (ProviderError, AuthRequired):
                infos = []
            info = infos[0] if infos else {}
            state = str(info.get("State") or record.state)
            if state == "Stopped" or not wait_stopped:
                break
            if time.time() > deadline:
                raise RentError("等待实例关机超时，请到控制台确认后释放")
            try:
                api.call(
                    "StopCompShareInstance",
                    {"Region": record.region, "Zone": record.zone, "UHostId": uhost_id},
                )
            except (ProviderError, AuthRequired):
                pass
            time.sleep(5)
        try:
            api.call(
                "TerminateCompShareInstance",
                {"Region": record.region, "Zone": record.zone, "UHostId": uhost_id, "ReleaseUDisk": True},
            )
        except (ProviderError, AuthRequired) as exc:
            raise RentError(f"释放失败：{exc}") from exc
        record.released = True
        record.state = "Terminated"
        with self._lock:
            self._save()
        return self._public(record)

    # ------------------------------------------------------------------ 持久化
    def _load(self) -> None:
        path = state_path(INSTANCE_FILE)
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text("utf-8"))
            for item in data.get("instances") or []:
                self._records.append(InstanceRecord(**item))
        except (OSError, ValueError, TypeError):
            self._records = []

    def _save(self) -> None:
        path = state_path(INSTANCE_FILE)
        try:
            # 密码可通过 Describe 接口重新获取，不在本地落盘
            payload = {
                "instances": [
                    {**r.to_dict(), "password": ""} for r in self._records
                ]
            }
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
            try:
                os.chmod(tmp, 0o600)
            except OSError:
                pass
            tmp.replace(path)
        except OSError:
            pass


def _public_ip(info: dict[str, Any]) -> str:
    for item in info.get("IPSet") or []:
        if isinstance(item, dict):
            ip = item.get("IP") or item.get("Ip") or ""
            if ip:
                return str(ip)
    return ""
