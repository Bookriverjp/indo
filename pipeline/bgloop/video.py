"""背景ループを MP4（または1コマずつの PNG）に書き出す。並列で描くときの作業プロセスの関数もここに置く
（spawn で起動した作業プロセスは パッケージの __main__ にある関数を読み込めないため）。"""
from __future__ import annotations

import multiprocessing as mp
import subprocess
import time
from pathlib import Path

_R = None


def _init_worker(kwargs: dict) -> None:
    global _R
    import cv2

    from pipeline.bgloop.render import LoopRenderer
    cv2.setNumThreads(1)          # プロセスごとに1本（並列はプロセスの数で取る）
    _R = LoopRenderer(**kwargs)


def _render_frame(i: int) -> bytes:
    return _R.frame(i).tobytes()


def render_video(kwargs: dict, out: Path, *, crf: int, preset: str, workers: int, tune: str | None = "grain",
                 log=print) -> Path:
    import imageio_ffmpeg

    from pipeline.bgloop.render import LoopRenderer

    first = LoopRenderer(**kwargs)
    W, H, N, fps = first.g.Wo, first.g.Ho, first.N, first.fps
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(fps), "-i", "-",
           "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p",
           # キーフレームは先頭の1枚だけ（途中のキーフレームで絵の細かい模様が一瞬変わって見えるのを防ぐ）
           "-x264-params", f"keyint={N}:min-keyint={N}:scenecut=0",
           *(["-tune", tune] if tune else []), "-movflags", "+faststart", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    t0 = time.time()
    pool = None
    try:
        if workers <= 1:
            frames = (first.frame(i).tobytes() for i in range(N))
        else:
            del first
            pool = mp.get_context("spawn").Pool(workers, initializer=_init_worker, initargs=(kwargs,))
            frames = pool.imap(_render_frame, range(N), chunksize=2)
        for k, buf in enumerate(frames):
            proc.stdin.write(buf)
            if k % max(1, N // 10) == 0:
                log(f"  {k * 100 // N}%  ({k}/{N} コマ, {time.time() - t0:.0f}秒)")
    finally:
        if pool is not None:
            pool.terminate()
            pool.join()
        proc.stdin.close()
        code = proc.wait()
    if code != 0:
        raise RuntimeError(f"ffmpeg failed (exit {code})")
    return out


def write_stills(kwargs: dict, frames: list[int], out_dir: Path) -> list[Path]:
    from PIL import Image

    from pipeline.bgloop.render import LoopRenderer

    r = LoopRenderer(**kwargs)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for i in frames:
        p = out_dir / f"frame_{i:05d}.png"
        Image.fromarray(r.frame(i)).save(p)
        paths.append(p)
    return paths
