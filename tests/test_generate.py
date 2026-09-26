import json
import shutil
from pathlib import Path

import pytest

from pipeline.generate import GenerateError, main, run_stage
from pipeline.llm.base import LLMResult, LLMUsage
from pipeline.prompts import PromptError, load_prompt, render

REPO = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"


class FakeProvider:
    name = "fake"
    model = "fake-model"

    def __init__(self, *outputs):
        self.outputs = list(outputs)
        self.calls = []

    def generate_json(self, *, system, user, schema, max_tokens=None):
        self.calls.append({"system": system, "user": user, "schema": schema})
        return LLMResult(data=self.outputs.pop(0), model="claude-opus-5", usage=LLMUsage(100, 50),
                         request_id="req_x", stop_reason="end_turn")


@pytest.fixture
def root(project_root: Path) -> Path:
    shutil.copytree(REPO / "prompts", project_root / "prompts")
    rdir = project_root / "episodes" / "EP0001_sample" / "research"
    rdir.mkdir(parents=True)
    shutil.copy(FIXTURES / "research_valid.json", rdir / "research.json")
    return project_root


def script_output(**over):
    data = json.loads((FIXTURES / "script_valid.json").read_text(encoding="utf-8"))
    data.update(over)
    return data


def storyboard_output():
    return json.loads((FIXTURES / "storyboard_valid.json").read_text(encoding="utf-8"))


# --- prompts -----------------------------------------------------------------

def test_render_replaces_placeholders() -> None:
    assert render("a {{x}} b {{ y }}", x="1", y="2") == "a 1 b 2"


def test_render_missing_variable_raises() -> None:
    with pytest.raises(PromptError, match="y"):
        render("{{x}} {{y}}", x="1")


def test_load_prompt_unknown_raises(tmp_path: Path) -> None:
    with pytest.raises(PromptError):
        load_prompt("nope", root=tmp_path)


def test_load_prompt_rejects_path_escape(tmp_path: Path) -> None:
    with pytest.raises(PromptError):
        load_prompt("../secret", root=tmp_path)


# --- script stage -------------------------------------------------------------

def test_script_stage_writes_json_markdown_and_usage(root: Path) -> None:
    provider = FakeProvider(script_output())
    out = run_stage(root, "EP0001_sample", "script", provider, pricing={})
    ep = root / "episodes" / "EP0001_sample"
    assert out == ep / "script" / "script_main.json"
    assert json.loads(out.read_text(encoding="utf-8"))["episode_title"]
    md = (ep / "script" / "script_main.md").read_text(encoding="utf-8")
    assert "【伝承】" in md and "【大仏飴】" in md
    usage = [json.loads(x) for x in (ep / "logs" / "llm_usage.jsonl").read_text(encoding="utf-8").splitlines()]
    assert usage[0]["stage"] == "script" and usage[0]["input_tokens"] == 100


def test_script_prompt_contains_research_and_policy(root: Path) -> None:
    provider = FakeProvider(script_output())
    run_stage(root, "EP0001_sample", "script", provider, pricing={})
    call = provider.calls[0]
    assert "テスト用の架空の題材" in call["user"]
    assert "大仏飴" in call["system"]
    assert call["schema"]["title"] == "Script"


def test_script_requires_research(root: Path) -> None:
    (root / "episodes" / "EP0001_sample" / "research" / "research.json").unlink()
    with pytest.raises(GenerateError, match="research.json"):
        run_stage(root, "EP0001_sample", "script", FakeProvider(), pricing={})


def test_refuses_overwrite_without_force(root: Path) -> None:
    run_stage(root, "EP0001_sample", "script", FakeProvider(script_output()), pricing={})
    with pytest.raises(GenerateError, match="--force"):
        run_stage(root, "EP0001_sample", "script", FakeProvider(script_output()), pricing={})
    run_stage(root, "EP0001_sample", "script", FakeProvider(script_output()), pricing={}, force=True)


def test_legend_block_with_unknown_source_is_retried_then_accepted(root: Path) -> None:
    bad = script_output()
    bad["sections"][0]["blocks"][0]["kind"] = "legend"
    bad["sections"][0]["blocks"][0]["source_ids"] = ["s99"]
    provider = FakeProvider(bad, script_output())
    run_stage(root, "EP0001_sample", "script", provider, pricing={})
    assert len(provider.calls) == 2
    assert "s99" in provider.calls[1]["user"]


def test_legend_block_without_sources_fails_after_retries(root: Path) -> None:
    bad = script_output()
    bad["sections"][0]["blocks"][0]["kind"] = "legend"
    bad["sections"][0]["blocks"][0]["source_ids"] = []
    with pytest.raises(GenerateError, match="source_ids"):
        run_stage(root, "EP0001_sample", "script", FakeProvider(bad, bad), pricing={}, validation_retries=1)
    assert not (root / "episodes" / "EP0001_sample" / "script" / "script_main.json").exists()


def test_schema_invalid_output_is_rejected(root: Path) -> None:
    with pytest.raises(GenerateError):
        run_stage(root, "EP0001_sample", "script", FakeProvider({"x": 1}, {"x": 1}), pricing={}, validation_retries=1)


# --- storyboard stage -------------------------------------------------------

def test_storyboard_stage_uses_script(root: Path) -> None:
    run_stage(root, "EP0001_sample", "script", FakeProvider(script_output()), pricing={})
    provider = FakeProvider(storyboard_output())
    out = run_stage(root, "EP0001_sample", "storyboard", provider, pricing={})
    assert out.name == "storyboard.json"
    assert "b01" in provider.calls[0]["user"]


def test_storyboard_unknown_block_id_is_rejected(root: Path) -> None:
    run_stage(root, "EP0001_sample", "script", FakeProvider(script_output()), pricing={})
    bad = storyboard_output()
    bad["scenes"][0]["block_ids"] = ["zz"]
    with pytest.raises(GenerateError, match="zz"):
        run_stage(root, "EP0001_sample", "storyboard", FakeProvider(bad, bad), pricing={}, validation_retries=1)


def test_storyboard_requires_script(root: Path) -> None:
    with pytest.raises(GenerateError, match="script_main.json"):
        run_stage(root, "EP0001_sample", "storyboard", FakeProvider(), pricing={})


# --- CLI -------------------------------------------------------------------

def test_cli_runs_with_injected_provider(root: Path, capsys) -> None:
    code = main(["script", "EP0001_sample"], project_root=root, provider=FakeProvider(script_output()))
    assert code == 0
    assert "script_main.json" in capsys.readouterr().out


def test_cli_error_returns_2(root: Path, capsys) -> None:
    assert main(["storyboard", "EP0001_sample"], project_root=root, provider=FakeProvider()) == 2
    assert "script_main.json" in capsys.readouterr().err


def test_cli_invalid_episode_returns_2(root: Path) -> None:
    assert main(["script", "../x"], project_root=root, provider=FakeProvider()) == 2


def test_expression_enum_matches_character_motion() -> None:
    import yaml

    from pipeline.schema_validation import load_schema

    motions = yaml.safe_load((REPO / "config" / "character_motion.yaml").read_text(encoding="utf-8"))["expressions"]
    enum = load_schema("script")["$defs"]["expression"]["enum"]
    assert set(enum) == {"neutral", *motions}


# --- manual provider (VS Code + Claude Code, API不要) ---------------------

def test_prepare_request_writes_prompt_input_and_schema(root: Path) -> None:
    from pipeline.generate import prepare_request

    req, resp = prepare_request(root, "EP0001_sample", "script")
    text = req.read_text(encoding="utf-8")
    ep = root / "episodes" / "EP0001_sample"
    assert req == ep / "script" / "script_request.md"
    assert resp == ep / "script" / "script_response.json"
    assert "大仏飴" in text and "テスト用の架空の題材" in text
    assert '"title": "Script"' in text
    assert "script/script_response.json" in text


def test_import_response_validates_and_saves(root: Path, tmp_path: Path) -> None:
    from pipeline.generate import import_response

    src = tmp_path / "resp.json"
    src.write_text(json.dumps(script_output(), ensure_ascii=False), encoding="utf-8")
    out = import_response(root, "EP0001_sample", "script", src)
    assert out.name == "script_main.json"
    assert (root / "episodes" / "EP0001_sample" / "script" / "script_main.md").exists()


def test_import_response_rejects_invalid(root: Path, tmp_path: Path) -> None:
    from pipeline.generate import import_response

    bad = script_output()
    bad["sections"][0]["blocks"][0]["kind"] = "legend"
    bad["sections"][0]["blocks"][0]["source_ids"] = []
    src = tmp_path / "resp.json"
    src.write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(GenerateError, match="source_ids"):
        import_response(root, "EP0001_sample", "script", src)
    assert not (root / "episodes" / "EP0001_sample" / "script" / "script_main.json").exists()


def test_import_response_broken_json(root: Path, tmp_path: Path) -> None:
    from pipeline.generate import import_response

    src = tmp_path / "resp.json"
    src.write_text("{", encoding="utf-8")
    with pytest.raises(GenerateError):
        import_response(root, "EP0001_sample", "script", src)


def test_cli_manual_mode_writes_request_then_imports(root: Path, capsys) -> None:
    assert main(["script", "EP0001_sample", "--provider", "manual"], project_root=root) == 0
    out = capsys.readouterr().out
    assert "script_request.md" in out and "script_response.json" in out
    resp = root / "episodes" / "EP0001_sample" / "script" / "script_response.json"
    resp.write_text(json.dumps(script_output(), ensure_ascii=False), encoding="utf-8")
    assert main(["script", "EP0001_sample", "--response", str(resp)], project_root=root) == 0
    assert (root / "episodes" / "EP0001_sample" / "script" / "script_main.json").exists()


def test_cli_default_provider_from_config_is_manual(root: Path, capsys) -> None:
    assert main(["script", "EP0001_sample"], project_root=root) == 0
    assert "script_request.md" in capsys.readouterr().out


def test_cli_import_failure_returns_1(root: Path, tmp_path: Path, capsys) -> None:
    src = tmp_path / "resp.json"
    src.write_text(json.dumps({"x": 1}), encoding="utf-8")
    assert main(["script", "EP0001_sample", "--response", str(src)], project_root=root) == 1
    assert "error" in capsys.readouterr().err
