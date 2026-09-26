"""PHASE 7: ナレーションの長さから、場面の時刻・カメラの動き・切り替え・字幕・大仏飴の表情を決める。

使い方:
  python -m pipeline.timeline EP0001_nishi_daak

入力: storyboard.json / asset_manifest.json / audio/narration.json / script_main.json / research.json
出力: render/timeline.json、script/subtitles.srt
設定: config/timeline.yaml
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

from pipeline.config import PROJECT_ROOT, ConfigError, load_yaml
from pipeline.schema_validation import SchemaValidationError, validate
from pipeline.workspace import create_episode_workspace, episode_paths


class TimelineError(Exception):
    pass


# --- subtitles ------------------------------------------------------------------------

_PIECE_RE = re.compile(r"[^、。！？!?]*[、。！？!?]|[^、。！？!?]+")
_SENTENCE_END = tuple("。！？!?")


def split_subtitle(text: str, *, max_chars: int, max_lines: int) -> list[list[str]]:
    """字幕を「行」と「画面（最大 max_lines 行）」に分ける。句読点で切り、文の終わりで画面を改める。"""
    lines: list[tuple[str, bool]] = []   # (行, 文の終わりか)
    current = ""
    for piece in _PIECE_RE.findall(text):
        while len(piece) > max_chars:
            if current:
                lines.append((current, False))
                current = ""
            lines.append((piece[:max_chars], False))
            piece = piece[max_chars:]
        if len(current) + len(piece) > max_chars and current:
            lines.append((current, False))
            current = ""
        current += piece
        if current.endswith(_SENTENCE_END):
            lines.append((current, True))
            current = ""
    if current:
        lines.append((current, True))

    captions: list[list[str]] = []
    cap: list[str] = []
    for line, sentence_end in lines:
        cap.append(line)
        if len(cap) == max_lines or sentence_end:
            captions.append(cap)
            cap = []
    if cap:
        captions.append(cap)
    return captions


def _srt_time(t: float) -> str:
    ms = round(t * 1000)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def render_srt(subtitles: list[dict]) -> str:
    return "".join(f"{s['index']}\n{_srt_time(s['start'])} --> {_srt_time(s['end'])}\n" + "\n".join(s["lines"]) + "\n\n"
                   for s in subtitles)


# --- cards ------------------------------------------------------------------------------

def _card(kind: str, research: dict, script: dict | None = None) -> dict:
    if kind == "region":
        rows = [["地域", research["region"]], ["言語", research["language"]]]
        if research.get("local_title"):
            rows.append(["現地名", research["local_title"]])
        if research.get("transliteration"):
            rows.append(["読み", research["transliteration"]])
        levels = Counter(s["reliability"] for s in research["sources"])
        rows.append(["資料", " / ".join(f"{k} {levels[k]}件" for k in "ABCD" if levels[k])])
        # 現地名は現地の文字のフォントで描く（config/render.yaml の fonts.scripts）
        return {"kind": kind, "title": "今日のお話の舞台", "rows": rows, "script": research.get("local_script")}
    if kind == "variants":
        rows = [[f"異説{i}", v["summary"]] for i, v in enumerate(research["variants"], 1)] or [["異説", "記録なし"]]
        return {"kind": kind, "title": "異説と背景", "rows": rows}
    # 出典カード: 台本の sources_card、なければ legend ブロックで使った出典（研究記録の順）
    wanted = list((script or {}).get("sources_card") or [])
    if not wanted and script:
        used = {i for sec in script["sections"] for b in sec["blocks"] if b["kind"] == "legend" for i in b["source_ids"]}
        wanted = [s["id"] for s in research["sources"] if s["id"] in used]
    by_id = {s["id"]: s for s in research["sources"]}
    rows = []
    for s in ([by_id[i] for i in wanted if i in by_id] or research["sources"]):
        meta = "、".join(str(x) for x in (s.get("author"), s.get("year")) if x)
        rows.append([f"{s['id']}（信頼度{s['reliability']}）", s["title"] + (f"（{meta}）" if meta else "")])
    return {"kind": "sources", "title": "出典", "rows": rows}


# --- timeline ---------------------------------------------------------------------------

def _motion(name: str | None, layout: str, cfg: dict) -> dict:
    motions = cfg["motions"]
    if layout == "card" or name not in motions:
        name = cfg["default_motion"][layout]
    m = motions[name]
    return {"name": name, "camera_from": list(m["camera_from"]), "camera_to": list(m["camera_to"]),
            "parallax": bool(m.get("parallax", False)), "fx_animation": m.get("fx_animation")}


def _transition(prev: dict | None, layout: str, cfg: dict, override: str | None = None) -> dict:
    t = cfg["transitions"]
    if override:
        match = next((v for v in t.values() if v["type"] == override), None)
        if match is None:
            raise TimelineError(f"unknown transition: {override}")
        return {"type": match["type"], "duration": match["duration"]}
    if prev is None:
        key = "first"
    elif prev["layout"] == "stage" and layout == "stage":
        key = "stage_to_stage"
    elif prev["layout"] != layout:
        key = "layout_change"
    else:
        key = "default"
    return {"type": t[key]["type"], "duration": t[key]["duration"]}


def _sfx_events(storyboard: dict, scenes: list[dict], sfx_cfg: dict | None, cfg: dict) -> list[dict]:
    """環境音（場面のあいだ鳴らし続け、続く場面の同じ音はつなげる）と効果音（1回）。"""
    lib = (sfx_cfg or {}).get("library", {})
    events: list[dict] = []
    open_amb: dict[str, dict] = {}
    for sb, sc in zip(storyboard["scenes"], scenes):
        names = sb.get("ambience") or []
        for name in [*names, *(e["name"] for e in sb.get("sfx") or [])]:
            if name not in lib:
                raise TimelineError(f"{sb['scene_id']}: 効果音 {name!r} が config/sfx.yaml の library にありません")
        end = sc["start"] + sc["duration"]
        for name in list(open_amb):
            if name not in names:
                del open_amb[name]
        for name in names:
            if name in open_amb:
                open_amb[name]["duration"] = round(end - open_amb[name]["start"], 3)
            else:
                ev = {"name": name, "start": sc["start"], "duration": sc["duration"], "loop": True,
                      "volume": lib[name]["volume"]}
                events.append(ev)
                open_amb[name] = ev
        for e in sb.get("sfx") or []:
            at = e.get("at", "start")
            if at == "end":
                start = max(sc["start"], end - cfg.get("sfx_end_offset", 2.0))
            elif at == "start":
                start = sc["start"] + cfg["scene_lead_in"] / 2
            else:
                start = sc["start"] + float(at)
            events.append({"name": e["name"], "start": round(start, 3), "duration": None, "loop": False,
                           "volume": lib[e["name"]]["volume"]})
    return events


def build_timeline(*, episode_id: str, storyboard: dict, manifest: dict, narration: dict, script: dict,
                   research: dict, cfg: dict, width: int = 1920, height: int = 1080, sfx_cfg: dict | None = None) -> dict:
    seconds = {i["block_id"]: i for i in narration["items"] if i["target"] == "main"}
    blocks = {b["block_id"]: (s["section"], b) for s in script["sections"] for b in s["blocks"]}
    layers = {s["scene_id"]: s["layers"] for s in manifest["scenes"]}

    scenes, audio, subtitles, narrator = [], [], [], []
    t = 0.0
    prev = None
    sub_cfg = cfg["subtitle"]
    for sc in storyboard["scenes"]:
        missing = [b for b in sc["block_ids"] if b not in seconds]
        if missing:
            raise TimelineError(f"{sc['scene_id']}: narration がないブロックがあります: {', '.join(missing)}（python -m pipeline.tts）")
        cursor = t + cfg["scene_lead_in"]
        for n, bid in enumerate(sc["block_ids"]):
            if n:
                cursor += cfg["block_gap"]
            dur = seconds[bid]["seconds"]
            audio.append({"block_id": bid, "file": seconds[bid]["file"], "start": round(cursor, 3), "duration": dur})
            section, block = blocks[bid]
            narrator.append({"block_id": bid, "start": round(cursor, 3), "duration": dur,
                             "expression": block["expression"],
                             "speaking": seconds[bid].get("voice", "narrator") == "narrator"})
            caps = split_subtitle(block["text"], max_chars=sub_cfg["max_chars_per_line"], max_lines=sub_cfg["max_lines"])
            total_chars = sum(len("".join(c)) for c in caps) or 1
            c_start = cursor
            for k, cap in enumerate(caps):
                c_end = cursor + dur if k == len(caps) - 1 else c_start + dur * len("".join(cap)) / total_chars
                subtitles.append({"index": len(subtitles) + 1, "block_id": bid, "start": round(c_start, 3),
                                  "end": round(c_end, 3), "lines": cap})
                c_start = c_end
            cursor += dur
        duration = max(cursor + cfg["scene_tail"] - t, cfg["min_scene_seconds"])

        card = None
        if sc["layout"] == "card":
            section = blocks[sc["block_ids"][-1]][0] if sc["block_ids"] else "intro"
            card = _card(cfg["card_by_section"].get(section, "region"), research, script)

        scene = {"scene_id": sc["scene_id"], "layout": sc["layout"], "start": round(t, 3), "duration": round(duration, 3),
                 "transition_in": _transition(prev, sc["layout"], cfg, sc.get("transition")), "motion": _motion(sc.get("suggested_motion"), sc["layout"], cfg),
                 "layers": layers.get(sc["scene_id"], []), "card": card}
        scenes.append(scene)
        prev = scene
        t += duration

    return {"schema_version": 1, "episode_id": episode_id, "width": width, "height": height, "fps": cfg["fps"],
            "total_seconds": round(t, 3), "region_label": f"{research['region']} ・ {research['language']}",
            "scenes": scenes, "audio": audio, "subtitles": subtitles, "narrator": narrator,
            "sfx": _sfx_events(storyboard, scenes, sfx_cfg, cfg)}


# --- CLI -------------------------------------------------------------------------------

def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise TimelineError(f"input not found: {path}") from None


def main(argv: list[str] | None = None, project_root: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build render/timeline.json and subtitles.srt")
    parser.add_argument("episode_id")
    args = parser.parse_args(argv)
    root = project_root or PROJECT_ROOT

    try:
        paths = episode_paths(root, args.episode_id)
        main_cfg = load_yaml("config/layout.yaml", root)["main"]
        tl = build_timeline(
            episode_id=args.episode_id,
            storyboard=_read_json(paths["storyboard"]),
            manifest=_read_json(paths["asset_manifest"]),
            narration=_read_json(paths["narration_index"]),
            script=_read_json(paths["script_json"]),
            research=_read_json(paths["research"]),
            cfg=load_yaml("config/timeline.yaml", root)["timeline"],
            sfx_cfg=load_yaml("config/sfx.yaml", root)["sfx"] if (root / "config" / "sfx.yaml").exists() else None,
            width=main_cfg["width"], height=main_cfg["height"],
        )
        validate(tl, "timeline", root)
    except (TimelineError, ValueError, ConfigError, SchemaValidationError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    create_episode_workspace(root, args.episode_id)
    for key, text in (("timeline", json.dumps(tl, ensure_ascii=False, indent=2) + "\n"),
                      ("subtitles", render_srt(tl["subtitles"]))):
        paths[key].parent.mkdir(parents=True, exist_ok=True)
        with paths[key].open("w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    total = tl["total_seconds"]
    print(f"合計 {int(total // 60)}分{total % 60:04.1f}秒 / 場面 {len(tl['scenes'])} / 字幕 {len(tl['subtitles'])}")
    print(f"saved: {paths['timeline']}")
    print(f"saved: {paths['subtitles']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
