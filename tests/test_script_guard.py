import copy
import json
from pathlib import Path

import pytest

from pipeline.config import load_yaml
from pipeline.script_guard import check_main_script, check_shorts_script, find_banned_phrases, render_review_md

FIX = Path(__file__).parent / "fixtures"
RULES = load_yaml("config/script_rules.yaml")
PERSONA = load_yaml("config/persona.yaml")["persona"]


@pytest.fixture
def script() -> dict:
    return json.loads((FIX / "script_valid.json").read_text(encoding="utf-8"))


@pytest.fixture
def shorts() -> dict:
    return json.loads((FIX / "shorts_valid.json").read_text(encoding="utf-8"))


def codes(issues) -> set[str]:
    return {i.code for i in issues}


def set_text(script: dict, section: str, text: str, kind: str | None = None) -> None:
    for sec in script["sections"]:
        if sec["section"] == section:
            sec["blocks"][0]["text"] = text
            if kind:
                sec["blocks"][0]["kind"] = kind
            return
    raise KeyError(section)


# --- banned phrases ------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "これは実際に起きた出来事です。",
    "本当にあった怖い話です。",
    "インド人はみんな信じています。",
    "日本では誰も知らない話です。",
    "これは日本初公開の伝説です。",
])
def test_banned_phrases_detected(text: str) -> None:
    assert find_banned_phrases(text, RULES)


@pytest.mark.parametrize("text", [
    "実話かどうかは分かりません。",
    "本当にあったとは言えません。",
    "実際に起きたわけではないようです。",
    "実話ではないとされています。",
])
def test_negated_phrases_are_allowed(text: str) -> None:
    assert find_banned_phrases(text, RULES) == []


def test_banned_phrase_in_script_is_error(script: dict) -> None:
    set_text(script, "story", "これは実際に起きた話です。")
    result = check_main_script(script, RULES, PERSONA)
    assert "E_BANNED_PHRASE" in codes(result.errors)


# --- structure -------------------------------------------------------------------

def test_valid_fixture_has_no_errors(script: dict) -> None:
    result = check_main_script(script, RULES, PERSONA)
    assert result.errors == []


def test_missing_required_section_is_error(script: dict) -> None:
    script["sections"] = [s for s in script["sections"] if s["section"] != "commentary"]
    assert "E_MISSING_SECTION" in codes(check_main_script(script, RULES, PERSONA).errors)


def test_section_order_is_error(script: dict) -> None:
    script["sections"][0], script["sections"][1] = script["sections"][1], script["sections"][0]
    assert "E_SECTION_ORDER" in codes(check_main_script(script, RULES, PERSONA).errors)


def test_duplicate_section_is_error(script: dict) -> None:
    script["sections"].insert(4, copy.deepcopy(script["sections"][3]))
    assert "E_SECTION_ORDER" in codes(check_main_script(script, RULES, PERSONA).errors)


def test_intro_without_name_is_error(script: dict) -> None:
    set_text(script, "intro", "こんにちは。今日も不思議なお話です。")
    assert "E_INTRO_NAME" in codes(check_main_script(script, RULES, PERSONA).errors)


def test_long_hook_is_warning(script: dict) -> None:
    set_text(script, "hook", "あ" * 91)
    assert "W_HOOK_LONG" in codes(check_main_script(script, RULES, PERSONA).warnings)


def test_short_script_is_warning(script: dict) -> None:
    assert "W_LENGTH" in codes(check_main_script(script, RULES, PERSONA).warnings)


def test_length_in_range_has_no_length_warning(script: dict) -> None:
    set_text(script, "story", "あ" * 3000, kind="staging")
    assert "W_LENGTH" not in codes(check_main_script(script, RULES, PERSONA).warnings)


def test_no_hedge_anywhere_is_warning(script: dict) -> None:
    set_text(script, "background", "テスト用の地域のお話です。")
    set_text(script, "commentary", "細部もいろいろです。")
    assert "W_NO_HEDGE" in codes(check_main_script(script, RULES, PERSONA).warnings)


def test_description_reference_is_warning(script: dict) -> None:
    set_text(script, "ending", "出典は概要欄にまとめたよ。またね。")
    assert "W_DESCRIPTION_REF" in codes(check_main_script(script, RULES, PERSONA).warnings)


def test_ending_without_sources_mention_is_warning(script: dict) -> None:
    set_text(script, "ending", "そんじゃ、またね。だいじだべ？")
    assert "W_ENDING_SOURCES" in codes(check_main_script(script, RULES, PERSONA).warnings)


# --- persona ---------------------------------------------------------------------

def test_forbidden_first_person_in_comment_is_error(script: dict) -> None:
    set_text(script, "intro", "こんにちは、大仏飴です。私と一緒に見ていきましょう。")
    assert "E_FIRST_PERSON" in codes(check_main_script(script, RULES, PERSONA).errors)


def test_boku_is_now_forbidden(script: dict) -> None:
    set_text(script, "intro", "おばんです、大仏飴だよ。ぼくと一緒に見てくべ。")
    assert "E_FIRST_PERSON" in codes(check_main_script(script, RULES, PERSONA).errors)


def test_comment_without_dialect_is_warning(script: dict) -> None:
    set_text(script, "intro", "こんにちは、大仏飴です。一緒に見ていきましょう。")
    set_text(script, "ending", "出典は概要欄にあります。またね。")
    assert "W_NO_DIALECT" in codes(check_main_script(script, RULES, PERSONA).warnings)


def test_kowai_in_comment_is_warning(script: dict) -> None:
    set_text(script, "ending", "今日はしゃべりすぎてこわいっぺ。出典は概要欄だよ。")
    assert "W_KOWAI" in codes(check_main_script(script, RULES, PERSONA).warnings)


def test_legend_not_desu_masu_is_warning(script: dict) -> None:
    set_text(script, "story", "むかし、村に灯りがともったんだべ。")
    assert "W_NARRATION_STYLE" in codes(check_main_script(script, RULES, PERSONA).warnings)


def test_legend_desu_masu_has_no_style_warning(script: dict) -> None:
    set_text(script, "story", "むかし、村に灯りがともった、と語られています。")
    assert "W_NARRATION_STYLE" not in codes(check_main_script(script, RULES, PERSONA).warnings)


def test_first_person_in_legend_quote_is_allowed(script: dict) -> None:
    set_text(script, "story", "娘は「私が行きます」と言った、と語られています。")
    assert "E_FIRST_PERSON" not in codes(check_main_script(script, RULES, PERSONA).errors)


# --- shorts ----------------------------------------------------------------------

def test_valid_shorts(shorts: dict) -> None:
    result = check_shorts_script(shorts, RULES, PERSONA)
    assert result.errors == [] and result.warnings == []


def test_shorts_too_long_is_error(shorts: dict) -> None:
    shorts["blocks"][1]["text"] = "あ" * 300
    assert "E_SHORTS_LENGTH" in codes(check_shorts_script(shorts, RULES, PERSONA).errors)


def test_shorts_long_hook_is_warning(shorts: dict) -> None:
    shorts["blocks"][0]["text"] = "あ" * 16
    assert "W_HOOK_LONG" in codes(check_shorts_script(shorts, RULES, PERSONA).warnings)


def test_shorts_banned_phrase_in_cta_is_error(shorts: dict) -> None:
    shorts["cta_text"] = "日本初公開の本編はこちら。"
    assert "E_BANNED_PHRASE" in codes(check_shorts_script(shorts, RULES, PERSONA).errors)


# --- review markdown -----------------------------------------------------------

def test_review_md(script: dict) -> None:
    md = render_review_md("テスト", check_main_script(script, RULES, PERSONA), chars=100, minutes=0.3)
    assert "W_LENGTH" in md and "約0.3分" in md and "- [ ]" in md
