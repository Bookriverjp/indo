from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ConfigError(Exception):
    """設定ファイルが読めない・中身が不正なときのエラー。"""


def load_yaml(relative_path: str, root: Path | None = None) -> dict:
    path = (root or PROJECT_ROOT) / relative_path
    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except FileNotFoundError:
        raise ConfigError(f"config file not found: {relative_path}") from None
    except yaml.YAMLError as e:
        raise ConfigError(f"invalid YAML in {relative_path}: {e}") from None
    if data is None:
        raise ConfigError(f"config file is empty: {relative_path}")
    if not isinstance(data, dict):
        raise ConfigError(f"config file must be a mapping: {relative_path}")
    return data
