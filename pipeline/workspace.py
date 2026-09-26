import json
import re
from datetime import datetime, timezone
from pathlib import Path

SUBDIRS = [
    "research", "script", "storyboard", "assets",
    "audio", "render", "output", "logs"
]

# 1話ごとの成果物はすべて episodes/<episode_id>/ の中に置く（docs/DATA_CONTRACT.md）。
# 各stageはここからパスを受け取り、エピソードフォルダの外へ書かない。
ARTIFACTS = {
    "research": "research/research.json",
    "research_review": "research/research_review.md",
    "script_request": "script/script_request.md",
    "script_response": "script/script_response.json",
    "script_json": "script/script_main.json",
    "script_main": "script/script_main.md",
    "script_review": "script/script_review.md",
    "shorts_request": "script/script_shorts_request.md",
    "shorts_response": "script/script_shorts_response.json",
    "shorts_json": "script/script_shorts.json",
    "script_shorts": "script/script_shorts.md",
    "shorts_review": "script/script_shorts_review.md",
    "subtitles": "script/subtitles.srt",
    "storyboard_request": "storyboard/storyboard_request.md",
    "storyboard_response": "storyboard/storyboard_response.json",
    "storyboard": "storyboard/storyboard.json",
    "asset_manifest": "storyboard/asset_manifest.json",
    "asset_manifest_md": "storyboard/asset_manifest.md",
    "assets_generated": "assets/generated",
    "assets_inbox": "assets/inbox",
    "image_requests": "assets/image_requests.md",
    "image_status": "assets/image_status.md",
    "narration": "audio/generated",
    "narration_index": "audio/narration.json",
    "pronunciation": "script/pronunciation.yaml",
    "timeline": "render/timeline.json",
    "episode_video": "output/episode.mp4",
    "shorts_video": "output/shorts.mp4",
    "thumbnail": "output/thumbnail.png",
    "youtube_metadata": "output/youtube_metadata.json",
    "qa_report": "output/qa_report.md",
    "log": "logs/pipeline.log",
    "llm_usage": "logs/llm_usage.jsonl",
    "image_usage": "logs/image_usage.jsonl",
}

# 例: EP0001_nishi_daak（docs/DATA_CONTRACT.md）
EPISODE_ID_RE = re.compile(r"EP\d{4}_[a-z0-9_]*[a-z0-9]")
EPISODE_META_VERSION = 1


def validate_episode_id(episode_id: str) -> None:
    if not EPISODE_ID_RE.fullmatch(episode_id):
        raise ValueError(
            f"invalid episode_id: {episode_id!r} "
            "(expected EP + 4 digits + _ + lowercase letters/digits/_, e.g. EP0001_nishi_daak)"
        )


def create_episode_workspace(project_root: Path, episode_id: str) -> Path:
    validate_episode_id(episode_id)
    root = project_root / "episodes" / episode_id
    for name in SUBDIRS:
        (root / name).mkdir(parents=True, exist_ok=True)

    meta_path = root / "episode.json"
    if not meta_path.exists():
        meta = {
            "schema_version": EPISODE_META_VERSION,
            "episode_id": episode_id,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        with meta_path.open("w", encoding="utf-8", newline="\n") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
            f.write("\n")
    return root


def episode_paths(project_root: Path, episode_id: str) -> dict[str, Path]:
    """エピソードの各成果物の置き場所。フォルダは作らない。"""
    validate_episode_id(episode_id)
    root = project_root / "episodes" / episode_id
    return {name: root / rel for name, rel in ARTIFACTS.items()}
