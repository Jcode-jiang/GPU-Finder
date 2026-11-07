"""命令行入口：list / refresh / serve / providers / doctor / config / login / export。"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import unicodedata
from pathlib import Path
from typing import Any

from .config import Config, config_path, CREDENTIAL_KEYS
from .service import GPUService, filter_offers

VERSION = "2.0.1"

# ---------------------------------------------------------------------- 终端样式
class Style:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def _wrap(self, code: str, text: str) -> str:
        return f"\x1b[{code}m{text}\x1b[0m" if self.enabled else text

    def bold(self, t: str) -> str:
        return self._wrap("1", t)

    def dim(self, t: str) -> str:
        return self._wrap("2", t)

    def green(self, t: str) -> str:
        return self._wrap("32", t)

    def red(self, t: str) -> str:
        return self._wrap("31", t)

    def yellow(self, t: str) -> str:
        return self._wrap("33", t)

    def cyan(self, t: str) -> str:
        return self._wrap("36", t)

    def blue(self, t: str) -> str:
        return self._wrap("38;5;69", t)


def _style() -> Style:
    enabled = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None and os.environ.get("TERM") != "dumb"
    return Style(enabled)


def _width(text: str) -> int:
    total = 0
    for ch in text:
        if unicodedata.east_asian_width(ch) in {"W", "F"}:
            total += 2
        elif unicodedata.combining(ch):
            total += 0
        else:
            total += 1
    return total


def _pad(text: str, width: int) -> str:
    diff = width - _width(text)
    return text + " " * max(0, diff)


def _truncate(text: str, width: int) -> str:
    if _width(text) <= width:
        return text
    out = ""
    for ch in text:
        if _width(out + ch) > width - 1:
            break
        out += ch
    return out + "…"


def _table(headers: list[str], rows: list[list[str]], aligns: list[str] | None = None) -> str:
    widths = [_width(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], _width(cell))
    aligns = aligns or ["left"] * len(headers)
    lines = []
    head = "  ".join(
        _pad(h, widths[i]) for i, h in enumerate(headers)
    )
    lines.append(head)
    lines.append("  ".join("─" * widths[i] for i in range(len(headers))))
    for row in rows:
        cells = []
        for i, cell in enumerate(row):
            if aligns[i] == "right":
                cells.append(" " * (widths[i] - _width(cell)) + cell)
            else:
                cells.append(_pad(cell, widths[i]))
        lines.append("  ".join(cells))
    return "\n".join(lines)


# ---------------------------------------------------------------------- 工具
def _family_filter(value: str | None) -> list[str] | None:
    if not value or value == "all":
        return None
    from .gpu import CATALOG, family_category

    fams: list[str] = []
    for part in value.replace("，", ",").split(","):
        part = part.strip().lower()
        if not part:
            continue
        if part in {"4090", "rtx4090", "rtx-4090"}:
            fams.append("rtx4090")
            continue
        if part in {"5090", "rtx5090", "rtx-5090"}:
            fams.append("rtx5090")
            continue
        if part in {"consumer", "workstation", "datacenter", "other"}:
            fams.extend(m.family for m in CATALOG if family_category(m.family) == part)
            continue
        for model in CATALOG:
            tokens = {model.family.lower(), model.key.lower(), model.display.lower()}
            if part in tokens:
                fams.append(model.family)
                break
    return list(dict.fromkeys(fams)) or None


def _preset_filter(value: str | None) -> dict | None:
    if not value or value == "all":
        return None
    from .presets import PRESETS

    return next((p for p in PRESETS if p["id"] == value), None)


def _platform_filter(value: str | None) -> list[str] | None:
    if not value or value == "all":
        return None
    return [p.strip() for p in value.replace("，", ",").split(",") if p.strip()]


def _mode_label(offer: dict[str, Any]) -> str:
    if offer.get("source") == "scrape":
        return "官网抓取"
    return "官网实时"


def _stock_label(offer: dict[str, Any], st: Style) -> str:
    avail = offer.get("available")
    if avail is True:
        stock = offer.get("stock")
        text = f"有货 {stock}" if stock is not None else "有货"
        return st.green(text)
    if avail is False:
        return st.red("无货")
    return st.dim("库存未知")


def _price(offer: dict[str, Any]) -> str:
    p = offer.get("price")
    if not isinstance(p, (int, float)):
        return "—"
    symbol = "$" if str(offer.get("currency") or "CNY").upper() == "USD" else "¥"
    return f"{symbol}{p:.2f}"


def _ensure_snapshot(svc: GPUService, *, force: bool = False, max_age: int = 120, quiet: bool = False) -> dict[str, Any]:
    snap = svc.get_snapshot()
    if force or snap is None or svc.snapshot_age > max_age:
        if not quiet:
            print("正在刷新各平台…", file=sys.stderr)
        snap = svc.refresh()
    return snap or {}


# ---------------------------------------------------------------------- 命令
def cmd_list(args: argparse.Namespace) -> int:
    st = _style()
    svc = GPUService()
    snap = _ensure_snapshot(svc, force=args.refresh, max_age=args.max_age)
    offers = filter_offers(
        snap.get("offers") or [],
        platforms=_platform_filter(args.platform),
        families=_family_filter(args.gpu),
        only_available=args.available,
    )
    preset = _preset_filter(getattr(args, "preset", None))
    if preset:
        from .presets import matches_offer

        offers = [o for o in offers if matches_offer(o, preset)]
    offers.sort(key=lambda o: (o.get("price") is None, o.get("price") or 1e9))

    if args.json:
        payload = {
            "generated_at": snap.get("generated_at"),
            "stale": snap.get("stale", False),
            "summary": snap.get("summary"),
            "offers": offers,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if not offers:
        print(st.yellow("没有符合条件的资源。试试加 --refresh，或去掉 --available。"))
        return 1

    rows = []
    for o in offers:
        rows.append(
            [
                o.get("platform_name", ""),
                o.get("gpu", ""),
                _truncate(o.get("region", ""), 14),
                _price(o),
                _stock_label(o, st),
                st.dim(_mode_label(o)),
            ]
        )
    table = _table(["平台", "显卡", "地区", "价格/时", "库存", "来源"], rows, ["left", "left", "left", "right", "left", "left"])

    print()
    print(st.bold("  GPU Finder X") + st.dim("  ·  多平台 GPU 实时算力比价"))
    print()
    print("  " + table.replace("\n", "\n  "))
    print()
    meta = [
        f"共 {len(offers)} 条",
        f"有货 {sum(1 for o in offers if o.get('available'))} 条",
        f"更新于 {snap.get('generated_at', '')[:19].replace('T', ' ')}",
    ]
    print("  " + st.dim("  ·  ".join(meta)))
    print("  " + st.dim("价格单位：¥ 或 $ /卡/小时；美元报价不做汇率换算，以下单页为准。"))
    print()
    return 0


def cmd_refresh(args: argparse.Namespace) -> int:
    st = _style()
    svc = GPUService()
    t0 = time.perf_counter()
    snap = svc.refresh()
    elapsed = time.perf_counter() - t0
    if args.json:
        print(json.dumps(snap, ensure_ascii=False, indent=2))
        return 0
    print(st.bold(f"\n刷新完成 · 用时 {elapsed:.2f}s · {snap['summary']['offers']} 条报价\n"))
    rows = []
    for p in snap.get("platforms", []):
        status = st.green("OK") if p["ok"] else st.red("失败")
        mode = {"live": "官网实时", "auth": "需登录", "error": "错误"}.get(p["mode"], p["mode"])
        rows.append([p["name"], status, mode, f"{p['offer_count']}", f"{p['latency_ms']}ms", _truncate(p.get("message", ""), 50)])
    print("  " + _table(["平台", "状态", "模式", "报价数", "耗时", "说明"], rows).replace("\n", "\n  "))
    print()
    return 0


def cmd_providers(args: argparse.Namespace) -> int:
    st = _style()
    svc = GPUService()
    rows = []
    for p in svc.providers_info():
        auth = st.dim("—")
        if p["auth_required"]:
            auth = st.green("已配置") if p["credentials_configured"] else st.yellow("未配置")
        rows.append([p["name"], p["id"], auth, p["description"] or ""])
    print()
    print(st.bold("  平台适配器"))
    print()
    print("  " + _table(["平台", "ID", "登录态", "数据源"], rows).replace("\n", "\n  "))
    print()
    print("  " + st.dim("所有平台均为实时数据：AutoDL / 恒源云需登录 token，优云智算需官方 API 密钥。"))
    print("  " + st.dim("AutoDL：gpufinder login autodl 或 config --token autodl <token>"))
    print("  " + st.dim("恒源云：gpufinder config --token gpushare <token>"))
    print("  " + st.dim("优云智算：gpufinder config --apikey compshare <AccessKeyId> <Secret>"))
    print()
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    st = _style()
    print()
    print(st.bold("  环境检查"))
    print()
    checks: list[tuple[str, bool, str]] = []
    checks.append(("Python", sys.version_info >= (3, 9), sys.version.split()[0]))
    checks.append(("配置文件", True, str(config_path())))
    try:
        from .config import cache_dir

        checks.append(("缓存目录", True, str(cache_dir())))
    except OSError as exc:
        checks.append(("缓存目录", False, str(exc)))

    cfg = Config.load()
    for key in CREDENTIAL_KEYS:
        configured = bool(cfg.credential(key))
        checks.append((f"凭据 {key}", configured, "已配置" if configured else "未配置（可选）"))

    for name, ok, detail in checks:
        mark = st.green("✓") if ok else st.yellow("•")
        print(f"  {mark} {name:<18} {st.dim(detail)}")

    print()
    print(st.bold("  连通性测试") + st.dim("（约 5s）"))
    print()
    svc = GPUService(cfg)
    snap = svc.refresh()
    rows = []
    for p in snap.get("platforms", []):
        if p["ok"] and p["mode"] == "live":
            status = st.green("● 正常")
        elif p["ok"]:
            status = st.yellow("● 参考数据")
        else:
            status = st.red("● 失败")
        rows.append([p["name"], status, f"{p['latency_ms']}ms", f"{p['offer_count']} 条", _truncate(p.get("message", ""), 44)])
    print("  " + _table(["平台", "状态", "耗时", "数据", "说明"], rows).replace("\n", "\n  "))
    print()
    bad = [p for p in snap.get("platforms", []) if not p["ok"]]
    if bad:
        print("  " + st.yellow("部分平台抓取失败，可稍后重试；不影响其它平台展示。"))
        print()
    return 0


def cmd_config(args: argparse.Namespace) -> int:
    st = _style()
    cfg = Config.load()
    changed = False

    if args.set:
        for pair in args.set:
            if "=" not in pair:
                print(st.red(f"格式应为 key=value: {pair}"))
                return 2
            key, value = pair.split("=", 1)
            key = key.strip()
            if key in {"port", "refresh_interval"}:
                setattr(cfg, key, int(value))
            elif key in {"open_on_start"}:
                setattr(cfg, key, value.strip().lower() in {"1", "true", "yes", "on"})
            else:
                print(st.red(f"未知配置项: {key}"))
                return 2
            changed = True

    if args.token:
        if len(args.token) != 2:
            print(st.red("用法: gpufinder config --token <autodl|gpushare> <token>"))
            return 2
        provider, token = args.token
        key = f"{provider}_token"
        if key not in CREDENTIAL_KEYS:
            print(st.red(f"未知凭据: {provider}"))
            return 2
        cfg.set_credential(key, token)
        changed = True
        print(st.green(f"已保存 {key}"))

    if args.apikey:
        if len(args.apikey) != 3:
            print(st.red("用法: gpufinder config --apikey compshare <AccessKeyId> <AccessKeySecret>"))
            return 2
        provider, public, secret = args.apikey
        if provider != "compshare":
            print(st.red(f"暂不支持 {provider} 的 API 密钥"))
            return 2
        cfg.set_credential("compshare_public_key", public)
        cfg.set_credential("compshare_private_key", secret)
        changed = True
        print(st.green("已保存优云智算 API 密钥"))

    if args.clear_token:
        provider = args.clear_token
        if provider == "compshare":
            cfg.set_credential("compshare_public_key", "")
            cfg.set_credential("compshare_private_key", "")
            print(st.green("已清除优云智算 API 密钥"))
        else:
            key = f"{provider}_token"
            cfg.set_credential(key, "")
            print(st.green(f"已清除 {key}"))
        changed = True

    if changed:
        path = cfg.save()
        print(st.dim(f"配置已写入 {path}"))

    if not changed or args.show:
        print()
        print(st.bold("  当前配置") + st.dim(f"  ({config_path()})"))
        print()
        rows = [
            ["port", str(cfg.port)],
            ["refresh_interval", f"{cfg.refresh_interval}s"],
            ["open_on_start", "on" if cfg.open_on_start else "off"],
        ]
        for key, masked in cfg.masked_credentials().items():
            rows.append([key, st.green(masked["hint"]) if masked["configured"] else st.dim("未配置")])
        print("  " + _table(["配置项", "值"], rows).replace("\n", "\n  "))
        print()
    return 0


def cmd_login(args: argparse.Namespace) -> int:
    st = _style()
    if args.provider != "autodl":
        print(st.yellow("目前仅支持 `gpufinder login autodl`；恒源云请从浏览器复制 token 后执行："))
        print("  gpufinder config --token gpushare <token>")
        return 2
    import getpass

    phone = args.phone or input("AutoDL 手机号: ").strip()
    password = getpass.getpass("AutoDL 密码（只用于换取 token，不会保存）: ")
    from .providers.autodl import AutodlProvider

    print("正在登录 AutoDL…")
    try:
        token = AutodlProvider.login(phone, password)
    except Exception as exc:  # noqa: BLE001
        print(st.red(f"登录失败: {exc}"))
        print(st.dim("如遇图形验证码，请登录网页后从 localStorage.token 复制，使用 gpufinder config --token autodl <token>"))
        return 1
    cfg = Config.load()
    cfg.set_credential("autodl_token", token)
    cfg.save()
    print(st.green("AutoDL token 已保存，运行 gpufinder refresh 验证。"))
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    svc = GPUService()
    snap = _ensure_snapshot(svc, force=args.refresh, max_age=args.max_age, quiet=True)
    offers = filter_offers(
        snap.get("offers") or [],
        platforms=_platform_filter(args.platform),
        families=_family_filter(args.gpu),
        only_available=args.available,
    )
    preset = _preset_filter(getattr(args, "preset", None))
    if preset:
        from .presets import matches_offer

        offers = [o for o in offers if matches_offer(o, preset)]
    fmt = args.format
    if fmt == "json":
        content = json.dumps({"generated_at": snap.get("generated_at"), "offers": offers}, ensure_ascii=False, indent=2)
    elif fmt == "csv":
        import csv
        import io

        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["platform", "gpu", "vram_gb", "region", "price_per_hour", "currency", "available", "stock", "capacity", "source", "url"])
        for o in offers:
            w.writerow([
                o.get("platform"), o.get("gpu"), o.get("vram_gb"), o.get("region"),
                o.get("price"), o.get("currency") or "CNY", o.get("available"), o.get("stock"), o.get("capacity"),
                o.get("source"), o.get("url"),
            ])
        content = buf.getvalue()
    else:  # markdown
        lines = [
            f"# GPU 报价 · {snap.get('generated_at', '')}",
            "",
            "| 平台 | 显卡 | 地区 | 价格/时 | 库存 | 来源 |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for o in offers:
            if o.get("available") is True:
                stock = "有货" + (f" {o['stock']}" if o.get("stock") is not None else "")
            elif o.get("available") is False:
                stock = "无货"
            else:
                stock = "未知"
            price = f"¥{o['price']:.2f}" if isinstance(o.get("price"), (int, float)) else "—"
            lines.append(
                f"| {o.get('platform_name')} | {o.get('gpu')} | {o.get('region')} | {price} | {stock} | {o.get('source_label') or o.get('source')} |"
            )
        content = "\n".join(lines) + "\n"

    if args.output:
        Path(args.output).expanduser().write_text(content + ("" if content.endswith("\n") else "\n"), "utf-8")
        print(f"已导出 {len(offers)} 条报价到 {args.output}", file=sys.stderr)
    else:
        print(content, end="" if content.endswith("\n") else "\n")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from . import server as server_mod

    argv = []
    if args.port is not None:
        argv += ["--port", str(args.port)]
    if args.open:
        argv.append("--open")
    if args.refresh:
        argv.append("--refresh")
    if args.no_scheduler:
        argv.append("--no-scheduler")
    if getattr(args, "parent_pid", 0):
        argv += ["--parent-pid", str(args.parent_pid)]
    return server_mod.main(argv)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gpufinder",
        description="GPU Finder X · 多平台 GPU 库存、价格与一键租卡",
        epilog="示例: gpufinder list --gpu 4090 --available",
    )
    parser.add_argument("--version", action="version", version=f"gpufinder {VERSION}")
    sub = parser.add_subparsers(dest="command", required=False)

    p_list = sub.add_parser("list", help="列出当前报价（默认命令）")
    p_list.add_argument("--gpu", default="all", help="4090 / 5090 / a100 / h100 / consumer / datacenter / all")
    p_list.add_argument("--preset", default="all", help="预设 id：all/consumer/4090/5090/training/largemem/inference/workstation/budget")
    p_list.add_argument("--platform", default=None, help="autodl,matpool,compshare,gpushare")
    p_list.add_argument("--available", action="store_true", help="只看有货")
    p_list.add_argument("--refresh", action="store_true", help="强制刷新")
    p_list.add_argument("--max-age", type=int, default=120, help="缓存有效期秒数（默认 120）")
    p_list.add_argument("--json", action="store_true", help="输出 JSON")
    p_list.set_defaults(func=cmd_list)

    p_refresh = sub.add_parser("refresh", help="立即刷新全部平台")
    p_refresh.add_argument("--json", action="store_true")
    p_refresh.set_defaults(func=cmd_refresh)

    p_prov = sub.add_parser("providers", help="查看平台适配器与登录态")
    p_prov.set_defaults(func=cmd_providers)

    p_doctor = sub.add_parser("doctor", help="环境与连通性自检")
    p_doctor.set_defaults(func=cmd_doctor)

    p_config = sub.add_parser("config", help="查看/修改配置与凭据")
    p_config.add_argument("--show", action="store_true")
    p_config.add_argument("--set", nargs="+", metavar="KEY=VALUE")
    p_config.add_argument("--token", nargs=2, metavar=("PROVIDER", "TOKEN"))
    p_config.add_argument("--apikey", nargs=3, metavar=("PROVIDER", "PUBLIC", "SECRET"))
    p_config.add_argument("--clear-token", metavar="PROVIDER")
    p_config.set_defaults(func=cmd_config)

    p_login = sub.add_parser("login", help="登录平台以获取库存权限（AutoDL）")
    p_login.add_argument("provider", choices=["autodl", "gpushare"], nargs="?", default="autodl")
    p_login.add_argument("--phone", default=None)
    p_login.set_defaults(func=cmd_login)

    p_export = sub.add_parser("export", help="导出 JSON / CSV / Markdown")
    p_export.add_argument("--format", choices=["json", "csv", "md"], default="md")
    p_export.add_argument("-o", "--output", default=None)
    p_export.add_argument("--gpu", default="all")
    p_export.add_argument("--preset", default="all")
    p_export.add_argument("--platform", default=None)
    p_export.add_argument("--available", action="store_true")
    p_export.add_argument("--refresh", action="store_true")
    p_export.add_argument("--max-age", type=int, default=300)
    p_export.set_defaults(func=cmd_export)

    p_serve = sub.add_parser("serve", help="启动本地 Web Dashboard 与 API")
    p_serve.add_argument("--port", type=int, default=None)
    p_serve.add_argument("--open", action="store_true")
    p_serve.add_argument("--refresh", action="store_true")
    p_serve.add_argument("--no-scheduler", action="store_true")
    p_serve.add_argument("--parent-pid", type=int, default=0, help=argparse.SUPPRESS)
    p_serve.set_defaults(func=cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    if not argv:
        # 默认走 list，交互更友好
        argv = ["list"]
    elif argv[0].startswith("-") and argv[0] not in {"--version", "-h", "--help"}:
        argv = ["list"] + argv
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return 0
    try:
        return int(func(args))
    except KeyboardInterrupt:
        return 130
    except BrokenPipeError:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
