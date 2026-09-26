"""PHASE 2: research → script、script → storyboard を LLM で生成する。

provider は config/llm.yaml の llm.provider で選ぶ。
  manual: APIを使わない。依頼ファイル（プロンプト・入力・schema）を書き出し、
          VS Code の Claude Code などで作った JSON を --response で取り込む。
  claude: Anthropic API を直接呼ぶ（.env に ANTHROPIC_API_KEY）。
どちらの経路でも、保存前に同じ検証（schema・出典・block の対応）を通す。

使い方:
  python -m pipeline.generate script EP0001_nishi_daak                 # manual: 依頼ファイルを書き出す
  python -m pipeline.generate script EP0001_nishi_daak --response FILE # 作った JSON を検証して取り込む
  python -m pipeline.generate storyboard EP0001_nishi_daak --provider claude
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from pipeline.config import PROJECT_ROOT, ConfigError, load_yaml
from pipeline.llm.base import LLMError, LLMProvider
from pipeline.llm.usage_log import append_usage, estimate_cost
from pipeline.prompts import PromptError, load_prompt
from pipeline.schema_validation import SchemaValidationError, load_schema, validate
from pipeline.workspace import create_episode_workspace, episode_paths


class GenerateError(Exception):
    """入力がない・上書きになるなど、生成を始められない。"""


class OutputRejectedError(GenerateError):
    """生成された出力が検証に通らなかった。"""


@dataclass(frozen=True)
class StageSpec:
    prompt: str
    schema: str
    input_key: str
    output_key: str


STAGES = {
    "script": StageSpec(prompt="02_script", schema="script", input_key="research", output_key="script_json"),
    "storyboard": StageSpec(prompt="03_storyboard", schema="storyboard", input_key="script_json", output_key="storyboard"),
}

# 1本に使える回数の上限（docs/CHARACTER_MOTION.md）
EXPRESSION_LIMITS = {"sleep": 1, "dust_bath": 1, "popcorn": 1, "grooming": 2}


def _read_json(path: Path) -> dict:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise GenerateError(f"input not found: {path}") from None
    except json.JSONDecodeError as e:
        raise GenerateError(f"cannot parse {path}: {e}") from None


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        f.write(text)


# --- prompt -----------------------------------------------------------------

def _build_prompt(project_root: Path, stage: str, input_data: dict) -> tuple[str, str]:
    spec = STAGES[stage]
    system = load_prompt("00_system", project_root).strip()
    instructions = load_prompt(spec.prompt, project_root).strip()
    user = (f"{instructions}\n\n<input name=\"{spec.input_key}\">\n"
            f"{json.dumps(input_data, ensure_ascii=False, indent=2)}\n</input>")
    return system, user


# --- validation -------------------------------------------------------------

def _check_script(data: dict, context: dict) -> list[str]:
    known = {s["id"] for s in context["research"]["sources"]}
    errors = []
    blocks = [b for sec in data["sections"] for b in sec["blocks"]]
    for bid, n in Counter(b["block_id"] for b in blocks).items():
        if n > 1:
            errors.append(f"block_id が重複しています: {bid}")
    for b in blocks:
        if b["kind"] == "legend" and not b["source_ids"]:
            errors.append(f"{b['block_id']}: legend ブロックには source_ids（根拠の出典）が必要です")
        for sid in b["source_ids"]:
            if sid not in known:
                errors.append(f"{b['block_id']}: research にない出典 id を参照しています: {sid}")
    used = Counter(b["expression"] for b in blocks)
    for expr, limit in EXPRESSION_LIMITS.items():
        if used[expr] > limit:
            errors.append(f"expression {expr} は1本に{limit}回までです（{used[expr]}回）")
    return errors


def _check_storyboard(data: dict, context: dict) -> list[str]:
    script_ids = [b["block_id"] for sec in context["script_json"]["sections"] for b in sec["blocks"]]
    used = Counter(i for s in data["scenes"] for i in s["block_ids"])
    errors = [f"script にない block_id です: {i}" for i in used if i not in script_ids]
    errors += [f"block_id {i} が {n} 回使われています（1回だけ）" for i, n in used.items() if n > 1 and i in script_ids]
    errors += [f"block_id {i} がどの scene にも入っていません" for i in script_ids if i not in used]
    return errors


_EXTRA_CHECKS = {"script": _check_script, "storyboard": _check_storyboard}


def validate_output(stage: str, data: object, context: dict, project_root: Path) -> list[str]:
    try:
        validate(data, STAGES[stage].schema, project_root)
    except SchemaValidationError as e:
        return [f"schema {m}" for m in e.messages]
    return _EXTRA_CHECKS[stage](data, context)


# --- output -----------------------------------------------------------------

_KIND_LABEL = {"legend": "【伝承】", "staging": "【演出】", "comment": "【大仏飴】"}
_SECTION_LABEL = {"hook": "フック", "intro": "導入", "background": "地域・言語・背景", "story": "物語",
                  "commentary": "民俗解説・異説", "comparison": "日本との比較", "ending": "締め"}


def render_script_md(script: dict) -> str:
    lines = [f"# {script['episode_title']}", ""]
    for sec in script["sections"]:
        lines += [f"## {_SECTION_LABEL[sec['section']]}", ""]
        for b in sec["blocks"]:
            src = f"（出典: {', '.join(b['source_ids'])}）" if b["source_ids"] else ""
            lines.append(f"- `{b['block_id']}` {_KIND_LABEL[b['kind']]} {b['text']}{src}  _表情: {b['expression']}_")
        lines.append("")
    return "\n".join(lines)


def _save_output(paths: dict, stage: str, data: dict) -> Path:
    out = paths[STAGES[stage].output_key]
    _write_text(out, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    if stage == "script":
        _write_text(paths["script_main"], render_script_md(data))
    return out


def _load_context(project_root: Path, episode_id: str, stage: str, force: bool) -> tuple[dict, dict]:
    if stage not in STAGES:
        raise GenerateError(f"unknown stage: {stage}")
    paths = episode_paths(project_root, episode_id)
    spec = STAGES[stage]
    context = {"research": _read_json(paths["research"])}
    if spec.input_key != "research":
        context[spec.input_key] = _read_json(paths[spec.input_key])
    out = paths[spec.output_key]
    if out.exists() and not force:
        raise GenerateError(f"{out} already exists (use --force to overwrite)")
    return paths, context


# --- entry points -----------------------------------------------------------

def run_stage(project_root: Path, episode_id: str, stage: str, provider: LLMProvider, *,
              pricing: dict, force: bool = False, validation_retries: int = 1) -> Path:
    """provider を呼んで生成し、検証に通ったものだけ保存する。"""
    paths, context = _load_context(project_root, episode_id, stage, force)
    create_episode_workspace(project_root, episode_id)
    system, user = _build_prompt(project_root, stage, context[STAGES[stage].input_key])
    schema = load_schema(STAGES[stage].schema, project_root)

    prompt = user
    for attempt in range(validation_retries + 1):
        result = provider.generate_json(system=system, user=prompt, schema=schema)
        append_usage(paths["llm_usage"], {
            "stage": stage, "attempt": attempt + 1, "provider": provider.name, "model": result.model,
            "request_id": result.request_id, "input_tokens": result.usage.input_tokens,
            "output_tokens": result.usage.output_tokens,
            "cache_creation_input_tokens": result.usage.cache_creation_input_tokens,
            "cache_read_input_tokens": result.usage.cache_read_input_tokens,
            "cost_usd": estimate_cost(result.model, result.usage, pricing),
        })
        errors = validate_output(stage, result.data, context, project_root)
        if not errors:
            return _save_output(paths, stage, result.data)
        prompt = (f"{user}\n\n<previous_attempt_errors>\n" + "\n".join(errors) +
                  "\n</previous_attempt_errors>\n前回の出力には上の問題がありました。直した JSON を出力してください。")
    raise OutputRejectedError(f"{stage} output rejected: " + "; ".join(errors))


def prepare_request(project_root: Path, episode_id: str, stage: str, force: bool = False) -> tuple[Path, Path]:
    """manual 用: プロンプト・入力・schema をまとめた依頼ファイルを書き出す。"""
    paths, context = _load_context(project_root, episode_id, stage, force)
    create_episode_workspace(project_root, episode_id)
    system, user = _build_prompt(project_root, stage, context[STAGES[stage].input_key])
    schema = load_schema(STAGES[stage].schema, project_root)
    req, resp = paths[f"{stage}_request"], paths[f"{stage}_response"]
    resp_rel = resp.relative_to(project_root).as_posix()
    text = "\n".join([
        f"# {stage} 生成依頼（{episode_id}）", "",
        "この依頼を読んだAI（VS Code の Claude Code など）への指示:",
        f"- 下の「System」と「指示と入力」に従い、「出力 schema」に合う JSON オブジェクトを1つだけ作る。",
        f"- 作った JSON を `{resp_rel}` に UTF-8 で保存する（JSON 以外の文字を入れない）。",
        f"- 保存したら `python -m pipeline.generate {stage} {episode_id} --response {resp_rel}` を実行し、",
        "  エラーが出たら内容を直して保存し直し、通るまで繰り返す。", "",
        "## System", "", system, "",
        "## 指示と入力", "", user, "",
        "## 出力 schema", "", "```json", json.dumps(schema, ensure_ascii=False, indent=2), "```", "",
    ])
    _write_text(req, text)
    return req, resp


def import_response(project_root: Path, episode_id: str, stage: str, src: Path, force: bool = False) -> Path:
    """manual 用: 外で作った JSON を検証して保存する。"""
    paths, context = _load_context(project_root, episode_id, stage, force)
    data = _read_json(src)
    errors = validate_output(stage, data, context, project_root)
    if errors:
        raise OutputRejectedError(f"{stage} response rejected: " + "; ".join(errors))
    create_episode_workspace(project_root, episode_id)
    return _save_output(paths, stage, data)


def main(argv: list[str] | None = None, project_root: Path | None = None,
         provider: LLMProvider | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate script / storyboard with an LLM")
    parser.add_argument("stage", choices=sorted(STAGES))
    parser.add_argument("episode_id")
    parser.add_argument("--provider", choices=["manual", "claude"], help="override llm.provider")
    parser.add_argument("--response", type=Path, help="import a JSON made outside (manual mode)")
    parser.add_argument("--force", action="store_true", help="overwrite existing output")
    args = parser.parse_args(argv)
    root = project_root or PROJECT_ROOT

    try:
        cfg = load_yaml("config/llm.yaml", root)
        llm_cfg = cfg["llm"]
        if args.response:
            out = import_response(root, args.episode_id, args.stage, args.response, force=args.force)
        elif provider is None and (args.provider or llm_cfg["provider"]) == "manual":
            req, resp = prepare_request(root, args.episode_id, args.stage, force=args.force)
            print(f"request: {req}")
            print(f"次に: {req.name} を Claude Code などに渡して JSON を作り、{resp} に保存してから")
            print(f"      python -m pipeline.generate {args.stage} {args.episode_id} --response {resp}")
            return 0
        else:
            if provider is None:
                from dotenv import load_dotenv

                from pipeline.llm.factory import create_provider

                load_dotenv(root / ".env")
                provider = create_provider(dict(llm_cfg, provider=args.provider or llm_cfg["provider"]))
            out = run_stage(root, args.episode_id, args.stage, provider, pricing=cfg.get("pricing", {}),
                            force=args.force, validation_retries=llm_cfg.get("validation_retries", 1))
    except (OutputRejectedError, LLMError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except (GenerateError, ValueError, ConfigError, PromptError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    print(f"saved: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
