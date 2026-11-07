"""显卡型号归一化：兼容旧 API，具体目录见 :mod:`gpufinder.gpu_catalog`。"""

from __future__ import annotations

from .gpu_catalog import (
    CATALOG,
    CATEGORY_LABELS,
    GPUModel,
    catalog,
    catalog_groups,
    clean_gpu_text,
    family_category,
    family_label,
    family_meta,
    normalize_gpu,
)

__all__ = [
    "CATALOG",
    "CATEGORY_LABELS",
    "GPUModel",
    "catalog",
    "catalog_groups",
    "clean_gpu_text",
    "family_category",
    "family_label",
    "family_meta",
    "normalize_gpu",
]
