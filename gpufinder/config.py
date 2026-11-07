"""配置与本地路径管理。

配置文件：``~/.config/gpufinder/config.json``（权限 0600，含可选凭据）
缓存目录：``~/Library/Caches/gpufinder``（macOS）
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

APP_NAME = "gpufinder"

CREDENTIAL_KEYS = (
    "autodl_token",         # AutoDL 登录后的 token（浏览器 localStorage.token）
    "gpushare_token",       # 恒源云登录后的 token（Cookie: gpu_share_token）
    "matpool_token",        # 矩池云 JWT（Authorization: Bearer <token>）
    "matpool_user_id",      # 矩池云用户 ID（X-Matpool-User-Id）
    "compshare_public_key",  # 优云智算官方 API AccessKey ID
    "compshare_private_key",  # 优云智算官方 API AccessKey Secret
)

ENV_KEYS = {
    "autodl_token": "GPUFINDER_AUTODL_TOKEN",
    "gpushare_token": "GPUFINDER_GPUSHARE_TOKEN",
    "matpool_token": "GPUFINDER_MATPOOL_TOKEN",
    "matpool_user_id": "GPUFINDER_MATPOOL_USER_ID",
    "compshare_public_key": "GPUFINDER_COMPSHARE_PUBLIC_KEY",
    "compshare_private_key": "GPUFINDER_COMPSHARE_PRIVATE_KEY",
}


def _xdg_config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")


def _home_override() -> Path | None:
    """``GPUFINDER_HOME`` 可把配置与缓存重定向到指定目录（测试/便携模式）。"""
    val = os.environ.get("GPUFINDER_HOME")
    return Path(val).expanduser() if val else None


def config_dir() -> Path:
    override = _home_override()
    d = (override / "config") if override else (_xdg_config_home() / APP_NAME)
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_path() -> Path:
    return config_dir() / "config.json"


def cache_dir() -> Path:
    override = _home_override()
    if override:
        d = override / "state"
    elif os.uname().sysname == "Darwin":  # type: ignore[attr-defined]
        d = Path.home() / "Library" / "Caches" / APP_NAME
    else:
        d = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass
class Config:
    port: int = 8765
    refresh_interval: int = 300          # 服务端自动刷新间隔（秒），0 = 关闭
    request_timeout: float = 20.0
    disabled_providers: list[str] = field(default_factory=list)
    credentials: dict[str, str] = field(default_factory=dict)
    rent: dict[str, Any] = field(default_factory=dict)
    overview_families: list[str] = field(default_factory=list)
    open_on_start: bool = False

    # ------------------------------------------------------------------ 读写
    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        path = path or config_path()
        raw: dict[str, Any] = {}
        if path.exists():
            try:
                raw = json.loads(path.read_text("utf-8"))
            except (OSError, ValueError):
                raw = {}
        cfg = cls()
        cfg.port = int(raw.get("port", cfg.port))
        cfg.refresh_interval = int(raw.get("refresh_interval", cfg.refresh_interval))
        cfg.request_timeout = float(raw.get("request_timeout", cfg.request_timeout))
        cfg.disabled_providers = list(raw.get("disabled_providers") or [])
        cfg.credentials = {k: str(v) for k, v in (raw.get("credentials") or {}).items() if v}
        cfg.rent = dict(raw.get("rent") or {})
        cfg.overview_families = [str(x) for x in (raw.get("overview_families") or [])][:3]
        cfg.open_on_start = bool(raw.get("open_on_start", False))
        cfg._apply_env()
        return cfg

    def _apply_env(self) -> None:
        for key, env in ENV_KEYS.items():
            val = os.environ.get(env)
            if val:
                self.credentials[key] = val
        if os.environ.get("GPUFINDER_PORT"):
            try:
                self.port = int(os.environ["GPUFINDER_PORT"])
            except ValueError:
                pass

    def save(self, path: Path | None = None) -> Path:
        path = path or config_path()
        payload = {
            "port": self.port,
            "refresh_interval": self.refresh_interval,
            "request_timeout": self.request_timeout,
            "disabled_providers": self.disabled_providers,
            "credentials": self.credentials,
            "rent": self.rent,
            "overview_families": self.overview_families,
            "open_on_start": self.open_on_start,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".config-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
                fh.write("\n")
            os.chmod(tmp, 0o600)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        return path

    # ------------------------------------------------------------------ 凭据
    def credential(self, key: str) -> str:
        return (self.credentials.get(key) or "").strip()

    def set_credential(self, key: str, value: str) -> None:
        if key not in CREDENTIAL_KEYS:
            raise KeyError(f"未知凭据: {key}")
        value = (value or "").strip()
        if value:
            self.credentials[key] = value
        else:
            self.credentials.pop(key, None)

    def masked_credentials(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key in CREDENTIAL_KEYS:
            val = self.credential(key)
            out[key] = {
                "configured": bool(val),
                "hint": (val[:4] + "…" + val[-4:]) if len(val) > 10 else ("已设置" if val else ""),
            }
        return out


def state_path(name: str) -> Path:
    return cache_dir() / name
