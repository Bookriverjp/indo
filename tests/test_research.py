import copy
import json
from datetime import date
from pathlib import Path

import pytest

from pipeline.research import (
    GATE_FAIL,
    GATE_PASS,
    GATE_WARN,
    ResearchImportError,
    import_research,
    load_research_file,
    main,
    qa_research,
    render_review_md,
)

FIXTURE = Path(__file__).parent / "fixtures" / "research_valid.json"
TODAY = date(2026, 9, 26)


@pytest.fixture
def research() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def codes(result, level: str) -> set[str]:
    return {i.code for i in getattr(result, level)}


# --- QA ---------------------------------------------------------------------

def test_valid_fixture_passes(research: dict) -> None:
    result = qa_research(research, today=TODAY)
    assert result.errors == [] and result.warnings == []
    assert result.gate == GATE_PASS


def test_schema_violation_is_error_and_stops(research: dict) -> None:
    del research["checked_at"]
    result = qa_research(research, today=TODAY)
    assert codes(result, "errors") == {"E_SCHEMA"}
    assert result.gate == GATE_FAIL


def test_unknown_field_is_rejected(research: dict) -> None:
    research["plot_sumary"] = "typo"
    assert "E_SCHEMA" in codes(qa_research(research, today=TODAY), "errors")


def test_duplicate_source_id(research: dict) -> None:
    research["sources"][1]["id"] = "s01"
    assert "E_DUP_SOURCE_ID" in codes(qa_research(research, today=TODAY), "errors")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r.__setitem__("earliest_or_notable_source", "s99"),
        lambda r: r.__setitem__("modern_sources", ["s99"]),
        lambda r: r.__setitem__("plot_source_ids", ["s99"]),
        lambda r: r["variants"][0].__setitem__("source_ids", ["s99"]),
    ],
)
def test_unknown_source_reference(research: dict, mutate) -> None:
    mutate(research)
    result = qa_research(research, today=TODAY)
    assert "E_UNKNOWN_SOURCE_REF" in codes(result, "errors")
    assert result.gate == GATE_FAIL


def test_only_d_sources_is_error(research: dict) -> None:
    for s in research["sources"]:
        s["reliability"] = "D"
    assert "E_ONLY_D" in codes(qa_research(research, today=TODAY), "errors")


def test_c_source_without_notes_is_error(research: dict) -> None:
    research["sources"][1]["notes"] = None
    assert "E_C_WITHOUT_NOTES" in codes(qa_research(research, today=TODAY), "errors")


def test_future_checked_at_is_error(research: dict) -> None:
    research["checked_at"] = "2026-12-31"
    assert "E_CHECKED_AT" in codes(qa_research(research, today=TODAY), "errors")


def test_impossible_checked_at_is_error(research: dict) -> None:
    research["checked_at"] = "2026-02-30"
    assert "E_CHECKED_AT" in codes(qa_research(research, today=TODAY), "errors")


def test_no_b_or_better_is_warning(research: dict) -> None:
    research["sources"][0]["reliability"] = "C"
    research["sources"][0]["notes"] = "説明"
    result = qa_research(research, today=TODAY)
    assert "W_NO_B_OR_BETTER" in codes(result, "warnings")
    assert result.gate == GATE_WARN


def test_plot_only_from_d_is_warning(research: dict) -> None:
    research["sources"].append(
        {"id": "s03", "title": "blog", "author": None, "year": None, "url": "https://example.org/b",
         "bibliography": None, "source_type": "blog", "reliability": "D", "language": None,
         "notes": None, "accessed_at": None}
    )
    research["plot_source_ids"] = ["s03"]
    assert "W_PLOT_ONLY_D" in codes(qa_research(research, today=TODAY), "warnings")


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("variants", [], "W_NO_VARIANTS"),
        ("uncertain_points", [], "W_NO_UNCERTAIN_POINTS"),
        ("japanese_coverage_notes", None, "W_NO_JAPANESE_COVERAGE"),
        ("local_script", None, "W_NO_LOCAL_SCRIPT"),
    ],
)
def test_missing_recommended_content_is_warning(research: dict, field, value, code) -> None:
    research[field] = value
    result = qa_research(research, today=TODAY)
    assert code in codes(result, "warnings")
    assert result.gate == GATE_WARN


def test_source_without_locator_is_warning(research: dict) -> None:
    research["sources"][0]["bibliography"] = None
    assert "W_SOURCE_NO_LOCATOR" in codes(qa_research(research, today=TODAY), "warnings")


def test_non_http_url_is_schema_error(research: dict) -> None:
    research["sources"][1]["url"] = "javascript:alert(1)"
    assert "E_SCHEMA" in codes(qa_research(research, today=TODAY), "errors")


# --- review markdown --------------------------------------------------------

def test_review_md_lists_gate_sources_and_checklist(research: dict) -> None:
    research["variants"] = []
    md = render_review_md(research, qa_research(research, today=TODAY))
    assert "テスト用の架空の題材" in md
    assert "WARN" in md
    assert "W_NO_VARIANTS" in md
    assert "| s01 |" in md and "| A |" in md
    assert "- [ ] 出典" in md


def test_review_md_for_schema_failure_does_not_crash(research: dict) -> None:
    research = {"canonical_title": 1}
    md = render_review_md(research, qa_research(research, today=TODAY))
    assert "FAIL" in md and "E_SCHEMA" in md


# --- load / import ----------------------------------------------------------

def test_load_yaml_and_json(tmp_path: Path, research: dict) -> None:
    import yaml

    y = tmp_path / "r.yaml"
    y.write_text(yaml.safe_dump(research, allow_unicode=True), encoding="utf-8")
    assert load_research_file(y) == research
    assert load_research_file(FIXTURE) == research


def test_load_rejects_other_extensions(tmp_path: Path) -> None:
    p = tmp_path / "r.txt"
    p.write_text("{}", encoding="utf-8")
    with pytest.raises(ResearchImportError):
        load_research_file(p)


def test_load_rejects_broken_file(tmp_path: Path) -> None:
    p = tmp_path / "r.json"
    p.write_text("{", encoding="utf-8")
    with pytest.raises(ResearchImportError):
        load_research_file(p)


def test_import_writes_research_and_review(project_root: Path) -> None:
    result = import_research(project_root, "EP0001_sample", FIXTURE, today=TODAY)
    rdir = project_root / "episodes" / "EP0001_sample" / "research"
    assert json.loads((rdir / "research.json").read_text(encoding="utf-8"))["canonical_title"].startswith("テスト")
    assert "PASS" in (rdir / "research_review.md").read_text(encoding="utf-8")
    assert result.gate == GATE_PASS


def test_import_refuses_overwrite_without_force(project_root: Path) -> None:
    import_research(project_root, "EP0001_sample", FIXTURE, today=TODAY)
    with pytest.raises(ResearchImportError, match="--force"):
        import_research(project_root, "EP0001_sample", FIXTURE, today=TODAY)
    import_research(project_root, "EP0001_sample", FIXTURE, today=TODAY, force=True)


def test_import_of_failing_research_writes_review_only(project_root: Path, tmp_path: Path, research: dict) -> None:
    bad = copy.deepcopy(research)
    for s in bad["sources"]:
        s["reliability"] = "D"
    src = tmp_path / "bad.json"
    src.write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
    result = import_research(project_root, "EP0001_sample", src, today=TODAY)
    rdir = project_root / "episodes" / "EP0001_sample" / "research"
    assert result.gate == GATE_FAIL
    assert not (rdir / "research.json").exists()
    assert "E_ONLY_D" in (rdir / "research_review.md").read_text(encoding="utf-8")


# --- CLI --------------------------------------------------------------------

def test_cli_import_and_check(project_root: Path, capsys) -> None:
    assert main(["import", "EP0001_sample", str(FIXTURE)], project_root=project_root) == 0
    assert main(["check", "EP0001_sample"], project_root=project_root) == 0
    out = capsys.readouterr().out
    assert "gate:" in out


def test_cli_check_missing_research_returns_2(project_root: Path, capsys) -> None:
    assert main(["check", "EP0001_sample"], project_root=project_root) == 2
    assert "research.json" in capsys.readouterr().err


def test_cli_fail_gate_returns_1(project_root: Path, tmp_path: Path, research: dict) -> None:
    research["sources"][1]["notes"] = None
    src = tmp_path / "bad.json"
    src.write_text(json.dumps(research, ensure_ascii=False), encoding="utf-8")
    assert main(["import", "EP0001_sample", str(src)], project_root=project_root) == 1


def test_cli_invalid_episode_id_returns_2(project_root: Path) -> None:
    assert main(["import", "../x", str(FIXTURE)], project_root=project_root) == 2


def test_template_file_is_valid_yaml_with_all_fields() -> None:
    import yaml

    from pipeline.schema_validation import load_schema

    tpl = yaml.safe_load((Path(__file__).parents[1] / "templates" / "research_template.yaml").read_text(encoding="utf-8"))
    assert set(tpl) == set(load_schema("research")["required"])
