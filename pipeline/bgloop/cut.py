"""背景ループの「切り抜き」段：1枚絵を層（空・雲・陸・手前の草）とマスク（水・映り込み・星・灯り・奥行き）に分ける。

成果物は <out>/cut/ に保存する。マスクを画像編集で直してから render だけやり直すこともできる。
- sky_plate.png  雲と陸を取り除いて補った空（月と星は残す）
- clouds.png     雲（RGBA）。陸に隠れている所も補ってあるので、動かしても穴が出ない
- land.png       空以外（RGBA）。手前の草の後ろは水と岸の模様で補ってある
- foreground.png 手前の草（RGBA）
- water.png / reflect.png / floaters.png / boat.png / lights.png / stars.png / depth.png
- overlay.png    確認用（切り抜きの境目を色で重ねた絵）
"""
from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from pipeline.bgloop.matte import (fill_holes, fill_plate, fill_rows, imwrite, luminance, pull_push, remove_small,
                                   rgb_to_hsv, soft_matte, unmix)
from pipeline.bgloop.scene import Scale, hue_in

CUT_VERSION = 1


def load_rgb(path: Path) -> np.ndarray:
    with Image.open(path) as im:
        return np.asarray(im.convert("RGB"), np.float32) / 255.0


def save_png(path: Path, arr: np.ndarray, bits: int = 8) -> None:
    arr = np.clip(arr, 0, 1)
    if bits == 16:
        imwrite(path, (arr * 65535 + 0.5).astype(np.uint16))
        return
    a = (arr * 255 + 0.5).astype(np.uint8)
    Image.fromarray(a, "L" if a.ndim == 2 else {3: "RGB", 4: "RGBA"}[a.shape[2]]).save(path)


def _ellipse(d: float) -> np.ndarray:
    d = max(1, int(round(d)) | 1)
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (d, d))


# --- 空 -------------------------------------------------------------------------------

def sky_mask(I, h, s, v, Y, sc: Scale, cfg: dict) -> tuple[np.ndarray, dict]:
    """空（雲・月・星を含む）の二値マスクと月の位置。色の判定 + 範囲のヒント + GrabCut（色が近い所だけ）。"""
    H, W = Y.shape
    blue = hue_in(h, cfg.get("hue", [98, 118])) & (v >= cfg.get("min_value", 42))
    cloudish = blue & (v >= 80) & (s <= 200)
    near_cloud = cv2.dilate(cloudish.astype(np.uint8), _ellipse(7 * sc.s)) > 0
    gold = (h >= 8) & (h <= 35) & (s >= 40) & (v >= 110)
    lo, hi = cfg.get("hue", [98, 118])
    dark_navy = hue_in(h, [lo + 6, hi - 2]) & (v >= 18) & (s >= 200)      # 暗い夜空（彩度が高い藍）
    rim = gold & near_cloud                                                 # 雲の金の縁取り
    # 縁取りの外側の細い暗い線も雲の一部（緑の葉は除く）
    outline = (cv2.dilate(rim.astype(np.uint8), _ellipse(5 * sc.s)) > 0) & (v < 90) & ~hue_in(h, [36, 100])
    rule_gc = blue | rim | outline
    rule = rule_gc | dark_navy
    zone = sc.poly_mask(cfg["zone"]) if cfg.get("zone") else np.ones((H, W), bool)
    sure_sky = sc.shapes_mask(cfg.get("sure_sky"))
    sure_land = sc.shapes_mask(cfg.get("sure_land"))
    sky = rule & zone

    for r in cfg.get("grabcut", []):
        x0, y0, x1, y1 = sc.rect(r)
        sub = np.ascontiguousarray((I[y0:y1, x0:x1, ::-1] * 255).astype(np.uint8))
        m = np.where(rule_gc[y0:y1, x0:x1], cv2.GC_PR_FGD, cv2.GC_PR_BGD).astype(np.uint8)
        m[sure_sky[y0:y1, x0:x1]] = cv2.GC_FGD
        m[sure_land[y0:y1, x0:x1]] = cv2.GC_BGD
        if (m == cv2.GC_FGD).any() and (m == cv2.GC_BGD).any():
            bgd, fgd = np.zeros((1, 65)), np.zeros((1, 65))
            cv2.grabCut(sub, m, None, bgd, fgd, 5, cv2.GC_INIT_WITH_MASK)
            gc = (m == cv2.GC_FGD) | (m == cv2.GC_PR_FGD)
            inner = np.zeros((y1 - y0, x1 - x0), np.float32)
            e = max(2, round(20 * sc.s))
            inner[e:-e or None, e:-e or None] = 1
            inner = cv2.GaussianBlur(inner, (0, 0), 8 * sc.s) > 0.5
            sky[y0:y1, x0:x1] = np.where(inner, gc & zone[y0:y1, x0:x1], sky[y0:y1, x0:x1])

    # 月（明るいかたまり）は空に入れる
    moon = {"x": 0.0, "y": 0.0, "r": 0.0}
    if cfg.get("moon"):
        mx, my = sc.pt(cfg["moon"])
        yy, xx = np.mgrid[0:H, 0:W]
        near = (xx - mx) ** 2 + (yy - my) ** 2 < (120 * sc.s) ** 2
        n, lab, st, cen = cv2.connectedComponentsWithStats(((Y > 0.7) & near).astype(np.uint8), 8)
        if n > 1:
            k = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
            moon = {"x": float(cen[k][0]), "y": float(cen[k][1]),
                    "r": float(0.5 * max(st[k, cv2.CC_STAT_WIDTH], st[k, cv2.CC_STAT_HEIGHT]))}
            sky |= cv2.dilate((lab == k).astype(np.uint8), _ellipse(5 * sc.s)) > 0

    sky = (sky | sure_sky) & ~sure_land
    # 空に囲まれた暗い藍の小さな穴（暗い夜空）は空
    hh, vv = h.astype(np.float64), v.astype(np.float64)
    h_lo = cfg.get("hue", [98, 118])[0] + 4

    def dark_blue(lab, n):
        area = np.maximum(np.bincount(lab.ravel(), minlength=n), 1)
        mh = np.bincount(lab.ravel(), hh.ravel(), n) / area
        mv = np.bincount(lab.ravel(), vv.ravel(), n) / area
        return (mh >= h_lo) & (mv < 70)

    def bright(lab, n):     # 空に囲まれた星
        area = np.maximum(np.bincount(lab.ravel(), minlength=n), 1)
        return np.bincount(lab.ravel(), vv.ravel(), n) / area > 120

    sky = fill_holes(sky, int(2500 * sc.s ** 2), ok=dark_blue)
    sky = fill_holes(sky, int(150 * sc.s ** 2), ok=bright)
    sky = fill_holes(sky, int(40 * sc.s ** 2))
    sky = remove_small(sky, int(25 * sc.s ** 2))
    return sky & ~sure_land, moon


def star_mask(Y: np.ndarray, allowed: np.ndarray, moon: dict, k: float) -> np.ndarray:
    """小さく明るい点（星）。"""
    th = Y - cv2.morphologyEx(Y, cv2.MORPH_OPEN, _ellipse(9 * k))
    cand = (th > 0.10) & allowed
    if moon["r"] > 0:
        H, W = Y.shape
        yy, xx = np.mgrid[0:H, 0:W]
        cand &= (xx - moon["x"]) ** 2 + (yy - moon["y"]) ** 2 > (moon["r"] * 1.6) ** 2
    n, lab, st, _ = cv2.connectedComponentsWithStats(cand.astype(np.uint8), 8)
    keep = (st[:, cv2.CC_STAT_AREA] >= 2) & (st[:, cv2.CC_STAT_AREA] <= 120 * k * k)
    keep[0] = False
    return keep[lab]


# --- 雲 -------------------------------------------------------------------------------

def cloud_alpha(I, h, s, v, Y, a_sky, moon, stars, sc: Scale, cfg: dict) -> np.ndarray:
    """空の明るさ（高さごと）より明るい所を雲とする。金の縁取りがある かたまりだけを残す。"""
    H, W = Y.shape
    sky = a_sky > 0.6
    yy, xx = np.mgrid[0:H, 0:W]
    moon_zone = ((xx - moon["x"]) ** 2 + (yy - moon["y"]) ** 2 < (moon["r"] * 2.4) ** 2) if moon["r"] else np.zeros_like(sky)
    ref = sky & ~moon_zone & ~stars
    base = np.full(H, np.nan, np.float32)
    for y in range(H):
        row = Y[y][ref[y]]
        if row.size > 60:
            base[y] = np.percentile(row, 30)
    ys = np.arange(H)
    ok = ~np.isnan(base)
    if not ok.any():
        return np.zeros((H, W), np.float32)
    base = np.interp(ys, ys[ok], base[ok]).astype(np.float32)
    base = cv2.GaussianBlur(base.reshape(-1, 1), (1, 0), 20 * sc.s).ravel()
    c = Y - base[:, None]

    gold = (h >= 8) & (h <= 35) & (s >= 40) & (v >= 110)
    core = (c > cfg.get("core", 0.13)) & sky & ~moon_zone
    low = ((c > cfg.get("low", 0.045)) | gold) & sky & ~moon_zone
    n, lab, st, _ = cv2.connectedComponentsWithStats(low.astype(np.uint8), 8)
    keep = np.zeros(n, bool)
    keep[np.unique(lab[core])] = True
    keep &= st[:, cv2.CC_STAT_AREA] >= 150 * sc.s ** 2
    keep[0] = False
    hard = keep[lab]
    hard = cv2.morphologyEx(hard.astype(np.uint8), cv2.MORPH_CLOSE, _ellipse(7 * sc.s)) > 0
    hard = fill_holes(hard, int(800 * sc.s ** 2))

    soft = np.clip((c - 0.02) / 0.08, 0, 1)
    soft = np.maximum(soft, gold.astype(np.float32))
    soft = cv2.GaussianBlur(soft, (0, 0), 1.2 * sc.s)
    a = soft_matte(I, hard.astype(np.float32) * soft, r=max(1, round(2 * sc.s)), eps=1e-3) * np.clip(a_sky, 0, 1)

    # 金の縁取り（星を除く）が十分ある、または大きい かたまりだけ
    rim = gold & ~(cv2.dilate(stars.astype(np.uint8), _ellipse(5 * sc.s)) > 0)
    rim = remove_small(rim, max(3, int(6 * sc.s ** 2)))
    comp = (a > 0.05).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(comp, 8)
    rims = np.bincount(lab.ravel(), (rim & (comp > 0)).ravel().astype(np.float64), n)
    keep = (rims >= cfg.get("min_rim", 40) * sc.s) | (st[:, cv2.CC_STAT_AREA] >= cfg.get("min_area", 8000) * sc.s ** 2)
    keep[0] = False
    a = a * keep[lab]
    a[a < 0.03] = 0
    return cv2.GaussianBlur(a, (0, 0), 0.8 * sc.s)


def sky_plate(I, a_sky, a_cloud, moon, k: float) -> np.ndarray:
    """雲と陸を取り除いた空。細かい筆の模様と星は、見えている空から写して補う。"""
    H, W = a_sky.shape
    excl = cv2.dilate((a_cloud > 0.02).astype(np.uint8), _ellipse(7 * k)) > 0
    core = cv2.erode((a_sky > 0.97).astype(np.uint8), _ellipse(7 * k)) > 0
    known = core & ~excl
    source = known.copy()
    if moon["r"]:
        yy, xx = np.mgrid[0:H, 0:W]
        d2 = (xx - moon["x"]) ** 2 + (yy - moon["y"]) ** 2
        known |= d2 < (moon["r"] * 1.3) ** 2
        source &= d2 > (moon["r"] * 3.0) ** 2      # 月のかけらを写さない
    return fill_plate(I, known, patch=max(16, round(40 * k)), sigma=12 * k, y_window=round(160 * k),
                      source=source, seed=1)


def cloud_layer(I, a_sky, a_vis, plate, k: float) -> np.ndarray:
    """雲の RGBA。alpha は「空に対する雲の覆い具合」。陸（ヤシの葉・木立）に隠れている所も
    まわりの雲から続けて補う（流したときに葉の形の穴や縁が出ないように）。"""
    conf = np.clip((a_sky - 0.2) / 0.6, 0, 1)
    C = np.where(a_sky > 0.2, np.clip(a_vis / np.maximum(a_sky, 1e-3), 0, 1), 0).astype(np.float32)
    near = cv2.dilate((a_vis > 0.05).astype(np.uint8), _ellipse(45 * k)).astype(np.float32)
    near = cv2.GaussianBlur(near, (0, 0), 6 * k)
    ext = pull_push(C[..., None], conf)[..., 0]
    C = np.where(conf > 0.99, C, ext * near)
    C[C < 0.02] = 0
    known = (a_sky > 0.95) & (C > 0.5)
    F = unmix(I, C, plate)
    if known.any():
        F = fill_plate(F, known, patch=max(12, round(28 * k)), sigma=6 * k, y_window=round(120 * k),
                       source=known & (C > 0.8), seed=2)
    return np.dstack([F, C]).astype(np.float32)


def cloud_sprites(alpha: np.ndarray, visible: np.ndarray, k: float) -> tuple[list[dict], np.ndarray]:
    """見えている雲のかたまりごとに流し、形の入れ替わりの時刻をずらす。
    陸の後ろに補った部分は、いちばん近い かたまりに付ける。"""
    seed = cv2.dilate((visible > 0.05).astype(np.uint8), _ellipse(9 * k))
    n, lab, st, _ = cv2.connectedComponentsWithStats(seed, 8)
    big = st[:, cv2.CC_STAT_AREA] >= 300 * k * k
    big[0] = False
    lab = np.where(big[lab], lab, 0).astype(np.int32)
    if not big.any():
        return [], np.zeros(alpha.shape, np.int32)
    src = (lab == 0).astype(np.uint8)
    _, near = cv2.distanceTransformWithLabels(src, cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_CCOMP)
    # distanceTransform の番号 → 自分の番号
    remap = np.zeros(int(near.max()) + 1, np.int32)
    remap[near[lab > 0]] = lab[lab > 0]
    full = np.where(alpha > 0.02, remap[near], 0)
    out = []
    for i in np.unique(full[full > 0]):
        ys, xs = np.nonzero(full == i)
        out.append({"id": int(i), "bbox": [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1],
                    "cy": float(ys.mean())})
    return out, full


# --- 水・手前の草 ---------------------------------------------------------------------

def water_masks(I, h, s, v, sc: Scale, cfg: dict) -> dict:
    H, W = v.shape
    zone = sc.poly_mask(cfg["zone"])
    bluish = hue_in(h, cfg.get("hue", [96, 122])) & (v >= 25)
    rc = cfg.get("reflect", {})
    warm = hue_in(h, rc.get("hue", [5, 40])) & (s >= rc.get("min_sat", 35)) & (v >= rc.get("min_value", 110))

    pc = cfg.get("pads", {})
    pads = hue_in(h, pc.get("hue", [26, 62])) & (s >= pc.get("min_sat", 70)) & (v >= pc.get("min_value", 50)) & zone
    pads = cv2.morphologyEx(pads.astype(np.uint8), cv2.MORPH_OPEN, _ellipse(3 * sc.s)) > 0
    pads = remove_small(pads, int(60 * sc.s ** 2))
    pads = cv2.morphologyEx(pads.astype(np.uint8), cv2.MORPH_CLOSE, _ellipse(7 * sc.s)) > 0
    pads = fill_holes(pads, int(900 * sc.s ** 2))

    lotus = np.zeros((H, W), bool)
    circles = sc.shapes_mask({"circles": cfg.get("lotus", [])})
    if circles.any():
        lotus = circles & ~(bluish & (s >= 60)) & (v >= 40)
        lotus = cv2.morphologyEx(lotus.astype(np.uint8), cv2.MORPH_OPEN, _ellipse(3 * sc.s)) > 0
        lotus = remove_small(lotus, int(20 * sc.s ** 2))

    def rigid(rect):
        if not rect:
            return np.zeros((H, W), bool)
        m = sc.rect_mask(rect) & ~(bluish & (v >= 25))
        m = cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_OPEN, _ellipse(3 * sc.s)) > 0
        return remove_small(m, int(40 * sc.s ** 2))

    boat = rigid(cfg.get("boat")) & zone
    jetty = rigid(cfg.get("jetty"))
    objects = pads | lotus | boat | jetty
    water = zone & ~objects
    water_soft = soft_matte(I, water.astype(np.float32), r=max(2, round(3 * sc.s)), eps=2e-3)
    water_soft *= ~(cv2.dilate(objects.astype(np.uint8), _ellipse(3 * sc.s)) > 0)
    reflect = warm & zone & ~objects
    reflect = remove_small(reflect, 3)
    return {"zone": zone, "water": water_soft, "reflect": reflect, "pads": pads, "lotus": lotus,
            "boat": boat, "jetty": jetty, "bluish": bluish, "warm": warm}


def foreground_mask(I, h, s, v, sc: Scale, entries: list[dict], wm: dict) -> np.ndarray:
    """手前の草：範囲の中で「水の色でない所」。岸に重なる帯では白い穂と金の茎だけ。"""
    H, W = v.shape
    fg = np.zeros((H, W), bool)
    # 水：藍〜青緑（岸の木の暗い映り込みを含む）。草の葉は黄緑なので分かれる
    waterish = (wm["bluish"] & (s >= 25)) | (hue_in(h, [85, 125]) & (s >= 25) & (v >= 15))
    # 範囲の外から入り込んでいる蓮の葉は除く
    n, lab, st, _ = cv2.connectedComponentsWithStats(wm["pads"].astype(np.uint8), 8)
    for e in entries:
        zone = sc.poly_mask(e["zone"])
        keep_water = sc.shapes_mask({"rects": e.get("reflect_rects", [])})
        wat = waterish | (wm["warm"] & keep_water)
        m = zone & ~wat & ~wm["lotus"]
        inside = np.bincount(lab.ravel(), zone.ravel().astype(np.float64), n) / np.maximum(st[:, cv2.CC_STAT_AREA], 1)
        outside_pads = (inside < 0.5)
        outside_pads[0] = False
        m &= ~outside_pads[lab]
        if e.get("band"):
            band = sc.poly_mask(e["band"])
            whitish = (s < 90) & (v > 150)
            stem = hue_in(h, [15, 35]) & (s >= 60) & (v >= 140)
            pick = cv2.dilate((whitish | stem).astype(np.uint8), _ellipse(3 * sc.s)) > 0
            m |= band & pick & (whitish | stem | (v < 60))
        m = remove_small(m, int(12 * sc.s ** 2))
        # 草の墨の輪郭（ほぼ黒）も草といっしょに動かす（水に残すと、揺れたときに影のように見える）
        m |= (cv2.dilate(m.astype(np.uint8), _ellipse(5 * sc.s)) > 0) & (v < 45) & zone
        fg |= m
    return fg


def find_lights(I, h, s, v, sc: Scale, cfg: dict, water_zone: np.ndarray) -> tuple[np.ndarray, list[dict]]:
    """窓・戸口・灯籠：spots（[x, y, r]）の中の明るい橙。ひとつの spot をひとつの灯りとしてゆらす。"""
    H, W = v.shape
    labels = np.zeros((H, W), np.uint8)
    lights = []
    if not cfg:
        return labels, lights
    bright = hue_in(h, cfg.get("hue", [5, 35])) & (s >= cfg.get("min_sat", 100)) & (v >= cfg.get("min_value", 200))
    bright &= ~water_zone
    for x, y, r in cfg.get("spots", [])[:250]:
        m = sc.shapes_mask({"circles": [[x, y, r]]}) & bright
        if m.sum() < 3:
            continue
        idx = len(lights) + 1
        labels[m] = idx
        ys, xs = np.nonzero(m)
        lights.append({"id": idx, "bbox": [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1],
                       "center": [float(xs.mean()), float(ys.mean())], "area": int(m.sum())})
    return labels, lights


def depth_map(sc: Scale, cfg: dict) -> np.ndarray:
    H, W = sc.H, sc.W
    ground = cfg.get("ground", [[0, 0.3], [sc.H / sc.sy, 0.9]])
    ys = np.arange(H) / sc.sy
    g = np.interp(ys, [p[0] for p in ground], [p[1] for p in ground]).astype(np.float32)
    D = np.repeat(g[:, None], W, 1)
    for r in cfg.get("regions", []):
        D[sc.poly_mask(r["poly"])] = r["depth"]
    return cv2.GaussianBlur(D, (0, 0), max(1.0, cfg.get("soften", 30) * sc.s))


# --- まとめ ---------------------------------------------------------------------------

def run_cut(scene: dict, image_path: Path, out_dir: Path, log=print) -> dict:
    I = load_rgb(image_path)
    H, W = I.shape[:2]
    sc = Scale(scene.get("ref_size"), (W, H))
    k = sc.s
    h, s, v = rgb_to_hsv(I)
    Y = luminance(I)
    out_dir.mkdir(parents=True, exist_ok=True)

    log("  空と陸を分ける")
    sky_hard, moon = sky_mask(I, h, s, v, Y, sc, scene["sky"])
    a_sky = soft_matte(I, sky_hard, r=max(1, round(2 * k)))
    stars0 = star_mask(Y, a_sky > 0.8, moon, k)

    log("  雲を切り抜く")
    a_cloud = cloud_alpha(I, h, s, v, Y, a_sky, moon, stars0, sc, scene.get("clouds", {}))
    log("  雲と陸の後ろの空を補う")
    plate = sky_plate(I, a_sky, a_cloud, moon, k)
    clouds = cloud_layer(I, a_sky, a_cloud, plate, k)
    sprites, sprite_lab = cloud_sprites(clouds[..., 3], a_cloud, k)

    log("  水・蓮・舟・手前の草を分ける")
    a_land = 1.0 - a_sky
    behind_sky = clouds[..., :3] * clouds[..., 3:] + plate * (1 - clouds[..., 3:])
    land_rgb = unmix(I, a_land, behind_sky)
    wm = water_masks(I, h, s, v, sc, scene["water"])
    fg_hard = foreground_mask(I, h, s, v, sc, scene.get("foreground", []), wm)
    a_fg = soft_matte(I, fg_hard, r=max(1, round(2 * k)), eps=1e-4)
    a_fg[~(cv2.dilate(fg_hard.astype(np.uint8), _ellipse(7 * k)) > 0)] = 0

    log("  手前の草の後ろを補う")
    hole = cv2.dilate((a_fg > 0.02).astype(np.uint8), _ellipse(9 * k)) > 0
    known = ~hole
    behind = I.copy()
    # 水の模様は横に長い筋なので、同じ行の左右の水から写す（草の近くの暗い縁は写さない）
    hw = hole & wm["zone"]
    if hw.any():
        clean = known & (wm["water"] > 0.8) & ~(cv2.dilate(hole.astype(np.uint8), _ellipse(9 * k)) > 0)
        clean &= ~(cv2.dilate(wm["warm"].astype(np.uint8), _ellipse(5 * k)) > 0)   # 灯りの映り込みの点は写さない
        offsets = [round(v * k) for v in (20, 34, 50, 70, 95, 125, 160, 210, 270, 350, 450)]
        fw = fill_rows(I, hw, clean, offsets=offsets, sigma=6 * k)
        behind[hw] = fw[hw]
    # 岸に重なる穂の後ろは、近くの岸から写す
    hb = hole & ~wm["zone"]
    if hb.any():
        fb = fill_plate(I, known, patch=max(8, round(16 * k)), sigma=4 * k, y_window=round(20 * k),
                        x_window=round(220 * k), source=known & ~wm["zone"], seed=4)
        behind[hb] = fb[hb]
    land_rgb = np.where(hole[..., None], behind, land_rgb)
    fg_rgb = unmix(I, a_fg, behind)
    water = np.where(hole, np.maximum(wm["water"], wm["zone"].astype(np.float32)), wm["water"])
    reflect = wm["reflect"] & ~hole

    lights_lab, lights = find_lights(I, h, s, v, sc, scene.get("lights", {}), wm["zone"])
    stars = star_mask(luminance(plate), cv2.dilate(sky_hard.astype(np.uint8), _ellipse(31 * k)) > 0, moon, k)
    depth = depth_map(sc, scene.get("depth", {}))

    n, floaters, _, _ = cv2.connectedComponentsWithStats((wm["pads"] | wm["lotus"]).astype(np.uint8), 8)
    floaters = np.minimum(floaters, 255).astype(np.uint8)
    lotus_ids = sorted(set(np.unique(floaters[wm["lotus"]]).tolist()) - {0})

    log("  保存")
    save_png(out_dir / "sky_plate.png", plate)
    save_png(out_dir / "clouds.png", clouds)
    save_png(out_dir / "land.png", np.dstack([land_rgb, a_land]))
    save_png(out_dir / "foreground.png", np.dstack([fg_rgb, a_fg]))
    save_png(out_dir / "water.png", water)
    save_png(out_dir / "reflect.png", reflect.astype(np.float32))
    save_png(out_dir / "boat.png", wm["boat"].astype(np.float32))
    save_png(out_dir / "stars.png", stars.astype(np.float32))
    save_png(out_dir / "depth.png", depth, bits=16)
    imwrite(out_dir / "floaters.png", floaters)
    imwrite(out_dir / "lights.png", lights_lab)
    imwrite(out_dir / "cloud_sprites.png", np.minimum(sprite_lab, 255).astype(np.uint8))
    meta = {"version": CUT_VERSION, "size": [W, H], "scale": k, "moon": moon, "sprites": sprites,
            "lights": lights, "lotus_ids": lotus_ids, "scene": scene.get("name", "")}
    (out_dir / "cut.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    save_png(out_dir / "overlay.png", _overlay(I, a_sky, clouds[..., 3] * a_sky, wm, a_fg, lights_lab, stars))
    return meta


def _overlay(I, a_sky, a_cloud, wm, a_fg, lights, stars) -> np.ndarray:
    """確認用：空=藍、雲=白、水=水色、蓮=緑、舟と桟橋=橙、手前の草=黄、灯り=赤。境目は線で描く。"""
    out = I * 0.55
    def tint(mask, color, k=0.45):
        nonlocal out
        m = np.clip(mask.astype(np.float32), 0, 1)[..., None] * k
        out = out * (1 - m) + np.array(color, np.float32) * m
    tint(a_sky * (1 - a_cloud), (0.15, 0.25, 0.9), 0.35)
    tint(a_cloud, (1, 1, 1), 0.45)
    tint(wm["water"], (0.1, 0.8, 0.9), 0.3)
    tint(wm["pads"] | wm["lotus"], (0.2, 0.95, 0.3), 0.55)
    tint(wm["boat"] | wm["jetty"], (1.0, 0.55, 0.1), 0.6)
    tint(a_fg, (1.0, 0.9, 0.1), 0.5)
    tint(lights > 0, (1, 0.1, 0.1), 0.8)
    tint(stars, (1, 1, 0.3), 0.8)
    for m, col in ((a_sky > 0.5, (0.3, 0.5, 1.0)), (a_fg > 0.5, (1, 1, 0))):
        cnt, _ = cv2.findContours(m.astype(np.uint8), cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
        tmp = np.ascontiguousarray(out)
        cv2.drawContours(tmp, cnt, -1, col, 1)
        out = tmp
    return out
