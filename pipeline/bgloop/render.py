"""背景ループの「動かす」段：切り抜いた層を、ループの長さで割り切れる動きで重ねて MP4 に書き出す。

重ねる順（奥から）：空（星のまたたき・月の光）→ 雲（漂い・形のうねり）→ 陸（風・水の流れと波・
映り込みのきらめき・灯りのゆらぎ・蓮と舟の上下）→ 川霧・灯りの光・蛍・花びら → 手前の草（風）→ 手前のボケ → 光のにじみ。
カメラはゆっくり楕円を描き、奥行きごとにずれ方を変えてパララックスを出す。
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from pipeline.bgloop.matte import imread
from pipeline.bgloop.motion import TAU, FieldBank, Pulse, Wind, flutter_terms, smooth_noise, smoothstep, two_phase
from pipeline.bgloop.scene import Scale


def _rgba(path: Path) -> np.ndarray:
    with Image.open(path) as im:
        return np.asarray(im.convert("RGBA"), np.float32) / 255.0


def _gray(path: Path) -> np.ndarray:
    im = imread(path)
    return im.astype(np.float32) / (65535.0 if im.dtype == np.uint16 else 255.0)


def _labels(path: Path) -> np.ndarray:
    return imread(path).astype(np.int32)


def _premul(rgba: np.ndarray) -> np.ndarray:
    out = rgba.copy()
    out[..., :3] *= out[..., 3:4]
    return out


def _clip_premul(rgba: np.ndarray) -> np.ndarray:
    """乗算済み RGBA を正しい範囲（0 ≤ 色 ≤ 不透明度 ≤ 1）に収める（その場で書き換える）。"""
    a = rgba[..., 3:4]
    np.clip(a, 0.0, 1.0, out=a)
    rgb = rgba[..., :3]
    np.maximum(rgb, 0.0, out=rgb)
    np.minimum(rgb, a, out=rgb)
    return rgba


class Geometry:
    """元の絵 → 作業用の少し大きな絵（canvas、カメラが動いても縁が出ない余白つき）→ 出力 の座標。"""

    def __init__(self, src_size: tuple[int, int], out_size: tuple[int, int], overscan: float):
        Ws, Hs = src_size
        self.Wo, self.Ho = out_size
        self.Wc, self.Hc = round(self.Wo * overscan), round(self.Ho * overscan)
        self.scale = max(self.Wc / Ws, self.Hc / Hs)
        self.cx0 = (Ws * self.scale - self.Wc) / 2
        self.cy0 = (Hs * self.scale - self.Hc) / 2
        self.ox = (self.Wc - self.Wo) / 2
        self.oy = (self.Hc - self.Ho) / 2
        self.u = self.Wo / 1920.0       # 動きの大きさは 1920 幅での px で書く

    def canvas(self, img: np.ndarray, interp=cv2.INTER_LANCZOS4) -> np.ndarray:
        M = np.float32([[self.scale, 0, -self.cx0], [0, self.scale, -self.cy0]])
        out = cv2.warpAffine(img, M, (self.Wc, self.Hc), flags=interp, borderMode=cv2.BORDER_REFLECT)
        return np.clip(out, 0, None) if interp in (cv2.INTER_CUBIC, cv2.INTER_LANCZOS4) else out

    def canvas_rgba(self, rgba: np.ndarray) -> np.ndarray:
        """RGBA を乗算済みにしてから拡大する（透明な所の色が縁ににじまない）。"""
        out = self.canvas(_premul(rgba))
        return _clip_premul(out)

    def out_view(self, canvas_img: np.ndarray, interp=cv2.INTER_LINEAR) -> np.ndarray:
        """canvas の配列を、出力の画素の位置で切り出す（カメラが止まっているとき）。"""
        M = np.float32([[1, 0, self.ox], [0, 1, self.oy]])
        return cv2.warpAffine(canvas_img, M, (self.Wo, self.Ho), flags=interp | cv2.WARP_INVERSE_MAP,
                              borderMode=cv2.BORDER_REFLECT)

    def src_to_out(self, x: float, y: float) -> tuple[float, float]:
        return x * self.scale - self.cx0 - self.ox, y * self.scale - self.cy0 - self.oy

    def src_to_canvas(self, x: float, y: float) -> tuple[float, float]:
        return x * self.scale - self.cx0, y * self.scale - self.cy0


class LoopRenderer:
    def __init__(self, cut_dir: Path, scene: dict, *, seconds: float, fps: int, size: tuple[int, int],
                 overscan: float = 1.04, seed: int = 7):
        self.cut_dir = Path(cut_dir)
        meta = json.loads((self.cut_dir / "cut.json").read_text(encoding="utf-8"))
        self.meta = meta
        self.scene = scene
        Ws, Hs = meta["size"]
        self.sc = Scale(scene.get("ref_size"), (Ws, Hs))
        self.g = Geometry((Ws, Hs), size, overscan)
        self.L = float(seconds)
        self.fps = fps
        self.N = int(round(seconds * fps))
        self.rng = np.random.default_rng(seed)
        self.mo = scene.get("motion", {})
        self.fx = scene.get("fx", {})
        self.depth_cfg = scene.get("depth", {})
        g = self.g
        u = g.u
        self.wind = Wind(self.L, self.rng, speed=self.mo.get("wind", {}).get("speed", 520) * u)
        cam = self.mo.get("camera", {})
        self.cam_shift = [v * u for v in cam.get("shift", [12, 4])]
        self.cam_zoom = cam.get("zoom", 0.008)

        # 半分の解像度の格子（変位場用）
        self.hw, self.hh = (g.Wo + 1) // 2, (g.Ho + 1) // 2
        hx, hy = np.meshgrid(np.arange(self.hw, dtype=np.float32) * 2 + 0.5, np.arange(self.hh, dtype=np.float32) * 2 + 0.5)
        self.HX, self.HY = hx, hy
        ox, oy = np.meshgrid(np.arange(g.Wo, dtype=np.float32), np.arange(g.Ho, dtype=np.float32))
        self.OX, self.OY = ox, oy

        self._init_sky()
        self._init_clouds()
        self._init_land()
        self._init_foreground()
        self._init_fx()

    # --- 座標の道具 -----------------------------------------------------------------------

    def P(self, p) -> tuple[float, float]:
        """シーンの座標（ref_size）→ 出力の座標。"""
        return self.g.src_to_out(*self.sc.pt(p))

    def Lsrc(self, v: float) -> float:
        return self.sc.len(v) * self.g.scale

    def half(self, out_img: np.ndarray, interp=cv2.INTER_AREA) -> np.ndarray:
        return cv2.resize(out_img, (self.hw, self.hh), interpolation=interp)

    def poly_out_half(self, pts, blur: float = 0.0) -> np.ndarray:
        m = np.zeros((self.hh, self.hw), np.uint8)
        q = np.array([[(x - 0.5) / 2, (y - 0.5) / 2] for x, y in (self.P(p) for p in pts)], np.float32)
        cv2.fillPoly(m, [np.round(q).astype(np.int32)], 1)
        m = m.astype(np.float32)
        return cv2.GaussianBlur(m, (0, 0), blur / 2) if blur > 0 else m

    def cam(self, t: float) -> tuple[float, float, float]:
        a = TAU * t / self.L
        return (self.cam_shift[0] * math.sin(a), self.cam_shift[1] * math.sin(2 * a + 1.0),
                self.cam_zoom * (0.5 - 0.5 * math.cos(a)))

    def depth_shift(self, d: float, x: float, y: float, t: float) -> tuple[float, float]:
        cx, cy, z = self.cam(t)
        return d * (cx + z * (x - self.g.Wo / 2)), d * (cy + z * (y - self.g.Ho / 2))

    def _parallax_terms(self, bank: FieldBank, depth: np.ndarray) -> None:
        bank.add(depth, None, lambda t: self.cam(t)[0])
        bank.add(None, depth, lambda t: self.cam(t)[1])
        bank.add(depth * (self.HX - self.g.Wo / 2), depth * (self.HY - self.g.Ho / 2), lambda t: self.cam(t)[2])

    # --- 空 -------------------------------------------------------------------------------

    def _init_sky(self) -> None:
        g, u = self.g, self.g.u
        self.plate = np.clip(g.canvas(_rgba(self.cut_dir / "sky_plate.png")[..., :3]), 0, 1)
        land_a = g.canvas(_rgba(self.cut_dir / "land.png")[..., 3], cv2.INTER_LINEAR)
        rows = np.nonzero((land_a < 0.995).any(1))[0]
        self.sky_rows = int(min(g.Hc, (rows.max() if rows.size else 0) + 60 * u + 20))
        self.sky_buf = self.plate.copy()
        self.d_sky = self.depth_cfg.get("sky", 0.04)

        # 星：ひとつずつ、周期 L/n でまたたく
        stars = g.canvas(_gray(self.cut_dir / "stars.png"), cv2.INTER_LINEAR)[: self.sky_rows] > 0.25
        stars = cv2.dilate(stars.astype(np.uint8), np.ones((3, 3), np.uint8))
        n, lab, st, cen = cv2.connectedComponentsWithStats(stars, 8)
        tw = self.mo.get("stars", {}).get("twinkle", 0.45)
        self.star_idx = np.flatnonzero(lab > 0)
        self.star_lab = lab.ravel()[self.star_idx]
        self.star_params = [(int(self.rng.integers(2, 10)), float(self.rng.uniform(0, TAU)),
                             float(self.rng.uniform(0.4, 1.0) * tw)) for _ in range(n)]
        # 明るい星には十字の光
        order = np.argsort(-st[1:, cv2.CC_STAT_AREA]) + 1 if n > 1 else []
        self.flares = [(float(cen[i][0]), float(cen[i][1]), i) for i in list(order)[:14]]
        self.flare_sprite = self._flare_sprite(int(round(22 * u)) | 1)

        # 月の光
        moon = self.meta["moon"]
        self.moon_glow = None
        if moon["r"] > 0:
            mx, my = g.src_to_canvas(moon["x"], moon["y"])
            r = moon["r"] * g.scale
            R = int(r * 5)
            x0, y0 = int(max(0, mx - R)), int(max(0, my - R))
            x1, y1 = int(min(g.Wc, mx + R)), int(min(self.sky_rows, my + R))
            yy, xx = np.mgrid[y0:y1, x0:x1].astype(np.float32)
            d = np.hypot(xx - mx, yy - my) / r
            glow = np.exp(-np.maximum(d - 1.0, 0) ** 2 / 1.8) * 0.5 + np.exp(-np.maximum(d - 1.0, 0) / 1.6) * 0.5
            glow *= d > 0.6
            self.moon_glow = ((y0, y1, x0, x1), glow[..., None] * np.array([1.0, 0.93, 0.72], np.float32))
        self.moon_amp = self.mo.get("moon", {}).get("glow", 0.06)

    @staticmethod
    def _flare_sprite(size: int) -> np.ndarray:
        c = size // 2
        yy, xx = np.mgrid[0:size, 0:size].astype(np.float32) - c
        r = np.hypot(xx, yy) + 1e-3
        rays = np.exp(-np.abs(yy) / 0.9) * np.exp(-np.abs(xx) / (size * 0.22)) + \
            np.exp(-np.abs(xx) / 0.9) * np.exp(-np.abs(yy) / (size * 0.22))
        core = np.exp(-(r / 1.6) ** 2)
        s = np.clip(rays * 0.55 + core, 0, 1)
        return s[..., None] * np.array([1.0, 0.95, 0.8], np.float32)

    def _sky(self, t: float) -> np.ndarray:
        buf = self.sky_buf
        R = self.sky_rows
        np.copyto(buf, self.plate)
        view = buf[:R].reshape(-1, 3)
        if self.star_idx.size:
            lut = np.ones(len(self.star_params), np.float32)
            for k, (n, ph, amp) in enumerate(self.star_params):
                if k:
                    lut[k] = 1.0 + amp * math.sin(TAU * n * t / self.L + ph)
            view[self.star_idx] *= lut[self.star_lab][:, None]
            fs = self.flare_sprite
            h = fs.shape[0] // 2
            for x, y, k in self.flares:
                n, ph, amp = self.star_params[k]
                a = max(0.0, math.sin(TAU * n * t / self.L + ph)) ** 3 * 0.7
                xi, yi = int(round(x)), int(round(y))
                if a <= 0.01 or yi - h < 0 or xi - h < 0 or yi + h + 1 > R or xi + h + 1 > self.g.Wc:
                    continue
                buf[yi - h:yi + h + 1, xi - h:xi + h + 1] += fs * a
        if self.moon_glow is not None:
            (y0, y1, x0, x1), glow = self.moon_glow
            buf[y0:y1, x0:x1] += glow * (self.moon_amp * math.sin(TAU * 2 * t / self.L))
        self._clouds(t, buf)
        if self.sky_mists:
            self._mist(buf, t, self.sky_mists)
        return self._warp_layer(buf, self.d_sky, t)

    def _warp_layer(self, img: np.ndarray, d: float, t: float) -> np.ndarray:
        """ひとつの奥行き d の層をカメラに合わせて出力へ（平行移動と拡大だけ）。"""
        cx, cy, z = self.cam(t)
        a = 1.0 - d * z
        g = self.g
        # 出力 p ← canvas: a*p + b
        bx = g.ox - d * cx + d * z * g.Wo / 2
        by = g.oy - d * cy + d * z * g.Ho / 2
        M = np.float32([[a, 0, bx], [0, a, by]])
        return cv2.warpAffine(img, M, (g.Wo, g.Ho), flags=cv2.INTER_CUBIC | cv2.WARP_INVERSE_MAP,
                              borderMode=cv2.BORDER_REFLECT)

    # --- 雲 -------------------------------------------------------------------------------

    def _init_clouds(self) -> None:
        """雲は ゆっくり左右に漂い（風の向きに少し進んで戻る）、形は大きくゆるやかにうねる。
        ループの長さで元の位置に戻るので、入れ替え（消えて現れる）をしない。"""
        g, u = self.g, self.g.u
        cc = self.mo.get("clouds", {})
        self.cloud_amp = cc.get("drift", 8.0) * u         # 左右に漂う幅（片側、出力 px）
        billow = cc.get("billow", 1.6) * u                # 形のうねり（出力 px）
        # 画面の端で切れている雲の切り口が見えないよう、ずれは余白（overscan）の中に収める
        if self.cloud_amp > 0.8 * g.ox:
            self.cloud_amp = 0.8 * g.ox
        clouds = g.canvas_rgba(_rgba(self.cut_dir / "clouds.png"))
        lab = g.canvas(_labels(self.cut_dir / "cloud_sprites.png").astype(np.float32), cv2.INTER_NEAREST).astype(np.int32)
        margin = int(self.cloud_amp * 1.3 + billow * 3 + 12 * u)
        dmin, dmax = self.depth_cfg.get("clouds", [0.07, 0.13])
        base_phase = float(self.rng.uniform(0, TAU))
        self.sprites = []
        for sp in self.meta.get("sprites", []):
            m = lab == sp["id"]
            if not m.any():
                continue
            ys, xs = np.nonzero(m)
            x0, x1 = max(0, xs.min() - margin), min(g.Wc, xs.max() + 1 + margin)
            y0, y1 = max(0, ys.min() - margin // 2), min(g.Hc, ys.max() + 1 + margin // 2)
            crop = clouds[y0:y1, x0:x1] * m[y0:y1, x0:x1, None]
            shape = crop.shape[:2]
            bank = FieldBank(shape)
            for n, k in ((1, 1.0), (2, 0.55)):
                w = TAU * n / self.L
                for fn in (lambda t, w=w: math.sin(w * t), lambda t, w=w: math.cos(w * t)):
                    bank.add(smooth_noise(shape, 45 * u, self.rng) * billow * k,
                             smooth_noise(shape, 45 * u, self.rng) * billow * k * 0.5, fn)
            gx, gy = np.meshgrid(np.arange(x1 - x0, dtype=np.float32), np.arange(y1 - y0, dtype=np.float32))
            cy = ys.mean() / g.Hc
            depth = dmax + (dmin - dmax) * np.clip((cy - 0.1) / 0.35, 0, 1)
            self.sprites.append({"box": (y0, y1, x0, x1), "rgba": crop, "bank": bank, "grid": (gx, gy),
                                 "depth": float(depth), "amp": self.cloud_amp * float(depth / dmax),
                                 "phase": base_phase + float(self.rng.uniform(-0.3, 0.3))})

    def _clouds(self, t: float, buf: np.ndarray) -> None:
        cx, cy, _ = self.cam(t)
        for sp in self.sprites:
            dx = sp["amp"] * math.sin(TAU * t / self.L + sp["phase"]) + (sp["depth"] - self.d_sky) * cx
            dy = (sp["depth"] - self.d_sky) * cy
            fx, fy = sp["bank"].eval(t)
            gx, gy = sp["grid"]
            moved = cv2.remap(sp["rgba"], gx - dx - fx, gy - dy - fy, cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT)
            self._over(buf, sp, _clip_premul(moved))

    @staticmethod
    def _over(buf: np.ndarray, sp: dict, moved: np.ndarray) -> None:
        y0, y1, x0, x1 = sp["box"]
        y1c = min(y1, buf.shape[0])
        moved = moved[: y1c - y0]
        region = buf[y0:y1c, x0:x1]
        region *= 1.0 - moved[..., 3:4]
        region += moved[..., :3]

    # --- 陸（木・水・灯り）---------------------------------------------------------------

    def _init_land(self) -> None:
        g, u = self.g, self.g.u
        self.land = g.canvas_rgba(_rgba(self.cut_dir / "land.png"))
        self.land_work = self.land.copy()
        water_c = g.canvas(_gray(self.cut_dir / "water.png"), cv2.INTER_LINEAR)
        reflect_c = g.canvas(_gray(self.cut_dir / "reflect.png"), cv2.INTER_LINEAR)
        depth_c = g.canvas(_gray(self.cut_dir / "depth.png"), cv2.INTER_LINEAR)
        boat_c = g.canvas(_gray(self.cut_dir / "boat.png"), cv2.INTER_LINEAR)
        floaters_c = g.canvas(_labels(self.cut_dir / "floaters.png").astype(np.float32), cv2.INTER_NEAREST).astype(np.int32)

        H = lambda img, interp=cv2.INTER_AREA: self.half(g.out_view(img), interp)
        water = np.clip(H(water_c), 0, 1)
        depth = H(depth_c)
        mo = self.mo
        bank = FieldBank((self.hh, self.hw))
        self._parallax_terms(bank, depth)
        flutter_w = np.zeros((self.hh, self.hw), np.float32)
        # 家・柵・灯籠は風で揺らさない
        protect = np.zeros((self.hh, self.hw), np.float32)
        for poly in mo.get("protect", []):
            protect = np.maximum(protect, self.poly_out_half(poly))
        keep = (1.0 - np.clip(cv2.GaussianBlur(protect, (0, 0), 3 * u) * 1.6, 0, 1)).astype(np.float32)
        sway = FieldBank((self.hh, self.hw))

        # 風で揺れる物
        for rig in mo.get("sway", []):
            amp = rig.get("amp", 0.0) * u
            if "top" in rig and "base" in rig:
                bx, by = self.P(rig["base"])
                tx, ty = self.P(rig["top"])
                R = self.Lsrc(rig.get("radius", 60))
                Lp = max(math.hypot(tx - bx, ty - by), 1.0)
                dc = np.hypot(self.HX - tx, self.HY - ty)
                crown = smoothstep(1.25 * R, 0.5 * R, dc)
                ex, ey = (tx - bx) / Lp, (ty - by) / Lp
                proj = ((self.HX - bx) * ex + (self.HY - by) * ey) / Lp
                perp = np.abs((self.HX - bx) * ey - (self.HY - by) * ex)
                trunk = smoothstep(0.3 * R, 0.08 * R, perp) * (proj > -0.02)
                h = np.clip(proj, 0, 1.3)
                w = np.maximum(crown, trunk * h ** 1.5).astype(np.float32)
                sway.add(w * (-(self.HY - by)) / Lp * amp, w * (self.HX - bx) / Lp * amp * 0.4,
                         lambda t, x=bx: self.wind.at(t, x))
                flutter_w += crown * np.clip(dc / R, 0.2, 1.0) * rig.get("flutter", 0.45) * u
            elif "tops" in rig:
                R = self.Lsrc(rig.get("radius", 26))
                rise = self.Lsrc(rig.get("rise", 70))
                for p in rig["tops"]:
                    tx, ty = self.P(p)
                    w = smoothstep(1.3 * R, 0.5 * R, np.hypot(self.HX - tx, (self.HY - ty) * 0.8))
                    w = np.maximum(w, smoothstep(0.25 * R, 0.05 * R, np.abs(self.HX - tx)) *
                                   smoothstep(ty + rise, ty, self.HY) * (self.HY > ty))
                    sway.add(w * amp, None, lambda t, x=tx: self.wind.at(t, x))
            elif "poly" in rig or "polys" in rig:
                polys = [rig["poly"]] if "poly" in rig else rig["polys"]
                for poly in polys:
                    m = self.poly_out_half(poly, blur=14 * u)
                    if "base" in rig and amp > 0:
                        bx, by = self.P(rig["base"])
                        top = min(self.P(p)[1] for p in poly)
                        h = np.clip((by - self.HY) / max(by - top, 1.0), 0, 1.1) ** 1.2
                        width = max(self.P(p)[0] for p in poly) - min(self.P(p)[0] for p in poly)
                        sway.add(m * h * amp, m * h * (self.HX - bx) / max(width, 1.0) * amp * 0.3,
                                 lambda t, x=bx: self.wind.at(t, x))
                        flutter_w += m * np.sqrt(h) * rig.get("flutter", 0.0) * u
                    else:
                        flutter_w += m * rig.get("flutter", 0.0) * u
        for bx_, by_, fn in flutter_terms(flutter_w, self.L, self.rng, sigma=5 * u):
            sway.add(bx_, by_, fn)
        for bx_, by_, fn in sway.terms:
            bank.add(None if bx_ is None else bx_ * keep, None if by_ is None else by_ * keep, fn)

        # 水
        wc = mo.get("water", {})
        zone_top = min(self.sc.pt(p)[1] for p in self.scene["water"]["zone"])
        self.y_h = g.src_to_out(0, zone_top)[1] - 4 * u
        persp_h = np.clip((self.HY - self.y_h) / (g.Ho - self.y_h), 0.06, 1.0)
        u_c = (self.HX - g.Wo * 0.5) / persp_h
        v_c = (g.Ho - self.y_h) * np.log(persp_h)
        r_far, r_near = wc.get("ripple", [0.35, 1.8])
        a = water * (r_far + (r_near - r_far) * persp_h) * u
        for lx, ly, n, dly in ((300, 55, 5, 0.9), (460, 38, 7, 2.1), (190, 80, 4, 4.0), (620, 28, 9, 5.2)):
            k1, k2 = TAU / (lx * u), TAU / (ly * u)
            phi = k1 * u_c + k2 * v_c + self.rng.uniform(0, TAU)
            w_ = TAU * n / self.L
            bank.add(a * 0.8 * np.sin(phi) * 0.5, a * 0.45 * np.sin(phi + dly) * 0.5, lambda t, w_=w_: math.cos(w_ * t))
            bank.add(-a * 0.8 * np.cos(phi) * 0.5, -a * 0.45 * np.cos(phi + dly) * 0.5, lambda t, w_=w_: math.sin(w_ * t))

        # 蓮の葉・花：ひとつずつ位相をずらして上下
        fl = g.out_view(floaters_c.astype(np.float32), cv2.INTER_NEAREST).astype(np.int32)
        fl_h = cv2.resize(fl, (self.hw, self.hh), interpolation=cv2.INTER_NEAREST)
        nf = int(fl_h.max()) + 1
        if nf > 1:
            ph = self.rng.uniform(0, TAU, nf).astype(np.float32)
            ph2 = self.rng.uniform(0, TAU, nf).astype(np.float32)
            soft = cv2.GaussianBlur((fl_h > 0).astype(np.float32), (0, 0), 1.2)
            soft = np.maximum(soft, (fl_h > 0).astype(np.float32))
            near = cv2.dilate(fl_h.astype(np.float32), np.ones((5, 5), np.uint8)).astype(np.int32)
            idx = np.maximum(fl_h, near)
            A = wc.get("pads", 0.7) * u
            wp, wp2 = TAU * 3 / self.L, TAU * 2 / self.L
            bank.add(None, soft * np.cos(ph[idx]) * A, lambda t: math.sin(wp * t))
            bank.add(None, soft * np.sin(ph[idx]) * A, lambda t: math.cos(wp * t))
            bank.add(soft * np.cos(ph2[idx]) * A * 0.5, None, lambda t: math.sin(wp2 * t))
            bank.add(soft * np.sin(ph2[idx]) * A * 0.5, None, lambda t: math.cos(wp2 * t))
        boat = np.clip(H(boat_c), 0, 1)
        if boat.max() > 0:
            boat = cv2.GaussianBlur(cv2.dilate(boat, np.ones((3, 3), np.uint8)), (0, 0), 1.0)
            ys, xs = np.nonzero(boat > 0.5)
            bxc = float(self.HX[0, int(xs.mean())]) if xs.size else 0.0
            half_w = float(xs.max() - xs.min()) if xs.size else 1.0
            A = wc.get("boat", 1.1) * u
            bank.add(None, boat * A, lambda t: math.sin(TAU * 4 * t / self.L))
            bank.add(None, boat * (self.HX - bxc) / max(half_w, 1.0) * A * 0.5, lambda t: math.sin(TAU * 3 * t / self.L + 1.3))
        self.land_bank = bank

        # 流れ（2相）：映り込みはあまり流さない
        refl_h = np.clip(H(cv2.GaussianBlur(cv2.dilate(reflect_c, np.ones((5, 5), np.uint8)), (0, 0), 3 * u)), 0, 1)
        f_far, f_near = wc.get("flow", [1.2, 8.0])
        self.flow_v = (-(f_far + (f_near - f_far) * persp_h) * u * water * (1 - 0.85 * refl_h)).astype(np.float32)
        self.flow_period = self.L / max(1, round(self.L / 2.0))
        self.flow_jitter = (0.5 + 0.5 * np.tanh(smooth_noise((self.hh, self.hw), 40 * u, self.rng))).astype(np.float32)
        rows = np.nonzero((water > 0.01).any(1))[0]
        self.water_rows = (int(rows.min()) * 2, min(g.Ho, int(rows.max()) * 2 + 2)) if rows.size else (g.Ho, g.Ho)

        # 映り込みのきらめき（細かい横揺れ・全解像度）
        y0, y1 = self.water_rows
        self.fine = None
        if y1 > y0:
            refl_o = np.clip(g.out_view(cv2.GaussianBlur(cv2.dilate(reflect_c, np.ones((7, 7), np.uint8)), (0, 0), 2.5 * u)), 0, 1)[y0:y1]
            water_o = np.clip(g.out_view(water_c), 0, 1)[y0:y1]
            X, Y = self.OX[y0:y1], self.OY[y0:y1]
            persp = np.clip((Y - self.y_h) / (g.Ho - self.y_h), 0.06, 1.0)
            uc = (X - g.Wo * 0.5) / persp
            vc = (g.Ho - self.y_h) * np.log(persp)
            amp = wc.get("shimmer", 2.4) * u * np.sqrt(persp) * refl_o * water_o
            fine = FieldBank((y1 - y0, g.Wo))
            for ly, lx, n in ((9, 700, 19), (13, 900, 23), (17, 520, 29)):
                phi = TAU / (ly * u) * vc + TAU / (lx * u) * uc + self.rng.uniform(0, TAU)
                w_ = TAU * n / self.L
                fine.add(amp * np.sin(phi) / 3 * 1.4, None, lambda t, w_=w_: math.cos(w_ * t))
                fine.add(-amp * np.cos(phi) / 3 * 1.4, None, lambda t, w_=w_: math.sin(w_ * t))
            self.fine = fine

        # 映り込みの明るさのゆらぎ（canvas 上）
        glint = wc.get("glint", 0.35)
        m = reflect_c > 0.02
        self.glint = None
        if m.any() and glint > 0:
            ys, xs = np.nonzero(m)
            gy0, gy1, gx0, gx1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
            mask = cv2.GaussianBlur(reflect_c, (0, 0), 1.0)[gy0:gy1, gx0:gx1]
            fields = []
            for n in (11, 17):
                w_ = TAU * n / self.L
                for fn in (lambda t, w_=w_: math.sin(w_ * t), lambda t, w_=w_: math.cos(w_ * t)):
                    f = smooth_noise((gy1 - gy0, gx1 - gx0), (6 * u, 1.3 * u), self.rng)
                    fields.append((f * mask * glint * 0.5, fn))
            self.glint = ((gy0, gy1, gx0, gx1), fields)

        # 灯りのゆらぎ（canvas 上、灯りの形のまま）
        lights_c = g.canvas(_labels(self.cut_dir / "lights.png").astype(np.float32), cv2.INTER_NEAREST).astype(np.int32)
        flick = mo.get("lights", {}).get("flicker", 0.07)
        self.lights = []
        for lt in self.meta.get("lights", []):
            m = lights_c == lt["id"]
            if not m.any():
                continue
            m = cv2.GaussianBlur(cv2.dilate(m.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(np.float32), (0, 0), 2 * u)
            ys, xs = np.nonzero(m > 0.01)
            box = (ys.min(), ys.max() + 1, xs.min(), xs.max() + 1)
            comps = [(n, float(self.rng.uniform(0, TAU)), a) for n, a in
                     ((int(self.rng.integers(2, 5)), 0.45), (int(self.rng.integers(23, 41)), 0.3),
                      (int(self.rng.integers(47, 83)), 0.25))]
            cxo, cyo = g.src_to_out(*lt["center"])
            self.lights.append({"box": box, "mask": m[box[0]:box[1], box[2]:box[3], None], "comps": comps,
                                "amp": flick, "center": (cxo, cyo),
                                "depth": float(depth_c[int(np.clip(cyo + g.oy, 0, g.Hc - 1)), int(np.clip(cxo + g.ox, 0, g.Wc - 1))])})

    def light_gain(self, lt: dict, t: float) -> float:
        return 1.0 + lt["amp"] * sum(a * math.sin(TAU * n * t / self.L + p) for n, p, a in lt["comps"])

    def _land(self, t: float) -> np.ndarray:
        g = self.g
        work = self.land_work
        for lt in self.lights:                       # 前のコマの灯りを戻す
            y0, y1, x0, x1 = lt["box"]
            work[y0:y1, x0:x1] = self.land[y0:y1, x0:x1]
        if self.glint is not None:                   # 映り込みのきらめき
            (y0, y1, x0, x1), fields = self.glint
            gain = np.ones((y1 - y0, x1 - x0), np.float32)
            for f, fn in fields:
                gain += f * np.float32(fn(t))
            work[y0:y1, x0:x1, :3] = self.land[y0:y1, x0:x1, :3] * gain[..., None]
        for lt in self.lights:                       # 灯りのゆらぎ（きらめきと重なっても両方効く）
            y0, y1, x0, x1 = lt["box"]
            k = self.light_gain(lt, t) - 1.0
            work[y0:y1, x0:x1, :3] *= 1.0 + k * lt["mask"]

        dx, dy = self.land_bank.eval(t)
        fa = (t / self.flow_period + self.flow_jitter) % 1.0
        fb = (fa + 0.5) % 1.0
        wa = 1.0 - np.abs(2.0 * fa - 1.0)
        dxa = dx + self.flow_v * self.flow_period * (fa - 0.5)
        dxb = dx + self.flow_v * self.flow_period * (fb - 0.5)
        size = (g.Wo, g.Ho)
        up = lambda a: cv2.resize(a, size, interpolation=cv2.INTER_LINEAR)
        DXa, DY, DXb, WA = up(dxa), up(dy), up(dxb), up(wa.astype(np.float32))
        y0, y1 = self.water_rows
        if self.fine is not None:
            fx, _ = self.fine.eval(t)
            DXa[y0:y1] += fx
            DXb[y0:y1] += fx
        mx = self.OX + g.ox - DXa
        my = self.OY + g.oy - DY
        out = cv2.remap(work, mx, my, cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)
        if y1 > y0:
            mxb = self.OX[y0:y1] + g.ox - DXb[y0:y1]
            outb = cv2.remap(work, mxb, my[y0:y1], cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)
            w = WA[y0:y1, :, None]
            out[y0:y1] = out[y0:y1] * w + outb * (1.0 - w)
        return _clip_premul(out)

    # --- 手前の草 -------------------------------------------------------------------------

    def _init_foreground(self) -> None:
        g, u = self.g, self.g.u
        self.fg = g.canvas_rgba(_rgba(self.cut_dir / "foreground.png"))
        self.d_fg = self.depth_cfg.get("foreground", 1.0)
        rc = self.mo.get("reeds", {})
        bank = FieldBank((self.hh, self.hw))
        self._parallax_terms(bank, np.full((self.hh, self.hw), self.d_fg, np.float32))
        top = self.P([0, rc.get("top", 610)])[1]
        bottom = self.P([0, rc.get("bottom", self.sc.H / self.sc.sy)])[1]
        h = np.clip((bottom - self.HY) / max(bottom - top, 1.0), 0, 1.25) ** 1.6
        for bx, fn in self.wind.traveling((h * rc.get("amp", 5.5) * u).astype(np.float32), self.HX):
            bank.add(bx, None, fn)
        fg_o = self.half(g.out_view(self.fg))
        white = np.clip((fg_o[..., :3].min(-1) / np.maximum(fg_o[..., 3], 1e-3) - 0.55) / 0.3, 0, 1) * fg_o[..., 3]
        white = cv2.GaussianBlur(white, (0, 0), 3 * u)
        for bx, by, fn in flutter_terms(white * h * rc.get("flutter", 0.8) * u, self.L, self.rng, sigma=3 * u):
            bank.add(bx, by, fn)
        self.fg_bank = bank

    def _foreground(self, t: float) -> np.ndarray:
        g = self.g
        dx, dy = self.fg_bank.eval(t)
        size = (g.Wo, g.Ho)
        DX = cv2.resize(dx, size, interpolation=cv2.INTER_LINEAR)
        DY = cv2.resize(dy, size, interpolation=cv2.INTER_LINEAR)
        return _clip_premul(cv2.remap(self.fg, self.OX + g.ox - DX, self.OY + g.oy - DY, cv2.INTER_CUBIC,
                                      borderMode=cv2.BORDER_REFLECT))

    # --- 足す効果 -------------------------------------------------------------------------

    def _init_fx(self) -> None:
        g, u = self.g, self.g.u
        fx = self.fx
        rng = self.rng

        # 霧：やわらかい雲模様を2相でゆっくり流す（分散を保つ重ね方で濃さが脈打たない）
        self.mists = []
        self.sky_mists = []
        moon = self.meta["moon"]
        for band in fx.get("mist", []):
            sky = band.get("layer") == "sky"
            conv = (lambda p: g.src_to_canvas(*self.sc.pt(p))) if sky else self.P
            Wl, Hl = (g.Wc, self.sky_rows) if sky else (g.Wo, g.Ho)
            x0, y0 = conv(band["rect"][:2])
            x1, y1 = conv(band["rect"][2:])
            x0, y0, x1, y1 = int(max(0, x0)), int(max(0, y0)), int(min(Wl, x1)), int(min(Hl, y1))
            if x1 - x0 < 8 or y1 - y0 < 4:
                continue
            pad = int(60 * u)
            big, small = (70 * u, 12 * u), (22 * u, 5 * u)
            if not sky:
                big, small = (38 * u, 7 * u), (12 * u, 3 * u)
            tex = smooth_noise((y1 - y0, x1 - x0 + 2 * pad), big, rng) * 0.7 + \
                smooth_noise((y1 - y0, x1 - x0 + 2 * pad), small, rng) * 0.3
            yy = np.linspace(0, 1, y1 - y0, dtype=np.float32)[:, None]
            xx = np.linspace(0, 1, x1 - x0, dtype=np.float32)[None, :]
            prof = (np.clip(np.sin(np.pi * yy), 0, 1) ** 1.5) * np.clip(np.minimum(xx, 1 - xx) / 0.12, 0, 1)
            color = np.broadcast_to(np.array(band.get("color", fx.get("mist_color", [0.72, 0.80, 0.95])), np.float32),
                                    (y1 - y0, x1 - x0, 3)).copy()
            if sky and moon["r"] > 0:   # 月の近くの霧は月の光で明るい
                mx, my = g.src_to_canvas(moon["x"], moon["y"])
                yy2, xx2 = np.mgrid[y0:y1, x0:x1].astype(np.float32)
                near = np.exp(-np.hypot(xx2 - mx, yy2 - my) / (moon["r"] * g.scale * 3.5))
                color *= (1.0 + 1.2 * near)[..., None] * np.array([1.0, 0.97, 0.88], np.float32)
            entry = {"box": (y0, y1, x0, x1), "tex": tex.astype(np.float32), "pad": pad, "prof": prof, "color": color,
                     "opacity": band.get("opacity", 0.15), "speed": band.get("speed", 6.0) * u,
                     "depth": band.get("depth", 0.3), "sky": sky}
            (self.sky_mists if sky else self.mists).append(entry)
        self.mist_period = self.L / max(1, round(self.L / 8.0))

        # 灯りの光（にじみ）
        lights_c = g.canvas(_labels(self.cut_dir / "lights.png").astype(np.float32), cv2.INTER_NEAREST).astype(np.int32)
        for lt in self.lights:
            y0, y1, x0, x1 = lt["box"]
            pad = int(40 * u)
            Y0, Y1, X0, X1 = max(0, y0 - pad), min(g.Hc, y1 + pad), max(0, x0 - pad), min(g.Wc, x1 + pad)
            src = self.land[Y0:Y1, X0:X1, :3] * (lights_c[Y0:Y1, X0:X1, None] > 0)
            glow = cv2.GaussianBlur(src, (0, 0), 7 * u) * 0.6 + cv2.GaussianBlur(src, (0, 0), 18 * u) * 0.5
            lt["glow"] = ((Y0 - g.oy, X0 - g.ox), glow.astype(np.float32))

        # 蛍
        ff = fx.get("fireflies", {})
        self.fireflies = []
        if ff.get("count", 0):
            zone = self.poly_out_half(ff["zone"]) > 0.5
            ys, xs = np.nonzero(zone)
            color = np.array(ff.get("color", [255, 236, 150]), np.float32) / 255
            for _ in range(int(ff["count"]) if len(ys) else 0):
                i = rng.integers(len(ys))
                p0 = (xs[i] * 2.0, ys[i] * 2.0)
                path = [(int(rng.integers(1, 4)), float(rng.uniform(15, 55) * u), float(rng.uniform(0, TAU)),
                         int(rng.integers(1, 4)), float(rng.uniform(8, 28) * u), float(rng.uniform(0, TAU)))
                        for _ in range(2)]
                size = float(rng.uniform(0.9, 1.5)) * ff.get("size", 1.0)
                self.fireflies.append({"p0": p0, "path": path,
                                       "pulse": Pulse(self.L, int(rng.integers(3, 9)), float(rng.uniform(0, TAU)), 4.0),
                                       "base": float(rng.uniform(0.15, 0.35)), "peak": float(rng.uniform(1.1, 1.6)),
                                       "depth": float(rng.uniform(0.45, 0.85)), "size": size, "color": color})

        # 花びら（花の木から散る）
        pc = fx.get("petals", {})
        self.petals = []
        if pc.get("count", 0):
            sx0, sy0 = self.P(pc["spawn"][:2])
            sx1, sy1 = self.P(pc["spawn"][2:])
            land0, land1 = (self.P([0, v])[1] for v in pc.get("land", [560, 690]))
            for k in range(int(pc["count"])):
                n = int(rng.integers(1, 3))
                self.petals.append({"x": float(rng.uniform(sx0, sx1)), "y": float(rng.uniform(sy0, sy1)),
                                    "land": float(rng.uniform(land0, land1)), "n": n,
                                    "phase": float(rng.uniform(0, 1)), "drift": float(rng.uniform(20, 90) * u),
                                    "sway": float(rng.uniform(6, 16) * u), "swf": int(rng.integers(2, 5)),
                                    "spin": int(rng.integers(2, 6)) * (1 if rng.random() < 0.5 else -1),
                                    "size": float(rng.uniform(3.2, 4.6) * u),
                                    "color": np.array([1.0, rng.uniform(0.9, 0.98), rng.uniform(0.86, 0.95)], np.float32)})

        # 手前のボケ：花の枝（右上の角から）と大きな花びら
        bk = fx.get("bokeh", {})
        self.branch = None
        br = bk.get("branch")
        if br:
            land_src = _rgba(self.cut_dir / "land.png")
            x0, y0, x1, y1 = self.sc.rect(br["source"])
            sp = _premul(land_src[y0:y1, x0:x1])
            if br.get("flip", True):
                sp = sp[:, ::-1]
            scale = br.get("scale", 1.0) * g.scale
            sp = _clip_premul(cv2.resize(np.ascontiguousarray(sp), None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC))
            # 切り取りの上下の直線を見せない（下の端はゆっくり消す）
            hh_ = sp.shape[0]
            yy = np.arange(hh_, dtype=np.float32)[:, None] / hh_
            fade = smoothstep(0.0, 0.08, yy) * smoothstep(1.0, 1.0 - br.get("fade_bottom", 0.3), yy)
            sp *= fade[..., None].astype(np.float32)
            pad = int(round(br.get("blur", 8) * u * 3))
            sp = cv2.copyMakeBorder(sp, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=0)
            r = max(1, int(round(br.get("blur", 8) * u)))
            k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1)).astype(np.float32)
            sp = cv2.filter2D(sp, -1, k / k.sum(), borderType=cv2.BORDER_CONSTANT)
            shade = br.get("shade", 0.6)
            sp[..., :3] *= np.array([shade * 0.95, shade * 0.95, shade * 1.05], np.float32)
            self.branch = {"img": np.clip(sp, 0, 1).astype(np.float32), "sway": br.get("sway", 1.2), "pad": pad,
                           "angle": br.get("angle", 0.0), "depth": br.get("depth", 2.0),
                           "at": br.get("at", [1.0, -0.05])}
        self.bokeh_petals = []
        for k in range(int(bk.get("petals", 0))):
            size = float(rng.uniform(12, 26) * u)
            self.bokeh_petals.append({"x": float(rng.uniform(0.1, 1.1) * g.Wo), "phase": float(rng.uniform(0, 1)),
                                      "n": 1, "size": size, "alpha": float(rng.uniform(0.25, 0.5)),
                                      "sway": float(rng.uniform(20, 60) * u), "swf": int(rng.integers(1, 3)),
                                      "slant": float(rng.uniform(0.25, 0.6)), "depth": float(rng.uniform(1.8, 2.6)),
                                      "color": np.array([1.0, rng.uniform(0.86, 0.95), rng.uniform(0.84, 0.93)], np.float32)})

        bl = fx.get("bloom") or {}
        self.bloom = (float(bl.get("threshold", 0.7)), float(bl.get("strength", 0.0)))
        v = fx.get("vignette", 0.2)
        yy, xx = np.mgrid[0:g.Ho, 0:g.Wo].astype(np.float32)
        r = np.hypot((xx - g.Wo / 2) / (g.Wo / 2), (yy - g.Ho / 2) / (g.Ho / 2)) / math.sqrt(2)
        self.vignette = (1.0 - v * r ** 2.2)[..., None].astype(np.float32)

    def _mist(self, out: np.ndarray, t: float, mists: list | None = None) -> None:
        for m in (self.mists if mists is None else mists):
            y0, y1, x0, x1 = m["box"]
            tex, pad = m["tex"], m["pad"]
            ja, jb, wa, wb = two_phase(t, self.mist_period)
            shift = m["speed"] * self.mist_period
            sx, sy = (0.0, 0.0) if m["sky"] else self.depth_shift(m["depth"], (x0 + x1) / 2, (y0 + y1) / 2, t)

            def sample(j):
                M = np.float32([[1, 0, pad - shift * j - sx], [0, 1, -sy]])   # speed > 0 で右へ
                return cv2.warpAffine(tex, M, (x1 - x0, y1 - y0), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                                      borderMode=cv2.BORDER_REFLECT)
            n = (sample(ja) * wa + sample(jb) * wb) / math.sqrt(wa * wa + wb * wb)
            a = np.clip(0.5 + 0.35 * n, 0, 1) ** 1.6 * m["prof"] * m["opacity"]
            region = out[y0:y1, x0:x1]
            region += (1.0 - np.clip(region, 0, 1)) * (a[..., None] * m["color"])

    def _add_glows(self, out: np.ndarray, t: float) -> None:
        for lt in self.lights:
            if "glow" not in lt:
                continue
            (oy, ox), glow = lt["glow"]
            dx, dy = self.depth_shift(lt["depth"], *lt["center"], t)
            k = (self.light_gain(lt, t) - 1.0) * 3.0 + 1.0
            self._add_patch(out, glow * (0.28 * k), ox + dx, oy + dy)

    @staticmethod
    def _add_patch(out: np.ndarray, patch: np.ndarray, x: float, y: float, mode: str = "add") -> None:
        """patch を出力の (x, y)（左上、小数も可）に足す／重ねる。"""
        H, W = out.shape[:2]
        xi, yi = int(math.floor(x)), int(math.floor(y))
        fx, fy = x - xi, y - yi
        if fx or fy:
            M = np.float32([[1, 0, fx], [0, 1, fy]])
            patch = cv2.warpAffine(patch, M, (patch.shape[1] + 1, patch.shape[0] + 1), flags=cv2.INTER_LINEAR,
                                   borderMode=cv2.BORDER_CONSTANT)
            if patch.ndim == 2:
                patch = patch[..., None]
        ph, pw = patch.shape[:2]
        x0, y0 = max(0, xi), max(0, yi)
        x1, y1 = min(W, xi + pw), min(H, yi + ph)
        if x1 <= x0 or y1 <= y0:
            return
        p = patch[y0 - yi:y1 - yi, x0 - xi:x1 - xi]
        region = out[y0:y1, x0:x1]
        if mode == "add":
            region += p[..., :3]
        else:   # premultiplied RGBA
            region *= 1.0 - p[..., 3:4]
            region += p[..., :3]

    def _fireflies(self, out: np.ndarray, t: float) -> None:
        u = self.g.u
        for f in self.fireflies:
            x, y = f["p0"]
            for nx, ax, px, ny, ay, py in f["path"]:
                x += ax * math.sin(TAU * nx * t / self.L + px)
                y += ay * math.sin(TAU * ny * t / self.L + py)
            dx, dy = self.depth_shift(f["depth"], x, y, t)
            x, y = x + dx, y + dy
            b = f["base"] + f["peak"] * f["pulse"](t)
            s = f["size"]
            R = int(14 * u * s) + 2
            yy, xx = np.mgrid[-R:R + 1, -R:R + 1].astype(np.float32)
            fx, fy = x - round(x), y - round(y)
            d2 = (xx - fx) ** 2 + (yy - fy) ** 2
            spot = (np.exp(-d2 / (2 * (1.4 * u * s) ** 2)) * 1.0 + np.exp(-d2 / (2 * (6.5 * u * s) ** 2)) * 0.42) * b
            self._add_patch(out, spot[..., None] * f["color"], round(x) - R, round(y) - R)

    def _petal_patch(self, size: float, angle: float, squash: float, color: np.ndarray, alpha: float,
                     blur: float = 0.0) -> np.ndarray:
        R = int(size * 1.6 + blur * 2.5) + 2
        yy, xx = np.mgrid[-R:R + 1, -R:R + 1].astype(np.float32)
        c, s = math.cos(angle), math.sin(angle)
        u_ = (xx * c + yy * s) / size
        v_ = (-xx * s + yy * c) / (size * 0.55 * max(squash, 0.15))
        d = np.sqrt(u_ ** 2 + v_ ** 2)
        a = np.clip((1.0 - d) * size * 0.8, 0, 1) if blur == 0 else np.exp(-d ** 2 * 1.4)
        if blur > 0:
            a = cv2.GaussianBlur(a.astype(np.float32), (0, 0), blur)
            a = a / max(a.max(), 1e-6)
        a = (a * alpha).astype(np.float32)
        return np.dstack([a[..., None] * color, a])

    def _petals(self, out: np.ndarray, t: float) -> None:
        for p in self.petals:
            T = self.L / p["n"]
            q = ((t / T) + p["phase"]) % 1.0
            y = p["y"] + (p["land"] - p["y"]) * q
            x = p["x"] + p["drift"] * q + p["sway"] * math.sin(TAU * p["swf"] * q + p["phase"] * 7)
            a = float(smoothstep(0.0, 0.08, q) * smoothstep(1.0, 0.9, q))
            if a <= 0.01:
                continue
            ang = TAU * p["spin"] * q
            dx, dy = self.depth_shift(0.5, x, y, t)
            patch = self._petal_patch(p["size"], ang, abs(math.cos(ang * 1.7)), p["color"], a * 0.95)
            R = patch.shape[0] // 2
            self._add_patch(out, patch, x + dx - R, y + dy - R, mode="over")

    def _bokeh(self, out: np.ndarray, t: float) -> None:
        g = self.g
        for p in self.bokeh_petals:
            q = ((t / self.L) * p["n"] + p["phase"]) % 1.0
            y = -0.15 * g.Ho + q * 1.3 * g.Ho
            x = p["x"] - p["slant"] * q * 1.3 * g.Ho + p["sway"] * math.sin(TAU * p["swf"] * q + p["phase"] * 5)
            dx, dy = self.depth_shift(p["depth"], x, y, t)
            ang = TAU * q * 1.5 + p["phase"] * 9
            patch = self._petal_patch(p["size"], ang, 0.6 + 0.4 * abs(math.cos(ang)), p["color"], p["alpha"],
                                      blur=p["size"] * 0.35)
            R = patch.shape[0] // 2
            self._add_patch(out, patch, x + dx - R, y + dy - R, mode="over")
        b = self.branch
        if b is not None:
            img = b["img"]
            h, w = img.shape[:2]
            ang = b["angle"] + b["sway"] * self.wind.at(t, g.Wo) * 0.6
            # sprite の右端の中ほどを支点に、画面の右端 at の位置へ
            px, py = w - 1.0 - b["pad"], h / 2
            ax, ay = b["at"][0] * g.Wo, b["at"][1] * g.Ho
            dx, dy = self.depth_shift(b["depth"], ax - w / 2, ay, t)
            M = cv2.getRotationMatrix2D((px, py), ang, 1.0)
            M[0, 2] += ax - px + dx
            M[1, 2] += ay - py + dy
            layer = cv2.warpAffine(img, M, (g.Wo, g.Ho), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
            out *= 1.0 - layer[..., 3:4]
            out += layer[..., :3]

    # --- 1コマ ----------------------------------------------------------------------------

    def render_t(self, t: float) -> np.ndarray:
        """時刻 t（秒）のコマ（0〜1 の float）。すべての動きは周期 L なので render_t(t) == render_t(t + L)。"""
        sky = self._sky(t)
        land = self._land(t)
        out = sky * (1.0 - land[..., 3:4]) + land[..., :3]
        self._mist(out, t)
        self._add_glows(out, t)
        self._petals(out, t)
        self._fireflies(out, t)
        fg = self._foreground(t)
        out = out * (1.0 - fg[..., 3:4]) + fg[..., :3]
        self._bokeh(out, t)
        self._bloom(out)
        out *= self.vignette
        return out

    def _bloom(self, out: np.ndarray) -> None:
        """明るい所（月・窓・映り込み・蛍・白い花）の まわりに光をにじませる。"""
        th, strength = self.bloom
        if strength <= 0:
            return
        g = self.g
        small = cv2.resize(out, (max(1, g.Wo // 4), max(1, g.Ho // 4)), interpolation=cv2.INTER_AREA)
        Y = small @ np.array([0.299, 0.587, 0.114], np.float32)
        b = small * np.clip((Y - th) / (1.0 - th), 0, 1)[..., None]
        k = g.Wo / 1920.0
        glow = cv2.GaussianBlur(b, (0, 0), 4 * k) * 0.6 + cv2.GaussianBlur(b, (0, 0), 12 * k) * 0.4
        glow = cv2.resize(glow, (g.Wo, g.Ho), interpolation=cv2.INTER_LINEAR)
        np.clip(out, 0, 1, out=out)
        out += (1.0 - out) * np.clip(glow * (2.2 * strength), 0, 1)

    def frame(self, i: int) -> np.ndarray:
        return (np.clip(self.render_t((i % self.N) / self.fps), 0, 1) * 255 + 0.5).astype(np.uint8)
