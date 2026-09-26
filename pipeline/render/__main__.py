"""PHASE 8: タイムラインどおりに紙芝居動画（MP4）を書き出す。

使い方:
  python -m pipeline.render EP0001_nishi_daak                 # 本番: output/episode.mp4（1920x1080, 30fps）
  python -m pipeline.render EP0001_nishi_daak --preview       # 確認用: output/preview.mp4（半分の大きさ、15fps）
  --start 秒 --duration 秒   一部分だけ書き出す
  --placeholders             まだない素材画像を、名前入りの仮の絵で代用する
  --draft                    Owner 未承認の大仏飴パーツで書き出す（画面に「下書き」と出る）
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import subprocess
import sys
import wave
from functools import lru_cache
from pathlib import Path

import yaml
from PIL import Image, ImageDraw, ImageFont

from pipeline.config import PROJECT_ROOT, ConfigError, load_yaml
from pipeline.render.audio import frame_levels, mix_narration
from pipeline.render.narrator import NarratorRig, blink_frames
from pipeline.workspace import episode_paths

STAGE_TEMPLATE = "assets/shared/stage_template.png"
DAIBUTSUAME_DIR = "assets/shared/daibutsuame"


class RenderError(Exception):
    pass


def _smooth(p: float) -> float:
    p = min(1.0, max(0.0, p))
    return p * p * (3 - 2 * p)


class Renderer:
    def __init__(self, root: Path, episode_id: str, *, scale: float = 1.0, fps: int | None = None,
                 placeholders: bool = False, draft: bool = False):
        self.root = root
        self.paths = episode_paths(root, episode_id)
        self.episode_dir = self.paths["timeline"].parents[1]
        self.timeline = self._json(self.paths["timeline"])
        manifest = self._json(self.paths["asset_manifest"])
        self.assets = {a["asset_id"]: a for a in manifest["assets"]}
        self.layouts = load_yaml("config/layout.yaml", root)["main"]["layouts"]
        self.cfg = load_yaml("config/render.yaml", root)["render"]
        self.scale = scale
        self.fps = fps or self.timeline["fps"]
        self.W, self.H = round(self.timeline["width"] * scale), round(self.timeline["height"] * scale)
        self.placeholders = placeholders
        self.draft = draft

        self._check_inputs()
        with Image.open(root / STAGE_TEMPLATE) as t:
            self.template = t.convert("RGBA").resize((self.W, self.H), Image.LANCZOS)
        self.rig = NarratorRig(root / DAIBUTSUAME_DIR, self.cfg["narrator"])
        self.samples, self.rate = mix_narration(self.timeline["audio"], self.episode_dir, self.timeline["total_seconds"])
        self.mouth = frame_levels(self.samples, self.rate, self.fps, self.timeline["audio"],
                                  self.cfg["narrator"]["lipsync_threshold"])
        self.blinks = blink_frames(total_seconds=self.timeline["total_seconds"], fps=self.fps,
                                   cfg=self.cfg["narrator"]["blink"], seed=episode_id)
        self._scene_cache: dict[str, dict] = {}
        self._last_frame_cache: dict[str, Image.Image] = {}

    # --- 準備 -------------------------------------------------------------------------

    @staticmethod
    def _json(path: Path) -> dict:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise RenderError(f"input not found: {path}") from None

    def _check_inputs(self) -> None:
        missing = [a["asset_id"] for a in self.assets.values()
                   if a["scope"] == "episode" and not (self.episode_dir / a["file"]).exists()]
        if missing and not self.placeholders:
            raise RenderError("素材画像がありません: " + ", ".join(missing) +
                              "（python -m pipeline.images check、または --placeholders で仮の絵を使う）")
        uses_narrator = any(l["slot"] == "narrator" for s in self.timeline["scenes"] for l in s["layers"])
        if uses_narrator and not self.draft:
            approval = self.root / DAIBUTSUAME_DIR / "approval.yaml"
            ok = approval.exists() and bool((yaml.safe_load(approval.read_text(encoding="utf-8")) or {}).get("approved"))
            if not ok:
                raise RenderError("大仏飴パーツが Owner 未承認です（approval.yaml）。確認用なら --draft を付ける")

    def s(self, v: float) -> int:
        return round(v * self.scale)

    def box(self, b: dict) -> tuple[int, int, int, int]:
        return self.s(b["x"]), self.s(b["y"]), self.s(b["w"]), self.s(b["h"])

    @lru_cache(maxsize=32)
    def font(self, kind: str, px: int) -> ImageFont.FreeTypeFont:
        return ImageFont.truetype(str(self.root / self.cfg["fonts"][kind]), max(8, px))

    @lru_cache(maxsize=8)
    def script_font(self, script: str | None, px: int) -> ImageFont.FreeTypeFont | None:
        path = (self.cfg["fonts"].get("scripts") or {}).get(script or "")
        return ImageFont.truetype(str(self.root / path), max(8, px)) if path else None

    def _placeholder(self, asset: dict, size: tuple[int, int]) -> Image.Image:
        h = hashlib.md5(asset["asset_id"].encode()).digest()
        color = (60 + h[0] % 120, 60 + h[1] % 120, 90 + h[2] % 120)
        w, hh = size
        if asset["kind"] == "background":
            img = Image.new("RGBA", size, color + (255,))
            d = ImageDraw.Draw(img)
            for y in range(0, hh, 4):
                k = y / max(1, hh)
                d.line([(0, y), (w, y)], fill=tuple(int(c * (0.6 + 0.4 * k)) for c in color) + (255,), width=4)
        else:
            img = Image.new("RGBA", size, (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            d.rounded_rectangle((2, 2, w - 3, hh - 3), radius=max(4, min(size) // 8), fill=color + (200,),
                                outline=(255, 255, 255, 230), width=max(1, self.s(3)))
        self._text_center(img, (0, 0, w, hh), [asset["label"]], self.font("gothic", max(10, min(w, hh) // 8)),
                          (255, 255, 255), stroke=(0, 0, 0))
        return img

    def _asset_image(self, asset_id: str, size: tuple[int, int], fit: str) -> Image.Image:
        asset = self.assets[asset_id]
        path = self.episode_dir / asset["file"]
        if path.exists():
            with Image.open(path) as im:
                src = im.convert("RGBA")
        else:
            return self._placeholder(asset, size)
        w, h = size
        k = max(w / src.width, h / src.height) if fit == "cover" else min(w / src.width, h / src.height)
        src = src.resize((max(1, round(src.width * k)), max(1, round(src.height * k))), Image.LANCZOS)
        out = Image.new("RGBA", size, (0, 0, 0, 0))
        if fit == "cover":
            out.alpha_composite(src.crop(((src.width - w) // 2, (src.height - h) // 2,
                                          (src.width - w) // 2 + w, (src.height - h) // 2 + h)))
        else:  # contain: 下端・中央にそろえる
            out.alpha_composite(src, ((w - src.width) // 2, h - src.height))
        return out

    def _scene(self, scene: dict) -> dict:
        if scene["scene_id"] in self._scene_cache:
            return self._scene_cache[scene["scene_id"]]
        lcfg = self.layouts[scene["layout"]]
        prep = {"slot": self.box(lcfg["story_art"]) if "story_art" in lcfg else None, "fx": [], "art": None, "card": None}
        if prep["slot"]:
            sx, sy, sw, sh = prep["slot"]
            art = Image.new("RGBA", (sw, sh), (20, 20, 30, 255))
            for layer in sorted((l for l in scene["layers"] if l["slot"] == "story_art"), key=lambda l: l["z"]):
                bx, by, bw, bh = layer["box"]
                size = (max(1, round(bw * sw)), max(1, round(bh * sh)))
                fit = "cover" if layer["layer"] in ("background", "fx") else "contain"
                img = self._asset_image(layer["asset_id"], size, fit)
                pos = (round(bx * sw), round(by * sh))
                if layer["layer"] == "fx" and scene["motion"]["fx_animation"]:
                    prep["fx"].append((img, pos))
                else:
                    art.alpha_composite(img, pos)
            prep["art"] = art
        if scene["card"]:
            prep["card"] = self._card(scene["card"], self.box(lcfg["info_card"]))
        self._scene_cache[scene["scene_id"]] = prep
        return prep

    def _card(self, card: dict, box: tuple[int, int, int, int]) -> Image.Image:
        _, _, w, h = box
        c = self.cfg["colors"]
        img = Image.new("RGBA", (w, h), tuple(c["card_bg"]) + (255,))
        d = ImageDraw.Draw(img)
        b = max(2, self.s(6))
        d.rectangle((0, 0, w - 1, h - 1), outline=tuple(c["card_border"]), width=b)
        d.rectangle((b * 2, b * 2, w - 1 - b * 2, h - 1 - b * 2), outline=tuple(c["card_accent"]), width=max(1, b // 3))
        pad = self.s(48)
        title_font = self.font("mincho", self.s(self.cfg["sizes"]["card_title"]))
        d.text((pad, pad), card["title"], font=title_font, fill=tuple(c["ink"]))
        row_font = self.font("gothic", self.s(self.cfg["sizes"]["card_row"]))
        y = pad + self.s(self.cfg["sizes"]["card_title"]) + self.s(36)
        label_w = max((d.textlength(k, font=row_font) for k, _ in card["rows"]), default=0) + self.s(28)
        line_h = round(self.s(self.cfg["sizes"]["card_row"]) * 1.45)
        for label, value in card["rows"]:
            if y + line_h > h - pad:
                break
            d.text((pad, y), label, font=row_font, fill=tuple(c["card_accent"]))
            value_font = row_font
            if label == "現地名":
                value_font = self.script_font(card.get("script"), self.s(self.cfg["sizes"]["card_row"])) or row_font
            for line in self._wrap(d, value, value_font, w - pad * 2 - label_w):
                if y + line_h > h - pad:
                    break
                d.text((pad + label_w, y), line, font=value_font, fill=tuple(c["ink"]))
                y += line_h
            y += self.s(10)
        return img

    @staticmethod
    def _wrap(d: ImageDraw.ImageDraw, text: str, font, width: float) -> list[str]:
        lines, cur = [], ""
        for ch in text:
            if d.textlength(cur + ch, font=font) > width and cur:
                lines.append(cur)
                cur = ch
            else:
                cur += ch
        return lines + ([cur] if cur else [])

    def _text_center(self, img: Image.Image, box: tuple[int, int, int, int], lines: list[str], font,
                     fill, stroke=None) -> None:
        d = ImageDraw.Draw(img)
        x, y, w, h = box
        sw = max(1, self.s(self.cfg["sizes"]["outline"])) if stroke else 0
        size = font.size
        while size > 8 and max(d.textlength(l, font=font) for l in lines) > w * 0.94:
            size -= 2
            font = ImageFont.truetype(font.path, size)
        line_h = round(size * 1.35)
        top = y + (h - line_h * len(lines)) // 2
        for i, line in enumerate(lines):
            lw = d.textlength(line, font=font)
            d.text((x + (w - lw) / 2, top + i * line_h + (line_h - size) / 2 - size * 0.1), line, font=font, fill=fill,
                   stroke_width=sw, stroke_fill=stroke)

    # --- 1コマ ------------------------------------------------------------------------

    def _scene_at(self, t: float) -> tuple[int, dict]:
        scenes = self.timeline["scenes"]
        for i, sc in enumerate(scenes):
            if sc["start"] <= t < sc["start"] + sc["duration"]:
                return i, sc
        return len(scenes) - 1, scenes[-1]

    def _compose(self, scene: dict, t: float) -> Image.Image:
        prep = self._scene(scene)
        lcfg = self.layouts[scene["layout"]]
        c = self.cfg["colors"]
        canvas = Image.new("RGBA", (self.W, self.H), (0, 0, 0, 255))
        local = t - scene["start"]
        p = _smooth(local / scene["duration"])

        if prep["art"] is not None:
            sx, sy, sw, sh = prep["slot"]
            m = scene["motion"]
            cam = [a + (b - a) * p for a, b in zip(m["camera_from"], m["camera_to"])]
            zoom = max(1.0, cam[0])
            art = prep["art"]
            if prep["fx"]:
                art = art.copy()
                for img, pos in prep["fx"]:
                    art.alpha_composite(*self._fx_frame(img, pos, m["fx_animation"], local, p, (sw, sh)))
            big = art.resize((round(sw * zoom), round(sh * zoom)), Image.BILINEAR) if zoom != 1.0 else art
            left = min(max(0, (big.width - sw) / 2 + cam[1] * sw), big.width - sw)
            top = min(max(0, (big.height - sh) / 2 + cam[2] * sh), big.height - sh)
            canvas.alpha_composite(big.crop((round(left), round(top), round(left) + sw, round(top) + sh)), (sx, sy))

        if any(l["slot"] == "template" for l in scene["layers"]):
            canvas.alpha_composite(self.template)
        if prep["card"] is not None:
            x, y, _, _ = self.box(lcfg["info_card"])
            canvas.alpha_composite(prep["card"], (x, y))

        label_box = self.box(lcfg["region_label"])
        label_font = self.font("gothic", self.s(self.cfg["sizes"]["label"]))
        if scene["layout"] == "fullbleed":
            x, y, w, h = label_box
            d = ImageDraw.Draw(canvas)
            d.rectangle((x, y, x + w, y + h), fill=tuple(c["chip_bg"]) + (240,))
            d.rectangle((x, y, x + max(2, self.s(8)), y + h), fill=tuple(c["card_accent"]) + (255,))
        self._text_center(canvas, label_box, [self.timeline["region_label"]], label_font, tuple(c["ink"]))

        nar = next((l for l in scene["layers"] if l["slot"] == "narrator"), None)
        if nar is not None:
            f = int(t * self.fps)
            track = next((n for n in self.timeline["narrator"] if n["start"] <= t < n["start"] + n["duration"]), None)
            expression = track["expression"] if track else "neutral"
            block_t = t - track["start"] if track else t
            ncfg = lcfg["narrator"]
            x, y, w, h = self.box(ncfg)
            img = self.rig.render((w, h), ncfg.get("style", "full_body"), t=block_t, expression=expression,
                                  eyes_closed=f in self.blinks,
                                  mouth_open=bool(track) and f < len(self.mouth) and self.mouth[f])
            canvas.alpha_composite(img, (x, y))

        sub = next((s for s in self.timeline["subtitles"] if s["start"] <= t < s["end"]), None)
        if sub is not None:
            font = self.font("gothic", self.s(self.cfg["sizes"]["subtitle"]))
            if scene["layout"] == "fullbleed":
                self._text_center(canvas, self.box(lcfg["subtitle"]), sub["lines"], font, tuple(c["light_text"]),
                                  stroke=tuple(c["outline"]))
            else:
                self._text_center(canvas, self.box(lcfg["subtitle"]), sub["lines"], font, tuple(c["ink"]))

        if self.draft:
            ImageDraw.Draw(canvas).text((self.s(12), self.H - self.s(34)), "下書き（大仏飴パーツ未承認）",
                                        font=self.font("gothic", self.s(22)), fill=(200, 40, 30, 255))
        return canvas

    def _fx_frame(self, img: Image.Image, pos: tuple[int, int], anim: str, local: float, p: float,
                  slot: tuple[int, int]):
        sw, sh = slot
        if anim == "drift":
            return img, (pos[0] + round((p - 0.5) * 0.06 * sw), pos[1])
        if anim == "flicker":
            k = 0.85 + 0.15 * abs(math.sin(local * 7))
            a = img.getchannel("A").point(lambda v: int(v * k))
            out = img.copy()
            out.putalpha(a)
            return out, pos
        if anim == "fall":
            return img, (pos[0], pos[1] + round(((local * 0.3) % 1 - 0.5) * 0.1 * sh))
        return img, pos

    def _last_frame(self, scene: dict) -> Image.Image:
        if scene["scene_id"] not in self._last_frame_cache:
            self._last_frame_cache[scene["scene_id"]] = self._compose(scene, scene["start"] + scene["duration"] - 1 / self.fps)
        return self._last_frame_cache[scene["scene_id"]]

    def frame(self, t: float) -> Image.Image:
        i, scene = self._scene_at(t)
        cur = self._compose(scene, t)
        tr = scene["transition_in"]
        local = t - scene["start"]
        if local < tr["duration"]:
            p = _smooth(local / tr["duration"])
            if tr["type"] == "fade_from_black" or i == 0:
                cur = Image.blend(Image.new("RGBA", cur.size, (0, 0, 0, 255)), cur, p)
            else:
                prev_scene = self.timeline["scenes"][i - 1]
                prev = self._last_frame(prev_scene)
                slot = self._scene(scene)["slot"]
                if tr["type"] == "card_pull" and slot:
                    x, y, w, h = slot
                    shift = round(p * w)
                    if shift < w:
                        cur.alpha_composite(prev.crop((x + shift, y, x + w, y + h)), (x, y))
                else:
                    cur = Image.blend(prev, cur, p)
        return cur.convert("RGB")

    # --- 書き出し ---------------------------------------------------------------------

    def render(self, out: Path, *, start: float = 0.0, duration: float | None = None, crf: int = 20,
               preset: str = "medium", audio_bitrate: str = "192k", progress=print) -> Path:
        import imageio_ffmpeg

        total = self.timeline["total_seconds"]
        end = total if duration is None else min(total, start + duration)
        f0, f1 = round(start * self.fps), round(end * self.fps)
        mix = self.paths["narration_mix"]
        mix.parent.mkdir(parents=True, exist_ok=True)
        s0, s1 = round(f0 / self.fps * self.rate), round(f1 / self.fps * self.rate)
        with wave.open(str(mix), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(self.rate)
            w.writeframes(self.samples[s0:s1].tobytes())

        out.parent.mkdir(parents=True, exist_ok=True)
        cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error",
               "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{self.W}x{self.H}", "-r", str(self.fps), "-i", "-",
               "-i", str(mix), "-map", "0:v", "-map", "1:a",
               "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-b:a", audio_bitrate, "-shortest", str(out)]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        try:
            n = f1 - f0
            for k, f in enumerate(range(f0, f1)):
                proc.stdin.write(self.frame(f / self.fps).tobytes())
                if progress and n >= 10 and k % max(1, n // 10) == 0:
                    progress(f"  {k * 100 // n}%  ({f / self.fps:.1f}s / {end:.1f}s)")
        finally:
            proc.stdin.close()
            code = proc.wait()
        if code != 0:
            raise RenderError(f"ffmpeg failed (exit {code})")
        return out


def main(argv: list[str] | None = None, project_root: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render the kamishibai video")
    parser.add_argument("episode_id")
    parser.add_argument("--preview", action="store_true", help="half size, lower fps -> output/preview.mp4")
    parser.add_argument("--scale", type=float, help="override output scale (1.0 = 1920x1080)")
    parser.add_argument("--fps", type=int, help="override fps")
    parser.add_argument("--start", type=float, default=0.0)
    parser.add_argument("--duration", type=float)
    parser.add_argument("--placeholders", action="store_true", help="use labeled placeholders for missing images")
    parser.add_argument("--draft", action="store_true", help="allow narrator parts not yet approved by the Owner")
    args = parser.parse_args(argv)
    root = project_root or PROJECT_ROOT

    try:
        cfg = load_yaml("config/render.yaml", root)["render"]
        scale = args.scale or (cfg["preview"]["scale"] if args.preview else 1.0)
        fps = args.fps or (cfg["preview"]["fps"] if args.preview else None)
        r = Renderer(root, args.episode_id, scale=scale, fps=fps, placeholders=args.placeholders, draft=args.draft)
        partial = args.start > 0 or args.duration is not None
        out = r.paths["preview_video"] if args.preview or partial else r.paths["episode_video"]
        print(f"書き出し: {r.W}x{r.H} {r.fps}fps → {out}")
        r.render(out, start=args.start, duration=args.duration, crf=cfg["video"]["crf"],
                 preset=cfg["video"]["preset"], audio_bitrate=cfg["video"]["audio_bitrate"])
        if out == r.paths["episode_video"] and r.paths["subtitles"].exists():
            shutil.copyfile(r.paths["subtitles"], r.paths["episode_srt"])
    except (RenderError, ValueError, ConfigError, FileNotFoundError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(f"saved: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
