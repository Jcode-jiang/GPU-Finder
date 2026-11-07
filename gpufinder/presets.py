"""常用显卡/配置预设。

预设是跨平台筛选条件，不绑定具体平台；Dashboard、CLI 和面板共用。
"""

from __future__ import annotations

PRESETS: list[dict] = [
    {
        "id": "all",
        "label": "全部显卡",
        "description": "所有平台、所有型号",
        "icon": "grid",
    },
    {
        "id": "consumer",
        "label": "消费级 40/50",
        "description": "RTX 4090/5090 及 40/50 系",
        "categories": ["consumer"],
        "icon": "gpu",
    },
    {
        "id": "4090",
        "label": "RTX 4090 家族",
        "description": "4090 / 4090D / 4090 48G",
        "families": ["rtx4090", "rtx4090d", "rtx409048"],
        "icon": "spark",
    },
    {
        "id": "5090",
        "label": "RTX 5090 家族",
        "description": "5090 / 5090D",
        "families": ["rtx5090", "rtx5090d"],
        "icon": "spark",
    },
    {
        "id": "training",
        "label": "训练卡",
        "description": "A100 / A800 / H100 / H800 / H200 / H20",
        "families": ["a100", "a800", "h100", "h800", "h200", "h20"],
        "icon": "train",
    },
    {
        "id": "largemem",
        "label": "大显存 ≥48G",
        "description": "48GB 以上，适合大模型/长上下文",
        "min_vram": 48,
        "icon": "memory",
    },
    {
        "id": "inference",
        "label": "推理卡",
        "description": "L4 / L40S / 4090 / 5090",
        "families": ["l4", "l40s", "rtx4090", "rtx4090d", "rtx409048", "rtx5090", "rtx5090d"],
        "icon": "bolt",
    },
    {
        "id": "workstation",
        "label": "工作站",
        "description": "A6000 / A5000 / RTX 6000 Ada 等",
        "categories": ["workstation"],
        "icon": "desktop",
    },
    {
        "id": "budget",
        "label": "¥3/时以下",
        "description": "人民币报价中价格不高于 ¥3/时",
        "max_price": 3,
        "currency": "CNY",
        "icon": "coin",
    },
]


def list_presets() -> list[dict]:
    return [dict(p) for p in PRESETS]


def matches_offer(offer: dict, preset: dict) -> bool:
    """字典版预设匹配（CLI / API 用）。"""
    families = preset.get("families")
    if families and offer.get("family") not in families:
        return False
    categories = preset.get("categories")
    if categories:
        from .gpu import family_category

        if family_category(str(offer.get("family") or "")) not in categories:
            return False
    min_vram = preset.get("min_vram")
    if min_vram and int(offer.get("vram_gb") or 0) < int(min_vram):
        return False
    wanted_currency = preset.get("currency")
    if wanted_currency and str(offer.get("currency") or "CNY").upper() != str(wanted_currency).upper():
        return False
    max_price = preset.get("max_price")
    if max_price is not None and offer.get("price") is not None:
        if float(offer["price"]) > float(max_price):
            return False
    return True


def matches_preset(offer, preset: dict) -> bool:
    families = preset.get("families")
    if families and offer.family not in families:
        return False
    categories = preset.get("categories")
    if categories:
        from .gpu import family_category

        if family_category(offer.family) not in categories:
            return False
    min_vram = preset.get("min_vram")
    if min_vram and (offer.vram_gb or 0) < int(min_vram):
        return False
    wanted_currency = preset.get("currency")
    if wanted_currency and (offer.currency or "CNY").upper() != str(wanted_currency).upper():
        return False
    max_price = preset.get("max_price")
    if max_price is not None and offer.price is not None and offer.price > float(max_price):
        return False
    return True
