from pathlib import Path
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]

def load_yaml(relative_path: str) -> dict:
    path = PROJECT_ROOT / relative_path
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)
