"""显卡型号归一化。

只关心 RTX 4090 / RTX 5090 家族，但会保留 D 版、48G 魔改版等变体，
避免把不同芯片/显存的卡混成一个报价。
"""

from __future__ import annotations

import re

FAMILIES = {
    "rtx4090": "RTX 4090",
    "rtx5090": "RTX 5090",
}

# 常见写法 -> (展示名, family, 显存)
_PATTERNS: list[tuple[re.Pattern[str], str, str, int]] = [
    (re.compile(r"(?:RTX[\s-]*)?4090[\s-]*D\b", re.I), "RTX 4090D", "rtx4090", 24),
    (re.compile(r"(?:RTX[\s_-]*)?4090[\s_-]*(48|48G|48GB)\b", re.I), "RTX 4090 48G", "rtx4090", 48),
    (re.compile(r"(?:RTX[\s-]*)?4090\b", re.I), "RTX 4090", "rtx4090", 24),
    (re.compile(r"(?:RTX[\s-]*)?5090[\s-]*D\b", re.I), "RTX 5090D", "rtx5090", 32),
    (re.compile(r"(?:RTX[\s-]*)?5090\b", re.I), "RTX 5090", "rtx5090", 32),
]

_VRAM_RE = re.compile(r"(\d{1,3})\s*(?:G|GB)\b", re.I)


def normalize_gpu(text: str) -> tuple[str, str, int] | None:
    """把平台返回的型号字符串归一化为 (展示名, family, 显存GB)。

    >>> normalize_gpu("NVIDIA GeForce RTX 4090")
    ('RTX 4090', 'rtx4090', 24)
    >>> normalize_gpu("RTX5090 32G")
    ('RTX 5090', 'rtx5090', 32)
    """
    if not text:
        return None
    s = str(text).strip()
    # 去掉厂商前缀，保留型号
    s = re.sub(r"^(NVIDIA|GeForce|NVIDIA GeForce|GEFORCE)\s+", "", s, flags=re.I)
    for pat, display, family, vram in _PATTERNS:
        if pat.search(s):
            m = _VRAM_RE.search(s)
            if m:
                try:
                    vram = int(m.group(1))
                except ValueError:
                    pass
            # 48G 的 4090 是魔改版本，即使型号描述里夹了其它文字也要区分开
            if display == "RTX 4090" and vram == 48:
                display = "RTX 4090 48G"
            return display, family, vram
    return None


def family_label(family: str) -> str:
    return FAMILIES.get(family, family)
