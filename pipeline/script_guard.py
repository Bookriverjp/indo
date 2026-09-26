"""PHASE 3: 台本の自動チェック（断定表現・構成・長さ・大仏飴の一人称）。

ルールは config/script_rules.yaml と config/persona.yaml。
errors は保存を止めて作り直させ、warnings は review に書いて Owner が判断する。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Issue:
    code: str
    message: str


@dataclass
class GuardResult:
    errors: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)


def find_banned_phrases(text: str, rules: dict) -> list[str]:
    """断定・一般化の表現を返す。直後が否定の形（「実話かどうか」など）なら除く。"""
    found = []
    for phrase in rules["banned_phrases"]:
        start = 0
        while (i := text.find(phrase, start)) != -1:
            after = text[i + len(phrase): i + len(phrase) + 8]
            if not any(after.startswith(n) for n in rules["negation_after"]):
                found.append(phrase)
                break
            start = i + 1
    return found


def _chars(text: str) -> int:
    return len("".join(text.split()))


def _check_texts(items: list[tuple[str, str, str]], rules: dict, persona: dict, result: GuardResult) -> None:
    """items: (block_id, kind, text)"""
    for bid, kind, text in items:
        for phrase in find_banned_phrases(text, rules):
            result.errors.append(Issue("E_BANNED_PHRASE", f"{bid}: 断定・一般化の表現「{phrase}」を使わないでください"))
        if kind == "comment":
            for fp in persona["forbidden_first_person"]:
                if fp in text:
                    result.errors.append(Issue(
                        "E_FIRST_PERSON",
                        f"{bid}: {persona['name']}の一人称は「{persona['first_person']}」です（「{fp}」は使わない）"))


def check_main_script(script: dict, rules: dict, persona: dict) -> GuardResult:
    r = rules["main"]
    result = GuardResult()
    sections = [s["section"] for s in script["sections"]]

    for name in r["required_sections"]:
        if name not in sections:
            result.errors.append(Issue("E_MISSING_SECTION", f"section {name} がありません"))
    order = [r["section_order"].index(s) for s in sections]
    if order != sorted(order) or len(set(sections)) != len(sections):
        result.errors.append(Issue("E_SECTION_ORDER",
                                   f"section は {' → '.join(r['section_order'])} の順に1回ずつ並べてください（現在: {' → '.join(sections)}）"))

    blocks = [(b["block_id"], b["kind"], b["text"], s["section"]) for s in script["sections"] for b in s["blocks"]]
    _check_texts([(bid, k, t) for bid, k, t, _ in blocks], rules, persona, result)

    by_section = {name: "".join(t for _, _, t, s in blocks if s == name) for name in sections}
    if "intro" in by_section and r["intro_must_include"] not in by_section["intro"]:
        result.errors.append(Issue("E_INTRO_NAME", f"intro で「{r['intro_must_include']}」と名乗ってください"))
    if _chars(by_section.get("hook", "")) > r["hook_max_chars"]:
        result.warnings.append(Issue("W_HOOK_LONG", f"hook が{r['hook_max_chars']}字（約15秒）を超えています"))
    if "ending" in by_section and not any(w in by_section["ending"] for w in r["ending_should_include"]):
        result.warnings.append(Issue("W_ENDING_SOURCES", "ending で出典・資料に触れていません"))

    all_text = "".join(t for _, _, t, _ in blocks)
    if not any(h in all_text for h in rules["hedge_phrases"]):
        result.warnings.append(Issue("W_NO_HEDGE", "「〜と語られています」など、伝承であることを示す言い回しがありません"))

    lo, hi = r["target_minutes"]
    minutes = _chars(all_text) / r["chars_per_minute"]
    if not lo <= minutes <= hi:
        result.warnings.append(Issue("W_LENGTH", f"長さが約{minutes:.1f}分です（目安 {lo}〜{hi}分）"))
    return result


def check_shorts_script(shorts: dict, rules: dict, persona: dict) -> GuardResult:
    r = rules["shorts"]
    result = GuardResult()
    items = [(b["block_id"], b["kind"], b["text"]) for b in shorts["blocks"]]
    _check_texts(items + [("cta", "comment", shorts["cta_text"])], rules, persona, result)

    total = _chars("".join(t for _, _, t in items) + shorts["cta_text"])
    if total > r["max_chars"]:
        result.errors.append(Issue("E_SHORTS_LENGTH", f"ショートが{total}字です（{r['max_chars']}字＝60秒以内）"))
    if _chars(shorts["blocks"][0]["text"]) > r["hook_max_chars"]:
        result.warnings.append(Issue("W_HOOK_LONG", f"最初のブロックが{r['hook_max_chars']}字（約2秒）を超えています"))
    return result


def script_length(texts: list[str], rules: dict) -> tuple[int, float]:
    chars = _chars("".join(texts))
    return chars, chars / rules["main"]["chars_per_minute"]


def render_review_md(title: str, result: GuardResult, *, chars: int, minutes: float) -> str:
    lines = [f"# 台本チェック: {title}", "", f"- 文字数: {chars}字（約{minutes:.1f}分）", ""]
    if result.warnings:
        lines += ["## 警告（Ownerが判断）", ""] + [f"- `{i.code}` {i.message}" for i in result.warnings] + [""]
    else:
        lines += ["警告はありません。", ""]
    lines += [
        "## Owner確認", "",
        "- [ ] 伝承（【伝承】）の内容が research の出典どおり",
        "- [ ] 不確実な点を断定していない",
        "- [ ] 大仏飴の口調・一人称が合っている",
        "- [ ] 表情の選び方が場面に合っている",
        "",
    ]
    return "\n".join(lines)
