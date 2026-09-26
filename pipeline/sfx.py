"""効果音・環境音を合成して assets/sfx/*.wav に書き出す（外部の音源を使わない）。

  python -m pipeline.sfx [--force]

乱数は固定しているので、何度作っても同じ音になる。
"""
from __future__ import annotations

import argparse
import sys
import wave
from pathlib import Path

import numpy as np

from pipeline.config import PROJECT_ROOT, ConfigError, load_yaml


def _to_int16(x: np.ndarray, peak: float = 0.9) -> np.ndarray:
    m = np.abs(x).max() or 1.0
    return (x / m * peak * 32767).astype(np.int16)


def _loopable(x: np.ndarray, rate: int, fade: float = 0.5) -> np.ndarray:
    """頭と終わりを重ねて、ループしてもつなぎ目が鳴らないようにする。"""
    n = int(rate * fade)
    head, body, tail = x[:n], x[n:-n], x[-n:]
    ramp = np.linspace(0, 1, n)
    joined = tail * (1 - ramp) + head * ramp
    return np.concatenate([joined, body])


def bell(rate: int) -> np.ndarray:
    """鈴「チリン」：高めの非整数倍音が速く減衰する音を2回重ねる。"""
    t = np.arange(int(rate * 2.2)) / rate
    out = np.zeros_like(t)
    for start in (0.0, 0.09):
        tt = np.clip(t - start, 0, None)
        on = (t >= start).astype(float)
        for f, a, d in ((2350, 1.0, 1.6), (2350 * 2.76, 0.5, 2.8), (2350 * 5.4, 0.25, 4.5), (2350 * 1.5, 0.3, 2.0)):
            out += on * a * np.sin(2 * np.pi * f * tt) * np.exp(-d * tt)
    attack = np.minimum(1.0, t / 0.003)
    return _to_int16(out * attack, 0.8)


def night_insects(rate: int, seconds: float = 12.0) -> np.ndarray:
    """夜の虫：コオロギのような高い音の短い連打を、数匹分ずらして重ねる。"""
    rng = np.random.default_rng(7)
    n = int(rate * seconds)
    t = np.arange(n) / rate
    out = np.zeros(n)
    for f0, rate_hz, amp in ((4300, 3.1, 1.0), (4700, 2.4, 0.7), (3900, 4.2, 0.5), (5200, 1.7, 0.4)):
        phase = rng.uniform(0, 1)
        chirp_env = (np.sin(2 * np.pi * (rate_hz * t + phase)) > 0.55).astype(float)
        pulses = (np.sin(2 * np.pi * 38 * t) > 0).astype(float)
        env = np.convolve(chirp_env * pulses, np.ones(48) / 48, mode="same")
        out += amp * env * np.sin(2 * np.pi * (f0 + 30 * np.sin(2 * np.pi * 0.3 * t)) * t)
    out += 0.02 * rng.standard_normal(n)
    return _to_int16(_loopable(out, rate), 0.7)


def river(rate: int, seconds: float = 12.0) -> np.ndarray:
    """ゆっくり流れる川：低めにこもらせたノイズに、ゆらぎと小さな水のはねを足す。"""
    rng = np.random.default_rng(11)
    n = int(rate * seconds)
    noise = rng.standard_normal(n)
    brown = np.cumsum(noise)
    brown -= np.convolve(brown, np.ones(2400) / 2400, mode="same")   # 低い揺れを取り除く
    smooth = np.convolve(noise, np.ones(12) / 12, mode="same")
    t = np.arange(n) / rate
    swell = 0.7 + 0.3 * np.sin(2 * np.pi * 0.13 * t) * np.sin(2 * np.pi * 0.07 * t + 1)
    out = (0.6 * brown / (np.abs(brown).max() or 1) + 0.5 * smooth) * swell
    for _ in range(int(seconds * 3)):
        at = rng.integers(0, n - 2400)
        tt = np.arange(2400) / rate
        f = rng.uniform(600, 1400)
        out[at:at + 2400] += 0.15 * np.sin(2 * np.pi * f * tt * (1 + 2 * tt)) * np.exp(-40 * tt)
    return _to_int16(_loopable(out, rate), 0.7)


def wind(rate: int, seconds: float = 12.0) -> np.ndarray:
    """夜風：ゆっくり強弱のついた、こもったノイズ。"""
    rng = np.random.default_rng(23)
    n = int(rate * seconds)
    noise = rng.standard_normal(n)
    soft = np.convolve(noise, np.ones(60) / 60, mode="same")
    t = np.arange(n) / rate
    gust = 0.5 + 0.5 * np.sin(2 * np.pi * 0.09 * t) ** 2
    return _to_int16(_loopable(soft * gust, rate), 0.6)


SYNTHS = {"bell": bell, "night_insects": night_insects, "river": river, "wind": wind}


def write_wav(path: Path, data: np.ndarray, rate: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(data.tobytes())


def main(argv: list[str] | None = None, project_root: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description="Synthesize sound effects into assets/sfx")
    parser.add_argument("--force", action="store_true", help="regenerate existing files")
    args = parser.parse_args(argv)
    root = project_root or PROJECT_ROOT
    try:
        cfg = load_yaml("config/sfx.yaml", root)["sfx"]
    except ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    for name, spec in cfg["library"].items():
        out = root / cfg["dir"] / f"{name}.wav"
        if out.exists() and not args.force:
            print(f"既存: {out}")
            continue
        if name not in SYNTHS:
            print(f"error: {name} の合成方法がありません（{out} に WAV を置けば使えます）", file=sys.stderr)
            return 2
        write_wav(out, SYNTHS[name](cfg["sample_rate"]), cfg["sample_rate"])
        print(f"作成: {out}（{spec.get('desc', '')}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
