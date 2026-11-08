"""错误分类与敏感信息脱敏。

所有返回给前端的平台错误都应先经过 ``redact``；分类只用于展示和排查，
不会被当作程序控制流。
"""

from __future__ import annotations

import re
from typing import Any

CATEGORY_LABELS = {
    "auth": "鉴权失败",
    "balance": "余额不足",
    "stock": "库存不足",
    "timeout": "请求超时",
    "rate_limit": "请求过于频繁",
    "conflict": "状态冲突",
    "unknown": "未知错误",
}

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("auth", re.compile(r"(?i)(401|403|unauthor|forbidden|invalid.?token|jwt|登录|鉴权|auth)")),
    ("balance", re.compile(r"(?i)(余额|balance|insufficient.?fund|欠费|充值)")),
    ("stock", re.compile(r"(?i)(无库存|库存不足|售罄|no.?stock|sold.?out|insufficient.?resource|无空闲|已租满)")),
    ("timeout", re.compile(r"(?i)(timeout|timed.?out|超时|deadline exceeded)")),
    ("rate_limit", re.compile(r"(?i)(429|rate.?limit|too.?many.?requests|限流|频繁)")),
    ("conflict", re.compile(r"(?i)(状态不符|conflict|already.?exists|duplicate|创建中|重复)")),
)

_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)(Authorization\s*:\s*Bearer\s+)[^\s,;]+"), r"\1***"),
    (re.compile(r"(?i)(Bearer\s+)[A-Za-z0-9._~+/=-]{12,}"), r"\1***"),
    (re.compile(r"(?i)((?:token|password|passwd|secret|access[_-]?key|cookie|jwt)\s*[=:]\s*)[^\s,;]+"), r"\1***"),
    (re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"), "***"),
)


def classify(message: Any) -> str:
    text = str(message or "")
    for category, pattern in _PATTERNS:
        if pattern.search(text):
            return category
    return "unknown"


def label(category: str) -> str:
    return CATEGORY_LABELS.get(category, CATEGORY_LABELS["unknown"])


def redact(message: Any) -> str:
    text = str(message or "")
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


def error_payload(message: Any) -> dict[str, Any]:
    text = redact(message)
    category = classify(text)
    return {"ok": False, "error": text, "category": category, "category_label": label(category)}
