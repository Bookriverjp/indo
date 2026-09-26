import json
from pathlib import Path

import pytest

from pipeline.schema_validation import SCHEMA_NAMES, SchemaValidationError, load_schema, validate

VALID = {
    "research": json.loads((Path(__file__).parent / "fixtures" / "research_valid.json").read_text(encoding="utf-8")),
    "script": json.loads((Path(__file__).parent / "fixtures" / "script_valid.json").read_text(encoding="utf-8")),
    "shorts": json.loads((Path(__file__).parent / "fixtures" / "shorts_valid.json").read_text(encoding="utf-8")),
    "youtube_metadata": json.loads((Path(__file__).parent / "fixtures" / "youtube_metadata_valid.json").read_text(encoding="utf-8")),
    "storyboard": json.loads((Path(__file__).parent / "fixtures" / "storyboard_valid.json").read_text(encoding="utf-8")),
    "asset_manifest": {
        "schema_version": 1,
        "episode_id": "EP0001_x",
        "assets": [{"asset_id": "bg_s01_v01", "kind": "background", "scope": "episode", "label": "…",
                    "prompt": "…", "transparent": False, "reference_image": None,
                    "file": "assets/generated/bg_s01_v01.png", "scenes": ["s01"]}],
        "scenes": [{"scene_id": "s01", "layout": "fullbleed", "motion": None, "estimated_seconds": 5,
                    "layers": [{"asset_id": "bg_s01_v01", "layer": "background", "slot": "story_art",
                                "box": [0, 0, 1, 1], "z": 10}]}],
    },
    "timeline": {
        "schema_version": 1, "episode_id": "EP0001_x", "width": 1920, "height": 1080, "fps": 30,
        "total_seconds": 5.0, "region_label": "West Bengal ・ Bengali",
        "scenes": [{"scene_id": "s01", "layout": "fullbleed", "start": 0, "duration": 5.0,
                    "transition_in": {"type": "fade_from_black", "duration": 0.6},
                    "motion": {"name": "static", "camera_from": [1, 0, 0], "camera_to": [1, 0, 0],
                               "parallax": False, "fx_animation": None},
                    "layers": [], "card": None}],
        "audio": [], "subtitles": [], "narrator": [],
    },
}


def test_all_schema_files_are_known() -> None:
    assert set(SCHEMA_NAMES) == set(VALID)


@pytest.mark.parametrize("name", sorted(VALID))
def test_schema_loads(name: str) -> None:
    assert load_schema(name)["type"] == "object"


@pytest.mark.parametrize("name", sorted(VALID))
def test_valid_sample_passes(name: str) -> None:
    validate(VALID[name], name)


def test_missing_required_field_fails_with_path() -> None:
    data = dict(VALID["research"])
    del data["sources"]
    with pytest.raises(SchemaValidationError) as exc:
        validate(data, "research")
    assert any("sources" in m for m in exc.value.messages)


def test_bad_reliability_fails() -> None:
    data = dict(VALID["research"])
    data["sources"] = [dict(data["sources"][0], reliability="E")]
    with pytest.raises(SchemaValidationError) as exc:
        validate(data, "research")
    assert any("sources/0/reliability" in m for m in exc.value.messages)


def test_all_errors_are_reported() -> None:
    with pytest.raises(SchemaValidationError) as exc:
        validate({}, "timeline")
    assert len(exc.value.messages) == len(load_schema("timeline")["required"])


def test_unknown_schema_name() -> None:
    with pytest.raises(ValueError):
        load_schema("../channel")
