import json
import shutil
import threading
import urllib.error
import urllib.request
import wave
from pathlib import Path

import pytest
from PIL import Image

from pipeline.qa.gates import GATES, decide, evaluate
from pipeline.qa.__main__ import main
from pipeline.qa.server import make_server

REPO = Path(__file__).resolve().parents[1]
FIX = Path(__file__).parent / "fixtures"
EP = "EP0001_sample"


def wav(path: Path, seconds=0.3):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000)
        w.writeframes(b"\x00\x00" * int(24000 * seconds))


@pytest.fixture
def root(project_root: Path) -> Path:
    shutil.copytree(REPO / "prompts", project_root / "prompts")
    shutil.copytree(REPO / "assets", project_root / "assets")
    ep = project_root / "episodes" / EP
    for sub, name, src in [("research", "research.json", "research_valid.json"),
                           ("script", "script_main.json", "script_valid.json"),
                           ("storyboard", "storyboard.json", "storyboard_rich.json")]:
        (ep / sub).mkdir(parents=True, exist_ok=True)
        shutil.copy(FIX / src, ep / sub / name)
    (ep / "research" / "research_review.md").write_text("# review\n", encoding="utf-8")
    return project_root


def ep(root):
    return root / "episodes" / EP


def status(root):
    return {g["gate"]: g for g in evaluate(root, EP)}


def make_visual_ready(root):
    from pipeline.assets import main as assets_main
    assert assets_main([EP], project_root=root) == 0
    manifest = json.loads((ep(root) / "storyboard" / "asset_manifest.json").read_text(encoding="utf-8"))
    for a in manifest["assets"]:
        if a["scope"] == "episode":
            p = ep(root) / a["file"]
            p.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGBA", (64, 64)).save(p)
    (ep(root) / "output").mkdir(exist_ok=True)
    Image.new("RGB", (1280, 720)).save(ep(root) / "output" / "thumbnail.png")
    appr = root / "assets" / "shared" / "daibutsuame" / "approval.yaml"
    appr.write_text("approved: true\napproved_by: owner\napproved_at: 2026-09-26\n", encoding="utf-8")


def make_audio_ready(root):
    items = []
    for b in ["b01", "b02", "b03", "b04", "b05", "b06"]:
        wav(ep(root) / "audio" / "generated" / f"main_{b}.wav")
        items.append({"target": "main", "block_id": b, "file": f"audio/generated/main_{b}.wav", "seconds": 0.3})
    (ep(root) / "audio" / "narration.json").write_text(json.dumps({"items": items}), encoding="utf-8")


# --- gates -------------------------------------------------------------------------

def test_gate_order():
    assert [g for g in GATES] == ["research", "script", "visual", "audio", "final"]


def test_initial_status(root):
    s = status(root)
    assert s["research"]["state"] == "pending" and s["research"]["errors"] == []
    assert s["script"]["state"] == "waiting"          # 前の関門が未承認
    assert s["visual"]["state"] == "waiting"


def test_research_fail_blocks(root):
    p = ep(root) / "research" / "research.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    for s in d["sources"]:
        s["reliability"] = "D"
    p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    s = status(root)
    assert s["research"]["state"] == "blocked" and any("E_ONLY_D" in e for e in s["research"]["errors"])
    with pytest.raises(ValueError, match="自動チェック"):
        decide(root, EP, "research", "approved", note="")


def test_approve_in_order_and_stale_on_change(root):
    decide(root, EP, "research", "approved", note="OK")
    s = status(root)
    assert s["research"]["state"] == "approved" and s["script"]["state"] == "pending"
    with pytest.raises(ValueError, match="前の関門"):
        decide(root, EP, "visual", "approved", note="")
    # 承認後に中身が変わったら再確認
    p = ep(root) / "research" / "research.json"
    d = json.loads(p.read_text(encoding="utf-8")); d["plot_summary"] += "（修正）"
    p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    s = status(root)
    assert s["research"]["state"] == "stale" and s["script"]["state"] == "waiting"


def test_reject_needs_note(root):
    with pytest.raises(ValueError, match="理由"):
        decide(root, EP, "research", "rejected", note="")
    decide(root, EP, "research", "rejected", note="出典をもう1つ")
    s = status(root)
    assert s["research"]["state"] == "rejected" and s["research"]["decision"]["note"] == "出典をもう1つ"


def test_visual_and_audio_checks(root):
    decide(root, EP, "research", "approved", note="")
    decide(root, EP, "script", "approved", note="")
    s = status(root)
    assert s["visual"]["state"] == "blocked"
    make_visual_ready(root)
    s = status(root)
    assert s["visual"]["state"] == "pending", s["visual"]["errors"]
    decide(root, EP, "visual", "approved", note="")
    assert status(root)["audio"]["state"] == "blocked"
    make_audio_ready(root)
    assert status(root)["audio"]["state"] == "pending"


def test_visual_blocked_without_narrator_approval(root):
    decide(root, EP, "research", "approved", note="")
    decide(root, EP, "script", "approved", note="")
    make_visual_ready(root)
    (root / "assets" / "shared" / "daibutsuame" / "approval.yaml").write_text("approved: false\n", encoding="utf-8")
    assert any("大仏飴" in e for e in status(root)["visual"]["errors"])


def test_final_requires_all_outputs(root):
    for g in ("research", "script"):
        decide(root, EP, g, "approved", note="")
    make_visual_ready(root); decide(root, EP, "visual", "approved", note="")
    make_audio_ready(root); decide(root, EP, "audio", "approved", note="")
    errs = status(root)["final"]["errors"]
    assert any("episode.mp4" in e for e in errs) and any("youtube_metadata.json" in e for e in errs)


# --- CLI ---------------------------------------------------------------------------

def test_cli_status_and_decisions(root, capsys):
    assert main(["status", EP], project_root=root) == 0
    assert "research" in capsys.readouterr().out
    assert main(["approve", EP, "research", "--note", "良い"], project_root=root) == 0
    assert main(["approve", EP, "visual"], project_root=root) == 2
    assert "前の関門" in capsys.readouterr().err
    assert main(["reject", EP, "script"], project_root=root) == 2   # 理由なし
    gates = (ep(root) / "output" / "qa_gates.yaml").read_text(encoding="utf-8")
    assert (ep(root) / "output" / "qa_report.md").exists()
    assert "research" in gates and "approved" in gates


# --- local server --------------------------------------------------------------------

@pytest.fixture
def server(root):
    srv = make_server(root, EP, port=0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", root
    srv.shutdown()


def get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, r.read()


def test_server_page_and_decision(server):
    base, root = server
    code, body = get(base + "/")
    text = body.decode("utf-8")
    assert code == 200 and "リサーチ" in text and "承認" in text
    req = urllib.request.Request(base + "/decide", data=json.dumps({"gate": "research", "decision": "approved", "note": "OK"}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=5) as r:
        assert json.loads(r.read())["ok"] is True
    assert status(root)["research"]["state"] == "approved"


def test_server_rejects_bad_decision(server):
    base, _ = server
    req = urllib.request.Request(base + "/decide", data=json.dumps({"gate": "final", "decision": "approved", "note": ""}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=5)
    assert e.value.code == 400


def test_server_serves_episode_files_only(server):
    base, _ = server
    code, body = get(base + "/file/research/research_review.md")
    assert code == 200 and b"review" in body
    for bad in ("/file/../../config/voice.yaml", "/file/%2e%2e/%2e%2e/config/voice.yaml", "/file//etc/passwd"):
        with pytest.raises(urllib.error.HTTPError) as e:
            get(base + bad)
        assert e.value.code in (403, 404)
