import json
from pathlib import Path

import pytest

from pipeline.workspace import SUBDIRS, create_episode_workspace, validate_episode_id


@pytest.mark.parametrize("episode_id", ["EP0001_nishi_daak", "EP0042_a", "EP9999_x1_y2"])
def test_valid_episode_ids(episode_id: str) -> None:
    validate_episode_id(episode_id)


@pytest.mark.parametrize(
    "episode_id",
    ["", "EP1_x", "EP0001", "EP0001_", "ep0001_x", "EP0001_Nishi", "EP0001_nishi-daak",
     "../EP0001_x", "EP0001_x/../../y", "EP0001_x\\y", "EP0001_にし"],
)
def test_invalid_episode_ids(episode_id: str) -> None:
    with pytest.raises(ValueError):
        validate_episode_id(episode_id)


def test_creates_all_subdirs(tmp_path: Path) -> None:
    root = create_episode_workspace(tmp_path, "EP0001_nishi_daak")
    assert root == tmp_path / "episodes" / "EP0001_nishi_daak"
    for name in SUBDIRS:
        assert (root / name).is_dir()


def test_writes_episode_json(tmp_path: Path) -> None:
    root = create_episode_workspace(tmp_path, "EP0001_nishi_daak")
    meta = json.loads((root / "episode.json").read_text(encoding="utf-8"))
    assert meta["episode_id"] == "EP0001_nishi_daak"
    assert meta["schema_version"] == 1
    assert meta["created_at"]


def test_rerun_keeps_existing_episode_json(tmp_path: Path) -> None:
    root = create_episode_workspace(tmp_path, "EP0001_nishi_daak")
    first = (root / "episode.json").read_text(encoding="utf-8")
    create_episode_workspace(tmp_path, "EP0001_nishi_daak")
    assert (root / "episode.json").read_text(encoding="utf-8") == first


def test_invalid_id_creates_nothing(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        create_episode_workspace(tmp_path, "../escape")
    assert not (tmp_path / "episodes").exists()
    assert not (tmp_path.parent / "escape").exists()
