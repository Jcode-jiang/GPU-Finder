"""平台 Provider 注册表。"""

from __future__ import annotations

from .autodl import AutodlProvider
from .base import AuthRequired, FetchContext, Provider, ProviderError
from .compshare import CompshareProvider
from .gpushare import GpushareProvider
from .matpool import MatpoolProvider

DEFAULT_PROVIDERS: list[Provider] = [
    AutodlProvider(),
    MatpoolProvider(),
    CompshareProvider(),
    GpushareProvider(),
]

__all__ = [
    "AuthRequired",
    "CompshareProvider",
    "AutodlProvider",
    "DEFAULT_PROVIDERS",
    "FetchContext",
    "GpushareProvider",
    "MatpoolProvider",
    "Provider",
    "ProviderError",
]
