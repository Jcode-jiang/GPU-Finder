#!/usr/bin/env bash
# 从源码直接运行 CLI：./gpufinder list --gpu 4090
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 -m gpufinder "$@"
