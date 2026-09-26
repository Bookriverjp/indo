"""VOICEVOX ENGINE の provider adapter（HTTP、APIキー不要）。"""
from __future__ import annotations

import copy
import json
import urllib.error
import urllib.parse
import urllib.request

from pipeline.tts.base import TTSError


def apply_prosody(query: dict, *, speed: float, intonation: float, phrase_end_rise: float,
                  post_phoneme: float) -> dict:
    """audio_query に話す速さ・抑揚を反映する。

    phrase_end_rise > 0 のとき、区切り（読点・句点の前）と文末のフレーズで、
    最後の2つの有声モーラの音高を +rise, +2*rise 上げる（栃木弁の尻上がり）。
    """
    q = copy.deepcopy(query)
    q["speedScale"] = speed
    q["intonationScale"] = intonation
    q["postPhonemeLength"] = post_phoneme
    if phrase_end_rise:
        phrases = q["accent_phrases"]
        for n, ap in enumerate(phrases):
            if not (ap.get("pause_mora") or n == len(phrases) - 1):
                continue
            voiced = [m for m in ap["moras"] if m["pitch"] > 0]
            for k, m in enumerate(voiced[-2:], start=1 if len(voiced) >= 2 else 2):
                m["pitch"] += phrase_end_rise * k
    return q


class VoicevoxProvider:
    name = "voicevox"

    def __init__(self, endpoint: str, timeout: float = 60):
        self.endpoint = endpoint.rstrip("/")
        self.timeout = timeout

    def _post(self, path: str, params: dict, body: bytes | None = None) -> bytes:
        url = f"{self.endpoint}{path}?{urllib.parse.urlencode(params)}"
        headers = {"Content-Type": "application/json"} if body is not None else {}
        req = urllib.request.Request(url, data=body if body is not None else b"", headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            raise TTSError(f"VOICEVOX がエラーを返しました（{e.code}）: {path}") from None
        except (urllib.error.URLError, OSError) as e:
            raise TTSError(f"VOICEVOX に接続できません（{self.endpoint}）。VOICEVOX を起動してください: {e}") from None

    def synthesize(self, text: str, *, style_id: int, speed: float, intonation: float,
                   phrase_end_rise: float, post_phoneme: float) -> bytes:
        query = json.loads(self._post("/audio_query", {"text": text, "speaker": style_id}))
        query = apply_prosody(query, speed=speed, intonation=intonation,
                              phrase_end_rise=phrase_end_rise, post_phoneme=post_phoneme)
        return self._post("/synthesis", {"speaker": style_id}, json.dumps(query).encode("utf-8"))
