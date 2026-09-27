"""動きの部品。すべての動きをループの長さ L で割り切れる周期（L/n）で作るので、最後のコマから最初のコマへ
継ぎ目なくつながる。

変位場は「前もって作った空間の形 B(x, y) × 時間だけの関数 s(t)」の和で表す（sin(kx - ωt) も
sin kx cos ωt - cos kx sin ωt と分けられる）。1コマごとの計算は掛け算と足し算だけになり速い。
"""
from __future__ import annotations

import math
from typing import Callable

import cv2
import numpy as np

TAU = 2.0 * math.pi


def smoothstep(e0: float, e1: float, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


class Wind:
    """風の強さ（おおむね -1〜1）。倍音の和。x での値は、風の波が速さ speed で画面を渡る分だけ遅れる。"""

    def __init__(self, L: float, rng: np.random.Generator, speed: float = 520.0,
                 harmonics=((1, 0.30), (2, 0.55), (3, 0.40), (5, 0.22), (7, 0.12))):
        self.L = L
        self.speed = speed
        self.comps = [(n, a, float(rng.uniform(0, TAU))) for n, a in harmonics]
        norm = sum(a for _, a, _ in self.comps)
        self.comps = [(n, a / norm * 1.6, p) for n, a, p in self.comps]

    def at(self, t: float, x: float = 0.0) -> float:
        tt = t - x / self.speed
        return sum(a * math.sin(TAU * n * tt / self.L + p) for n, a, p in self.comps)

    def traveling(self, weight: np.ndarray, x: np.ndarray) -> list[tuple[np.ndarray, Callable]]:
        """weight(x, y) * at(t, x) を、空間の形 × 時間の関数 の組に分ける。"""
        terms = []
        for n, a, p in self.comps:
            w = TAU * n / self.L
            k = w / self.speed
            c, s = np.cos(k * x).astype(np.float32), np.sin(k * x).astype(np.float32)
            # sin(w t - k x + p) = sin(w t + p) cos(k x) - cos(w t + p) sin(k x)
            terms.append((weight * c, lambda t, w=w, p=p, a=a: a * math.sin(w * t + p)))
            terms.append((-weight * s, lambda t, w=w, p=p, a=a: a * math.cos(w * t + p)))
        return terms


class FieldBank:
    """変位場 (dx, dy) = Σ (Bx_k, By_k) * s_k(t)。"""

    def __init__(self, shape: tuple[int, int]):
        self.shape = shape
        self.terms: list[tuple[np.ndarray | None, np.ndarray | None, Callable]] = []

    def add(self, bx: np.ndarray | None, by: np.ndarray | None, fn: Callable[[float], float]) -> None:
        self.terms.append((None if bx is None else bx.astype(np.float32),
                           None if by is None else by.astype(np.float32), fn))

    def eval(self, t: float) -> tuple[np.ndarray, np.ndarray]:
        dx = np.zeros(self.shape, np.float32)
        dy = np.zeros(self.shape, np.float32)
        for bx, by, fn in self.terms:
            s = np.float32(fn(t))
            if s == 0:
                continue
            if bx is not None:
                dx += bx * s
            if by is not None:
                dy += by * s
        return dx, dy


def smooth_noise(shape: tuple[int, int], sigma: float | tuple[float, float], rng: np.random.Generator) -> np.ndarray:
    """ぼかした乱数（平均0・標準偏差1）。"""
    n = rng.standard_normal(shape).astype(np.float32)
    sx, sy = (sigma, sigma) if np.isscalar(sigma) else sigma
    n = cv2.GaussianBlur(n, (0, 0), sigmaX=sx, sigmaY=sy)
    return (n - n.mean()) / (n.std() + 1e-6)


def flutter_terms(weight: np.ndarray, L: float, rng: np.random.Generator, sigma: float,
                  harmonics=(9, 13)) -> list[tuple[np.ndarray, np.ndarray, Callable]]:
    """葉のざわめき：場所ごとに位相のちがう小さな揺れ。"""
    terms = []
    for n in harmonics:
        w = TAU * n / L
        for fn in (lambda t, w=w: math.sin(w * t), lambda t, w=w: math.cos(w * t)):
            bx = weight * smooth_noise(weight.shape, sigma, rng) * 0.5
            by = weight * smooth_noise(weight.shape, sigma, rng) * 0.35
            terms.append((bx, by, fn))
    return terms


def two_phase(t: float, period: float) -> tuple[float, float, float, float]:
    """流れの2相：(相Aのずれ, 相Bのずれ, 相Aの重み, 相Bの重み)。ずれは -0.5〜0.5（×速さ×周期で px）。
    それぞれの相は重みが 0 の瞬間に巻き戻るので、ずっと流れ続けて見える。"""
    fa = (t / period) % 1.0
    fb = (fa + 0.5) % 1.0
    wa = 1.0 - abs(2.0 * fa - 1.0)
    return fa - 0.5, fb - 0.5, wa, 1.0 - wa


class Pulse:
    """周期 L/n の なめらかな点滅（0〜1）。蛍・星のまたたき用。"""

    def __init__(self, L: float, n: int, phase: float, sharp: float = 6.0):
        self.w = TAU * n / L
        self.phase = phase
        self.sharp = sharp

    def __call__(self, t: float) -> float:
        return (0.5 + 0.5 * math.sin(self.w * t + self.phase)) ** self.sharp
