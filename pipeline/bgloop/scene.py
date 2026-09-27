"""背景ループのシーン設定（切り抜きのヒントと動きの設定）を読み、座標を実際の画像の大きさに合わせる。

座標は scene の ref_size の画像での px で書く。別の大きさの画像（元の高解像度の PNG など）でも比率で合わせる。
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import yaml


class SceneError(Exception):
    pass


def load_scene(path: Path) -> dict:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SceneError(f"scene file not found: {path}") from None
    except yaml.YAMLError as e:
        raise SceneError(f"invalid YAML in {path}: {e}") from None
    if not isinstance(data, dict):
        raise SceneError(f"scene file must be a mapping: {path}")
    return data


class Scale:
    """ref_size の座標を、大きさ (W, H) の画像の座標に直す。"""

    def __init__(self, ref_size, size: tuple[int, int]):
        self.W, self.H = size
        rw, rh = ref_size or size
        self.sx, self.sy = self.W / rw, self.H / rh
        self.s = (self.sx + self.sy) / 2

    def pt(self, p) -> tuple[float, float]:
        return p[0] * self.sx, p[1] * self.sy

    def len(self, v: float) -> float:
        return v * self.s

    def rect(self, r) -> tuple[int, int, int, int]:
        x0, y0, x1, y1 = r
        return (int(np.clip(round(x0 * self.sx), 0, self.W)), int(np.clip(round(y0 * self.sy), 0, self.H)),
                int(np.clip(round(x1 * self.sx), 0, self.W)), int(np.clip(round(y1 * self.sy), 0, self.H)))

    def poly(self, pts) -> np.ndarray:
        return np.array([[round(x * self.sx), round(y * self.sy)] for x, y in pts], np.int32)

    def poly_mask(self, pts) -> np.ndarray:
        m = np.zeros((self.H, self.W), np.uint8)
        cv2.fillPoly(m, [self.poly(pts)], 1)
        return m > 0

    def rect_mask(self, r) -> np.ndarray:
        m = np.zeros((self.H, self.W), bool)
        x0, y0, x1, y1 = self.rect(r)
        m[y0:y1, x0:x1] = True
        return m

    def shapes_mask(self, shapes: dict | None) -> np.ndarray:
        """{rects: [[x0,y0,x1,y1]], polys: [[[x,y],...]], lines: [[x0,y0,x1,y1,width]], circles: [[x,y,r]]}"""
        m = np.zeros((self.H, self.W), np.uint8)
        shapes = shapes or {}
        for r in shapes.get("rects", []):
            x0, y0, x1, y1 = self.rect(r)
            m[y0:y1, x0:x1] = 1
        for p in shapes.get("polys", []):
            cv2.fillPoly(m, [self.poly(p)], 1)
        for x0, y0, x1, y1, w in shapes.get("lines", []):
            a, b = self.pt((x0, y0)), self.pt((x1, y1))
            cv2.line(m, (round(a[0]), round(a[1])), (round(b[0]), round(b[1])), 1, max(1, round(self.len(w))))
        for x, y, r in shapes.get("circles", []):
            c = self.pt((x, y))
            cv2.circle(m, (round(c[0]), round(c[1])), max(1, round(self.len(r))), 1, -1)
        return m > 0


def hue_in(h: np.ndarray, rng) -> np.ndarray:
    """色相の範囲（[lo, hi]、lo > hi なら 180 をまたぐ）。"""
    lo, hi = rng
    return (h >= lo) & (h <= hi) if lo <= hi else (h >= lo) | (h <= hi)
