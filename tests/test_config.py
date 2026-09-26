from pathlib import Path

import pytest

from pipeline.config import ConfigError, load_yaml

CONFIG_FILES = [
    "config/channel.yaml",
    "config/pipeline.yaml",
    "config/visual_style.yaml",
    "config/layout.yaml",
    "config/character_motion.yaml",
]


@pytest.mark.parametrize("relative_path", CONFIG_FILES)
def test_repository_configs_load_as_mappings(relative_path: str) -> None:
    data = load_yaml(relative_path)
    assert isinstance(data, dict) and data


def test_load_yaml_reads_from_given_root(project_root: Path) -> None:
    data = load_yaml("config/channel.yaml", root=project_root)
    assert data["narrator"]["name"] == "大仏飴"


def test_missing_file_raises_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="missing.yaml"):
        load_yaml("missing.yaml", root=tmp_path)


def test_empty_file_raises_config_error(tmp_path: Path) -> None:
    (tmp_path / "empty.yaml").write_text("", encoding="utf-8")
    with pytest.raises(ConfigError, match="empty"):
        load_yaml("empty.yaml", root=tmp_path)


def test_non_mapping_raises_config_error(tmp_path: Path) -> None:
    (tmp_path / "list.yaml").write_text("- a\n- b\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="mapping"):
        load_yaml("list.yaml", root=tmp_path)


def test_invalid_yaml_raises_config_error(tmp_path: Path) -> None:
    (tmp_path / "bad.yaml").write_text("a: [1, 2\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="bad.yaml"):
        load_yaml("bad.yaml", root=tmp_path)
