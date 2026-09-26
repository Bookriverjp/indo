"""PHASE 1: research.json の取り込みと Research Gate の自動QA。

使い方:
  python -m pipeline.research import EP0001_nishi_daak path/to/research.yaml [--force]
  python -m pipeline.research check EP0001_nishi_daak
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

from pipeline.config import PROJECT_ROOT
from pipeline.schema_validation import SchemaValidationError, validate
from pipeline.workspace import create_episode_workspace, episode_paths

GATE_PASS = "PASS"   # 自動QAに問題なし。Ownerの確認へ進める
GATE_WARN = "WARN"   # 警告あり。Ownerが内容を見て判断する
GATE_FAIL = "FAIL"   # エラーあり。本編化しない



class ResearchImportError(Exception):
    pass


@dataclass
class Issue:
    code: str
    message: str


@dataclass
class QAResult:
    errors: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)

    @property
    def gate(self) -> str:
        if self.errors:
            return GATE_FAIL
        return GATE_WARN if self.warnings else GATE_PASS


def qa_research(data: dict, today: date | None = None) -> QAResult:
    """docs/RESEARCH_POLICY.md の採用原則を機械的に確認する。"""
    today = today or date.today()
    result = QAResult()
    err = lambda code, msg: result.errors.append(Issue(code, msg))  # noqa: E731
    warn = lambda code, msg: result.warnings.append(Issue(code, msg))  # noqa: E731

    try:
        validate(data, "research")
    except SchemaValidationError as e:
        for m in e.messages:
            err("E_SCHEMA", m)
        return result

    sources = data["sources"]
    by_id: dict[str, dict] = {}
    for s in sources:
        if s["id"] in by_id:
            err("E_DUP_SOURCE_ID", f"出典IDが重複しています: {s['id']}")
        by_id[s["id"]] = s

    refs = [("earliest_or_notable_source", data["earliest_or_notable_source"])]
    refs += [("modern_sources", i) for i in data["modern_sources"]]
    refs += [("plot_source_ids", i) for i in data["plot_source_ids"]]
    refs += [(f"variants[{n}].source_ids", i) for n, v in enumerate(data["variants"]) for i in v["source_ids"]]
    for where, sid in refs:
        if sid not in by_id:
            err("E_UNKNOWN_SOURCE_REF", f"{where} が存在しない出典IDを参照しています: {sid}")

    levels = {s["reliability"] for s in sources}
    if levels == {"D"}:
        err("E_ONLY_D", "信頼度Dの出典だけでは本編化できません（RESEARCH_POLICY: D単独で本編化しない）")
    elif not levels & {"A", "B"}:
        warn("W_NO_B_OR_BETTER", "信頼度B以上の出典がありません（目標: B以上を1つ以上）")

    for s in sources:
        if s["reliability"] == "C" and not s["notes"]:
            err("E_C_WITHOUT_NOTES", f"信頼度Cの出典 {s['id']} は notes に資料の性質を書いてください")
        if not s["url"] and not s["bibliography"]:
            warn("W_SOURCE_NO_LOCATOR", f"出典 {s['id']} に url も bibliography もありません")

    plot_levels = {by_id[i]["reliability"] for i in data["plot_source_ids"] if i in by_id}
    if plot_levels == {"D"}:
        warn("W_PLOT_ONLY_D", "あらすじの根拠が信頼度Dの出典だけです")

    try:
        checked = date.fromisoformat(data["checked_at"])
    except ValueError:
        err("E_CHECKED_AT", f"checked_at が日付として不正です: {data['checked_at']}")
    else:
        if checked > today:
            err("E_CHECKED_AT", f"checked_at が未来の日付です: {data['checked_at']}")

    if not data["variants"]:
        warn("W_NO_VARIANTS", "異説が記録されていません。本当に異説がないか確認してください")
    if not data["uncertain_points"]:
        warn("W_NO_UNCERTAIN_POINTS", "不確実点が記録されていません")
    if not data["japanese_coverage_notes"]:
        warn("W_NO_JAPANESE_COVERAGE", "日本語圏での既出状況が未記入です")
    if not data["local_script"]:
        warn("W_NO_LOCAL_SCRIPT", "現地の文字体系（local_script）が未記入です")
    return result


def _cell(value: object) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def render_review_md(data: dict, result: QAResult) -> str:
    """Research Gate 用の確認レポート（research_review.md）。"""
    title = data.get("canonical_title") if isinstance(data, dict) else None
    lines = [f"# Research Review: {_cell(title) or '(題名なし)'}", "", f"**gate: {result.gate}**", ""]

    lines += ["## 自動QA", ""]
    if not result.errors and not result.warnings:
        lines.append("問題は見つかりませんでした。")
    for label, issues in (("エラー", result.errors), ("警告", result.warnings)):
        if issues:
            lines.append(f"### {label}")
            lines += [f"- `{i.code}` {i.message}" for i in issues]
            lines.append("")
    lines.append("")

    if result.errors and any(i.code == "E_SCHEMA" for i in result.errors):
        return "\n".join(lines).rstrip() + "\n"

    lines += [
        "## 概要", "",
        f"- 地域: {_cell(data['region'])}",
        f"- 言語: {_cell(data['language'])}",
        f"- 現地名: {_cell(data['local_title'])}（{_cell(data['local_script'])} / {_cell(data['transliteration'])}）",
        f"- 背景: {_cell(data['community_or_context'])}",
        f"- 確認日: {_cell(data['checked_at'])}",
        "",
        "## 出典", "",
        "| ID | 信頼度 | 種別 | 題名 | 年 | 所在 | 備考 |",
        "|---|---|---|---|---|---|---|",
    ]
    for s in data["sources"]:
        where = s["url"] or s["bibliography"]
        lines.append(f"| {_cell(s['id'])} | {s['reliability']} | {s['source_type']} | {_cell(s['title'])} "
                     f"| {_cell(s['year'])} | {_cell(where)} | {_cell(s['notes'])} |")
    lines += [
        "",
        f"- 最古または代表的な出典: {data['earliest_or_notable_source']}",
        f"- 現代の出典: {', '.join(data['modern_sources']) or '(なし)'}",
        "",
        "## あらすじ", "", data["plot_summary"], "", f"根拠: {', '.join(data['plot_source_ids'])}", "",
        "## 異説", "",
    ]
    lines += [f"- {v['summary']}（{', '.join(v['source_ids'])}）" for v in data["variants"]] or ["(記録なし)"]
    lines += ["", "## 不確実点", ""]
    lines += [f"- {p}" for p in data["uncertain_points"]] or ["(記録なし)"]
    lines += ["", "## 日本語圏での既出状況", "", _cell(data["japanese_coverage_notes"]) or "(未記入)", ""]
    lines += [
        "## Owner確認", "",
        "- [ ] 出典を確認した（信頼度の付け方を含む）",
        "- [ ] 地域・言語・現地名が正しい",
        "- [ ] 異説を1つの「正解」に統合していない",
        "- [ ] 不確実点を台本で断定しない",
        "- [ ] 本編化を承認する",
        "",
    ]
    return "\n".join(lines)


def load_research_file(path: Path) -> dict:
    suffix = path.suffix.lower()
    if suffix not in (".json", ".yaml", ".yml"):
        raise ResearchImportError(f"research file must be .json, .yaml or .yml: {path}")
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f) if suffix == ".json" else yaml.safe_load(f)
    except FileNotFoundError:
        raise ResearchImportError(f"research file not found: {path}") from None
    except (json.JSONDecodeError, yaml.YAMLError) as e:
        raise ResearchImportError(f"cannot parse {path}: {e}") from None
    if not isinstance(data, dict):
        raise ResearchImportError(f"research file must contain a mapping: {path}")
    return data


def _write_text(path: Path, text: str) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def import_research(project_root: Path, episode_id: str, src: Path,
                    force: bool = False, today: date | None = None) -> QAResult:
    """手作業で書いた research を検証し、episodes/<id>/research/ へ保存する。

    FAIL の場合は research.json を書かず、research_review.md だけ出す。
    """
    paths = episode_paths(project_root, episode_id)
    data = load_research_file(src)
    target = paths["research"]
    if target.exists() and not force:
        raise ResearchImportError(f"{target} already exists (use --force to overwrite)")

    result = qa_research(data, today=today)
    create_episode_workspace(project_root, episode_id)
    if result.gate != GATE_FAIL:
        _write_text(target, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    _write_text(paths["research_review"], render_review_md(data, result))
    return result


def check_research(project_root: Path, episode_id: str, today: date | None = None) -> QAResult:
    paths = episode_paths(project_root, episode_id)
    data = load_research_file(paths["research"])
    result = qa_research(data, today=today)
    _write_text(paths["research_review"], render_review_md(data, result))
    return result


def _print_result(result: QAResult, review: Path) -> None:
    print(f"gate: {result.gate}")
    for i in result.errors:
        print(f"  ERROR {i.code}: {i.message}")
    for i in result.warnings:
        print(f"  WARN  {i.code}: {i.message}")
    print(f"review: {review}")


def main(argv: list[str] | None = None, project_root: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description="Research import and Research Gate QA")
    sub = parser.add_subparsers(dest="command", required=True)
    p_imp = sub.add_parser("import", help="validate a hand-written research file and store it")
    p_imp.add_argument("episode_id")
    p_imp.add_argument("file", type=Path)
    p_imp.add_argument("--force", action="store_true", help="overwrite existing research.json")
    p_chk = sub.add_parser("check", help="re-run QA on episodes/<id>/research/research.json")
    p_chk.add_argument("episode_id")
    args = parser.parse_args(argv)
    root = project_root or PROJECT_ROOT

    try:
        if args.command == "import":
            result = import_research(root, args.episode_id, args.file, force=args.force)
        else:
            result = check_research(root, args.episode_id)
    except (ValueError, ResearchImportError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    _print_result(result, episode_paths(root, args.episode_id)["research_review"])
    return 1 if result.gate == GATE_FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
