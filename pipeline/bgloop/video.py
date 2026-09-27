"""背景ループを MP4（または1コマずつの PNG）に書き出す。並列で描くときの作業プロセスの関数もここに置く
（spawn で起動した作業プロセスは パッケージの __main__ にある関数を読み込めないため）。"""
from __future__ import annotations

import multiprocessing as mp
import shutil
import subprocess
import time
from pathlib import Path

import numpy as np

_R = None


def _init_worker(kwargs: dict) -> None:
    global _R
    import cv2

    from pipeline.bgloop.render import LoopRenderer
    cv2.setNumThreads(1)          # プロセスごとに1本（並列はプロセスの数で取る）
    _R = LoopRenderer(**kwargs)


def _render_frame(i: int) -> bytes:
    return _R.frame(i).tobytes()


def find_ffmpeg() -> str | None:
    """ffmpeg の場所。imageio-ffmpeg に同梱のもの → PATH の ffmpeg の順。どちらもなければ None。"""
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return shutil.which("ffmpeg")


def _frames(kwargs: dict, first, N: int, workers: int):
    if workers <= 1:
        for i in range(N):
            yield first.frame(i)
        return
    pool = mp.get_context("spawn").Pool(workers, initializer=_init_worker, initargs=(kwargs,))
    try:
        for buf in pool.imap(_render_frame, range(N), chunksize=2):
            yield buf
    finally:
        pool.terminate()
        pool.join()


def render_video(kwargs: dict, out: Path, *, crf: int, preset: str, workers: int, tune: str | None = "grain",
                 log=print) -> Path:
    from pipeline.bgloop.render import LoopRenderer

    first = LoopRenderer(**kwargs)
    W, H, N, fps = first.g.Wo, first.g.Ho, first.N, first.fps
    out.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = find_ffmpeg()
    t0 = time.time()

    def progress(k):
        if k % max(1, N // 10) == 0:
            log(f"  {k * 100 // N}%  ({k}/{N} コマ, {time.time() - t0:.0f}秒)")

    if ffmpeg is None:
        # ffmpeg がない環境（ChatGPT など）：OpenCV で書き出す。画質とファイルの大きさは H.264 より劣る
        import cv2
        log("  ffmpeg が見つからないので OpenCV（mp4v）で書き出します")
        writer = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"mp4v"), fps, (W, H))
        if not writer.isOpened():
            raise RuntimeError("動画を書き出せません（ffmpeg も OpenCV の mp4v も使えない）。--stills でコマを PNG にしてください")
        try:
            for k, fr in enumerate(_frames(kwargs, first, N, workers)):
                arr = fr if not isinstance(fr, bytes) else np.frombuffer(fr, np.uint8).reshape(H, W, 3)
                writer.write(np.ascontiguousarray(arr[:, :, ::-1]))
                progress(k)
        finally:
            writer.release()
        return out

    cmd = [ffmpeg, "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(fps), "-i", "-",
           "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p",
           # キーフレームは先頭の1枚だけ（途中のキーフレームで絵の細かい模様が一瞬変わって見えるのを防ぐ）
           "-x264-params", f"keyint={N}:min-keyint={N}:scenecut=0",
           *(["-tune", tune] if tune else []), "-movflags", "+faststart", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        for k, fr in enumerate(_frames(kwargs, first, N, workers)):
            proc.stdin.write(fr if isinstance(fr, bytes) else fr.tobytes())
            progress(k)
    finally:
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
