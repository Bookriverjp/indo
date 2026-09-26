"""PHASE 9: YouTube の投稿用文面の仕上げ（チャプター、概要欄の組み立て）。"""
from __future__ import annotations

SECTION_LABELS = {"hook": "はじまり", "intro": "ごあいさつ", "background": "舞台と言葉", "story": "お話",
                  "commentary": "異説と背景", "comparison": "日本との比較", "ending": "おわりに"}
MIN_CHAPTER_SECONDS = 10     # YouTube のチャプターは各10秒以上
MIN_CHAPTERS = 3             # 3つ以上ないと YouTube はチャプターにしない


def chapters_from_timeline(timeline: dict, script: dict) -> list[dict]:
    """場面の最初のブロックの section でチャプターを切る。短すぎるものは前にまとめる。"""
    section_of = {b["block_id"]: s["section"] for s in script["sections"] for b in s["blocks"]}
    block_of_scene = {}
    for a in timeline["audio"]:
        for sc in timeline["scenes"]:
            if sc["start"] <= a["start"] < sc["start"] + sc["duration"]:
                block_of_scene.setdefault(sc["scene_id"], a["block_id"])
    chapters: list[dict] = []
    for sc in timeline["scenes"]:
        bid = block_of_scene.get(sc["scene_id"])
        label = SECTION_LABELS.get(section_of.get(bid, ""), "お話")
        if chapters and chapters[-1]["label"] == label:
            continue
        chapters.append({"start": 0.0 if not chapters else sc["start"], "label": label})
    ends = [c["start"] for c in chapters[1:]] + [timeline["total_seconds"]]
    kept: list[dict] = []
    for c, end in zip(chapters, ends):
        if kept and end - c["start"] < MIN_CHAPTER_SECONDS:
            continue          # 短いチャプターは前のチャプターに含める
        if not kept or c["start"] - kept[-1]["start"] >= MIN_CHAPTER_SECONDS:
            kept.append(c)
    return kept if len(kept) >= MIN_CHAPTERS else []


def _stamp(seconds: float) -> str:
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def format_chapters(chapters: list[dict]) -> str:
    return "\n".join(f"{_stamp(c['start'])} {c['label']}" for c in chapters)


def build_description(data: dict, chapters: list[dict]) -> str:
    parts = [data["description"].strip()]
    if chapters:
        parts.append(format_chapters(chapters))
    if data["hashtags"]:
        parts.append(" ".join(data["hashtags"]))
    return "\n\n".join(parts)


def render_metadata_md(data: dict) -> str:
    lines = ["# YouTube 投稿用文面", "", "## タイトル案", ""]
    lines += [f"{i}. {t}" for i, t in enumerate(data["title_candidates"], 1)]
    lines += ["", "## サムネイルの文字案", ""] + [f"{i}. {t}" for i, t in enumerate(data["thumbnail_text_candidates"], 1)]
    lines += ["", "## 概要欄（そのまま貼る）", "", "```", data["description_full"], "```", ""]
    lines += ["## チャプター", "", format_chapters(data["chapters"]) or "(動画が短いため、なし)", ""]
    lines += ["## タグ（カンマ区切り）", "", ", ".join(data["tags"]), ""]
    return "\n".join(lines)
