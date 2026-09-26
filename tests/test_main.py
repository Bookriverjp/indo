import json
from pathlib import Path

from pipeline.main import main


def test_dry_run_creates_episode_without_api(project_root: Path, capsys) -> None:
    code = main(["EP0001_nishi_daak", "--dry-run"], project_root=project_root)
    assert code == 0
    root = project_root / "episodes" / "EP0001_nishi_daak"
    assert json.loads((root / "episode.json").read_text(encoding="utf-8"))["episode_id"] == "EP0001_nishi_daak"
    log = (root / "logs" / "pipeline.log").read_text(encoding="utf-8")
    assert "DRY RUN" in log
    assert "DRY RUN" in capsys.readouterr().out


def test_invalid_episode_id_returns_2(project_root: Path, capsys) -> None:
    code = main(["../escape", "--dry-run"], project_root=project_root)
    assert code == 2
    assert "episode_id" in capsys.readouterr().err
    assert not (project_root / "episodes").exists()


def test_missing_config_returns_2(tmp_path: Path, capsys) -> None:
    code = main(["EP0001_nishi_daak", "--dry-run"], project_root=tmp_path)
    assert code == 2
    assert "channel.yaml" in capsys.readouterr().err


def test_config_dry_run_true_is_respected_without_flag(project_root: Path) -> None:
    assert main(["EP0002_sample"], project_root=project_root) == 0


def test_second_run_appends_to_same_log(project_root: Path) -> None:
    main(["EP0001_nishi_daak", "--dry-run"], project_root=project_root)
    main(["EP0001_nishi_daak", "--dry-run"], project_root=project_root)
    log = (project_root / "episodes" / "EP0001_nishi_daak" / "logs" / "pipeline.log").read_text(encoding="utf-8")
    assert log.count("DRY RUN") == 2


def test_log_handlers_are_closed_after_run(project_root: Path) -> None:
    import logging

    from pipeline.logging_setup import LOGGER_NAME

    main(["EP0001_nishi_daak", "--dry-run"], project_root=project_root)
    assert logging.getLogger(LOGGER_NAME).handlers == []
