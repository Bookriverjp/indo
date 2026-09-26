"""大仏飴（最小セットのパーツ）を、瞬き・口パク・呼吸・体全体の動き付きで描く。"""
from __future__ import annotations

import math
import random
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw

from pipeline.images.parts import content_bbox, fit_full_body

PARTS = ("body_base", "eyes_open", "eyes_closed", "mouth_open", "mouth_closed")


def blink_frames(*, total_seconds: float, fps: int, cfg: dict, seed: str) -> set[int]:
    """瞬きするコマ。seed が同じなら毎回同じ（作り直しても同じ動画になる）。"""
    rng = random.Random(seed)
    lo, hi = cfg["interval"]
    length = max(1, round(cfg["seconds"] * fps))
    frames: set[int] = set()
    t = rng.uniform(lo, hi)
    while t < total_seconds:
        starts = [t] + ([t + cfg["seconds"] + 0.12] if rng.random() < cfg["double_probability"] else [])
        for s in starts:
            f = int(s * fps)
            frames.update(range(f, f + length))
        t += rng.uniform(lo, hi)
    return frames


def _motion(name: str | None, t: float) -> tuple[float, float, float, float]:
    """(dx, dy, 回転角, 拡大率)。dx, dy は 1254px の元画像での px。"""
    two_pi = 2 * math.pi
    if name == "tremble":
        return 6 * math.sin(two_pi * 12 * t), 0, 0, 1
    if name == "bounce":
        return 0, -abs(math.sin(two_pi * 2 * t)) * 30, 0, 1
    if name == "jump":
        return 0, -abs(math.sin(two_pi * 1.1 * t)) * 70, 0, 1
    if name == "hop":
        return 0, -max(0.0, math.sin(two_pi * 0.8 * t)) * 50, 0, 1
    if name == "tilt":
        return 0, 0, 6 * math.sin(min(t, 1.0) * math.pi / 2), 1
    if name == "nod":
        return 0, 15 * abs(math.sin(two_pi * 1.5 * t)), 0, 1
    if name == "shake":
        return 0, 0, 4 * math.sin(two_pi * 2 * t), 1
    if name == "sway":
        return 0, 10 * abs(math.sin(two_pi * 0.35 * t)), 5 * math.sin(two_pi * 0.35 * t), 1
    if name == "roll":
        return 0, 0, 20 * math.sin(two_pi * 0.9 * t), 1
    if name == "popcorn":
        return 0, -abs(math.sin(two_pi * 0.8 * t)) * 100, 15 * math.sin(two_pi * 1.6 * t), 1
    if name == "jitter":
        return 5 * math.sin(two_pi * 9 * t), 5 * math.cos(two_pi * 7 * t), 0, 1
    if name == "shrink":
        return 0, 0, 0, 0.95
    if name == "bow_small":
        return 0, 20 * math.sin(min(t, 1.0) * math.pi), 0, 1
    if name == "bow":
        return 0, 50 * math.sin(min(t, 1.2) / 1.2 * math.pi), 0, 1
    return 0, 0, 0, 1


class NarratorRig:
    def __init__(self, parts_dir: Path, cfg: dict):
        self.cfg = cfg
        self.parts = {}
        for name in PARTS:
            with Image.open(parts_dir / f"{name}.png") as im:
                self.parts[name] = im.convert("RGBA")
        self.size = self.parts["body_base"].size
        self.bbox = content_bbox(self.parts["body_base"])   # 全身は余白を切り詰めて枠に収める

    @lru_cache(maxsize=32)
    def _face(self, eyes_closed: bool, mouth_open: bool) -> Image.Image:
        img = self.parts["body_base"].copy()
        img.alpha_composite(self.parts["eyes_closed" if eyes_closed else "eyes_open"])
        img.alpha_composite(self.parts["mouth_open" if mouth_open else "mouth_closed"])
        return img

    @lru_cache(maxsize=64)
    def _scaled(self, eyes_closed: bool, mouth_open: bool, box: tuple[int, int]) -> tuple[Image.Image, float, int, int]:
        k, x, y = fit_full_body(self.size, self.bbox, box)
        img = self._face(eyes_closed, mouth_open).crop(self.bbox)
        return img.resize((max(1, round(img.width * k)), max(1, round(img.height * k))), Image.LANCZOS), k, x, y

    def render(self, box: tuple[int, int], style: str, *, t: float, expression: str,
               eyes_closed: bool, mouth_open: bool) -> Image.Image:
        """box の大きさの透明画像に大仏飴を描く。style は full_body か medallion。"""
        bw, bh = box
        eyes_closed = eyes_closed or expression in self.cfg["eyes_closed_expressions"]
        dx, dy, angle, scale = _motion(self.cfg["expression_motion"].get(expression), t)
        breath = 1 + self.cfg["breath"]["amplitude"] * math.sin(2 * math.pi * t / self.cfg["breath"]["period"])

        if style == "medallion":
            x0, y0, x1, y1 = self.cfg["medallion_crop"]
            w, h = self.size
            crop = self._face(eyes_closed, mouth_open).crop((int(x0 * w), int(y0 * h), int(x1 * w), int(y1 * h)))
            k = max(bw / crop.width, bh / crop.height)
            crop = crop.resize((max(1, round(crop.width * k)), max(1, round(crop.height * k))), Image.LANCZOS)
            face = Image.new("RGBA", box, (244, 235, 214, 255))
            face.alpha_composite(crop, ((bw - crop.width) // 2, (bh - crop.height) // 2 + round(dy * k * 0.3)))
            mask = Image.new("L", box, 0)
            ImageDraw.Draw(mask).ellipse((0, 0, bw - 1, bh - 1), fill=255)
            out = Image.new("RGBA", box, (0, 0, 0, 0))
            out.paste(face, (0, 0), mask)
            border = max(2, round(min(box) * 0.03))
            ImageDraw.Draw(out).ellipse((0, 0, bw - 1, bh - 1), outline=(199, 154, 58, 255), width=border)
            return out

        img, k, _, _ = self._scaled(eyes_closed, mouth_open, (bw, bh))
        sw, sh = max(1, round(img.width * scale)), max(1, round(img.height * scale * breath))
        if (sw, sh) != img.size:
            img = img.resize((sw, sh), Image.BILINEAR)
        out = Image.new("RGBA", box, (0, 0, 0, 0))
        x = (bw - sw) // 2 + round(dx * k)
        y = bh - sh + round(dy * k)
        out.paste(img, (x, y), img)
        if angle:
            out = out.rotate(angle, resample=Image.BICUBIC, center=(bw / 2, bh))
        return out
