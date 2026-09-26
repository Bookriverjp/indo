import wave
from pathlib import Path

import numpy as np

from pipeline.config import load_yaml
from pipeline.sfx import SYNTHS, main


def read(path: Path):
    with wave.open(str(path)) as w:
        return w.getframerate(), np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)


def test_synths_are_deterministic_and_not_silent():
    for name, fn in SYNTHS.items():
        a, b = fn(24000), fn(24000)
        assert np.array_equal(a, b), name
        assert np.abs(a).max() > 1000 and np.abs(a).max() <= 32767, name


def test_bell_decays():
    bell = SYNTHS["bell"](24000).astype(float)
    head, tail = np.abs(bell[:2400]).mean(), np.abs(bell[-2400:]).mean()
    assert tail < head * 0.1


def test_loops_start_and_end_quietly_matched():
    for name in ("night_insects", "river", "wind"):
        x = SYNTHS[name](24000).astype(float)
        steps = np.abs(np.diff(x))
        # つなぎ目（最後→最初）の段差が、ふだんの隣り合う差の範囲に収まる＝プツッと鳴らない
        assert abs(x[0] - x[-1]) <= np.percentile(steps, 99.9), name


def test_cli_writes_library(project_root: Path, capsys):
    assert main([], project_root=project_root) == 0
    cfg = load_yaml("config/sfx.yaml", project_root)["sfx"]
    for name in cfg["library"]:
        rate, data = read(project_root / cfg["dir"] / f"{name}.wav")
        assert rate == 24000 and len(data) > 0
    assert main([], project_root=project_root) == 0          # 既存は作り直さない
    assert "既存" in capsys.readouterr().out
