"""背景ループのスクリプト一式を、このプロジェクトなしで動く bgloop_kit.zip にまとめる。

  python scripts/build_bgloop_kit.py            # → dist/bgloop_kit.zip
  python scripts/build_bgloop_kit.py --out 保存先.zip

中身は pipeline/bgloop の写し（import を `bgloop` に書き換え）、見本のシーン、設定、README、ChatGPT 用の説明。
"""
from __future__ import annotations

import argparse
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KIT = "bgloop_kit"

REQUIREMENTS = """numpy>=1.26
opencv-python-headless>=4.8
Pillow>=10.0
PyYAML>=6.0
imageio-ffmpeg>=0.5
"""
BAT = "@echo off\r\ncd /d %~dp0\r\nif exist .venv\\Scripts\\activate.bat call .venv\\Scripts\\activate.bat\r\n{cmd}\r\npause\r\n"


def _rewrite(text: str) -> str:
    text = text.replace("pipeline.bgloop", "bgloop")
    return re.sub(r"docs/BGLOOP\.md", "README.md", text)


def build(out: Path) -> Path:
    with tempfile.TemporaryDirectory() as tmp:
        kit = Path(tmp) / KIT
        pkg = kit / "bgloop"
        pkg.mkdir(parents=True)
        for src in sorted((ROOT / "pipeline" / "bgloop").glob("*.py")):
            (pkg / src.name).write_text(_rewrite(src.read_text(encoding="utf-8")), encoding="utf-8", newline="\n")
        (kit / "config").mkdir()
        shutil.copyfile(ROOT / "config" / "bgloop.yaml", kit / "config" / "bgloop.yaml")
        assets = kit / "assets" / "bgloop"
        assets.mkdir(parents=True)
        for src in sorted((ROOT / "assets" / "bgloop").iterdir()):
            if src.suffix == ".yaml":
                (assets / src.name).write_text(_rewrite(src.read_text(encoding="utf-8")), encoding="utf-8", newline="\n")
            elif src.is_file():
                shutil.copyfile(src, assets / src.name)
        for name in ("README.md", "GPT_INSTRUCTIONS.md"):
            shutil.copyfile(ROOT / "docs" / "bgloop_kit" / name, kit / name)
        (kit / "requirements.txt").write_text(REQUIREMENTS, encoding="utf-8", newline="\n")
        with (kit / "run_preview.bat").open("w", encoding="utf-8", newline="") as f:
            f.write(BAT.format(cmd="python -m bgloop assets/bgloop/night_river.yaml --preview"))
        with (kit / "run_full.bat").open("w", encoding="utf-8", newline="") as f:
            f.write(BAT.format(cmd="python -m bgloop assets/bgloop/night_river.yaml"))

        out.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for p in sorted(kit.rglob("*")):
                if p.is_file():
                    z.write(p, p.relative_to(kit.parent).as_posix())
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build bgloop_kit.zip")
    parser.add_argument("--out", default=str(ROOT / "dist" / f"{KIT}.zip"))
    args = parser.parse_args(argv)
    print(f"saved: {build(Path(args.out))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
