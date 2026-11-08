"""核心解析与 API 单元测试（完全离线，使用本地 fixture）。"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import urllib.error
import urllib.request
import urllib.request
from pathlib import Path

from gpufinder.gpu import normalize_gpu
from gpufinder.models import Offer, Snapshot
from gpufinder.providers import base
from gpufinder.providers.compshare import pick_single_gpu_config, sign_params
from gpufinder.providers.matpool import parse_host_market, parse_pools
from gpufinder.service import GPUService, filter_offers

FIXTURES = Path(__file__).parent / "fixtures"


class GpuNormalizeTest(unittest.TestCase):
    def test_variants(self) -> None:
        self.assertEqual(normalize_gpu("NVIDIA GeForce RTX 4090"), ("RTX 4090", "rtx4090", 24))
        self.assertEqual(normalize_gpu("RTX4090 24G"), ("RTX 4090", "rtx4090", 24))
        self.assertEqual(normalize_gpu("RTX 4090D"), ("RTX 4090D", "rtx4090d", 24))
        self.assertEqual(normalize_gpu("RTX4090-48G"), ("RTX 4090 48G", "rtx409048", 48))
        self.assertEqual(normalize_gpu("NVIDIA GeForce RTX 5090"), ("RTX 5090", "rtx5090", 32))
        self.assertEqual(normalize_gpu("RTX 5090D"), ("RTX 5090D", "rtx5090d", 32))
        self.assertEqual(normalize_gpu("RTX 3090"), ("RTX 3090", "rtx3090", 24))
        self.assertEqual(normalize_gpu("RTX 4060 Ti 16G"), ("RTX 4060 Ti 16G", "rtx4060ti", 16))
        self.assertEqual(normalize_gpu("A100 40GB"), ("A100 40GB", "a100", 40))
        self.assertEqual(normalize_gpu("A100-SXM4-80GB"), ("A100 80GB", "a100", 80))
        self.assertEqual(normalize_gpu("H100 SXM"), ("H100", "h100", 80))
        self.assertEqual(normalize_gpu("RTX PRO 6000"), ("RTX PRO 6000", "rtxpro6000", 96))
        self.assertIsNone(normalize_gpu("CMP 170HX"))
        self.assertIsNone(normalize_gpu(""))


class MatpoolParserTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        html = (FIXTURES / "matpool_host_market.html").read_text("utf-8")
        cls.offers = parse_pools(parse_host_market(html))

    def test_counts(self) -> None:
        self.assertEqual(len(self.offers), 15)
        self.assertTrue({"rtx4090", "rtx5090", "a100", "rtx3090"}.issubset({o.family for o in self.offers}))

    def test_price_and_stock(self) -> None:
        in_stock = [o for o in self.offers if o.family == "rtx4090" and o.available]
        self.assertEqual(len(in_stock), 1)
        self.assertAlmostEqual(in_stock[0].price or 0, 2.2)
        self.assertEqual(in_stock[0].stock, 1)

    def test_capacity_and_specs(self) -> None:
        total = sum(o.capacity or 0 for o in self.offers if o.family == "rtx4090")
        self.assertEqual(total, 32)
        self.assertTrue(any(o.specs.get("cpu_cores") for o in self.offers))


class CompshareAPITest(unittest.TestCase):
    def test_signature_matches_ucloud_docs(self) -> None:
        params = {
            "Action": "DescribeUHostInstance",
            "Limit": 10,
            "PublicKey": "ucloudsomeone@example.com1296235120854146120",
            "Region": "cn-bj2",
        }
        secret = "46f09bb9fab4f12dfc160dae12273d5332b5debe"
        self.assertEqual(sign_params(params, secret), "cba5cf5ec4d4233d206b1b54951e3787350a642f")

    def test_pick_single_gpu_config(self) -> None:
        item = {
            "MachineSizes": [
                {"Gpu": 8, "Collection": [{"Cpu": 124, "Memory": [940]}]},
                {"Gpu": 1, "Collection": [
                    {"Cpu": 16, "Memory": [96, 64]},
                    {"Cpu": 14, "Memory": [64, 48]},
                ]},
            ]
        }
        self.assertEqual(pick_single_gpu_config(item), (14, 48))
        self.assertIsNone(pick_single_gpu_config({"MachineSizes": [{"Gpu": 8, "Collection": []}]}))


class CatalogAndPresetTest(unittest.TestCase):
    def test_catalog_has_common_models(self) -> None:
        from gpufinder.gpu import catalog

        families = {m["family"] for m in catalog()}
        self.assertTrue({"rtx4090", "rtx5090", "rtx3090", "a100", "h100", "l40s", "a6000"} <= families)

    def test_preset_matching(self) -> None:
        from gpufinder.presets import matches_offer

        training = next(p for p in __import__("gpufinder.presets", fromlist=["PRESETS"]).PRESETS if p["id"] == "training")
        self.assertTrue(matches_offer({"family": "a100", "vram_gb": 80, "price": 1.0}, training))
        self.assertFalse(matches_offer({"family": "rtx4090", "vram_gb": 24, "price": 1.0}, training))
        budget = next(p for p in __import__("gpufinder.presets", fromlist=["PRESETS"]).PRESETS if p["id"] == "budget")
        self.assertTrue(matches_offer({"family": "rtx4090", "price": 2.9, "currency": "CNY"}, budget))
        self.assertFalse(matches_offer({"family": "rtx4090", "price": 3.1, "currency": "CNY"}, budget))
        # 预算预设有币种限制：美元报价不混进 ¥3 以下
        self.assertFalse(matches_offer({"family": "rtx4090", "price": 1.0, "currency": "USD"}, budget))


class CurrencyTest(unittest.TestCase):
    def test_usd_label_and_summary_prefers_cny(self) -> None:
        usd = Offer(platform="v", platform_name="V", gpu="H100", family="h100", region="US",
                    price=1.0, currency="USD", available=True)
        cny = Offer(platform="a", platform_name="A", gpu="H100", family="h100", region="CN",
                    price=9.0, currency="CNY", available=True)
        self.assertEqual(usd.price_label, "$1/时")
        summary = Snapshot(offers=[usd, cny]).summary()
        self.assertEqual(summary["by_family"]["h100"]["currency"], "CNY")
        self.assertAlmostEqual(summary["by_family"]["h100"]["min_price"], 9.0)


class SnapshotSummaryTest(unittest.TestCase):
    def test_summary(self) -> None:
        offers = [
            Offer(platform="a", platform_name="A", gpu="RTX 4090", family="rtx4090", region="x", price=2.0, available=True, stock=2),
            Offer(platform="b", platform_name="B", gpu="RTX 4090", family="rtx4090", region="y", price=1.5, available=False),
            Offer(platform="b", platform_name="B", gpu="RTX 5090", family="rtx5090", region="y", price=3.0, available=True),
        ]
        snap = Snapshot(offers=offers)
        summary = snap.summary()
        self.assertEqual(summary["offers"], 3)
        self.assertEqual(summary["available"], 2)
        # 最低价只在有货的报价里取（1.5 的 B 无货，不计入）
        self.assertAlmostEqual(summary["by_family"]["rtx4090"]["min_price"], 2.0)
        data = snap.to_dict()
        self.assertEqual(data["schema"], 1)
        self.assertEqual(len(data["offers"]), 3)
        self.assertEqual(data["offers"][0]["stock_label"], "有货 2 卡")

    def test_filter(self) -> None:
        offers = [
            {"platform": "a", "family": "rtx4090", "available": True},
            {"platform": "a", "family": "rtx5090", "available": False},
        ]
        self.assertEqual(len(filter_offers(offers, families=["rtx4090"])), 1)
        self.assertEqual(len(filter_offers(offers, only_available=True)), 1)


class FakeProvider(base.Provider):
    id = "fake"
    name = "Fake"

    def fetch(self, ctx: base.FetchContext):
        return [
            Offer(platform=self.id, platform_name=self.name, gpu="RTX 4090", family="rtx4090", region="r", price=1.0, available=True)
        ]


class ServiceTest(unittest.TestCase):
    def test_refresh_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["GPUFINDER_HOME"] = tmp
            try:
                svc = GPUService(providers=[FakeProvider()])
                snap = svc.refresh()
                self.assertEqual(snap["summary"]["offers"], 1)
                self.assertEqual(snap["platforms"][0]["mode"], "live")
            finally:
                os.environ.pop("GPUFINDER_HOME", None)


class HttpClientRetryTest(unittest.TestCase):
    def test_mutating_request_is_not_retried(self) -> None:
        from gpufinder.http import HttpClient, HttpError

        hits = {"n": 0}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                hits["n"] += 1
                self.send_response(500)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *args):  # noqa: D401
                return

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            client = HttpClient(timeout=3, retries=3)
            response = client.post_json(f"http://127.0.0.1:{httpd.server_address[1]}/pay", {})
            self.assertEqual(response.status, 500)
            self.assertEqual(hits["n"], 1)
        finally:
            httpd.shutdown()
            httpd.server_close()


class ConfigSecurityTest(unittest.TestCase):
    def test_env_credentials_are_not_persisted_or_prefixed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["GPUFINDER_HOME"] = tmp
            os.environ["GPUFINDER_AUTODL_TOKEN"] = "env-secret-token-value"
            try:
                from gpufinder.config import Config

                cfg = Config.load()
                self.assertEqual(cfg.credential("autodl_token"), "env-secret-token-value")
                path = cfg.save()
                saved = json.loads(path.read_text("utf-8"))
                self.assertNotIn("env-secret-token-value", json.dumps(saved))
                self.assertEqual(cfg.masked_credentials()["autodl_token"]["hint"], "已设置")
            finally:
                os.environ.pop("GPUFINDER_AUTODL_TOKEN", None)
                os.environ.pop("GPUFINDER_HOME", None)

    def test_rent_settings_reject_invalid_values(self) -> None:
        from gpufinder.config import Config
        from gpufinder.rent import RentService

        with tempfile.TemporaryDirectory() as tmp:
            os.environ["GPUFINDER_HOME"] = tmp
            try:
                svc = RentService(Config.load())
                with self.assertRaises(ValueError):
                    svc.update_settings({"max_hourly_price": float("nan")})
                with self.assertRaises(ValueError):
                    svc.update_settings({"enabled": "not-a-bool"})
                merged = svc.update_settings({"enabled": "false", "max_hourly_price": 3})
                self.assertFalse(merged["enabled"])
                self.assertEqual(merged["max_hourly_price"], 3.0)
            finally:
                os.environ.pop("GPUFINDER_HOME", None)


class ServerTest(unittest.TestCase):
    def test_create_is_idempotent_by_request_id(self) -> None:
        from gpufinder.server import Server

        class FakeRenter:
            def __init__(self) -> None:
                self.calls = 0

            def active_count(self) -> int:
                return 0

            def create(self, *args, **kwargs):
                self.calls += 1
                return {"platform": "autodl", "uhost_id": "new-instance", "state": "creating"}

        with tempfile.TemporaryDirectory() as tmp:
            os.environ["GPUFINDER_HOME"] = tmp
            try:
                svc = GPUService(providers=[FakeProvider()])
                svc.refresh()
                srv = Server(svc, 0)
                fake = FakeRenter()
                srv.autodl_rent = fake
                srv.start()
                try:
                    base_url = f"http://127.0.0.1:{srv.port}"
                    body = json.dumps({
                        "machine_id": "m1", "image_id": "i1", "confirm": "RENT",
                        "gpu_type": "RTX 4090", "region": "北京A区", "price": 1.5,
                        "request_id": "test-request-0001",
                    }).encode("utf-8")
                    headers = {"Content-Type": "application/json", "X-GPU-Finder-Token": srv.token}
                    for _ in range(2):
                        with urllib.request.urlopen(urllib.request.Request(
                            base_url + "/api/rent/autodl/create", data=body, method="POST", headers=headers,
                        ), timeout=5) as resp:
                            payload = json.loads(resp.read())
                        self.assertTrue(payload["ok"])
                    self.assertEqual(fake.calls, 1)
                finally:
                    srv.stop()
            finally:
                os.environ.pop("GPUFINDER_HOME", None)

    def test_api(self) -> None:
        from gpufinder.server import Server

        with tempfile.TemporaryDirectory() as tmp:
            os.environ["GPUFINDER_HOME"] = tmp
            try:
                svc = GPUService(providers=[FakeProvider()])
                svc.refresh()
                srv = Server(svc, 0)
                srv.start()
                try:
                    base_url = f"http://127.0.0.1:{srv.port}"
                    with urllib.request.urlopen(base_url + "/api/health", timeout=5) as resp:
                        health = json.loads(resp.read())
                    self.assertEqual(health["app"], "gpufinder")
                    with urllib.request.urlopen(base_url + "/api/snapshot", timeout=10) as resp:
                        snap = json.loads(resp.read())
                    self.assertEqual(snap["summary"]["offers"], 1)
                    with urllib.request.urlopen(base_url + "/api/catalog", timeout=5) as resp:
                        catalog = json.loads(resp.read())
                    self.assertTrue(catalog["groups"])
                    self.assertTrue(catalog["presets"])
                    with urllib.request.urlopen(base_url + "/", timeout=5) as resp:
                        html = resp.read().decode("utf-8")
                    self.assertIn("GPU Finder", html)
                    self.assertNotIn("__GPU_FINDER_TOKEN__", html)
                    self.assertIn(srv.token, html)

                    body = json.dumps({"overview_families": []}).encode("utf-8")
                    with self.assertRaises(urllib.error.HTTPError) as ctx:
                        urllib.request.urlopen(urllib.request.Request(
                            base_url + "/api/config", data=body, method="POST",
                            headers={"Content-Type": "application/json"},
                        ), timeout=5)
                    self.assertEqual(ctx.exception.code, 403)

                    with self.assertRaises(urllib.error.HTTPError) as ctx:
                        urllib.request.urlopen(base_url + "/api/config", timeout=5)
                    self.assertEqual(ctx.exception.code, 403)

                    with urllib.request.urlopen(urllib.request.Request(
                        base_url + "/api/config",
                        headers={"X-GPU-Finder-Token": srv.token},
                    ), timeout=5) as resp:
                        self.assertEqual(resp.status, 200)

                    with self.assertRaises(urllib.error.HTTPError) as ctx:
                        urllib.request.urlopen(urllib.request.Request(
                            base_url + "/api/config", data=body, method="POST",
                            headers={
                                "Content-Type": "application/json",
                                "X-GPU-Finder-Token": srv.token,
                                "Origin": "https://evil.example",
                            },
                        ), timeout=5)
                    self.assertEqual(ctx.exception.code, 403)

                    with self.assertRaises(urllib.error.HTTPError) as ctx:
                        urllib.request.urlopen(urllib.request.Request(
                            base_url + "/api/config", data=body, method="POST",
                            headers={"Content-Type": "text/plain", "X-GPU-Finder-Token": srv.token},
                        ), timeout=5)
                    self.assertEqual(ctx.exception.code, 415)

                    with urllib.request.urlopen(urllib.request.Request(
                        base_url + "/api/config", data=body, method="POST",
                        headers={"Content-Type": "application/json", "X-GPU-Finder-Token": srv.token},
                    ), timeout=5) as resp:
                        self.assertEqual(resp.status, 200)
                finally:
                    srv.stop()
            finally:
                os.environ.pop("GPUFINDER_HOME", None)


if __name__ == "__main__":
    unittest.main()


class AutodlParserTest(unittest.TestCase):
    def test_merge_and_price(self) -> None:
        from gpufinder.providers.autodl import merge_machines, normalize_item

        items = [
            {"gpu_name": "RTX 4090", "region_name": "西北B区", "gpu_idle_num": 3,
             "gpu_number": 8, "payg_price": 1980, "on_line": 1, "machine_tag_name": "通用型"},
            {"gpu_name": "RTX 4090", "region_name": "西北B区", "gpu_idle_num": 2,
             "gpu_number": 8, "payg_price": 1980, "on_line": 1, "machine_tag_name": "通用型"},
            {"gpu_name": "RTX 5090", "region_name": "北京A区", "gpu_idle_num": 5,
             "gpu_number": 8, "payg_price": 2930, "on_line": 4},
            {"gpu_name": "A100", "region_name": "北京A区", "gpu_idle_num": 2,
             "gpu_number": 8, "payg_price": 5000, "on_line": 1},
        ]
        self.assertEqual(normalize_item(items[0])["price"], 1.98)
        offers = {o.gpu: o for o in merge_machines(items)}
        self.assertEqual(set(offers), {"RTX 4090", "RTX 5090", "A100"})
        self.assertEqual(offers["RTX 4090"].stock, 5)
        self.assertAlmostEqual(offers["RTX 4090"].price or 0, 1.98)
        # 离线机器空闲数按 0 处理
        self.assertEqual(offers["RTX 5090"].stock, 0)
        self.assertFalse(offers["RTX 5090"].available)


class GpushareParserTest(unittest.TestCase):
    def test_parse(self) -> None:
        from gpufinder.providers.gpushare import parse_machines

        machines = [
            {"gpuNum": 8, "gpuUsed": 5, "isOnline": True, "status": 1,
             "baseInfo": {"gpuName": "NVIDIA GeForce RTX 5090"},
             "regionName": "重庆",
             "skuList": [
                 {"skuName": "包月", "price": 1.2, "enable": 1, "status": 1},
                 {"skuName": "按量计费", "price": 2.9, "enable": 1, "status": 1},
             ]},
            {"gpuNum": 4, "gpuUsed": 4, "isOnline": True, "status": 1,
             "baseInfo": {"gpuName": "RTX 4090"}, "regionName": "北京",
             "skuList": [{"skuName": "按量", "price": 2.2, "enable": 1, "status": 1}]},
        ]
        offers = {o.gpu: o for o in parse_machines(machines)}
        self.assertEqual(offers["RTX 5090"].price, 2.9)  # 优先按量，而不是包月单价
        self.assertEqual(offers["RTX 5090"].stock, 3)
        self.assertTrue(offers["RTX 5090"].available)
        self.assertFalse(offers["RTX 4090"].available)
