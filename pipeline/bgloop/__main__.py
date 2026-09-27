"""背景ループ：1枚絵から「雲が流れ、川が流れ、木と草が風に揺れ、蛍と花びらが舞う」継ぎ目のないループ動画を作る。

使い方:
  python -m pipeline.bgloop 新しい絵.png --stage grid                         # 座標の目盛りの絵 grid.png と、シーン設定のひな形 新しい絵.yaml
  python -m pipeline.bgloop assets/bgloop/night_river.yaml                  # 切り抜き → 書き出し
  python -m pipeline.bgloop assets/bgloop/night_river.yaml --image 元の絵.png   # 画像を差し替える
  python -m pipeline.bgloop assets/bgloop/night_river.yaml --preview        # 確認用（半分の大きさ）
  --stage cut      切り抜きだけ（output/bgloop/<name>/cut/ に層とマスク、overlay.png が確認用）
  --stage render   書き出しだけ（cut/ の画像を手で直したあとなど）
  --stills 0,240   そのコマを PNG で書き出す（stills/）
  --seconds 24 --fps 30 --workers 4
出力: output/bgloop/<name>/loop.mp4（--preview は preview.mp4）と確認用の index.html
"""
from __future__ import annotations

import argparse
import html
import sys
from pathlib import Path

import yaml

from pipeline.bgloop.scene import SceneError, load_scene
from pipeline.bgloop.video import render_video, write_stills

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")
DEFAULTS = {"seconds": 24, "fps": 30, "size": [1920, 1080], "overscan": 1.04, "seed": 7, "workers": 4,
            "video": {"crf": 15, "preset": "slow", "tune": "grain"}, "preview": {"scale": 0.5},
            "out_dir": "output/bgloop"}


def _find_root(start: Path) -> Path:
    """config/bgloop.yaml のあるフォルダ（このプロジェクトでも、単体の bgloop_kit でも動くように）。"""
    for p in (start, *start.parents):
        if (p / "config" / "bgloop.yaml").exists():
            return p
    return Path.cwd()


PROJECT_ROOT = _find_root(Path(__file__).resolve().parent)


def load_config(root: Path) -> dict:
    path = root / "config" / "bgloop.yaml"
    if not path.exists():
        return dict(DEFAULTS)
    try:
        data = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("bgloop") or {}
    except yaml.YAMLError as e:
        raise SceneError(f"invalid YAML in {path}: {e}") from None
    return {**DEFAULTS, **data}


def write_grid(image: Path, out: Path) -> Path:
    """座標の目盛りを重ねた絵。シーン設定の座標（元の絵の px）を読み取るのに使う。"""
    from PIL import Image, ImageDraw, ImageFont

    with Image.open(image) as im:
        im = im.convert("RGB")
    W, H = im.size
    step = next((s for s in (25, 50, 100, 200, 250, 500) if W / s <= 24), 1000)
    try:
        font = ImageFont.load_default(size=max(14, round(W / 90)))
    except TypeError:                                   # Pillow 10.0 以前
        font = ImageFont.load_default()
    d = ImageDraw.Draw(im)
    for x in range(0, W, step):
        d.line([(x, 0), (x, H)], fill=(255, 70, 70), width=1)
    for y in range(0, H, step):
        d.line([(0, y), (W, y)], fill=(70, 230, 70), width=1)
    label = {"fill": (255, 255, 0), "stroke_width": 2, "stroke_fill": (0, 0, 0), "font": font}
    for x in range(step, W, step):                       # 上の端と下の端に x、左の端と右の端に y
        d.text((x + 3, 2), str(x), **label)
        d.text((x + 3, H - font.size - 6), str(x), **label)
    for y in range(step, H, step):
        d.text((3, y + 2), str(y), **label)
        d.text((W - d.textlength(str(y), font=font) - 6, y + 2), str(y), **label)
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out)
    return out


def starter_scene(image: Path) -> str:
    """新しい絵のシーン設定のひな形。座標は絵の大きさからの だいたいの値なので、grid.png を見て直す。"""
    from PIL import Image

    with Image.open(image) as im:
        W, H = im.size
    Y = lambda f: round(H * f)
    return f"""# 背景ループのシーン設定（ひな形）。座標は この絵（{W}x{H}）の px。grid.png の目盛りを見て直す
# 書き方の見本: assets/bgloop/night_river.yaml / 説明: README.md の「新しい絵で作る」
name: {image.stem}
image: {image.name}
ref_size: [{W}, {H}]

sky:
  hue: [98, 118]                 # 空の色相（OpenCV の HSV、H: 0-180）。夜の藍。夕焼けなら [0, 30] など
  min_value: 42
  zone: [[0, 0], [{W}, 0], [{W}, {Y(0.55)}], [0, {Y(0.55)}]]    # 空がありうる範囲（多角形）
  grabcut: []                    # 空と色が近い木立などの矩形 [x0, y0, x1, y1]
  sure_sky: {{rects: [[0, 0, {W}, {Y(0.1)}]]}}                  # 必ず空の所
  sure_land: {{rects: [[0, {Y(0.6)}, {W}, {H}]]}}               # 必ず空でない所（lines: 幹 [x0,y0,x1,y1,太さ]）
  # moon: [x, y]                 # 月があれば だいたいの中心

clouds: {{}}

water:
  zone: [[0, {Y(0.7)}], [{W}, {Y(0.7)}], [{W}, {H}], [0, {H}]]   # 水面の範囲（多角形）
  hue: [96, 122]
  lotus: []                      # 蓮の花 [x, y, 半径]
  # boat: [x0, y0, x1, y1]       # 舟（ゆっくり上下）
  # jetty: [x0, y0, x1, y1]      # 桟橋（揺らさない）

foreground: []                   # 手前の草（風で揺らす層）: - {{name: reeds, zone: [[x, y], ...]}}

lights: {{hue: [5, 35], min_sat: 100, min_value: 190, spots: []}}   # 窓・灯籠 [x, y, 半径]

depth:
  sky: 0.04
  clouds: [0.07, 0.13]
  ground: [[{Y(0.6)}, 0.3], [{H}, 0.95]]   # y ごとの奥行き（0=空、1=手前）
  regions: []
  foreground: 1.0
  soften: 30

motion:
  camera: {{shift: [12, 4], zoom: 0.008}}
  wind: {{speed: 520}}
  clouds: {{drift: 9, billow: 1.8}}
  stars: {{twinkle: 0.45}}
  water: {{flow: [1.2, 8.0], ripple: [0.35, 1.8], shimmer: 2.4, glint: 0.35, pads: 0.7, boat: 1.1}}
  lights: {{flicker: 0.07}}
  sway: []                       # 揺れる木: {{name: palm, base: [x, y], top: [x, y], radius: 60, amp: 3}}
                                 #          {{name: tree, base: [x, y], amp: 2, flutter: 0.6, poly: [[x, y], ...]}}
  protect: []                    # 揺らさない物（家など）の多角形
  reeds: {{amp: 5.5, top: {Y(0.65)}, bottom: {H}, flutter: 0.8}}

fx:
  fireflies: {{count: 20, zone: [[0, {Y(0.5)}], [{W}, {Y(0.5)}], [{W}, {Y(0.8)}], [0, {Y(0.8)}]]}}
  mist:
    - {{rect: [0, {Y(0.55)}, {W}, {Y(0.7)}], opacity: 0.15, speed: -6}}
  bloom: {{threshold: 0.7, strength: 0.18}}
  vignette: 0.22
"""


def write_review(out_dir: Path, name: str, video: str, seconds: float, fps: int) -> Path:
    """確認用のページ（動画のループ再生と、切り抜いた層）。"""
    layers = [("overlay.png", "切り抜きの確認（空=藍・雲=白・水=水色・蓮=緑・舟=橙・手前の草=黄・灯り=赤）"),
              ("sky_plate.png", "空（雲と陸を取り除いて補った板）"), ("clouds.png", "雲（陸に隠れた所も補ってある）"),
              ("land.png", "陸（空以外。手前の草の後ろは水で補ってある）"), ("foreground.png", "手前の草")]
    items = "\n".join(f'<figure><img src="cut/{f}" loading="lazy"><figcaption>{html.escape(c)}</figcaption></figure>'
                      for f, c in layers if (out_dir / "cut" / f).exists())
    page = f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(name)} 背景ループ</title>
<style>
body{{margin:0;background:#101218;color:#e8e4da;font-family:system-ui,sans-serif}}
main{{max-width:1280px;margin:0 auto;padding:16px}}
video{{width:100%;height:auto;display:block;background:#000}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px;margin-top:16px}}
figure{{margin:0;background:repeating-conic-gradient(#2a2d36 0 25%,#1d2028 0 50%) 0 0/16px 16px}}
figure img{{width:100%;display:block}} figcaption{{background:#101218;font-size:13px;padding:6px 2px}}
</style></head><body><main>
<h1 style="font-size:20px">{html.escape(name)}：背景ループ（{seconds:g}秒・{fps}fps・継ぎ目なし）</h1>
<video src="{html.escape(video)}" autoplay loop muted playsinline controls></video>
<div class="grid">{items}</div>
</main></body></html>
"""
    p = out_dir / "index.html"
    p.write_text(page, encoding="utf-8", newline="\n")
    return p


def main(argv: list[str] | None = None, project_root: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description="Make a seamless background loop from one picture")
    parser.add_argument("scene", help="scene YAML (assets/bgloop/<name>.yaml), or a picture with --stage grid")
    parser.add_argument("--image", help="picture to use instead of the one named in the scene")
    parser.add_argument("--stage", choices=["all", "grid", "cut", "render"], default="all")
    parser.add_argument("--preview", action="store_true", help="half size -> preview.mp4")
    parser.add_argument("--seconds", type=float)
    parser.add_argument("--fps", type=int)
    parser.add_argument("--workers", type=int)
    parser.add_argument("--stills", help="comma separated frame numbers to save as PNG")
    parser.add_argument("--out", help="output folder (default: output/bgloop/<name>)")
    args = parser.parse_args(argv)
    root = project_root or PROJECT_ROOT

    try:
        cfg = load_config(root)
        scene_path = Path(args.scene)
        if not scene_path.is_absolute():
            scene_path = (root / scene_path) if (root / scene_path).exists() else scene_path
        if scene_path.suffix.lower() in IMAGE_EXTENSIONS:       # 絵を直接渡したとき：同じ名前の .yaml を使う
            picture = scene_path
            scene_path = picture.with_suffix(".yaml")
            if args.stage == "grid":
                if not picture.exists():
                    raise FileNotFoundError(f"image not found: {picture}")
                out_dir = Path(args.out) if args.out else root / cfg.get("out_dir", "output/bgloop") / picture.stem
                print(f"saved: {write_grid(picture, out_dir / 'grid.png')}")
                if scene_path.exists():
                    print(f"シーン設定はそのまま: {scene_path}")
                else:
                    scene_path.write_text(starter_scene(picture), encoding="utf-8", newline="\n")
                    print(f"saved: {scene_path}（ひな形。grid.png を見て座標を直す）")
                return 0
            if not scene_path.exists():
                raise FileNotFoundError(f"scene file not found: {scene_path}（先に --stage grid でひな形を作る）")
        scene = load_scene(scene_path)
        name = scene.get("name") or scene_path.stem
        out_dir = Path(args.out) if args.out else root / cfg.get("out_dir", "output/bgloop") / name
        cut_dir = out_dir / "cut"

        if args.stage == "grid":
            image = Path(args.image) if args.image else scene_path.parent / scene["image"]
            print(f"saved: {write_grid(image, out_dir / 'grid.png')}")
            return 0
        if args.stage in ("all", "cut"):
            from pipeline.bgloop.cut import run_cut
            image = Path(args.image) if args.image else scene_path.parent / scene["image"]
            if not image.exists():
                raise FileNotFoundError(f"image not found: {image}")
            print(f"切り抜き: {image} → {cut_dir}")
            run_cut(scene, image, cut_dir)
        if args.stage == "cut":
            print(f"saved: {cut_dir}（確認用: {cut_dir / 'overlay.png'}）")
            return 0
        if not (cut_dir / "cut.json").exists():
            raise FileNotFoundError(f"cut not found: {cut_dir}（先に --stage cut）")

        W, H = cfg.get("size", [1920, 1080])
        if args.preview:
            k = cfg.get("preview", {}).get("scale", 0.5)
            W, H = round(W * k / 2) * 2, round(H * k / 2) * 2
        kwargs = {"cut_dir": cut_dir, "scene": scene, "seconds": args.seconds or cfg.get("seconds", 24),
                  "fps": args.fps or cfg.get("fps", 30), "size": (W, H), "overscan": cfg.get("overscan", 1.04),
                  "seed": cfg.get("seed", 7)}
        if args.stills:
            frames = [int(v) for v in args.stills.split(",") if v.strip()]
            for p in write_stills(kwargs, frames, out_dir / "stills"):
                print(f"saved: {p}")
            return 0
        video = "preview.mp4" if args.preview else "loop.mp4"
        v = cfg.get("video", {})
        workers = args.workers or cfg.get("workers", 4)
        print(f"書き出し: {W}x{H} {kwargs['fps']}fps {kwargs['seconds']:g}秒のループ → {out_dir / video}")
        render_video(kwargs, out_dir / video, crf=v.get("crf", 16), preset=v.get("preset", "slow"), workers=workers,
                     tune=v.get("tune", "grain"))
        page = write_review(out_dir, name, video, kwargs["seconds"], kwargs["fps"])
        print(f"saved: {out_dir / video}")
        print(f"確認用: {page}")
    except (SceneError, FileNotFoundError, KeyError, RuntimeError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
