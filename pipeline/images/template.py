"""Owner 指定の構図画像から、紙芝居舞台テンプレート（共通素材）を作る。"""
from __future__ import annotations

from PIL import Image, ImageStat


def _median_color(im: Image.Image, box: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    return tuple(int(v) for v in ImageStat.Stat(im.crop(box).convert("RGB")).median) + (255,)


def _box(b: dict) -> tuple[int, int, int, int]:
    return b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"]


def build_stage_template(base: Image.Image, stage: dict, size: tuple[int, int] = (1920, 1080)) -> Image.Image:
    """- 物語の絵の窓（story_art）を透明に抜く
    - 字幕枠と地域ラベル枠の見本文字を、枠の地の色で塗りつぶす
    - 参照画像に描かれた大仏飴を、右パネルの地の色で塗りつぶす（本番の大仏飴はパーツで上に重ねる）
    """
    im = base.convert("RGBA").resize(size, Image.LANCZOS)

    for key in ("subtitle", "region_label"):
        b = _box(stage[key])
        im.paste(_median_color(im, b), b)

    n = stage["narrator"]
    bottom = min(n["y"] + n["h"], stage["rug"]["y"]) if "rug" in stage else n["y"] + n["h"]
    sample = (n["x"], max(0, n["y"] - 90), n["x"] + n["w"], n["y"] - 10)
    im.paste(_median_color(im, sample), (n["x"], n["y"], n["x"] + n["w"], bottom))

    a = _box(stage["story_art"])
    im.paste((0, 0, 0, 0), a)
    return im
