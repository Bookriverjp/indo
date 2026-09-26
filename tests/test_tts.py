import io
import json
import shutil
import urllib.request
import wave
from pathlib import Path

import pytest

from pipeline.config import load_yaml
from pipeline.tts.__main__ import main, synthesize_episode
from pipeline.tts.base import TTSError
from pipeline.tts.readings import apply_readings, load_readings
from pipeline.tts.voicevox import VoicevoxProvider, apply_prosody

REPO = Path(__file__).resolve().parents[1]
FIX = Path(__file__).parent / "fixtures"


def wav_bytes(seconds: float, rate: int = 24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(rate * seconds))
    return buf.getvalue()


class FakeTTS:
    name = "fake"

    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def synthesize(self, text, *, style_id, speed, intonation, phrase_end_rise, post_phoneme):
        if self.fail:
            raise TTSError("VOICEVOX に接続できません")
        self.calls.append({"text": text, "style_id": style_id, "speed": speed,
                           "intonation": intonation, "rise": phrase_end_rise})
        return wav_bytes(0.1 * len(text))


# --- prosody ------------------------------------------------------------------------

def query():
    def mora(p): return {"text": "ア", "pitch": p}
    return {"accent_phrases": [
        {"moras": [mora(5.5), mora(5.6), mora(5.7)], "pause_mora": {"text": "、", "pitch": 0}},
        {"moras": [mora(5.5), mora(0.0), mora(5.4)], "pause_mora": None},
        {"moras": [mora(5.5), mora(5.6), mora(5.8)], "pause_mora": None},
    ], "speedScale": 1.0, "intonationScale": 1.0}


def test_prosody_flat_and_rise() -> None:
    q = apply_prosody(query(), speed=1.05, intonation=0.4, phrase_end_rise=0.1, post_phoneme=0.1)
    assert q["speedScale"] == 1.05 and q["intonationScale"] == 0.4 and q["postPhonemeLength"] == 0.1
    first = [m["pitch"] for m in q["accent_phrases"][0]["moras"]]
    assert first == pytest.approx([5.5, 5.7, 5.9])            # 区切りの前：最後の2モーラを +0.1, +0.2
    middle = [m["pitch"] for m in q["accent_phrases"][1]["moras"]]
    assert middle == pytest.approx([5.5, 0.0, 5.4])           # 区切りでないフレーズは変えない
    last = [m["pitch"] for m in q["accent_phrases"][2]["moras"]]
    assert last == pytest.approx([5.5, 5.7, 6.0])             # 文末も上げる


def test_prosody_without_rise_keeps_pitch() -> None:
    q = apply_prosody(query(), speed=1.05, intonation=1.0, phrase_end_rise=0.0, post_phoneme=0.1)
    assert [m["pitch"] for m in q["accent_phrases"][2]["moras"]] == [5.5, 5.6, 5.8]


def test_prosody_skips_unvoiced_moras() -> None:
    q = query()
    q["accent_phrases"][2]["moras"][2]["pitch"] = 0.0
    q = apply_prosody(q, speed=1.0, intonation=1.0, phrase_end_rise=0.1, post_phoneme=0.1)
    assert [m["pitch"] for m in q["accent_phrases"][2]["moras"]] == pytest.approx([5.6, 5.8, 0.0])


# --- readings ---------------------------------------------------------------------

def test_readings_longest_first_and_episode_override(tmp_path: Path) -> None:
    glob = tmp_path / "g.yaml"
    glob.write_text("words:\n  - {surface: ベンガル, reading: べんがる}\n  - {surface: 西ベンガル州, reading: にしべんがるしゅう}\n  - {surface: 大仏飴, reading: だいぶつあめ}\n", encoding="utf-8")
    ep = tmp_path / "e.yaml"
    ep.write_text("words:\n  - {surface: 大仏飴, reading: だいぶつくん}\n", encoding="utf-8")
    words = load_readings(glob, ep)
    assert apply_readings("西ベンガル州とベンガルの大仏飴", words) == "にしべんがるしゅうとべんがるのだいぶつくん"


def test_readings_missing_episode_file(tmp_path: Path) -> None:
    glob = tmp_path / "g.yaml"
    glob.write_text("words: []\n", encoding="utf-8")
    assert load_readings(glob, tmp_path / "none.yaml") == []


# --- VOICEVOX adapter (stub HTTP) ---------------------------------------------------

class StubResponse(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): return False


def test_voicevox_adapter_requests(monkeypatch) -> None:
    seen = []

    def fake_urlopen(req, timeout=None):
        seen.append(req)
        if "/audio_query" in req.full_url:
            return StubResponse(json.dumps(query()).encode())
        return StubResponse(wav_bytes(0.2))

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    p = VoicevoxProvider("http://localhost:50021")
    data = p.synthesize("こんにちは", style_id=63, speed=1.05, intonation=0.4, phrase_end_rise=0.1, post_phoneme=0.1)
    assert data[:4] == b"RIFF"
    assert "speaker=63" in seen[0].full_url and "text=" in seen[0].full_url
    body = json.loads(seen[1].data)
    assert body["intonationScale"] == 0.4 and body["speedScale"] == 1.05
    assert "speaker=63" in seen[1].full_url


def test_voicevox_unreachable_raises_tts_error() -> None:
    p = VoicevoxProvider("http://127.0.0.1:9", timeout=1)
    with pytest.raises(TTSError, match="VOICEVOX"):
        p.synthesize("あ", style_id=61, speed=1.0, intonation=1.0, phrase_end_rise=0.0, post_phoneme=0.1)


# --- workflow ----------------------------------------------------------------------

@pytest.fixture
def root(project_root: Path) -> Path:
    ep = project_root / "episodes" / "EP0001_sample" / "script"
    ep.mkdir(parents=True)
    shutil.copy(FIX / "script_valid.json", ep / "script_main.json")
    shutil.copy(FIX / "shorts_valid.json", ep / "script_shorts.json")
    return project_root


def narration(root: Path) -> dict:
    return json.loads((root / "episodes" / "EP0001_sample" / "audio" / "narration.json").read_text(encoding="utf-8"))


def test_synthesizes_every_block_with_style_and_prosody(root: Path) -> None:
    tts = FakeTTS()
    synthesize_episode(root, "EP0001_sample", tts)
    items = narration(root)["items"]
    main_items = [i for i in items if i["target"] == "main"]
    assert [i["block_id"] for i in main_items] == ["b01", "b02", "b03", "b04", "b05", "b06"]
    by_id = {i["block_id"]: i for i in main_items}
    assert by_id["b02"]["kind"] == "comment" and by_id["b02"]["intonation"] == 0.4 and by_id["b02"]["phrase_end_rise"] == 0.1
    assert by_id["b04"]["intonation"] == 1.0 and by_id["b04"]["phrase_end_rise"] == 0.0
    assert by_id["b04"]["style_id"] == 61
    # 読みの辞書：字幕用の text は元のまま、spoken_text は読み
    assert "大仏飴" in by_id["b02"]["text"] and "だいぶつあめ" in by_id["b02"]["spoken_text"]
    wav_path = root / "episodes" / "EP0001_sample" / by_id["b02"]["file"]
    assert wav_path.exists() and by_id["b02"]["seconds"] == pytest.approx(0.1 * len(by_id["b02"]["spoken_text"]), abs=0.01)
    shorts = [i for i in items if i["target"] == "shorts"]
    assert [i["block_id"] for i in shorts] == ["sb01", "sb02", "cta"]
    assert shorts[0]["style_id"] == 62                        # expression surprise → おどろき
    assert narration(root)["credit"] == "VOICEVOX:中国うさぎ"


def test_character_voice_uses_its_own_speaker_and_credit(root: Path) -> None:
    path = root / "episodes" / "EP0001_sample" / "script" / "script_main.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["sections"][3]["blocks"].append({"block_id": "b07", "kind": "staging", "text": "……アニク……",
                                          "source_ids": [], "expression": "scared", "voice": "woman"})
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tts = FakeTTS()
    synthesize_episode(root, "EP0001_sample", tts)
    items = {i["block_id"]: i for i in narration(root)["items"] if i["target"] == "main"}
    assert items["b07"]["voice"] == "woman" and items["b07"]["style_id"] == 36
    assert items["b07"]["phrase_end_rise"] == 0.0
    call = next(c for c in tts.calls if c["text"] == "……アニク……")
    assert call["speed"] == 0.9
    assert items["b04"]["voice"] == "narrator"
    assert narration(root)["credits"] == ["VOICEVOX:中国うさぎ", "VOICEVOX:四国めたん"]


def test_unknown_character_voice_is_an_error(root: Path) -> None:
    from pipeline.tts.__main__ import NarrationError

    path = root / "episodes" / "EP0001_sample" / "script" / "script_main.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["sections"][3]["blocks"][0]["voice"] = "ghost_king"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(NarrationError, match="ghost_king"):
        synthesize_episode(root, "EP0001_sample", FakeTTS())


def test_rerun_only_regenerates_changed_blocks(root: Path) -> None:
    synthesize_episode(root, "EP0001_sample", FakeTTS())
    tts = FakeTTS()
    synthesize_episode(root, "EP0001_sample", tts)
    assert tts.calls == []
    path = root / "episodes" / "EP0001_sample" / "script" / "script_main.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["sections"][3]["blocks"][0]["text"] = "変更したテスト用の伝承部分です。"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    synthesize_episode(root, "EP0001_sample", tts)
    assert [c["text"] for c in tts.calls] == ["変更したテスト用の伝承部分です。"]
    tts2 = FakeTTS()
    synthesize_episode(root, "EP0001_sample", tts2, force=True)
    assert len(tts2.calls) == 9


def test_shorts_are_optional(root: Path) -> None:
    (root / "episodes" / "EP0001_sample" / "script" / "script_shorts.json").unlink()
    synthesize_episode(root, "EP0001_sample", FakeTTS())
    assert {i["target"] for i in narration(root)["items"]} == {"main"}


def test_cli_missing_script(project_root: Path, capsys) -> None:
    assert main(["EP0001_sample"], project_root=project_root, provider=FakeTTS()) == 2
    assert "script_main.json" in capsys.readouterr().err


def test_cli_engine_down_explains(root: Path, capsys) -> None:
    assert main(["EP0001_sample"], project_root=root, provider=FakeTTS(fail=True)) == 2
    assert "VOICEVOX" in capsys.readouterr().err


def test_cli_ok(root: Path, capsys) -> None:
    assert main(["EP0001_sample"], project_root=root, provider=FakeTTS()) == 0
    out = capsys.readouterr().out
    assert "narration.json" in out and "本編" in out


# --- 実エンジン（起動していなければ skip） ----------------------------------------

def engine_up() -> bool:
    try:
        with urllib.request.urlopen("http://localhost:50021/version", timeout=1):
            return True
    except OSError:
        return False


@pytest.mark.skipif(not engine_up(), reason="VOICEVOX engine is not running")
def test_real_voicevox_engine() -> None:
    cfg = load_yaml("config/voice.yaml")["tts"]
    p = VoicevoxProvider(cfg["endpoint"])
    data = p.synthesize("おばんです、大仏飴だよ。", style_id=cfg["styles"]["normal"]["id"], speed=1.05,
                        intonation=0.4, phrase_end_rise=0.1, post_phoneme=0.1)
    with wave.open(io.BytesIO(data)) as w:
        assert w.getnframes() / w.getframerate() > 0.5
