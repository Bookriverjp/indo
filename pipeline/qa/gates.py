"""PHASE 10: 確認の関門（リサーチ → 台本 → 画像 → 音声 → 最終）。

各関門は自動チェックのあと Owner が承認・差し戻しする。承認は対象ファイルの内容の指紋と一緒に
output/qa_gates.yaml に記録し、あとで中身が変わったら「再確認（stale）」に戻る。
前の関門が承認されるまで、次の関門は承認できない。
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import yaml

from pipeline.config import load_yaml
from pipeline.workspace import episode_paths

GATES = {
    "research": "リサーチ",
    "script": "台本・絵コンテ",
    "visual": "画像",
    "audio": "音声",
    "final": "最終（動画・サムネイル・文面）",
}
DAIBUTSUAME_APPROVAL = "assets/shared/daibutsuame/approval.yaml"


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _fingerprint(files: list[Path]) -> str:
    h = hashlib.sha256()
    for f in sorted(files):
        if f.exists() and f.is_file():
            h.update(str(f.name).encode())
            with f.open("rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
    return h.hexdigest()[:20]


def media_seconds(path: Path) -> float | None:
    """ffmpeg の出力から動画の長さを読む（全体をデコードしない）。"""
    import imageio_ffmpeg

    proc = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-i", str(path)],
                          capture_output=True, text=True, errors="replace")
    m = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", proc.stderr)
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else None


# --- 自動チェック ------------------------------------------------------------------------

def _check(root: Path, episode_id: str, gate: str) -> tuple[list[str], list[str], list[Path], list[dict]]:
    """(errors, warnings, 指紋の対象ファイル, 画面に出すファイル)"""
    paths = episode_paths(root, episode_id)
    ep = paths["research"].parents[1]
    rel = lambda p: p.relative_to(ep).as_posix()  # noqa: E731
    errors: list[str] = []
    warnings: list[str] = []
    show: list[dict] = []

    if gate == "research":
        from pipeline.research import qa_research

        data = _read_json(paths["research"])
        if data is None:
            errors.append("research/research.json がありません（python -m pipeline.research import）")
        else:
            r = qa_research(data)
            errors += [f"{i.code} {i.message}" for i in r.errors]
            warnings += [f"{i.code} {i.message}" for i in r.warnings]
        files = [paths["research"]]
        show += [{"path": rel(paths["research_review"]), "type": "text"}]

    elif gate == "script":
        from pipeline.script_guard import check_main_script, check_shorts_script

        rules = load_yaml("config/script_rules.yaml", root)
        persona = load_yaml("config/persona.yaml", root)["persona"]
        script = _read_json(paths["script_json"])
        if script is None:
            errors.append("script/script_main.json がありません（python -m pipeline.generate script）")
        else:
            r = check_main_script(script, rules, persona)
            errors += [f"{i.code} {i.message}" for i in r.errors]
            warnings += [f"{i.code} {i.message}" for i in r.warnings]
        shorts = _read_json(paths["shorts_json"])
        if shorts is not None:
            r = check_shorts_script(shorts, rules, persona)
            errors += [f"ショート {i.code} {i.message}" for i in r.errors]
            warnings += [f"ショート {i.code} {i.message}" for i in r.warnings]
        if not paths["storyboard"].exists():
            warnings.append("絵コンテ（storyboard/storyboard.json）がまだありません")
        files = [paths["script_json"], paths["shorts_json"], paths["storyboard"]]
        show += [{"path": rel(p), "type": "text"} for p in (paths["script_main"], paths["script_review"],
                                                            paths["script_shorts"]) if p.exists()]

    elif gate == "visual":
        manifest = _read_json(paths["asset_manifest"])
        files = [paths["asset_manifest"]]
        if manifest is None:
            errors.append("storyboard/asset_manifest.json がありません（python -m pipeline.assets）")
        else:
            missing = []
            for a in manifest["assets"]:
                if a["scope"] != "episode":
                    continue
                f = ep / a["file"]
                files.append(f)
                if f.exists():
                    show.append({"path": a["file"], "type": "image", "label": f"{a['asset_id']} {a['label']}"})
                else:
                    missing.append(a["asset_id"])
            if missing:
                errors.append("素材画像がありません: " + ", ".join(missing) + "（python -m pipeline.images check）")
        approval = root / DAIBUTSUAME_APPROVAL
        ok = approval.exists() and bool((yaml.safe_load(approval.read_text(encoding="utf-8")) or {}).get("approved"))
        if not ok:
            errors.append("大仏飴パーツが Owner 未承認です（assets/shared/daibutsuame/approval.yaml）")

    elif gate == "audio":
        nar = _read_json(paths["narration_index"])
        script = _read_json(paths["script_json"]) or {"sections": []}
        files = [paths["narration_index"]]
        if nar is None:
            errors.append("audio/narration.json がありません（python -m pipeline.tts）")
        else:
            have = {i["block_id"]: i for i in nar["items"] if i["target"] == "main"}
            need = [b["block_id"] for s in script["sections"] for b in s["blocks"]]
            missing = [b for b in need if b not in have or not (ep / have[b]["file"]).exists()]
            if missing:
                errors.append("音声がないブロック: " + ", ".join(missing) + "（python -m pipeline.tts）")
            for i in nar["items"]:
                files.append(ep / i["file"])
                if (ep / i["file"]).exists():
                    show.append({"path": i["file"], "type": "audio", "label": f"{i['target']} {i['block_id']} {i.get('text', '')}"})

    else:  # final
        need = [paths["episode_video"], paths["episode_srt"], paths["thumbnail"], paths["youtube_metadata"]]
        files = list(need)
        for p in need:
            if not p.exists():
                errors.append(f"{rel(p)} がありません")
        timeline = _read_json(paths["timeline"])
        if paths["episode_video"].exists() and timeline:
            secs = media_seconds(paths["episode_video"])
            if secs is None or abs(secs - timeline["total_seconds"]) > 1.0:
                errors.append(f"動画の長さ（{secs}秒）がタイムライン（{timeline['total_seconds']}秒）と合いません。書き出し直してください")
        meta = _read_json(paths["youtube_metadata"])
        if meta is not None:
            from pipeline.generate import DESCRIPTION_FORBIDDEN

            for w in DESCRIPTION_FORBIDDEN:
                if w in meta.get("description_full", meta.get("description", "")):
                    errors.append(f"概要欄に「{w}」があります（出典とクレジットは動画の中で見せる）")
        show += [{"path": rel(paths["episode_video"]), "type": "video"}] if paths["episode_video"].exists() else []
        show += [{"path": rel(paths["thumbnail"]), "type": "image", "label": "サムネイル"}] if paths["thumbnail"].exists() else []
        show += [{"path": rel(paths["youtube_metadata_md"]), "type": "text"}] if paths["youtube_metadata_md"].exists() else []
    return errors, warnings, files, show


# --- 状態 ------------------------------------------------------------------------------

def load_decisions(root: Path, episode_id: str) -> dict:
    p = episode_paths(root, episode_id)["qa_gates"]
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}) if p.exists() else {}


def evaluate(root: Path, episode_id: str) -> list[dict]:
    decisions = load_decisions(root, episode_id)
    out = []
    previous_ok = True
    for gate, label in GATES.items():
        errors, warnings, files, show = _check(root, episode_id, gate)
        fp = _fingerprint(files)
        d = decisions.get(gate)
        if not previous_ok:
            state = "waiting"
        elif errors:
            state = "blocked"
        elif d and d["fingerprint"] == fp:
            state = d["decision"]           # approved / rejected
        elif d and d["decision"] == "approved":
            state = "stale"
        else:
            state = "pending"
        out.append({"gate": gate, "label": label, "state": state, "errors": errors, "warnings": warnings,
                    "files": show, "fingerprint": fp, "decision": d})
        previous_ok = previous_ok and state == "approved"
    return out


def decide(root: Path, episode_id: str, gate: str, decision: str, note: str, by: str = "owner") -> None:
    if gate not in GATES:
        raise ValueError(f"unknown gate: {gate}")
    if decision not in ("approved", "rejected"):
        raise ValueError(f"unknown decision: {decision}")
    g = next(x for x in evaluate(root, episode_id) if x["gate"] == gate)
    if g["state"] == "waiting":
        raise ValueError(f"{g['label']}: 前の関門がまだ承認されていません")
    if decision == "approved" and g["errors"]:
        raise ValueError(f"{g['label']}: 自動チェックに通っていません: " + " / ".join(g["errors"]))
    if decision == "rejected" and not note.strip():
        raise ValueError(f"{g['label']}: 差し戻しの理由を書いてください")
    decisions = load_decisions(root, episode_id)
    decisions[gate] = {"decision": decision, "by": by, "note": note.strip(),
                       "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "fingerprint": g["fingerprint"]}
    paths = episode_paths(root, episode_id)
    paths["qa_gates"].parent.mkdir(parents=True, exist_ok=True)
    with paths["qa_gates"].open("w", encoding="utf-8", newline="\n") as f:
        yaml.safe_dump(decisions, f, allow_unicode=True, sort_keys=False)
    write_report(root, episode_id)


STATE_LABEL = {"approved": "承認済み", "rejected": "差し戻し", "pending": "確認待ち", "stale": "再確認（承認後に変更あり）",
               "blocked": "自動チェックNG", "waiting": "前の関門の承認待ち"}


def write_report(root: Path, episode_id: str) -> Path:
    lines = [f"# QA レポート: {episode_id}", ""]
    for g in evaluate(root, episode_id):
        lines.append(f"## {g['label']} — {STATE_LABEL[g['state']]}")
        d = g["decision"]
        if d:
            lines.append(f"- 判断: {d['decision']}（{d['by']}, {d['at']}）{'　メモ: ' + d['note'] if d['note'] else ''}")
        lines += [f"- NG: {e}" for e in g["errors"]] + [f"- 警告: {w}" for w in g["warnings"]] + [""]
    p = episode_paths(root, episode_id)["qa_report"]
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))
    return p
