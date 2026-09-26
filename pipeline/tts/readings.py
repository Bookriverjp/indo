"""読み方の辞書。字幕は元の表記のまま、音声だけ読みを置き換える。"""
from __future__ import annotations

from pathlib import Path

import yaml


def _load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return list(data.get("words") or [])


def load_readings(global_path: Path, episode_path: Path | None = None) -> list[dict]:
    """全話共通の辞書に、エピソードの辞書を重ねる（同じ表記はエピソードが優先）。"""
    words = {w["surface"]: w["reading"] for w in _load(global_path)}
    if episode_path is not None:
        words.update({w["surface"]: w["reading"] for w in _load(episode_path)})
    return [{"surface": s, "reading": r} for s, r in words.items()]


def apply_readings(text: str, words: list[dict]) -> str:
    """長い表記から先に置き換える。置き換えた読みがさらに置き換わらないよう1回で処理する。"""
    ordered = sorted(words, key=lambda w: len(w["surface"]), reverse=True)
    out, i = [], 0
    while i < len(text):
        for w in ordered:
            if w["surface"] and text.startswith(w["surface"], i):
                out.append(w["reading"])
                i += len(w["surface"])
                break
        else:
            out.append(text[i])
            i += 1
    return "".join(out)
