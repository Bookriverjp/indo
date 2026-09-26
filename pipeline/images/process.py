"""取り込んだ画像のチェックと仕上げ（サイズ・透過・PNG化）。"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, UnidentifiedImageError

INPUT_EXTENSIONS = (".png", ".webp", ".jpg", ".jpeg")


def _cover(im: Image.Image, size: tuple[int, int]) -> Image.Image:
    """はみ出す分を中央で切り落として、ぴったり size にする。"""
    tw, th = size
    scale = max(tw / im.width, th / im.height)
    rw, rh = round(im.width * scale), round(im.height * scale)
    im = im.resize((rw, rh), Image.LANCZOS)
    left, top = (rw - tw) // 2, (rh - th) // 2
    return im.crop((left, top, left + tw, top + th))


def process_asset(src: Path, dst: Path, asset: dict, rules: dict) -> list[str]:
    """src を検査し、合格なら dst（PNG）に仕上げて保存する。問題があればその内容を返す。"""
    cfg = rules["kinds"][asset["kind"]]
    try:
        with Image.open(src) as opened:
            im = opened.copy()
    except (UnidentifiedImageError, OSError) as e:
        return [f"画像を開けません: {e}"]

    if min(im.size) < cfg["min_short_side"]:
        return [f"画像が小さすぎます（{im.width}x{im.height}、短い辺 {cfg['min_short_side']}px 以上）"]

    if asset["transparent"]:
        im = im.convert("RGBA")
        alpha = im.getchannel("A")
        clear = alpha.histogram()[0] / (im.width * im.height)
        if clear < rules["min_transparent_ratio"]:
            return [f"背景の透過がありません（透明な部分 {clear:.0%}）。背景を透明にした PNG で作り直してください"]
    else:
        im = im.convert("RGB")

    if cfg.get("output_size"):
        im = _cover(im, tuple(cfg["output_size"]))

    dst.parent.mkdir(parents=True, exist_ok=True)
    im.save(dst, "PNG")
    return []


def find_input(inbox: Path, asset_id: str) -> Path | None:
    for ext in INPUT_EXTENSIONS:
        for cand in (inbox / f"{asset_id}{ext}", inbox / f"{asset_id}{ext.upper()}"):
            if cand.exists():
                return cand
    return None
