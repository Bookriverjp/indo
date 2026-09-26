"""OpenAI 画像API の provider adapter。"""
from __future__ import annotations

import base64
from contextlib import ExitStack
from pathlib import Path

from pipeline.images.base import ImageError


class OpenAIImageProvider:
    name = "openai"

    def __init__(self, *, model: str, quality: str, max_retries: int = 2, client=None):
        if client is None:
            import openai  # 実際に呼ぶときだけ読み込む（テストはネットワークなし）

            client = openai.OpenAI(max_retries=max_retries)
        self.client = client
        self.model = model
        self.quality = quality

    def generate(self, *, prompt: str, size: str, transparent: bool,
                 reference_images: tuple[Path, ...] = ()) -> bytes:
        params = {"model": self.model, "prompt": prompt, "size": size, "quality": self.quality,
                  "background": "transparent" if transparent else "opaque", "output_format": "png", "n": 1}
        try:
            if reference_images:
                with ExitStack() as stack:
                    files = [stack.enter_context(open(p, "rb")) for p in reference_images]
                    resp = self.client.images.edit(image=files, **params)
            else:
                resp = self.client.images.generate(**params)
        except Exception as e:  # SDK の例外型を外へ漏らさない
            if type(e).__module__.startswith("openai"):
                raise ImageError(f"OpenAI image API error: {e}") from e
            raise
        if not resp.data or not resp.data[0].b64_json:
            raise ImageError("OpenAI image API returned no image")
        return base64.b64decode(resp.data[0].b64_json)
