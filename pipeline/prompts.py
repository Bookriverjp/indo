from __future__ import annotations

import re
from pathlib import Path

from pipeline.config import PROJECT_ROOT

_NAME_RE = re.compile(r"[0-9a-z_]+")
_VAR_RE = re.compile(r"\{\{\s*([a-z_][a-z0-9_]*)\s*\}\}")


class PromptError(Exception):
    pass


def load_prompt(name: str, root: Path | None = None) -> str:
    """prompts/<name>.md を読む。"""
    if not _NAME_RE.fullmatch(name):
        raise PromptError(f"invalid prompt name: {name!r}")
    path = (root or PROJECT_ROOT) / "prompts" / f"{name}.md"
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise PromptError(f"prompt not found: prompts/{name}.md") from None


def render(template: str, **variables: str) -> str:
    """{{name}} を置き換える。足りない変数があればエラー。"""
    missing = sorted({m for m in _VAR_RE.findall(template) if m not in variables})
    if missing:
        raise PromptError(f"missing prompt variables: {', '.join(missing)}")
    return _VAR_RE.sub(lambda m: str(variables[m.group(1)]), template)


def persona_block(persona: dict) -> str:
    """config/persona.yaml から、口調の指示文を作る。"""
    styles = persona["styles"]
    d = persona["dialect"]
    lines = [
        f"{persona['name']}の一人称は「{persona['first_person']}」です。",
        f"- 物語を読む部分（kind: {', '.join(styles['narration']['kinds'])}）: {styles['narration']['description']}",
        f"- {persona['name']}のコメント（kind: {', '.join(styles['comment']['kinds'])}）: {styles['comment']['description']}",
        f"{d['name']}の特徴:",
        *[f"- {f}" for f in d["features"]],
        f"{d['name']}の言葉:",
        *[f"- {v['word']}: {v['meaning']}" + (f"（{v['note']}）" if v.get("note") else "") for v in d["vocabulary"]],
    ]
    return "\n".join(lines)
