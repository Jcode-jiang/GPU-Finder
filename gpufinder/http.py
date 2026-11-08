"""极简 HTTP 客户端（仅标准库）。

- 自动 gzip 解压、重试、超时
- 支持每平台自定义 UA / Cookie
- 统一返回 ``Response``，方便 provider 做容错
"""

from __future__ import annotations

import gzip
import io
import json
import random
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from dataclasses import dataclass, field
from typing import Any

from .errors import redact

DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


class HttpError(Exception):
    def __init__(self, message: str, status: int = 0, url: str = "") -> None:
        super().__init__(redact(message))
        self.status = status
        self.url = url


@dataclass
class Response:
    status: int
    url: str
    content: bytes
    headers: dict[str, str] = field(default_factory=dict)

    @property
    def text(self) -> str:
        charset = "utf-8"
        ctype = self.headers.get("content-type", "")
        if "charset=" in ctype:
            charset = ctype.split("charset=")[-1].split(";")[0].strip() or "utf-8"
        try:
            return self.content.decode(charset, errors="replace")
        except LookupError:
            return self.content.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self.text)


class HttpClient:
    def __init__(
        self,
        timeout: float = 20.0,
        retries: int = 2,
        user_agent: str = DEFAULT_UA,
        cookie: str = "",
    ) -> None:
        self.timeout = timeout
        self.retries = retries
        self.user_agent = user_agent
        self.cookie = cookie
        self._ctx = ssl.create_default_context()

    # ------------------------------------------------------------------ 请求
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        data: bytes | None = None,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
        retries: int | None = None,
    ) -> Response:
        if params:
            sep = "&" if urllib.parse.urlparse(url).query else "?"
            url = f"{url}{sep}{urllib.parse.urlencode(params, doseq=True)}"

        hdrs = {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/html, */*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate",
        }
        if self.cookie:
            hdrs["Cookie"] = self.cookie
        if headers:
            hdrs.update(headers)

        # 安全边界：只有幂等请求允许默认重试。
        # 创建/释放实例等 POST/PUT/DELETE 绝不能因超时被盲目重发。
        safe_method = method.upper() in {"GET", "HEAD", "OPTIONS"}
        if safe_method:
            attempts = self.retries if retries is None else retries
        else:
            attempts = 0
        last_err: Exception | None = None
        for attempt in range(attempts + 1):
            req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
            try:
                with urllib.request.urlopen(req, timeout=timeout or self.timeout, context=self._ctx) as resp:
                    raw = resp.read()
                    body = _decompress(raw, resp.headers.get("Content-Encoding", ""))
                    return Response(
                        status=resp.status,
                        url=resp.geturl(),
                        content=body,
                        headers={k.lower(): v for k, v in resp.headers.items()},
                    )
            except urllib.error.HTTPError as exc:
                raw = b""
                try:
                    raw = exc.read()
                except Exception:  # pragma: no cover - 极端情况
                    pass
                body = _decompress(raw, exc.headers.get("Content-Encoding", "") if exc.headers else "")
                # 4xx 不重试（鉴权/参数错误重试无意义），5xx 重试
                if exc.code < 500 or attempt >= attempts:
                    return Response(
                        status=exc.code,
                        url=url,
                        content=body,
                        headers={k.lower(): v for k, v in (exc.headers.items() if exc.headers else [])},
                    )
                last_err = exc
            except (urllib.error.URLError, TimeoutError, ssl.SSLError, ConnectionError) as exc:
                last_err = exc
                if attempt >= attempts:
                    break
            # 指数退避 + 抖动
            time.sleep(min(0.6 * (2**attempt), 3.0) + random.uniform(0, 0.25))

        raise HttpError(f"请求失败: {url} ({last_err})", url=url)

    def get(self, url: str, **kwargs: Any) -> Response:
        return self.request("GET", url, **kwargs)

    def post_form(self, url: str, fields: dict[str, Any], **kwargs: Any) -> Response:
        headers = dict(kwargs.pop("headers", {}) or {})
        headers.setdefault("Content-Type", "application/x-www-form-urlencoded; charset=utf-8")
        body = urllib.parse.urlencode({k: str(v) for k, v in fields.items()}).encode("utf-8")
        return self.request("POST", url, data=body, headers=headers, **kwargs)

    def delete_json(self, url: str, payload: Any, **kwargs: Any) -> Response:
        headers = dict(kwargs.pop("headers", {}) or {})
        headers.setdefault("Content-Type", "application/json")
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        return self.request("DELETE", url, data=body, headers=headers, **kwargs)

    def put_json(self, url: str, payload: Any, **kwargs: Any) -> Response:
        headers = dict(kwargs.pop("headers", {}) or {})
        headers.setdefault("Content-Type", "application/json")
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        return self.request("PUT", url, data=body, headers=headers, **kwargs)

    def post_json(self, url: str, payload: Any, **kwargs: Any) -> Response:
        headers = dict(kwargs.pop("headers", {}) or {})
        headers.setdefault("Content-Type", "application/json")
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        return self.request("POST", url, data=body, headers=headers, **kwargs)

    def get_json(self, url: str, **kwargs: Any) -> Any:
        resp = self.get(url, **kwargs)
        if resp.status >= 400:
            raise HttpError(f"HTTP {resp.status}: {url}", status=resp.status, url=url)
        return resp.json()


def _decompress(raw: bytes, encoding: str) -> bytes:
    enc = (encoding or "").lower()
    try:
        if "gzip" in enc:
            return gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
        if "deflate" in enc:
            try:
                return zlib.decompress(raw)
            except zlib.error:
                return zlib.decompress(raw, -zlib.MAX_WBITS)
    except (OSError, EOFError, zlib.error):
        return raw
    return raw
