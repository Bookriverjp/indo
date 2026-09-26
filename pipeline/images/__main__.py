"""PHASE 5: 素材画像の生成と取り込み。

provider は config/image.yaml の image.provider で選ぶ（標準は manual）。

この回の素材:
  python -m pipeline.images request EP0001_nishi_daak   # 指示文の一覧 assets/image_requests.md を書き出す
  python -m pipeline.images check EP0001_nishi_daak     # assets/inbox/ の画像をチェックして generated/ に取り込む
  python -m pipeline.images generate EP0001_nishi_daak  # openai: API で生成して取り込む（--force で作り直し）
共通素材:
  python -m pipeline.images shared-template             # 構図の正本から紙芝居舞台テンプレートを作る
  python -m pipeline.images shared-request              # 大仏飴パーツの依頼書と承認ファイルを書き出す
  python -m pipeline.images shared-check                # 大仏飴パーツがそろい、Owner が承認済みかを確認する
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml
from PIL import Image

from pipeline.config import PROJECT_ROOT, ConfigError, load_yaml
from pipeline.images.base import ImageError, ImageProvider
from pipeline.images.process import INPUT_EXTENSIONS, find_input, process_asset
from pipeline.images.template import build_stage_template
from pipeline.llm.usage_log import append_usage
from pipeline.workspace import episode_paths

STAGE_REFERENCE = "assets/reference/layout_stage_reference.webp"
STAGE_TEMPLATE = "assets/shared/stage_template.png"
DAIBUTSUAME_DIR = "assets/shared/daibutsuame"
# パーツ画像を作らず、レンダラーの回転・移動で表す状態
MOTION_STATES = {"twitch", "swing", "ring", "sway", "droop"}

_KIND_JA = {"background": "背景", "character": "人物", "prop": "小物", "foreground": "前景", "fx": "効果"}


class ImageWorkflowError(Exception):
    pass


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def _episode_assets(root: Path, episode_id: str) -> tuple[dict, list[dict]]:
    paths = episode_paths(root, episode_id)
    try:
        manifest = json.loads(paths["asset_manifest"].read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ImageWorkflowError(f"input not found: {paths['asset_manifest']} (run: python -m pipeline.assets {episode_id})") from None
    return paths, [a for a in manifest["assets"] if a["scope"] == "episode"]


# --- この回の素材 -----------------------------------------------------------------

def write_request(root: Path, episode_id: str, rules: dict) -> Path:
    paths, assets = _episode_assets(root, episode_id)
    inbox_rel = paths["assets_inbox"].relative_to(root).as_posix()
    lines = [
        f"# 画像の生成依頼（{episode_id}）", "",
        "1. 下の指示文で画像を作る（ChatGPT などの画像生成）。",
        f"2. できた画像を `{inbox_rel}/` に、指定のファイル名で保存する（png / webp / jpg）。",
        f"3. `python -m pipeline.images check {episode_id}` を実行する。サイズ・透過をチェックして取り込む。", "",
        "- 「透過: 必要」の素材は、背景を透明にした PNG で作る（依頼するときに「背景を透明にしたPNGで」と伝える）。",
        "- 画像の中に文字・ロゴ・透かしを入れない。",
        "- 同じ人物は、この回のすべての場面でこの1枚を使う。", "",
    ]
    for a in assets:
        cfg = rules["kinds"][a["kind"]]
        lines += [
            f"## {a['asset_id']}.png — {_KIND_JA[a['kind']]}: {a['label']}", "",
            f"- 生成サイズ: {cfg['generate_size']}" + (f"（取り込み時に {cfg['output_size'][0]}x{cfg['output_size'][1]} に整える）" if cfg.get("output_size") else ""),
            f"- 透過: {'必要' if a['transparent'] else 'なし'}",
            f"- 使う場面: {', '.join(a['scenes'])}", "",
            "```", a["prompt"].strip(), "```", "",
        ]
    _write_text(paths["image_requests"], "\n".join(lines))
    return paths["image_requests"]


def check_assets(root: Path, episode_id: str, rules: dict) -> dict[str, list[str] | None]:
    """{asset_id: None(未提出) / [](OK) / [問題...]}"""
    paths, assets = _episode_assets(root, episode_id)
    status: dict[str, list[str] | None] = {}
    for a in assets:
        dst = paths["assets_generated"] / f"{a['asset_id']}.png"
        src = find_input(paths["assets_inbox"], a["asset_id"]) or (dst if dst.exists() else None)
        status[a["asset_id"]] = None if src is None else process_asset(src, dst, a, rules)
    _write_status(paths, assets, status)
    return status


def _write_status(paths: dict, assets: list[dict], status: dict) -> None:
    lines = ["# 画像の取り込み状況", "", "| ID | 内容 | 状態 |", "|---|---|---|"]
    for a in assets:
        s = status.get(a["asset_id"])
        state = "未提出" if s is None else ("OK" if not s else "NG: " + " / ".join(s))
        lines.append(f"| {a['asset_id']} | {a['label']} | {state} |")
    ok = sum(1 for s in status.values() if s == [])
    lines += ["", f"{ok} / {len(assets)} 件 OK", ""]
    _write_text(paths["image_status"], "\n".join(lines))


def generate_assets(root: Path, episode_id: str, provider: ImageProvider, rules: dict,
                    force: bool = False) -> dict[str, list[str]]:
    paths, assets = _episode_assets(root, episode_id)
    failures: dict[str, list[str]] = {}
    for a in assets:
        dst = paths["assets_generated"] / f"{a['asset_id']}.png"
        if dst.exists() and not force:
            continue
        src = paths["assets_inbox"] / f"{a['asset_id']}.png"
        errors: list[str] = []
        for attempt in range(rules.get("check_retries", 1) + 1):
            try:
                data = provider.generate(prompt=a["prompt"], size=rules["kinds"][a["kind"]]["generate_size"],
                                         transparent=a["transparent"])
                src.parent.mkdir(parents=True, exist_ok=True)
                src.write_bytes(data)
                errors = process_asset(src, dst, a, rules)
            except ImageError as e:
                errors = [str(e)]
            append_usage(paths["image_usage"], {"asset_id": a["asset_id"], "attempt": attempt + 1,
                                                "provider": provider.name, "model": provider.model,
                                                "size": rules["kinds"][a["kind"]]["generate_size"], "ok": not errors})
            if not errors:
                break
        if errors:
            failures[a["asset_id"]] = errors
    check_assets(root, episode_id, rules)
    return failures


# --- 共通素材 ----------------------------------------------------------------------

def shared_part_files(motion: dict) -> list[tuple[str, str]]:
    """config/character_motion.yaml から、用意する大仏飴パーツのファイル名と説明を作る。"""
    files = []
    for part, spec in motion["parts"].items():
        if part == "fx":
            files += [(f"fx_{n}.png", f"効果: {n}") for n in spec]
        elif part == "props":
            files += [(f"prop_{n}.png", f"小物: {n}") for n in spec]
        elif isinstance(spec, dict) and spec.get("states"):
            files += [(f"{part}_{s}.png", f"{part}: {s}") for s in spec["states"] if s not in MOTION_STATES]
        else:
            files.append((f"{part}.png", part))
    return files


def write_shared_request(root: Path) -> Path:
    full = load_yaml("config/character_motion.yaml", root)
    motion = full["character"]
    ref = root / motion["reference_image"]
    with Image.open(ref) as im:
        w, h = im.size
    ddir = root / DAIBUTSUAME_DIR
    lines = [
        "# 大仏飴パーツの依頼書", "",
        f"外見の正本: `{motion['reference_image']}`（{w}x{h}）。外見（灰白色の毛、赤い首輪、金色の鈴、草）を変えない。", "",
        "## 共通の仕様",
        f"- すべて {w}x{h} の透明背景 PNG。正本と同じ位置・同じ大きさで描き、重ねるとぴったり合うこと",
        "- body.png は目・口・耳・腕を除いた頭と胴。ほかのパーツは自分の部分だけを描く",
        "- 表情の違いは目・口・耳・腕の組み合わせで作る（docs/CHARACTER_MOTION.md）",
        "- ぴくっ・揺れ・鳴る（twitch / sway / swing / ring / droop）は画像を作らず、動画で回転・移動させる",
        "- 仕上がったら Owner が確認し、approval.yaml の approved を true にする。承認前のパーツは動画に使わない", "",
        "## 作るファイル", "",
    ]
    lines += [f"- [ ] `{name}` — {desc}" for name, desc in shared_part_files(full)]
    _write_text(ddir / "REQUEST.md", "\n".join(lines) + "\n")
    approval = ddir / "approval.yaml"
    if not approval.exists():
        _write_text(approval, "# 大仏飴パーツの Owner 承認。確認したら approved を true にし、名前と日付を書く\n"
                              "approved: false\napproved_by: null\napproved_at: null\n")
    return ddir / "REQUEST.md"


def check_shared(root: Path) -> tuple[list[str], bool]:
    full = load_yaml("config/character_motion.yaml", root)
    ddir = root / DAIBUTSUAME_DIR
    missing = [name for name, _ in shared_part_files(full) if not (ddir / name).exists()]
    approval_path = ddir / "approval.yaml"
    approved = False
    if approval_path.exists():
        approved = bool((yaml.safe_load(approval_path.read_text(encoding="utf-8")) or {}).get("approved"))
    if not (root / STAGE_TEMPLATE).exists():
        missing.insert(0, STAGE_TEMPLATE)
    return missing, approved


# --- CLI -----------------------------------------------------------------------------

def _create_provider(cfg: dict, root: Path) -> ImageProvider:
    if cfg["provider"] != "openai":
        raise ImageWorkflowError("image.provider is manual: use `request` and `check` "
                                 "(or pass --provider openai to generate with the API)")
    from dotenv import load_dotenv

    from pipeline.images.openai_provider import OpenAIImageProvider

    load_dotenv(root / ".env")
    o = cfg["openai"]
    return OpenAIImageProvider(model=o["model"], quality=o["quality"], max_retries=o.get("max_retries", 2))


def main(argv: list[str] | None = None, project_root: Path | None = None,
         provider: ImageProvider | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate and import image assets")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("request", "check", "generate"):
        p = sub.add_parser(name)
        p.add_argument("episode_id")
        if name == "generate":
            p.add_argument("--provider", choices=["manual", "openai"])
            p.add_argument("--force", action="store_true", help="regenerate existing images")
    p = sub.add_parser("shared-template")
    p.add_argument("--base", type=Path, help=f"base image (default: {STAGE_REFERENCE})")
    sub.add_parser("shared-request")
    sub.add_parser("shared-check")
    args = parser.parse_args(argv)
    root = project_root or PROJECT_ROOT

    try:
        cfg = load_yaml("config/image.yaml", root)["image"]
        if args.command == "request":
            print(f"request: {write_request(root, args.episode_id, cfg)}")
            return 0
        if args.command == "check":
            status = check_assets(root, args.episode_id, cfg)
        elif args.command == "generate":
            if provider is None:
                provider = _create_provider(dict(cfg, provider=args.provider or cfg["provider"]), root)
            failures = generate_assets(root, args.episode_id, provider, cfg, force=args.force)
            for aid, errs in failures.items():
                print(f"  NG {aid}: {' / '.join(errs)}", file=sys.stderr)
            status = check_assets(root, args.episode_id, cfg)
        elif args.command == "shared-template":
            layout = load_yaml("config/layout.yaml", root)["main"]["layouts"]["stage"]
            with Image.open(args.base or root / STAGE_REFERENCE) as base:
                tpl = build_stage_template(base, layout)
            out = root / STAGE_TEMPLATE
            out.parent.mkdir(parents=True, exist_ok=True)
            tpl.save(out, "PNG")
            print(f"saved: {out}")
            return 0
        elif args.command == "shared-request":
            print(f"request: {write_shared_request(root)}")
            return 0
        else:
            missing, approved = check_shared(root)
            for m in missing:
                print(f"  未提出 {m}")
            print(f"大仏飴パーツ: {'承認済み' if approved else '未承認'} / 未提出 {len(missing)} 件")
            return 0 if approved and not missing else 1
    except (ImageWorkflowError, ValueError, ConfigError, FileNotFoundError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    ok = sum(1 for s in status.values() if s == [])
    missing = sum(1 for s in status.values() if s is None)
    print(f"OK {ok} / 未提出 {missing} / NG {len(status) - ok - missing}（{len(status)} 件）")
    print(f"status: {episode_paths(root, args.episode_id)['image_status']}")
    return 0 if ok == len(status) else 1


if __name__ == "__main__":
    raise SystemExit(main())
