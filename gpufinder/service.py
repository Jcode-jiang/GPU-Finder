"""服务编排：并发刷新各平台、合并第三方参考价、磁盘缓存与历史。"""

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from pathlib import Path
from typing import Any

from .config import Config, state_path
from .errors import redact
from .http import HttpClient
from .models import Offer, ProviderResult, Snapshot
from .providers import DEFAULT_PROVIDERS, FetchContext, Provider

LAST_SNAPSHOT = "last_snapshot.json"
HISTORY = "history.jsonl"

# 平台抓取整体超时（秒），超过则标记该平台失败，不阻塞其它平台
PROVIDER_DEADLINE = 28.0


class GPUService:
    def __init__(self, config: Config | None = None, providers: list[Provider] | None = None) -> None:
        self.config = config or Config.load()
        self.providers = providers or DEFAULT_PROVIDERS
        self.http = HttpClient(
            timeout=self.config.request_timeout, retries=2
        )
        self._refresh_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._snapshot: dict[str, Any] | None = None
        self._snapshot_ts = 0.0
        self._refreshing = False
        self._load_disk()

    # ------------------------------------------------------------------ 状态
    @property
    def refreshing(self) -> bool:
        return self._refreshing

    def providers_info(self) -> list[dict[str, Any]]:
        out = []
        for p in self.providers:
            out.append(
                {
                    "id": p.id,
                    "name": p.name,
                    "homepage": p.homepage,
                    "accent": p.accent,
                    "description": p.description,
                    "auth_required": p.auth_required,
                    "credentials_configured": p.credentials_configured(self.config),
                    "credential_keys": list(p.credential_keys),
                    "disabled": p.id in self.config.disabled_providers,
                }
            )
        return out

    # ------------------------------------------------------------------ 读取
    @property
    def snapshot_age(self) -> float:
        with self._state_lock:
            ts = self._snapshot_ts
        return (time.time() - ts) if ts else float("inf")

    def get_snapshot(self) -> dict[str, Any] | None:
        with self._state_lock:
            return self._snapshot

    def _load_disk(self) -> None:
        path = state_path(LAST_SNAPSHOT)
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text("utf-8"))
            with self._state_lock:
                self._snapshot = data
                self._snapshot_ts = float(data.get("generated_ts") or 0)
        except (OSError, ValueError):
            pass

    # ------------------------------------------------------------------ 刷新
    def refresh(self) -> dict[str, Any]:
        """同步刷新全部平台，返回快照 dict。并发刷新会被串行化。"""
        with self._refresh_lock:
            started = time.perf_counter()
            self._refreshing = True
            try:
                snapshot = self._collect()
            finally:
                self._refreshing = False
            snapshot.duration_ms = int((time.perf_counter() - started) * 1000)
            data = snapshot.to_dict()
            with self._state_lock:
                self._snapshot = data
                self._snapshot_ts = time.time()
            self._save_disk(data)
            self._append_history(data)
            return data

    def refresh_async(self) -> None:
        if self.refreshing:
            return

        def _run() -> None:
            try:
                self.refresh()
            except Exception:  # noqa: BLE001 - 后台刷新失败不应崩溃
                pass

        threading.Thread(target=_run, name="gpufinder-refresh", daemon=True).start()

    def _collect(self) -> Snapshot:
        ctx = FetchContext(config=self.config, http=self.http, timeout=self.config.request_timeout)
        disabled = set(self.config.disabled_providers)
        active = [p for p in self.providers if p.id not in disabled]

        results: dict[str, ProviderResult] = {}
        pool = ThreadPoolExecutor(max_workers=max(1, len(active)), thread_name_prefix="provider")
        try:
            futures = {pool.submit(p.run, ctx): p for p in active}
            done, pending = wait(futures, timeout=PROVIDER_DEADLINE)
            for fut in done:
                prov = futures[fut]
                try:
                    results[prov.id] = fut.result()
                except Exception as exc:  # noqa: BLE001
                    results[prov.id] = ProviderResult(
                        provider_id=prov.id,
                        provider_name=prov.name,
                        ok=False,
                        mode="error",
                        message=redact(f"{type(exc).__name__}: {exc}"),
                        homepage=prov.homepage,
                        accent=prov.accent,
                    )
            for fut in pending:
                prov = futures[fut]
                results[prov.id] = ProviderResult(
                    provider_id=prov.id,
                    provider_name=prov.name,
                    ok=False,
                    mode="error",
                    message=f"抓取超时（>{int(PROVIDER_DEADLINE)}s）",
                    homepage=prov.homepage,
                    accent=prov.accent,
                )
        finally:
            # wait() 只负责等；ThreadPoolExecutor 的 with 退出会再次 join，
            # 从而把 28 秒 soft deadline 拖成无限等待。这里不等待未完成任务。
            for future in locals().get("pending", []):
                future.cancel()
            pool.shutdown(wait=False, cancel_futures=True)

        all_offers: list[Offer] = []
        for res in results.values():
            all_offers.extend(res.offers)

        all_offers.sort(
            key=lambda o: (
                o.family,
                o.price if o.price is not None else 1e9,
                o.platform,
                o.region,
            )
        )
        providers_sorted = [results[p.id] for p in active if p.id in results]
        return Snapshot(offers=all_offers, providers=providers_sorted)

    # ------------------------------------------------------------------ 持久化
    def _save_disk(self, data: dict[str, Any]) -> None:
        path = state_path(LAST_SNAPSHOT)
        try:
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False), "utf-8")
            tmp.replace(path)
        except OSError:
            pass

    def _append_history(self, data: dict[str, Any]) -> None:
        """记录每个 (平台, 卡型) 的最低价，便于以后画趋势。"""
        path = state_path(HISTORY)
        summary = (data.get("summary") or {}).get("by_family") or {}
        row = {
            "ts": data.get("generated_ts"),
            "at": data.get("generated_at"),
            "families": {
                fam: {
                    "min": info.get("min_price"),
                    "platform": info.get("cheapest_platform"),
                    "available": info.get("available"),
                }
                for fam, info in summary.items()
            },
        }
        try:
            if path.exists() and path.stat().st_size > 2_000_000:
                # 历史缓存只保留最近 1000 条，避免长期运行无限增长。
                lines = path.read_text("utf-8", errors="replace").splitlines()[-1000:]
                path.write_text("\n".join(lines) + ("\n" if lines else ""), "utf-8")
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        except OSError:
            pass

    # ------------------------------------------------------------------ 配置
    def update_config(self, **changes: Any) -> Config:
        for key in ("port", "refresh_interval", "open_on_start"):
            if key in changes and changes[key] is not None:
                setattr(self.config, key, type(getattr(self.config, key))(changes[key]))
        if "disabled_providers" in changes and changes["disabled_providers"] is not None:
            self.config.disabled_providers = [str(x) for x in changes["disabled_providers"]]
        self.config.save()
        return self.config


def parse_platform_arg(value: str | None) -> list[str] | None:
    if not value:
        return None
    parts = [p.strip() for p in value.replace("，", ",").split(",") if p.strip()]
    return parts or None


def filter_offers(
    offers: list[dict[str, Any]],
    *,
    platforms: list[str] | None = None,
    families: list[str] | None = None,
    only_available: bool = False,
) -> list[dict[str, Any]]:
    out = []
    for o in offers:
        if platforms and o.get("platform") not in platforms:
            continue
        if families and o.get("family") not in families:
            continue
        if only_available and not o.get("available"):
            continue
        out.append(o)
    return out


def snapshot_path() -> Path:
    return state_path(LAST_SNAPSHOT)
