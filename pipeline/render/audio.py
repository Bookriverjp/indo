"""ナレーションの WAV をタイムラインどおりに1本にまとめ、口パク用の音量を出す。"""
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np


def mix_narration(audio: list[dict], episode_dir: Path, total_seconds: float) -> tuple[np.ndarray, int]:
    """int16 モノラルの配列と sample rate を返す。"""
    rate = None
    clips = []
    for a in audio:
        with wave.open(str(episode_dir / a["file"])) as w:
            if w.getnchannels() != 1 or w.getsampwidth() != 2:
                raise ValueError(f"{a['file']}: 16bit モノラルの WAV が必要です")
            if rate is None:
                rate = w.getframerate()
            elif w.getframerate() != rate:
                raise ValueError(f"{a['file']}: sample rate が揃っていません")
            clips.append((a["start"], np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)))
    rate = rate or 24000
    out = np.zeros(int(round(total_seconds * rate)), dtype=np.int32)
    for start, data in clips:
        i = int(round(start * rate))
        n = max(0, min(len(data), len(out) - i))
        out[i:i + n] += data[:n]
    return np.clip(out, -32768, 32767).astype(np.int16), rate


def frame_levels(samples: np.ndarray, rate: int, fps: int, audio: list[dict], threshold: float) -> list[bool]:
    """コマごとに「口を開くか」。各ブロックの中で一番大きい音に対する割合で決める。"""
    n_frames = int(np.ceil(len(samples) / rate * fps))
    opened = [False] * n_frames
    spf = rate / fps
    for a in audio:
        f0 = int(a["start"] * fps)
        f1 = min(n_frames, int(np.ceil((a["start"] + a["duration"]) * fps)))
        rms = []
        for f in range(f0, f1):
            seg = samples[int(f * spf): int((f + 1) * spf)].astype(np.float64)
            rms.append(float(np.sqrt(np.mean(seg ** 2))) if len(seg) else 0.0)
        peak = max(rms, default=0.0)
        for k, f in enumerate(range(f0, f1)):
            if peak and rms[k] > threshold * peak:
                opened[f] = True
    return opened
