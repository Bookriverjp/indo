from pathlib import Path

SUBDIRS = [
    "research", "script", "storyboard", "assets",
    "audio", "render", "output", "logs"
]

def create_episode_workspace(project_root: Path, episode_id: str) -> Path:
    root = project_root / "episodes" / episode_id
    for name in SUBDIRS:
        (root / name).mkdir(parents=True, exist_ok=True)
    return root
