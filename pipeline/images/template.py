"""Owner 指定の構図画像から、紙芝居舞台テンプレート（共通素材）を作る。"""
from __future__ import annotations

from PIL import Image, ImageStat

from pipeline.images.parts import content_bbox, fit_full_body


def _median_color(im: Image.Image, box: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    return tuple(int(v) for v in ImageStat.Stat(im.crop(box).convert("RGB")).median) + (255,)


def _box(b: dict) -> tuple[int, int, int, int]:
    return b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"]


def _narrator_mask(size: tuple[int, int], stage: dict, body: Image.Image, shift_up: int = 70):
    """新しい大仏飴を描く位置の輪郭。構図画像の大仏飴（少し上にいる）も覆うよう、上へずらした輪郭も重ねる。"""
    import cv2
    import numpy as np

    n = stage["narrator"]
    bbox = content_bbox(body)
    k, ox, oy = fit_full_body(body.size, bbox, (n["w"], n["h"]))
    crop = body.crop(bbox)
    fit = crop.resize((max(1, round(crop.width * k)), max(1, round(crop.height * k))), Image.LANCZOS)
    sil = (np.array(fit.getchannel("A")) > 20).astype(np.uint8) * 255
    mask = np.zeros((size[1], size[0]), np.uint8)
    x0, y0 = n["x"] + ox, n["y"] + oy
    for dy in range(0, -shift_up - 1, -10):
        for dx in (-10, 0, 10):
            ys, xs = y0 + dy, x0 + dx
            region = mask[ys:ys + fit.height, xs:xs + fit.width]
            region[...] = np.maximum(region, sil[:region.shape[0], :region.shape[1]])
    mask = cv2.dilate(mask, np.ones((15, 15), np.uint8))
    if "rug" in stage:
        mask[stage["rug"]["y"] + 10:, :] = 0
    return mask


def build_stage_template(base: Image.Image, stage: dict, size: tuple[int, int] = (1920, 1080),
                         narrator_body: Image.Image | None = None) -> Image.Image:
    """- 物語の絵の窓（story_art）を透明に抜く
    - 字幕枠と地域ラベル枠の見本文字を、枠の地の色で塗りつぶす
    - 参照画像に描かれた大仏飴を消す。narrator_body（透過済みの体）があれば、その輪郭の周りだけを
      周囲の柄から補間して消す。なければ右パネルの地の色で四角く塗る（本番の大仏飴はパーツで上に重ねる）
    """
    im = base.convert("RGBA").resize(size, Image.LANCZOS)

    for key in ("subtitle", "region_label"):
        b = _box(stage[key])
        im.paste(_median_color(im, b), b)

    n = stage["narrator"]
    if narrator_body is not None:
        import cv2
        import numpy as np

        rgb = cv2.cvtColor(np.array(im.convert("RGB")), cv2.COLOR_RGB2BGR)
        filled = cv2.inpaint(rgb, _narrator_mask(size, stage, narrator_body), 15, cv2.INPAINT_TELEA)
        im = Image.fromarray(cv2.cvtColor(filled, cv2.COLOR_BGR2RGB)).convert("RGBA")
    else:
        bottom = min(n["y"] + n["h"], stage["rug"]["y"]) if "rug" in stage else n["y"] + n["h"]
        sample = (n["x"], max(0, n["y"] - 90), n["x"] + n["w"], n["y"] - 10)
        im.paste(_median_color(im, sample), (n["x"], n["y"], n["x"] + n["w"], bottom))

    a = _box(stage["story_art"])
    im.paste((0, 0, 0, 0), a)
    return im
