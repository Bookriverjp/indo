import copy
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image

from pipeline.bgloop.__main__ import main
from pipeline.bgloop.cut import run_cut
from pipeline.bgloop.matte import fill_plate, soft_matte, unmix
from pipeline.bgloop.motion import Pulse, Wind, two_phase
from pipeline.bgloop.render import LoopRenderer
from pipeline.bgloop.scene import Scale, hue_in, load_scene

REPO = Path(__file__).resolve().parents[1]

# 小さな作り物の夜景：空（藍）に金の縁取りの雲、陸（緑）に木と灯り、川（青）、右下に手前の草
W, H = 192, 108
SCENE = {
    "name": "tiny",
    "image": "tiny.png",
    "ref_size": [W, H],
    "sky": {"hue": [98, 118], "min_value": 42, "zone": [[0, 0], [W, 0], [W, 64], [0, 64]]},
    "clouds": {},
    "water": {"zone": [[0, 76], [W, 76], [W, H], [0, H]], "hue": [96, 122]},
    "foreground": [{"name": "reeds", "zone": [[150, 76], [W, 76], [W, H], [150, H]]}],
    "lights": {"hue": [5, 35], "min_sat": 100, "min_value": 190, "spots": [[50, 68, 5]]},
    "depth": {"sky": 0.05, "clouds": [0.08, 0.12], "ground": [[60, 0.3], [H, 0.9]], "soften": 4},
    "motion": {
        "camera": {"shift": [12, 4], "zoom": 0.01},
        "clouds": {"drift": 4.0, "billow": 1.0},
        "water": {"flow": [2, 8], "ripple": [0.5, 2]},
        "sway": [{"name": "tree", "base": [30, 76], "amp": 3, "flutter": 0.5,
                  "poly": [[10, 40], [50, 40], [50, 76], [10, 76]]}],
        "protect": [[[44, 62], [58, 62], [58, 76], [44, 76]]],
        "reeds": {"amp": 6, "top": 76, "bottom": H},
    },
    "fx": {
        "fireflies": {"count": 3, "zone": [[0, 60], [W, 60], [W, 80], [0, 80]]},
        "petals": {"count": 2, "spawn": [10, 40, 50, 60], "land": [70, 76]},
        "mist": [{"rect": [0, 64, W, 80], "opacity": 0.2}, {"rect": [60, 5, W, 45], "layer": "sky", "opacity": 0.1}],
        "bokeh": {"petals": 1, "branch": {"source": [10, 40, 50, 70], "blur": 4, "depth": 2}},
    },
}


def tiny_scene_image(path: Path) -> Path:
    img = np.zeros((H, W, 3), np.uint8)
    img[:64] = (30, 60, 100)                                     # 夜空
    for x, y in ((20, 8), (90, 14), (170, 6), (60, 30)):          # 星
        img[y, x] = (255, 250, 220)
    cv2.ellipse(img, (125, 28), (32, 11), 0, 0, 360, (80, 110, 150), -1)   # 雲
    cv2.ellipse(img, (125, 28), (32, 11), 0, 180, 360, (200, 160, 60), 2)  # 金の縁取り
    img[64:76] = (40, 90, 40)                                    # 岸
    cv2.ellipse(img, (30, 55), (18, 14), 0, 0, 360, (30, 80, 35), -1)      # 木
    img[65:71, 47:53] = (255, 170, 40)                           # 灯り
    img[76:] = (20, 60, 100)                                     # 川
    for y in range(78, H, 4):
        img[y, ::3] = (60, 100, 140)
    for x in range(160, W, 6):                                   # 手前の草
        cv2.line(img, (x, H - 1), (x + 4, 80), (70, 120, 40), 2)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(img).save(path)
    return path


@pytest.fixture
def cut(tmp_path: Path) -> Path:
    image = tiny_scene_image(tmp_path / "tiny.png")
    run_cut(copy.deepcopy(SCENE), image, tmp_path / "cut", log=lambda *a: None)
    return tmp_path / "cut"


def renderer(cut: Path, **kw) -> LoopRenderer:
    args = {"seconds": 1.0, "fps": 8, "size": (W, H), "overscan": 1.08, "seed": 3}
    args.update(kw)
    return LoopRenderer(cut, copy.deepcopy(SCENE), **args)


# --- 動きの部品 -------------------------------------------------------------------------

def test_wind_is_periodic_and_travels() -> None:
    w = Wind(10.0, np.random.default_rng(0), speed=100.0)
    for t in (0.0, 1.3, 7.7):
        assert w.at(t) == pytest.approx(w.at(t + 10.0), abs=1e-9)
    assert w.at(2.0, x=100.0) == pytest.approx(w.at(1.0, x=0.0), abs=1e-9)   # 100px 先は 1秒遅れ


def test_wind_traveling_terms_match_direct_evaluation() -> None:
    w = Wind(8.0, np.random.default_rng(1), speed=50.0)
    x = np.linspace(0, 300, 7, dtype=np.float32)
    weight = np.ones_like(x)
    terms = w.traveling(weight, x)
    for t in (0.0, 2.5, 5.1):
        got = sum(b * fn(t) for b, fn in terms)
        want = np.array([w.at(t, float(v)) for v in x])
        assert np.allclose(got, want, atol=1e-4)


def test_two_phase_weights_hide_the_reset() -> None:
    for t in np.linspace(0, 4, 41):
        ja, jb, wa, wb = two_phase(float(t), 2.0)
        assert wa + wb == pytest.approx(1.0)
        assert -0.5 <= ja <= 0.5 and -0.5 <= jb <= 0.5
        if abs(abs(ja) - 0.5) < 1e-6:        # 巻き戻る瞬間は重みが 0
            assert wa == pytest.approx(0.0, abs=1e-6)


def test_pulse_is_periodic() -> None:
    p = Pulse(6.0, 3, 0.7)
    assert p(1.1) == pytest.approx(p(7.1))
    assert 0.0 <= p(2.0) <= 1.0


# --- 切り抜きの道具 ---------------------------------------------------------------------

def test_soft_matte_snaps_to_the_color_edge() -> None:
    I = np.zeros((40, 40, 3), np.float32)
    I[:, 20:] = (0.9, 0.8, 0.2)               # 色の境目は x=19 と 20 の間
    for off in (19, 21):                      # 1px ずれた大まかなマスク（はみ出す／足りない）
        rough = np.zeros((40, 40), np.float32)
        rough[:, off:] = 1.0
        a = soft_matte(I, rough, r=2, eps=1e-4)
        assert a.min() >= 0.0 and a.max() <= 1.0
        assert int(np.argmax(np.diff(a[5]))) == 19          # いちばん大きな段差は色の境目
        assert a[5, :14].max() < 0.01 and a[5, 26:].min() > 0.99


def test_unmix_recovers_foreground_color() -> None:
    F = np.full((4, 4, 3), (0.9, 0.2, 0.1), np.float32)
    B = np.full((4, 4, 3), (0.1, 0.2, 0.8), np.float32)
    a = np.full((4, 4), 0.4, np.float32)
    I = a[..., None] * F + (1 - a[..., None]) * B
    assert np.allclose(unmix(I, a, B), F, atol=1e-5)


def test_fill_plate_fills_holes_with_nearby_colors() -> None:
    rng = np.random.default_rng(0)
    I = np.clip(np.full((60, 80, 3), 0.3, np.float32) + rng.normal(0, 0.03, (60, 80, 3)).astype(np.float32), 0, 1)
    I[20:40, 30:50] = (1.0, 0.0, 0.0)          # 取り除く物
    known = np.ones((60, 80), bool)
    known[18:42, 28:52] = False
    out = fill_plate(I, known, patch=12, sigma=4)
    assert np.isfinite(out).all()
    assert abs(out[20:40, 30:50].mean() - 0.3) < 0.05
    assert np.allclose(out[known], I[known], atol=1e-5)


def test_scale_maps_reference_coordinates() -> None:
    s = Scale([100, 50], (200, 100))
    assert s.pt((10, 20)) == (20.0, 40.0)
    assert s.rect([0, 0, 50, 25]) == (0, 0, 100, 50)
    m = s.shapes_mask({"rects": [[0, 0, 10, 10]], "circles": [[50, 25, 5]]})
    assert m[5, 5] and m[50, 100] and not m[90, 190]
    h = np.array([2, 90, 178])
    assert hue_in(h, [170, 10]).tolist() == [True, False, True]


# --- 切り抜き → 書き出し -----------------------------------------------------------------

def test_cut_separates_layers(cut: Path) -> None:
    for name in ("sky_plate.png", "clouds.png", "land.png", "foreground.png", "water.png", "depth.png", "overlay.png",
                 "cut.json"):
        assert (cut / name).exists(), name
    land = np.asarray(Image.open(cut / "land.png"))
    assert land[10, 100, 3] < 30 and land[70, 100, 3] > 220       # 空は透明、岸は不透明
    clouds = np.asarray(Image.open(cut / "clouds.png"))
    assert clouds[28, 125, 3] > 200 and clouds[50, 20, 3] < 10     # 雲だけ
    plate = np.asarray(Image.open(cut / "sky_plate.png")).astype(int)
    assert abs(plate[28, 125] - np.array([30, 60, 100])).max() < 40   # 雲の後ろは空の色で補ってある
    fg = np.asarray(Image.open(cut / "foreground.png"))
    assert fg[95, 170:190, 3].max() > 200 and fg[95, 20:100, 3].max() < 10
    water = np.asarray(Image.open(cut / "water.png"))
    assert water[90, 60] > 200 and water[30, 60] == 0


def test_loop_is_seamless_and_moving(cut: Path) -> None:
    r = renderer(cut)
    a, b = r.render_t(0.0), r.render_t(r.L)
    assert np.abs(a - b).max() < 1e-3                       # 最後のコマの次は最初のコマ
    frames = [r.frame(i).astype(np.float32) for i in range(r.N)]
    steps = [np.abs(frames[(i + 1) % r.N] - frames[i]).mean() for i in range(r.N)]
    assert min(steps) > 0.05                                # ずっと動いている
    assert steps[-1] < 3 * np.median(steps)                 # 継ぎ目だけ大きく変わらない
    assert frames[0].shape == (H, W, 3)


def test_protected_region_does_not_sway(cut: Path) -> None:
    scene = copy.deepcopy(SCENE)
    scene["motion"]["camera"] = {"shift": [0, 0], "zoom": 0.0}
    r = LoopRenderer(cut, scene, seconds=1.0, fps=8, size=(W, H), overscan=1.08, seed=3)
    dx, dy = r.land_bank.eval(0.3)
    hx, hy = int(51 / 2 * r.hw / (W / 2)), int(69 / 2)
    assert abs(dx[hy, hx]) < 0.05 and abs(dy[hy, hx]) < 0.05   # 灯りのある家は動かない
    assert np.abs(dx[25:35, 8:18]).max() > 0.1                 # 木は揺れる


def test_cli_cut_then_stills(tmp_path: Path, project_root: Path) -> None:
    tiny_scene_image(project_root / "assets/bgloop/tiny.png")
    import yaml
    (project_root / "assets/bgloop/tiny.yaml").write_text(yaml.safe_dump(SCENE, allow_unicode=True), encoding="utf-8")
    out = tmp_path / "out"
    assert main(["assets/bgloop/tiny.yaml", "--stage", "cut", "--out", str(out)], project_root=project_root) == 0
    assert (out / "cut" / "overlay.png").exists()
    assert main(["assets/bgloop/tiny.yaml", "--stage", "render", "--preview", "--stills", "0,3", "--out", str(out),
                 "--seconds", "1", "--fps", "4"], project_root=project_root) == 0
    assert (out / "stills" / "frame_00000.png").exists() and (out / "stills" / "frame_00003.png").exists()


def test_cli_reports_missing_scene(project_root: Path, capsys) -> None:
    assert main(["assets/bgloop/none.yaml"], project_root=project_root) == 2
    assert "scene file not found" in capsys.readouterr().err


def test_night_river_scene_is_valid() -> None:
    scene = load_scene(REPO / "assets/bgloop/night_river.yaml")
    assert (REPO / "assets/bgloop" / scene["image"]).exists()
    for key in ("sky", "water", "motion", "fx", "depth"):
        assert key in scene
    for rig in scene["motion"]["sway"]:
        assert ("base" in rig and ("top" in rig or "poly" in rig)) or "tops" in rig or "polys" in rig, rig["name"]


def test_grid_writes_starter_scene_that_runs(tmp_path: Path, project_root: Path) -> None:
    picture = tiny_scene_image(project_root / "assets/bgloop/new_scene.png")
    out = tmp_path / "out"
    assert main(["assets/bgloop/new_scene.png", "--stage", "grid", "--out", str(out)], project_root=project_root) == 0
    assert (out / "grid.png").exists()
    scene = load_scene(picture.with_suffix(".yaml"))
    assert scene["ref_size"] == [W, H] and scene["image"] == "new_scene.png"
    # ひな形のままでも切り抜き → 1コマの書き出しまで通る
    assert main(["assets/bgloop/new_scene.png", "--stage", "cut", "--out", str(out)], project_root=project_root) == 0
    assert main(["assets/bgloop/new_scene.png", "--stage", "render", "--stills", "0", "--seconds", "1", "--fps", "4",
                 "--out", str(out)], project_root=project_root) == 0
    assert (out / "stills" / "frame_00000.png").exists()


def test_video_without_ffmpeg_falls_back_to_opencv(cut: Path, tmp_path: Path, monkeypatch) -> None:
    from pipeline.bgloop import video
    monkeypatch.setattr(video, "find_ffmpeg", lambda: None)
    kwargs = {"cut_dir": cut, "scene": copy.deepcopy(SCENE), "seconds": 0.5, "fps": 8, "size": (W, H),
              "overscan": 1.08, "seed": 3}
    out = video.render_video(kwargs, tmp_path / "v.mp4", crf=20, preset="fast", workers=1, log=lambda *a: None)
    cap = cv2.VideoCapture(str(out))
    n = 0
    while cap.read()[0]:
        n += 1
    assert n == 4
