import json
from pathlib import Path

from jsonschema import Draft202012Validator

from pipeline.config import PROJECT_ROOT

SCHEMA_NAMES = ("research", "script", "shorts", "storyboard", "asset_manifest", "timeline", "youtube_metadata")


class SchemaValidationError(Exception):
    def __init__(self, schema_name: str, messages: list[str]):
        self.schema_name = schema_name
        self.messages = messages
        super().__init__(f"{schema_name}: " + "; ".join(messages))


def load_schema(name: str, root: Path | None = None) -> dict:
    if name not in SCHEMA_NAMES:
        raise ValueError(f"unknown schema: {name!r} (expected one of {', '.join(SCHEMA_NAMES)})")
    path = (root or PROJECT_ROOT) / "schemas" / f"{name}.schema.json"
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def validate(data: object, name: str, root: Path | None = None) -> None:
    """schemas/<name>.schema.json で検証し、違反をすべてまとめて SchemaValidationError で返す。"""
    validator = Draft202012Validator(load_schema(name, root))
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
    if errors:
        messages = [f"/{'/'.join(str(p) for p in e.absolute_path)}: {e.message}" for e in errors]
        raise SchemaValidationError(name, messages)
