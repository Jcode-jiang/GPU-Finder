# 贡献指南

感谢你愿意改进 GPU Finder。这个项目优先保证三件事：**数据真实、租卡安全、零第三方依赖**。

## 开发环境

- Python 3.9+（macOS 系统自带的 `/usr/bin/python3` 也可）
- macOS 13+，构建状态栏 App 需要 Xcode Command Line Tools
- 无 Python 第三方依赖；不需要 `pip install` 也能运行

```bash
git clone <repo-url>
cd GPU-Finder

python3 -m unittest discover -s tests -v
python3 -m gpufinder serve --open
```

## 代码约定

- Python 使用 3.9 兼容语法，文件头保留 `from __future__ import annotations`；
- 网络请求统一走 `gpufinder/http.py` 的 `HttpClient`，不要在 provider 里直接 `urllib`；
- 新增平台时只实现 `Provider` 接口，失败必须抛出 `ProviderError`，不要返回假数据；
- 前端保持零构建：直接编辑 `gpufinder/web/` 下的 HTML/CSS/JS；
- Swift 目标 macOS 13，使用 AppKit + SwiftUI，避免依赖 Xcode 工程文件。

## 提交前检查

```bash
make test
python3 scripts/check_no_secrets.py
```

**禁止提交任何真实 token、Cookie、AccessKey、私钥、SSH 密码、实例 ID、IP、账号截图。**
配置示例只能写空字符串或明显的占位符。

## Pull Request

1. 从 `main` 切分支，分支名建议 `feat/...`、`fix/...`；
2. 一个 PR 只做一件事，说明「改了什么 / 为什么 / 怎么验证」；
3. 涉及平台的改动请附上脱敏后的接口字段或测试结果；
4. 不要提交 `dist/`、`build/`、`__pycache__`、`.venv`、本地配置文件。

## 新增显卡型号

1. 在 `gpufinder/gpu_catalog.py` 的 `CATALOG` 加一条记录（display / family / vram / category / aliases）；
2. 在 `tests/test_core.py` 加归一化断言；
3. 如果平台接口使用特殊命名，补一条 alias；
4. 不需要修改任何 provider。

## 新增平台适配器

1. 在 `gpufinder/providers/` 新建模块，继承 `Provider`；
2. 在 `gpufinder/providers/__init__.py` 注册；
3. 在 `tests/` 里加入离线解析测试（不要访问真实网络）；
4. 在 `docs/PROVIDERS.md` 补充数据来源、凭据、已知限制；
5. 如果支持租卡，先在 `docs/RENT.md` 写清楚验证过的链路，再实现 `rent_*.py`。

## 安全问题

请不要在 Issue 里贴 token。发现凭据泄露或租卡安全问题，按 [SECURITY.md](SECURITY.md) 私下联系。
