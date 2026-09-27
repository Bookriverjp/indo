"""切り抜きの道具：ガイド付きフィルタ（輪郭に沿った柔らかいマスク）、穴埋め、色の分離。

色の二値判定のままだとヤシの葉や草の縁がギザギザになり、動かすと白い縁や穴が出る。
ここでは「ざっくりした判定 → 元の絵の輪郭に沿って柔らかくする → 背景の色を差し引いて前景の色を求める」
という合成の基本どおりに処理する。
"""
from __future__ import annotations

import cv2
import numpy as np


def box(x: np.ndarray, r: int) -> np.ndarray:
    return cv2.boxFilter(x, -1, (2 * r + 1, 2 * r + 1), normalize=True, borderType=cv2.BORDER_REFLECT)


def guided_filter(I: np.ndarray, p: np.ndarray, r: int, eps: float) -> np.ndarray:
    """カラーのガイド付きフィルタ（He et al.）。I: HxWx3 (0-1), p: HxW。p を I の輪郭に沿わせて柔らかくする。"""
    I = I.astype(np.float32)
    p = p.astype(np.float32)
    mI = box(I, r)
    mp = box(p, r)
    cov = box(I * p[..., None], r) - mI * mp[..., None]
    S = np.empty(I.shape[:2] + (3, 3), np.float32)
    for i in range(3):
        for j in range(i, 3):
            v = box(I[..., i] * I[..., j], r) - mI[..., i] * mI[..., j]
            S[..., i, j] = v
            S[..., j, i] = v
    S += np.float32(eps) * np.eye(3, dtype=np.float32)
    a = np.linalg.solve(S, cov[..., None])[..., 0]
    b = mp - (a * mI).sum(-1)
    return (box(a, r) * I).sum(-1) + box(b, r)


def soft_matte(I: np.ndarray, hard: np.ndarray, r: int = 2, eps: float = 1e-4) -> np.ndarray:
    return np.clip(guided_filter(I, hard.astype(np.float32), r, eps), 0.0, 1.0)


def pull_push(img: np.ndarray, w: np.ndarray, eps: float = 1e-6) -> np.ndarray:
    """w=0 の所を周りの色でなめらかに埋める（ピラミッドで粗い段から補う）。img: HxWxC, w: HxW (0-1)。"""
    img = img.astype(np.float32)
    w = np.clip(w.astype(np.float32), 0, 1)
    h, wd = w.shape
    if min(h, wd) <= 4:
        tot = float(w.sum())
        mean = (img * w[..., None]).sum((0, 1)) / tot if tot > 0 else img.mean((0, 1))
        return img * w[..., None] + mean * (1 - w[..., None])
    small = cv2.pyrDown(img * w[..., None])
    ws = cv2.pyrDown(w)
    if small.ndim == 2:
        small = small[..., None]
    coarse = pull_push(small / np.maximum(ws, eps)[..., None], np.clip(ws * 2.0, 0, 1))
    up = cv2.pyrUp(coarse, dstsize=(wd, h))
    if up.ndim == 2:
        up = up[..., None]
    return img * w[..., None] + up * (1 - w[..., None])


def quilt_fill(hf: np.ndarray, source: np.ndarray, need: np.ndarray, *, patch: int = 40, y_window: int = 160,
               x_window: int | None = None, seed: int = 0) -> np.ndarray:
    """need の所の細かい模様（hf）を、source の中から切り取った小片を重ねて作る。
    小片の継ぎ目は滑らかな窓でぼかし、分散を保つ重ね方にして模様のコントラストを落とさない。"""
    rng = np.random.default_rng(seed)
    H, W = source.shape
    if not need.any():
        return hf
    ii = cv2.integral(source.astype(np.uint8))
    ys, xs = np.mgrid[0:H - patch:4, 0:W - patch:4]
    xs, ys = xs.ravel(), ys.ravel()
    full = ii[ys + patch, xs + patch] - ii[ys, xs + patch] - ii[ys + patch, xs] + ii[ys, xs]
    ok = full >= 0.98 * patch * patch
    cand = np.stack([xs[ok], ys[ok]], 1)
    if len(cand) == 0:
        return hf
    win1 = np.sin(np.linspace(0, np.pi, patch, dtype=np.float32)) ** 2 + 1e-3
    win = np.outer(win1, win1)
    acc = np.zeros(hf.shape, np.float32)
    w2 = np.zeros((H, W), np.float32)
    ni = cv2.integral(need.astype(np.uint8))
    step = patch // 2
    for y in range(-step, H, step):
        for x in range(-step, W, step):
            x0, y0, x1, y1 = max(x, 0), max(y, 0), min(x + patch, W), min(y + patch, H)
            if x1 <= x0 or y1 <= y0 or ni[y1, x1] - ni[y0, x1] - ni[y1, x0] + ni[y0, x0] == 0:
                continue
            near = np.abs(cand[:, 1] - y) < y_window
            if x_window is not None:
                near &= np.abs(cand[:, 0] - x) < x_window
            pool = cand[near] if near.sum() > 20 else cand
            sx, sy = pool[rng.integers(len(pool))]
            oy, ox = y0 - y, x0 - x
            ww = win[oy:oy + y1 - y0, ox:ox + x1 - x0]
            src = hf[sy + oy:sy + oy + y1 - y0, sx + ox:sx + ox + x1 - x0]
            acc[y0:y1, x0:x1] += src * (ww[..., None] if hf.ndim == 3 else ww)
            w2[y0:y1, x0:x1] += ww * ww
    synth = acc / (np.sqrt(np.maximum(w2, 1e-8))[..., None] if hf.ndim == 3 else np.sqrt(np.maximum(w2, 1e-8)))
    out = hf.copy()
    m = need & (w2 > 0)
    out[m] = synth[m]
    return out


def fill_plate(I: np.ndarray, known: np.ndarray, *, patch: int = 40, sigma: float = 12.0, y_window: int = 160,
               x_window: int | None = None, source: np.ndarray | None = None, seed: int = 0) -> np.ndarray:
    """known 以外を埋めた「きれいな背景板」。大まかな色はなめらかに、細かい筆の模様は周りから写して作る。"""
    kf = known.astype(np.float32)
    num = cv2.GaussianBlur(I * kf[..., None], (0, 0), sigma)
    den = cv2.GaussianBlur(kf, (0, 0), sigma)
    low = num / np.maximum(den, 1e-4)[..., None]
    low = pull_push(low, np.clip(den * 2.0 - 0.2, 0, 1) * kf)
    hf = (I - low) * kf[..., None]
    src = known if source is None else (source & known)
    hf = quilt_fill(hf, src, ~known, patch=patch, y_window=y_window, x_window=x_window, seed=seed)
    return np.clip(low + hf, 0.0, 1.0)


def fill_rows(I: np.ndarray, need: np.ndarray, source: np.ndarray, *, offsets, sigma: float = 5.0,
              rounds: int = 4) -> np.ndarray:
    """need の所を、同じ行の左右（source の所）から写して埋める。水面の横長の筋がそのまま続く。
    大まかな色は source からなめらかに補い、細かい模様だけを横にずらして写す。"""
    kf = source.astype(np.float32)
    num = cv2.GaussianBlur(I * kf[..., None], (0, 0), sigma)
    den = cv2.GaussianBlur(kf, (0, 0), sigma)
    low = pull_push(num / np.maximum(den, 1e-4)[..., None], np.clip(den * 2.0 - 0.2, 0, 1) * kf)
    hf = (I - low) * kf[..., None]
    have = source.copy()
    W = have.shape[1]
    order = [d for s in offsets for d in (int(s), -int(s)) if 0 < abs(d) < W]
    for _ in range(rounds):
        if not (need & ~have).any():
            break
        for d in order:
            todo = need & ~have
            if not todo.any():
                break
            src_have = np.zeros_like(have)
            src_hf = np.zeros_like(hf)
            if d > 0:
                src_have[:, :W - d] = have[:, d:]
                src_hf[:, :W - d] = hf[:, d:]
            else:
                src_have[:, -d:] = have[:, :W + d]
                src_hf[:, -d:] = hf[:, :W + d]
            m = todo & src_have
            hf[m] = src_hf[m]
            have |= m
    return np.clip(low + hf, 0.0, 1.0)


def unmix(I: np.ndarray, alpha: np.ndarray, B: np.ndarray, amin: float = 0.05) -> np.ndarray:
    """I = a*F + (1-a)*B から前景の色 F を求める。縁に元の背景の色が残らないので、動かしても色のにじみが出ない。"""
    a = np.clip(alpha, amin, 1.0)[..., None]
    return np.clip((I - (1 - a) * B) / a, 0.0, 1.0)


def remove_small(mask: np.ndarray, min_area: int, connectivity: int = 8) -> np.ndarray:
    n, lab, st, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=connectivity)
    keep = st[:, cv2.CC_STAT_AREA] >= min_area
    keep[0] = False
    return keep[lab]


def fill_holes(mask: np.ndarray, max_area: int, ok=None) -> np.ndarray:
    """mask の中の小さな穴（画像の縁に触れないもの）を埋める。ok(label_mask_stats) で条件を足せる。"""
    inv = (~mask).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(inv, connectivity=4)
    H, W = mask.shape
    x, y, w, h, area = st[:, 0], st[:, 1], st[:, 2], st[:, 3], st[:, 4]
    inner = (x > 0) & (y > 0) & (x + w < W) & (y + h < H) & (area <= max_area)
    inner[0] = False
    if ok is not None:
        inner &= ok(lab, n)
    return mask | inner[lab]


def rgb_to_hsv(I: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """OpenCV の HSV（H: 0-180, S/V: 0-255）を int32 で返す。"""
    hsv = cv2.cvtColor((np.clip(I, 0, 1) * 255).astype(np.uint8), cv2.COLOR_RGB2HSV).astype(np.int32)
    return hsv[..., 0], hsv[..., 1], hsv[..., 2]


def luminance(I: np.ndarray) -> np.ndarray:
    return I @ np.array([0.299, 0.587, 0.114], np.float32)


def imread(path) -> np.ndarray:
    """PNG をそのままの型（8bit / 16bit、チャンネル数）で読む。Windows の日本語のパスでも読めるよう imdecode を使う。"""
    data = np.fromfile(str(path), np.uint8)
    im = cv2.imdecode(data, cv2.IMREAD_UNCHANGED) if data.size else None
    if im is None:
        raise FileNotFoundError(path)
    return im


def imwrite(path, arr: np.ndarray) -> None:
    ok, buf = cv2.imencode(".png", arr)
    if not ok:
        raise OSError(f"cannot encode {path}")
    buf.tofile(str(path))
