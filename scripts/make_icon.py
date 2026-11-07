#!/usr/bin/env python3
"""生成 macOS App 图标（1024px 主图 + iconset + .icns）。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

SIZE = 1024
OUT = Path(__file__).resolve().parent.parent / "build" / "icon"


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def gradient(size: int, c1: tuple[int, int, int], c2: tuple[int, int, int]) -> Image.Image:
    img = Image.new("RGB", (size, size))
    px = img.load()
    for y in range(size):
        for x in range(size):
            t = (x / size * 0.55 + y / size * 0.45)
            px[x, y] = (
                int(lerp(c1[0], c2[0], t)),
                int(lerp(c1[1], c2[1], t)),
                int(lerp(c1[2], c2[2], t)),
            )
    return img


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    margin = 92
    radius = 232

    base = gradient(SIZE, (86, 128, 255), (112, 78, 240)).convert("RGBA")
    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [margin, margin, SIZE - margin, SIZE - margin], radius=radius, fill=255
    )
    icon = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    icon.paste(base, (0, 0), mask)

    # 顶部高光
    glow = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([margin - 60, margin - 220, SIZE - margin + 60, 520], fill=(255, 255, 255, 46))
    glow = glow.filter(ImageFilter.GaussianBlur(90))
    icon = Image.alpha_composite(icon, Image.composite(glow, Image.new("RGBA", glow.size, (0, 0, 0, 0)), mask))

    # 芯片图形
    layer = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    cx, cy = SIZE // 2, SIZE // 2
    chip = 250
    d.rounded_rectangle(
        [cx - chip, cy - chip, cx + chip, cy + chip],
        radius=64,
        outline=(255, 255, 255, 245),
        width=30,
    )
    inner = 84
    d.rounded_rectangle(
        [cx - inner, cy - inner, cx + inner, cy + inner],
        radius=22,
        fill=(255, 255, 255, 240),
    )
    # 引脚
    pin_len = 58
    gap = 58
    for i in (-1, 0, 1):
        offset = i * gap * 1.55
        # 上下
        d.rounded_rectangle(
            [cx + offset - 13, cy - chip - pin_len, cx + offset + 13, cy - chip - 6],
            radius=10, fill=(255, 255, 255, 235),
        )
        d.rounded_rectangle(
            [cx + offset - 13, cy + chip + 6, cx + offset + 13, cy + chip + pin_len],
            radius=10, fill=(255, 255, 255, 235),
        )
        # 左右
        d.rounded_rectangle(
            [cx - chip - pin_len, cy + offset - 13, cx - chip - 6, cy + offset + 13],
            radius=10, fill=(255, 255, 255, 235),
        )
        d.rounded_rectangle(
            [cx + chip + 6, cy + offset - 13, cx + chip + pin_len, cy + offset + 13],
            radius=10, fill=(255, 255, 255, 235),
        )

    shadow = layer.filter(ImageFilter.GaussianBlur(18))
    shadow_alpha = shadow.split()[3].point(lambda a: int(a * 0.35))
    shadow.putalpha(shadow_alpha)
    icon = Image.alpha_composite(icon, shadow)
    icon = Image.alpha_composite(icon, layer)

    master = OUT / "icon_1024.png"
    icon.save(master)

    iconset = OUT / "AppIcon.iconset"
    iconset.mkdir(exist_ok=True)
    sizes = {
        "icon_16x16.png": 16,
        "icon_16x16@2x.png": 32,
        "icon_32x32.png": 32,
        "icon_32x32@2x.png": 64,
        "icon_128x128.png": 128,
        "icon_128x128@2x.png": 256,
        "icon_256x256.png": 256,
        "icon_256x256@2x.png": 512,
        "icon_512x512.png": 512,
        "icon_512x512@2x.png": 1024,
    }
    for name, px in sizes.items():
        icon.resize((px, px), Image.LANCZOS).save(iconset / name)

    icns = OUT / "AppIcon.icns"
    try:
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(icns)], check=True)
        print(f"icon: {icns}")
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"iconutil 失败（可忽略）: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
