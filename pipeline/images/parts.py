"""大仏飴パーツのうち、基準画像からそのまま切り出せるもの（外見を変えない）。"""
from __future__ import annotations

from PIL import Image, ImageDraw, ImageFilter


def cut_ellipses(ref: Image.Image, ellipses: list[list[int]], feather: float = 3.0) -> Image.Image:
    """基準画像と同じ大きさの透明PNGに、楕円の範囲だけを残す（縁は少しぼかす）。"""
    mask = Image.new("L", ref.size, 0)
    draw = ImageDraw.Draw(mask)
    for cx, cy, rx, ry in ellipses:
        draw.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill=255)
    out = ref.convert("RGBA")
    out.putalpha(mask.filter(ImageFilter.GaussianBlur(feather)))
    return out


def _ellipse_value(xx, yy, cx, cy, rx, ry):
    return ((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2


def draft_minimal_parts(ref: Image.Image, eyes: list[list[int]], mouth: list[int],
                        fur_offsets: list[int]) -> dict[str, Image.Image]:
    """最小セットの手作業パーツの「仮」版を作る（Owner が確認して、必要なら描き直す）。

    - body_base: 口は周りから補間して消し、目は上（額）の毛並みを色を合わせて移植して消す
    - eyes_closed: 移植した毛並みの上に、閉じた目の弧を描く
    - mouth_closed: 鼻の下から分かれる小さな口の線
    """
    import cv2
    import numpy as np

    rgb = np.array(ref.convert("RGB")).astype(np.float32)
    h, w = rgb.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]

    mcx, mcy, mrx, mry = mouth
    mask = np.zeros((h, w), np.uint8)
    cv2.ellipse(mask, (mcx, mcy), (mrx + 4, mry + 4), 0, 0, 360, 255, -1)
    bgr = cv2.cvtColor(rgb.astype(np.uint8), cv2.COLOR_RGB2BGR)
    base = cv2.cvtColor(cv2.inpaint(bgr, mask, 9, cv2.INPAINT_TELEA), cv2.COLOR_BGR2RGB)

    fur = np.zeros((h, w, 4), np.float32)
    for (cx, cy, rx, ry), dy in zip(eyes, fur_offsets):
        src = np.roll(rgb, -dy, axis=0)
        ring = (_ellipse_value(xx, yy, cx, cy, rx + 18, ry + 18) <= 1) & (_ellipse_value(xx, yy, cx, cy, rx + 6, ry + 6) > 1)
        inner = _ellipse_value(xx, yy, cx, cy, rx + 6, ry + 6) <= 1
        matched = (src - src[inner].mean(0)) / (src[inner].std(0) + 1e-3) * rgb[ring].std(0) + rgb[ring].mean(0)
        alpha = cv2.GaussianBlur(np.clip(1.6 - _ellipse_value(xx, yy, cx, cy, rx + 8, ry + 8), 0, 1).astype(np.float32), (0, 0), 3)
        take = alpha > fur[..., 3]
        fur[..., :3][take] = matched[take]
        fur[..., 3] = np.maximum(fur[..., 3], alpha)
    fur_img = Image.fromarray(np.clip(np.dstack([fur[..., :3], fur[..., 3] * 255]), 0, 255).astype(np.uint8), "RGBA")

    body = Image.fromarray(base).convert("RGBA")
    body.alpha_composite(fur_img)

    closed = fur_img.copy()
    d = ImageDraw.Draw(closed)
    for cx, cy, _, _ in eyes:
        d.arc((cx - 30, cy - 22, cx + 30, cy + 18), start=20, end=160, fill=(45, 38, 40, 255), width=6)

    mouth_closed = Image.new("RGBA", ref.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(mouth_closed)
    col = (125, 80, 85, 255)
    d.line([(mcx + 9, mcy - 33), (mcx + 9, mcy - 15)], fill=col, width=4)
    d.arc((mcx - 23, mcy - 30, mcx + 11, mcy), start=10, end=110, fill=col, width=4)
    d.arc((mcx + 7, mcy - 30, mcx + 41, mcy), start=70, end=170, fill=col, width=4)

    return {"body_base.png": body, "eyes_closed.png": closed, "mouth_closed.png": mouth_closed}
