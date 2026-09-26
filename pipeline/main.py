from __future__ import annotations
import argparse
import sys
from pathlib import Path

from pipeline.config import PROJECT_ROOT, ConfigError, load_yaml
from pipeline.logging_setup import close_logging, setup_logging
from pipeline.workspace import create_episode_workspace, validate_episode_id


def main(argv: list[str] | None = None, project_root: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description="Daibutsuame folklore pipeline starter")
    parser.add_argument("episode_id", help="e.g. EP0001_nishi_daak")
    parser.add_argument("--dry-run", action="store_true", help="create workspace only")
    args = parser.parse_args(argv)
    root = project_root or PROJECT_ROOT

    try:
        validate_episode_id(args.episode_id)
        channel = load_yaml("config/channel.yaml", root)
        pipeline_cfg = load_yaml("config/pipeline.yaml", root)
    except (ValueError, ConfigError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    workdir = create_episode_workspace(root, args.episode_id)
    log = setup_logging(workdir / "logs" / "pipeline.log")
    try:
        return _run(args, channel, pipeline_cfg, workdir, log)
    finally:
        close_logging(log)


def _run(args, channel: dict, pipeline_cfg: dict, workdir: Path, log) -> int:
    log.info(f"Project: {channel['channel']['working_name']}")
    log.info(f"Episode: {args.episode_id}")
    log.info(f"Workspace: {workdir}")
    log.info(f"Reference image: {channel['narrator']['reference_image']}")
    log.info("Configured stages: " + ", ".join(pipeline_cfg["pipeline"]["stages"]))

    if args.dry_run or pipeline_cfg["pipeline"].get("dry_run", True):
        log.info("DRY RUN: external APIs are not called.")
        return 0

    raise NotImplementedError(
        "Provider stages are intentionally not implemented in v1 starter. "
        "Follow docs/PHASE.md one PHASE at a time."
    )


if __name__ == "__main__":
    raise SystemExit(main())
