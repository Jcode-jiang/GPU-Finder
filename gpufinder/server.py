"""本地 Web 服务：JSON API + Dashboard 静态资源（仅标准库）。

只监听 127.0.0.1，默认端口 8765。启动后会打印一行 ``READY <url>``，
macOS App 通过这一行确认后端就绪。
"""

from __future__ import annotations

import json
import mimetypes
import os
import socket
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .config import Config, config_path
from .models import now_iso
from .rent import RentError, RentService
from .rent_autodl import AutoDLRentError, AutoDLRenter
from .rent_gpushare import GpushareRentError, GpushareRenter
from .rent_matpool import MatpoolRentError, MatpoolRenter
from .service import GPUService

VERSION = "1.0.0"
WEB_ROOT = Path(__file__).resolve().parent / "web"

_MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".json": "application/json; charset=utf-8",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
}


def free_port(preferred: int = 8765) -> int:
    """优先使用 preferred，被占用则让内核分配。"""
    for port in (preferred, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
            except OSError:
                continue
            return s.getsockname()[1]
    raise RuntimeError("无法分配端口")


class APIHandler(BaseHTTPRequestHandler):
    server_version = f"GPUFinder/{VERSION}"
    service: GPUService  # 由 Server 注入
    rent: RentService    # 由 Server 注入
    autodl_rent: AutoDLRenter
    gpushare_rent: GpushareRenter
    matpool_rent: MatpoolRenter

    # ------------------------------------------------------------------ 基础
    def log_message(self, fmt: str, *args: Any) -> None:
        if os.environ.get("GPUFINDER_VERBOSE"):
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send_json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _send_error_json(self, message: str, status: int = 400) -> None:
        self._send_json({"ok": False, "error": message}, status=status)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        if length > 1_000_000:
            raise ValueError("请求体过大")
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValueError(f"JSON 解析失败: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("请求体必须是 JSON 对象")
        return data

    def _static(self, path: str) -> None:
        rel = path.lstrip("/") or "index.html"
        if rel in {"", "/"}:
            rel = "index.html"
        target = (WEB_ROOT / rel).resolve()
        if not str(target).startswith(str(WEB_ROOT.resolve())) or not target.is_file():
            self._send_json({"ok": False, "error": "not found"}, status=404)
            return
        data = target.read_bytes()
        ctype = _MIME.get(target.suffix.lower()) or mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    # ------------------------------------------------------------------ 路由
    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path == "/api/health":
            snap = self.service.get_snapshot()
            self._send_json(
                {
                    "ok": True,
                    "app": "gpufinder",
                    "version": VERSION,
                    "refreshing": self.service.refreshing,
                    "age_seconds": None if self.service.snapshot_age == float("inf") else int(self.service.snapshot_age),
                    "generated_at": (snap or {}).get("generated_at"),
                    "time": now_iso(),
                }
            )
            return

        if path == "/api/snapshot":
            snap = self.service.get_snapshot()
            if snap is None:
                snap = self.service.refresh()
            elif query.get("refresh", ["0"])[0] in {"1", "true"}:
                snap = self.service.refresh()
            self._send_json(snap)
            return

        if path == "/api/providers":
            self._send_json({"ok": True, "providers": self.service.providers_info()})
            return

        if path == "/api/config":
            cfg = self.service.config
            self._send_json(
                {
                    "ok": True,
                    "port": cfg.port,
                    "refresh_interval": cfg.refresh_interval,
                    "open_on_start": cfg.open_on_start,
                    "credentials": cfg.masked_credentials(),
                    "rent": self.rent.rent,
                    "config_path": str(config_path()),
                }
            )
            return

        if path == "/api/rent/options":
            region = query.get("region", ["cn-wlcb"])[0]
            zone = query.get("zone", ["cn-wlcb-01"])[0]
            try:
                api = self.rent._api()
                zones = [
                    {"region": r, "zone": z, "name": name}
                    for r, z, name in api.zones()
                ]
                images = []
                for image_type in ("App", "System"):
                    for item in api.images(region, zone, image_type):
                        if item.get("Status") != "Available":
                            continue
                        images.append(
                            {
                                "id": item.get("CompShareImageId"),
                                "name": item.get("Name"),
                                "type": image_type,
                            }
                        )
                balance = 0.0
                try:
                    info = api.call("GetBalance").get("AccountInfo") or {}
                    balance = float(info.get("AmountAvailable") or 0)
                except Exception:  # noqa: BLE001
                    pass
            except (RentError, Exception) as exc:  # noqa: BLE001
                self._send_error_json(f"读取租卡选项失败：{exc}", status=400)
                return
            self._send_json(
                {
                    "ok": True,
                    "settings": self.rent.rent,
                    "zones": zones,
                    "images": images,
                    "balance": balance,
                }
            )
            return

        if path == "/api/rent/matpool/instances":
            try:
                instances = self.matpool_rent.instances()
            except MatpoolRentError as exc:
                self._send_error_json(str(exc), status=400)
                return
            self._send_json({"ok": True, "instances": instances})
            return

        if path == "/api/rent/gpushare/instances":
            try:
                instances = self.gpushare_rent.instances()
            except GpushareRentError as exc:
                self._send_error_json(str(exc), status=400)
                return
            self._send_json({"ok": True, "instances": instances})
            return

        if path == "/api/rent/autodl/instances":
            try:
                instances = self.autodl_rent.instances()
            except AutoDLRentError as exc:
                self._send_error_json(str(exc), status=400)
                return
            self._send_json({"ok": True, "instances": instances})
            return

        if path == "/api/rent/instances":
            try:
                instances = self.rent.list_instances(refresh=True)
            except RentError as exc:
                self._send_error_json(str(exc), status=400)
                return
            self._send_json({"ok": True, "instances": instances, "settings": self.rent.rent})
            return

        if path == "/api/export":
            fmt = (query.get("format", ["json"])[0] or "json").lower()
            snap = self.service.get_snapshot() or self.service.refresh()
            if fmt == "csv":
                body = _to_csv(snap).encode("utf-8-sig")
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", 'attachment; filename="gpufinder.csv"')
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self._send_json(snap)
            return

        if path.startswith("/api/"):
            self._send_error_json("not found", status=404)
            return

        self._static(path)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        try:
            body = self._read_json()
        except ValueError as exc:
            self._send_error_json(str(exc), status=400)
            return

        if path == "/api/refresh":
            self._send_json(self.service.refresh())
            return

        if path == "/api/refresh/async":
            self.service.refresh_async()
            self._send_json({"ok": True, "refreshing": True}, status=202)
            return

        if path == "/api/config":
            cfg = self.service.config
            if "credentials" in body and isinstance(body["credentials"], dict):
                for key, value in body["credentials"].items():
                    try:
                        cfg.set_credential(str(key), str(value or ""))
                    except KeyError:
                        self._send_error_json(f"未知凭据: {key}", status=400)
                        return
            for key in ("port", "refresh_interval", "open_on_start"):
                if key in body:
                    setattr(cfg, key, type(getattr(cfg, key))(body[key]))
            if isinstance(body.get("rent"), dict):
                self.rent.update_settings(body["rent"])
            cfg.save()
            self._send_json(
                {"ok": True, "credentials": cfg.masked_credentials(), "rent": self.rent.rent}
            )
            return

        if path == "/api/rent/matpool/quote":
            try:
                quote = self.matpool_rent.quote(
                    str(body.get("gpu_type") or ""),
                    str(body.get("region") or ""),
                    body.get("price"),
                )
            except (MatpoolRentError, ValueError) as exc:
                self._send_error_json(str(exc), status=400)
                return
            self._send_json({"ok": True, "quote": quote})
            return

        if path == "/api/rent/matpool/create":
            try:
                record = self.matpool_rent.create(
                    str(body.get("machine_id") or ""),
                    str(body.get("image_id") or ""),
                    str(body.get("name") or ""),
                    str(body.get("confirm") or ""),
                )
            except MatpoolRentError as exc:
                self._send_error_json(str(exc), status=400)
                return
            self._send_json({"ok": True, "instance": record})
            return

        if path == "/api/rent/matpool/terminate":
            try:
                record = self.matpool_rent.terminate(str(body.get("uhost_id") or ""))
            except MatpoolRentError as exc:
                self._send_error_json(str(exc), status=400)
                return
            self._send_json({"ok": True, "instance": record})
            return

        if path == "/api/rent/gpushare/quote":
            try:
                quote = self.gpushare_rent.quote(
                    str(body.get("gpu_type") or ""),
                    str(body.get("region") or ""),
                    body.get("price"),
                )
            except (GpushareRentError, ValueError) as exc:
                self._send_error_json(str(exc), status=400)
                return
            self._send_json({"ok": True, "quote": quote})
            return

        if path == "/api/rent/gpushare/create":
            try:
                record = self.gpushare_rent.create(
                    str(body.get("machine_id") or ""),
                    str(body.get("image_id") or ""),
                    str(body.get("name") or ""),
                    str(body.get("confirm") or ""),
                )
            except GpushareRentError as exc:
                self._send_error_json(str(exc), status=400)
                return
            self._send_json({"ok": True, "instance": record})
            return

        if path == "/api/rent/gpushare/terminate":
            try:
                record = self.gpushare_rent.terminate(str(body.get("uhost_id") or ""))
            except GpushareRentError as exc:
                self._send_error_json(str(exc), status=400)
                return
            self._send_json({"ok": True, "instance": record})
            return

        if path == "/api/rent/autodl/quote":
            try:
                quote = self.autodl_rent.quote(
                    str(body.get("gpu_type") or ""),
                    str(body.get("region") or ""),
                    body.get("price"),
                )
            except (AutoDLRentError, ValueError) as exc:
                self._send_error_json(str(exc), status=400)
                return
            self._send_json({"ok": True, "quote": quote})
            return

        if path == "/api/rent/autodl/create":
            try:
                record = self.autodl_rent.create(
                    str(body.get("machine_id") or ""),
                    str(body.get("image_id") or ""),
                    str(body.get("name") or ""),
                    str(body.get("confirm") or ""),
                    gpu_type=str(body.get("gpu_type") or ""),
                    region=str(body.get("region") or ""),
                    price=body.get("price"),
                )
            except AutoDLRentError as exc:
                self._send_error_json(str(exc), status=400)
                return
            self._send_json({"ok": True, "instance": record})
            return

        if path == "/api/rent/autodl/terminate":
            try:
                record = self.autodl_rent.terminate(str(body.get("uhost_id") or ""))
            except AutoDLRentError as exc:
                self._send_error_json(str(exc), status=400)
                return
            self._send_json({"ok": True, "instance": record})
            return

        if path == "/api/rent/quote":
            try:
                quote = self.rent.quote(
                    str(body.get("gpu_type") or ""),
                    str(body.get("region") or ""),
                    str(body.get("zone") or ""),
                    int(body.get("cpu") or 0),
                    int(body.get("mem_gb") or 0),
                )
            except (RentError, ValueError) as exc:
                self._send_error_json(str(exc), status=400)
                return
            except Exception as exc:  # noqa: BLE001
                self._send_error_json(f"报价失败：{exc}", status=400)
                return
            self._send_json({"ok": True, "quote": quote})
            return

        if path == "/api/rent/create":
            try:
                record = self.rent.create(
                    gpu_type=str(body.get("gpu_type") or ""),
                    region=str(body.get("region") or ""),
                    zone=str(body.get("zone") or ""),
                    cpu=int(body.get("cpu") or 0),
                    mem_gb=int(body.get("mem_gb") or 0),
                    image_id=str(body.get("image_id") or ""),
                    name=str(body.get("name") or ""),
                    confirm=str(body.get("confirm") or ""),
                )
            except RentError as exc:
                self._send_error_json(str(exc), status=400)
                return
            except Exception as exc:  # noqa: BLE001
                self._send_error_json(f"创建失败：{exc}", status=400)
                return
            self._send_json({"ok": True, "instance": record})
            return

        if path == "/api/rent/refresh":
            try:
                info = self.rent.refresh_one(str(body.get("uhost_id") or ""))
            except RentError as exc:
                self._send_error_json(str(exc), status=400)
                return
            self._send_json({"ok": True, "instance": info})
            return

        if path == "/api/rent/stop":
            try:
                info = self.rent.stop(str(body.get("uhost_id") or ""))
            except RentError as exc:
                self._send_error_json(str(exc), status=400)
                return
            self._send_json({"ok": True, "instance": info})
            return

        if path == "/api/rent/terminate":
            try:
                info = self.rent.terminate(str(body.get("uhost_id") or ""))
            except RentError as exc:
                self._send_error_json(str(exc), status=400)
                return
            except Exception as exc:  # noqa: BLE001
                self._send_error_json(f"释放失败：{exc}", status=400)
                return
            self._send_json({"ok": True, "instance": info})
            return

        if path == "/api/login/autodl":
            phone = str(body.get("phone") or "").strip()
            password = str(body.get("password") or "")
            if not phone or not password:
                self._send_error_json("需要手机号与密码", status=400)
                return
            try:
                from .providers.autodl import AutodlProvider

                token = AutodlProvider.login(phone, password, timeout=self.service.config.request_timeout)
            except Exception as exc:  # noqa: BLE001
                self._send_error_json(str(exc), status=400)
                return
            self.service.config.set_credential("autodl_token", token)
            self.service.config.save()
            self._send_json({"ok": True, "message": "AutoDL token 已保存"})
            return

        self._send_error_json("not found", status=404)


def _to_csv(snap: dict[str, Any]) -> str:
    import csv
    import io

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["平台", "显卡", "显存GB", "地区", "价格(元/卡/小时)", "有货", "可租卡数", "总卡数", "来源", "更新时间", "链接"])
    for o in snap.get("offers") or []:
        writer.writerow(
            [
                o.get("platform_name", ""),
                o.get("gpu", ""),
                o.get("vram_gb", ""),
                o.get("region", ""),
                o.get("price", ""),
                {"true": "有货", "false": "无货"}.get(str(o.get("available")).lower(), "未知"),
                o.get("stock", ""),
                o.get("capacity", ""),
                o.get("source_label") or o.get("source", ""),
                o.get("fetched_at", ""),
                o.get("url", ""),
            ]
        )
    return buf.getvalue()


class Server:
    def __init__(self, service: GPUService, port: int | None = None) -> None:
        self.service = service
        self.rent = RentService(service.config, http=service.http)
        self.autodl_rent = AutoDLRenter(service.config, http=service.http)
        self.gpushare_rent = GpushareRenter(service.config, http=service.http)
        self.matpool_rent = MatpoolRenter(service.config, http=service.http)
        self.port = port if port is not None else service.config.port
        self._httpd: ThreadingHTTPServer | None = None
        self._scheduler: threading.Thread | None = None
        self._stop = threading.Event()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> None:
        handler = type(
            "BoundAPIHandler",
            (APIHandler,),
            {"service": self.service, "rent": self.rent, "autodl_rent": self.autodl_rent,
             "gpushare_rent": self.gpushare_rent, "matpool_rent": self.matpool_rent},
        )
        self._httpd = ThreadingHTTPServer(("127.0.0.1", self.port), handler)
        self._httpd.daemon_threads = True
        self.port = self._httpd.server_address[1]
        threading.Thread(target=self._httpd.serve_forever, name="gpufinder-http", daemon=True).start()
        self._start_scheduler()

    def _start_scheduler(self) -> None:
        interval = int(self.service.config.refresh_interval or 0)
        if interval <= 0:
            return

        def loop() -> None:
            while not self._stop.wait(15):
                if self.service.refreshing:
                    continue
                if self.service.snapshot_age >= interval:
                    self.service.refresh_async()

        self._scheduler = threading.Thread(target=loop, name="gpufinder-scheduler", daemon=True)
        self._scheduler.start()

    def serve_forever(self) -> None:
        assert self._httpd is not None
        try:
            while not self._stop.is_set():
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def stop(self) -> None:
        self._stop.set()
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()


def _watch_parent(pid: int) -> None:
    """父进程（菜单栏 App）退出后自动结束，避免留下孤儿进程。"""
    def loop() -> None:
        while True:
            time.sleep(5)
            try:
                os.kill(pid, 0)
            except OSError:
                os._exit(0)

    threading.Thread(target=loop, name="gpufinder-parent-watch", daemon=True).start()


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="gpufinder serve", description="启动本地 Dashboard 与 JSON API")
    parser.add_argument("--port", type=int, default=None, help="端口（默认 8765；被占用时自动换端口）")
    parser.add_argument("--open", action="store_true", help="启动后打开浏览器")
    parser.add_argument("--refresh", action="store_true", help="启动时立即刷新一次")
    parser.add_argument("--no-scheduler", action="store_true", help="关闭后台定时刷新")
    parser.add_argument("--parent-pid", type=int, default=0, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    config = Config.load()
    if args.no_scheduler:
        config.refresh_interval = 0
    service = GPUService(config)

    if args.refresh or service.get_snapshot() is None:
        service.refresh_async()

    port = args.port if args.port is not None else config.port
    srv = Server(service, port)
    try:
        srv.start()
    except OSError:
        srv = Server(service, 0)
        srv.start()

    if args.parent_pid:
        _watch_parent(args.parent_pid)

    print(f"GPU Finder 后端已启动: {srv.url}", flush=True)
    print(f"READY {srv.url}", flush=True)
    print("按 Ctrl+C 停止", flush=True)

    if args.open or config.open_on_start:
        import webbrowser

        webbrowser.open(srv.url)

    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n正在停止…", flush=True)
    finally:
        srv.stop()
    return 0
