import shutil
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    """config と schemas だけを複製した使い捨てのプロジェクトルート。"""
    for name in ("config", "schemas"):
        shutil.copytree(REPO_ROOT / name, tmp_path / name)
    return tmp_path
