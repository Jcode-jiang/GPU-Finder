"""可扩展的 GPU 型号目录。

新增显卡只需要在 ``CATALOG`` 里加一条记录；归一化、筛选、预设和 UI
都会自动读取这里，不再把 4090/5090 写死在 provider 里。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

CATEGORY_LABELS = {
    "consumer": "消费级",
    "workstation": "工作站",
    "datacenter": "数据中心",
    "other": "其它",
}
CATEGORY_ORDER = {"consumer": 0, "workstation": 1, "datacenter": 2, "other": 3}


@dataclass(frozen=True)
class GPUModel:
    key: str
    display: str
    family: str
    vram_gb: int
    category: str
    vendor: str = "NVIDIA"
    aliases: tuple[str, ...] = field(default_factory=tuple)
    tier: int = 0

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "display": self.display,
            "family": self.family,
            "vram_gb": self.vram_gb,
            "category": self.category,
            "vendor": self.vendor,
            "tier": self.tier,
        }


def _m(key: str, display: str, family: str, vram: int, category: str, *aliases: str, vendor: str = "NVIDIA", tier: int = 0) -> GPUModel:
    return GPUModel(key, display, family, vram, category, vendor, tuple(aliases), tier)


CATALOG: list[GPUModel] = [
    # ---- 消费级：RTX 50 ----
    _m("rtx5090", "RTX 5090", "rtx5090", 32, "consumer", "RTX 5090", "5090", "RTX5090", tier=100),
    _m("rtx5090d", "RTX 5090D", "rtx5090d", 32, "consumer", "RTX 5090 D", "RTX5090D", "5090D", "5090 D", tier=99),
    _m("rtx5080", "RTX 5080", "rtx5080", 16, "consumer", "RTX 5080", "5080", "RTX5080", tier=98),
    _m("rtx5070ti", "RTX 5070 Ti", "rtx5070ti", 16, "consumer", "RTX 5070 Ti", "5070 Ti", "5070Ti", "RTX5070Ti", tier=97),
    _m("rtx5070", "RTX 5070", "rtx5070", 12, "consumer", "RTX 5070", "5070", "RTX5070", tier=96),
    _m("rtx5060ti16", "RTX 5060 Ti 16G", "rtx5060ti", 16, "consumer", "RTX 5060 Ti 16G", "5060 Ti 16G", "5060Ti 16G", tier=95),
    _m("rtx5060ti", "RTX 5060 Ti", "rtx5060ti", 8, "consumer", "RTX 5060 Ti", "5060 Ti", "5060Ti", "RTX5060Ti", tier=94),
    _m("rtx5060", "RTX 5060", "rtx5060", 8, "consumer", "RTX 5060", "5060", "RTX5060", tier=93),

    # ---- 消费级：RTX 40 ----
    _m("rtx409048", "RTX 4090 48G", "rtx409048", 48, "consumer", "RTX 4090 48G", "4090 48G", "4090-48G", "4090 48GB", "RTX4090 48G", tier=90),
    _m("rtx4090d", "RTX 4090D", "rtx4090d", 24, "consumer", "RTX 4090 D", "RTX 4090D", "4090D", "4090 D", tier=89),
    _m("rtx4090", "RTX 4090", "rtx4090", 24, "consumer", "RTX 4090", "4090", "RTX4090", tier=88),
    _m("rtx4080s", "RTX 4080 Super", "rtx4080", 16, "consumer", "RTX 4080 Super", "4080 Super", "4080S", "4080 S", tier=87),
    _m("rtx4080", "RTX 4080", "rtx4080", 16, "consumer", "RTX 4080", "4080", "RTX4080", tier=86),
    _m("rtx4070tis", "RTX 4070 Ti Super", "rtx4070ti", 16, "consumer", "RTX 4070 Ti Super", "4070 Ti Super", "4070TiS", "4070 Ti S", "4070S Ti", tier=85),
    _m("rtx4070ti", "RTX 4070 Ti", "rtx4070ti", 12, "consumer", "RTX 4070 Ti", "4070 Ti", "4070Ti", "RTX4070Ti", tier=84),
    _m("rtx4070s", "RTX 4070 Super", "rtx4070", 12, "consumer", "RTX 4070 Super", "4070 Super", "4070S", "4070 S", tier=83),
    _m("rtx4070", "RTX 4070", "rtx4070", 12, "consumer", "RTX 4070", "4070", "RTX4070", tier=82),
    _m("rtx4060ti16", "RTX 4060 Ti 16G", "rtx4060ti", 16, "consumer", "RTX 4060 Ti 16G", "4060 Ti 16G", "4060Ti 16G", tier=81),
    _m("rtx4060ti", "RTX 4060 Ti", "rtx4060ti", 8, "consumer", "RTX 4060 Ti", "4060 Ti", "4060Ti", "RTX4060Ti", tier=80),
    _m("rtx4060", "RTX 4060", "rtx4060", 8, "consumer", "RTX 4060", "4060", "RTX4060", tier=79),

    # ---- 消费级：RTX 30 ----
    _m("rtx3090ti", "RTX 3090 Ti", "rtx3090", 24, "consumer", "RTX 3090 Ti", "3090 Ti", "3090Ti", tier=75),
    _m("rtx3090", "RTX 3090", "rtx3090", 24, "consumer", "RTX 3090", "3090", "RTX3090", tier=74),
    _m("rtx3080ti", "RTX 3080 Ti", "rtx3080", 12, "consumer", "RTX 3080 Ti", "3080 Ti", "3080Ti", tier=73),
    _m("rtx308012", "RTX 3080 12G", "rtx3080", 12, "consumer", "RTX 3080 12G", "3080 12G", "3080 12GB", tier=72),
    _m("rtx3080", "RTX 3080", "rtx3080", 10, "consumer", "RTX 3080", "3080", "RTX3080", tier=71),
    _m("rtx3070ti", "RTX 3070 Ti", "rtx3070", 8, "consumer", "RTX 3070 Ti", "3070 Ti", "3070Ti", tier=70),
    _m("rtx3070", "RTX 3070", "rtx3070", 8, "consumer", "RTX 3070", "3070", "RTX3070", tier=69),
    _m("rtx3060ti", "RTX 3060 Ti", "rtx3060", 8, "consumer", "RTX 3060 Ti", "3060 Ti", "3060Ti", tier=68),
    _m("rtx3060", "RTX 3060", "rtx3060", 12, "consumer", "RTX 3060", "3060", "RTX3060", tier=67),

    # ---- 消费级：RTX 20 ----
    _m("rtx2080ti", "RTX 2080 Ti", "rtx2080", 11, "consumer", "RTX 2080 Ti", "2080 Ti", "2080Ti", tier=60),
    _m("rtx2080s", "RTX 2080 Super", "rtx2080", 8, "consumer", "RTX 2080 Super", "2080 Super", "2080S", tier=59),
    _m("rtx2080", "RTX 2080", "rtx2080", 8, "consumer", "RTX 2080", "2080", tier=58),
    _m("rtx2070s", "RTX 2070 Super", "rtx2070", 8, "consumer", "RTX 2070 Super", "2070 Super", "2070S", tier=57),
    _m("rtx2070", "RTX 2070", "rtx2070", 8, "consumer", "RTX 2070", "2070", tier=56),
    _m("rtx2060s", "RTX 2060 Super", "rtx2060", 8, "consumer", "RTX 2060 Super", "2060 Super", "2060S", tier=55),
    _m("rtx2060", "RTX 2060", "rtx2060", 6, "consumer", "RTX 2060", "2060", tier=54),

    # ---- 工作站 ----
    _m("rtxpro6000", "RTX PRO 6000", "rtxpro6000", 96, "workstation", "RTX PRO 6000", "RTX PRO 6000 Blackwell", "PRO 6000", "RTXPRO6000", tier=50),
    _m("rtx6000ada", "RTX 6000 Ada", "rtx6000ada", 48, "workstation", "RTX 6000 Ada", "RTX6000Ada", "6000Ada", "RTX 6000D", tier=49),
    _m("rtx5000ada", "RTX 5000 Ada", "rtx5000ada", 32, "workstation", "RTX 5000 Ada", "RTX5000Ada", "5000Ada", tier=48),
    _m("rtx4500ada", "RTX 4500 Ada", "rtx4500ada", 24, "workstation", "RTX 4500 Ada", "RTX4500Ada", "4500Ada", tier=47),
    _m("rtx4000ada", "RTX 4000 Ada", "rtx4000ada", 20, "workstation", "RTX 4000 Ada", "RTX4000Ada", "4000Ada", tier=46),
    _m("a6000", "RTX A6000", "a6000", 48, "workstation", "RTX A6000", "A6000", "RTXA6000", tier=45),
    _m("a5000", "RTX A5000", "a5000", 24, "workstation", "RTX A5000", "A5000", "RTXA5000", tier=44),
    _m("a4000", "RTX A4000", "a4000", 16, "workstation", "RTX A4000", "A4000", "RTXA4000", tier=43),
    _m("a2000", "RTX A2000", "a2000", 12, "workstation", "RTX A2000", "A2000", "RTXA2000", tier=42),
    _m("rtx8000", "Quadro RTX 8000", "rtx8000", 48, "workstation", "Quadro RTX 8000", "RTX 8000", "RTX8000", tier=41),
    _m("rtx6000", "Quadro RTX 6000", "rtx6000", 24, "workstation", "Quadro RTX 6000", "RTX 6000", "RTX6000", tier=40),
    _m("rtx5000", "Quadro RTX 5000", "rtx5000", 16, "workstation", "Quadro RTX 5000", "RTX 5000", "RTX5000", tier=39),
    _m("p5000", "Quadro P5000", "p5000", 16, "workstation", "Quadro P5000", "P5000", tier=38),
    _m("p4000", "Quadro P4000", "p4000", 8, "workstation", "Quadro P4000", "P4000", tier=37),

    # ---- 数据中心 ----
    _m("b300", "B300", "b300", 288, "datacenter", "B300", tier=35),
    _m("b200", "B200", "b200", 180, "datacenter", "B200", tier=34),
    _m("h200", "H200", "h200", 141, "datacenter", "H200", "H200 NVL", tier=33),
    _m("h100", "H100", "h100", 80, "datacenter", "H100", "H100 SXM", "H100 PCIE", "H100 NVL", tier=32),
    _m("h800", "H800", "h800", 80, "datacenter", "H800", tier=31),
    _m("h20", "H20", "h20", 96, "datacenter", "H20", tier=30),
    _m("a100_80", "A100 80GB", "a100", 80, "datacenter", "A100 80G", "A100 80GB", "A100 SXM4 80G", "A100 PCIE 80G", "A100-SXM4-80GB", tier=29),
    _m("a100_40", "A100 40GB", "a100", 40, "datacenter", "A100 40G", "A100 40GB", "A100 SXM4 40G", "A100 PCIE 40G", "A100-SXM4-40GB", tier=28),
    _m("a100", "A100", "a100", 80, "datacenter", "A100", "A100 SXM4", "A100 PCIE", "A100 PCIe", tier=27),
    _m("a800_80", "A800 80GB", "a800", 80, "datacenter", "A800 80G", "A800 80GB", tier=26),
    _m("a800_40", "A800 40GB", "a800", 40, "datacenter", "A800 40G", "A800 40GB", tier=25),
    _m("a800", "A800", "a800", 80, "datacenter", "A800", tier=24),
    _m("l40s", "L40S", "l40s", 48, "datacenter", "L40S", "L40 S", tier=23),
    _m("l40", "L40", "l40", 48, "datacenter", "L40", tier=22),
    _m("l4", "L4", "l4", 24, "datacenter", "L4", tier=21),
    _m("a40", "A40", "a40", 48, "datacenter", "A40", tier=20),
    _m("a30", "A30", "a30", 24, "datacenter", "A30", tier=19),
    _m("a10", "A10", "a10", 24, "datacenter", "A10", tier=18),
    _m("a16", "A16", "a16", 16, "datacenter", "A16", tier=17),
    _m("v100_32", "V100 32GB", "v100", 32, "datacenter", "V100 32G", "V100 32GB", "V100-SXM2-32GB", tier=16),
    _m("v100", "V100", "v100", 16, "datacenter", "V100", "V100 16G", "V100 16GB", "Tesla V100", tier=15),
    _m("t4", "T4", "t4", 16, "datacenter", "T4", "Tesla T4", tier=14),
    _m("p100", "P100", "p100", 16, "datacenter", "P100", "Tesla P100", tier=13),
    _m("p40", "P40", "p40", 24, "datacenter", "P40", "Tesla P40", tier=12),
    _m("mi300x", "MI300X", "mi300x", 192, "datacenter", "MI300X", "AMD Instinct MI300X", vendor="AMD", tier=11),
]


def _pattern(alias: str) -> re.Pattern[str]:
    parts = re.split(r"[\s_-]+", alias.strip())
    body = r"[\s_-]*".join(re.escape(p) for p in parts)
    return re.compile(r"(?<![A-Za-z0-9])" + body + r"(?![A-Za-z0-9])", re.I)


_RULES: list[tuple[re.Pattern[str], GPUModel]] = []
for _model in CATALOG:
    for _alias in _model.aliases:
        _RULES.append((_pattern(_alias), _model))
# 长 alias 优先，保证 "4090 48G" / "A100 80G" 先于 "4090" / "A100"
_RULES.sort(key=lambda x: len(x[0].pattern), reverse=True)

_BY_FAMILY: dict[str, GPUModel] = {}
for _model in CATALOG:
    _BY_FAMILY.setdefault(_model.family, _model)


def clean_gpu_text(text: str) -> str:
    s = str(text or "").strip()
    s = re.sub(r"^(NVIDIA|GeForce|NVIDIA GeForce|GEFORCE|AMD)\s+", "", s, flags=re.I)
    s = re.sub(r"\s+", " ", s)
    return s


def normalize_gpu(text: str) -> tuple[str, str, int] | None:
    """返回 ``(展示名, family, 显存GB)``；不认识的型号返回 None。"""
    s = clean_gpu_text(text)
    if not s:
        return None
    for pattern, model in _RULES:
        if pattern.search(s):
            return model.display, model.family, model.vram_gb
    return None


def family_label(family: str) -> str:
    model = _BY_FAMILY.get(family)
    return model.display if model else family


def family_category(family: str) -> str:
    model = _BY_FAMILY.get(family)
    return model.category if model else "other"


def family_meta(family: str) -> dict:
    model = _BY_FAMILY.get(family)
    if not model:
        return {"family": family, "label": family, "category": "other", "vram_gb": None}
    return {
        "family": family,
        "label": model.display,
        "category": model.category,
        "vram_gb": model.vram_gb,
        "vendor": model.vendor,
    }


def catalog() -> list[dict]:
    models = sorted(CATALOG, key=lambda m: (CATEGORY_ORDER.get(m.category, 9), -m.tier, m.display))
    return [m.to_dict() for m in models]


def catalog_groups() -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for model in sorted(CATALOG, key=lambda m: (CATEGORY_ORDER.get(m.category, 9), -m.tier, m.display)):
        groups.setdefault(model.category, []).append(model.to_dict())
    return [
        {"id": key, "label": CATEGORY_LABELS.get(key, key), "models": models}
        for key, models in groups.items()
    ]
