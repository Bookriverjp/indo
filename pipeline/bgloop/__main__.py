"""背景ループ：1枚絵から「雲が流れ、川が流れ、木と草が風に揺れ、蛍と花びらが舞う」継ぎ目のないループ動画を作る。

使い方:
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

from pipeline.bgloop.scene import SceneError, load_scene
from pipeline.bgloop.video import render_video, write_stills
from pipeline.config import PROJECT_ROOT, ConfigError, load_yaml


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
    parser.add_argument("scene", help="scene YAML (assets/bgloop/<name>.yaml)")
    parser.add_argument("--image", help="picture to use instead of the one named in the scene")
    parser.add_argument("--stage", choices=["all", "cut", "render"], default="all")
    parser.add_argument("--preview", action="store_true", help="half size -> preview.mp4")
    parser.add_argument("--seconds", type=float)
    parser.add_argument("--fps", type=int)
    parser.add_argument("--workers", type=int)
    parser.add_argument("--stills", help="comma separated frame numbers to save as PNG")
    parser.add_argument("--out", help="output folder (default: output/bgloop/<name>)")
    args = parser.parse_args(argv)
    root = project_root or PROJECT_ROOT

    try:
        cfg = load_yaml("config/bgloop.yaml", root)["bgloop"]
        scene_path = Path(args.scene)
        if not scene_path.is_absolute():
            scene_path = (root / scene_path) if (root / scene_path).exists() else scene_path
        scene = load_scene(scene_path)
        name = scene.get("name") or scene_path.stem
        out_dir = Path(args.out) if args.out else root / cfg.get("out_dir", "output/bgloop") / name
        cut_dir = out_dir / "cut"

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
    except (SceneError, ConfigError, FileNotFoundError, KeyError, RuntimeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
