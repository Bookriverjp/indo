"""PHASE 6: 台本（本編・ショート）をブロックごとに読み上げ、WAV と narration.json を作る。

使い方:
  python -m pipeline.tts EP0001_nishi_daak [--force]

VOICEVOX（config/voice.yaml の endpoint）を起動しておくこと。APIキーは不要。
内容が変わったブロックだけ作り直す（--force で全部作り直す）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import wave
from pathlib import Path

from pipeline.config import PROJECT_ROOT, ConfigError, load_yaml
from pipeline.tts.base import TTSError, TTSProvider
from pipeline.tts.readings import apply_readings, load_readings
from pipeline.workspace import create_episode_workspace, episode_paths

NARRATION_VERSION = 1


class NarrationError(Exception):
    pass


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise NarrationError(f"input not found: {path}") from None


def _blocks(paths: dict) -> list[dict]:
    """読み上げる順番の一覧: {target, block_id, kind, expression, text}"""
    script = _read_json(paths["script_json"])
    out = [{"target": "main", "block_id": b["block_id"], "kind": b["kind"], "expression": b["expression"], "text": b["text"]}
           for s in script["sections"] for b in s["blocks"]]
    if paths["shorts_json"].exists():
        shorts = _read_json(paths["shorts_json"])
        out += [{"target": "shorts", "block_id": b["block_id"], "kind": b["kind"], "expression": b["expression"],
                 "text": b["text"]} for b in shorts["blocks"]]
        out.append({"target": "shorts", "block_id": "cta", "kind": "comment", "expression": "neutral",
                    "text": shorts["cta_text"]})
    return out


def _wav_seconds(path: Path) -> float:
    with wave.open(str(path)) as w:
        return w.getnframes() / w.getframerate()


def synthesize_episode(root: Path, episode_id: str, provider: TTSProvider, force: bool = False) -> dict:
    paths = episode_paths(root, episode_id)
    voice = load_yaml("config/voice.yaml", root)["tts"]
    persona = load_yaml("config/persona.yaml", root)["persona"]
    comment_kinds = persona["styles"]["comment"]["kinds"]
    words = load_readings(root / "config" / "pronunciation.yaml", paths["pronunciation"])
    blocks = _blocks(paths)
    episode_dir = create_episode_workspace(root, episode_id)

    previous = {}
    if paths["narration_index"].exists() and not force:
        previous = {i["file"]: i for i in _read_json(paths["narration_index"])["items"]}

    items = []
    for b in blocks:
        style_key = voice["expression_to_style"].get(b["expression"], voice["expression_to_style"]["default"])
        style_id = voice["styles"][style_key]["id"]
        prosody = voice["prosody"]["comment" if b["kind"] in comment_kinds else "narration"]
        spoken = apply_readings(b["text"], words)
        params = {"spoken_text": spoken, "style_id": style_id, "speed": voice["speed_scale"],
                  "intonation": prosody["intonation_scale"], "phrase_end_rise": prosody["phrase_end_rise"],
                  "post_phoneme": voice["post_phoneme_length"], "speaker": voice["speaker_uuid"],
                  "engine_version": voice["engine_version"]}
        digest = hashlib.sha256(json.dumps(params, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]
        wav_path = paths["narration"] / f"{b['target']}_{b['block_id']}.wav"
        rel = wav_path.relative_to(episode_dir).as_posix()

        prev = previous.get(rel)
        if not (prev and prev["params_hash"] == digest and wav_path.exists()):
            data = provider.synthesize(spoken, style_id=style_id, speed=params["speed"],
                                       intonation=params["intonation"], phrase_end_rise=params["phrase_end_rise"],
                                       post_phoneme=params["post_phoneme"])
            wav_path.parent.mkdir(parents=True, exist_ok=True)
            wav_path.write_bytes(data)

        items.append({"target": b["target"], "block_id": b["block_id"], "kind": b["kind"], "expression": b["expression"],
                      "text": b["text"], "spoken_text": spoken, "style_id": style_id,
                      "intonation": params["intonation"], "phrase_end_rise": params["phrase_end_rise"],
                      "file": rel, "seconds": round(_wav_seconds(wav_path), 3), "params_hash": digest})

    index = {"schema_version": NARRATION_VERSION, "engine": voice["engine"], "speaker": voice["speaker_name"],
             "credit": voice["credit"], "speed_scale": voice["speed_scale"], "items": items}
    with paths["narration_index"].open("w", encoding="utf-8", newline="\n") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return index


def _fmt(seconds: float) -> str:
    return f"{int(seconds // 60)}分{seconds % 60:04.1f}秒"


def main(argv: list[str] | None = None, project_root: Path | None = None,
         provider: TTSProvider | None = None) -> int:
    parser = argparse.ArgumentParser(description="Synthesize narration with VOICEVOX")
    parser.add_argument("episode_id")
    parser.add_argument("--force", action="store_true", help="regenerate every block")
    args = parser.parse_args(argv)
    root = project_root or PROJECT_ROOT

    try:
        if provider is None:
            from pipeline.tts.voicevox import VoicevoxProvider

            provider = VoicevoxProvider(load_yaml("config/voice.yaml", root)["tts"]["endpoint"])
        index = synthesize_episode(root, args.episode_id, provider, force=args.force)
    except (NarrationError, TTSError, ValueError, ConfigError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    for target, label in (("main", "本編"), ("shorts", "ショート")):
        its = [i for i in index["items"] if i["target"] == target]
        if its:
            print(f"{label}: {len(its)} ブロック / {_fmt(sum(i['seconds'] for i in its))}")
    print(f"saved: {episode_paths(root, args.episode_id)['narration_index']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
