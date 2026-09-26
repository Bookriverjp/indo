from __future__ import annotations
import argparse
from pipeline.config import PROJECT_ROOT, load_yaml
from pipeline.workspace import create_episode_workspace

def main() -> int:
    parser = argparse.ArgumentParser(description="Daibutsuame folklore pipeline starter")
    parser.add_argument("episode_id", help="e.g. EP0001_sample")
    parser.add_argument("--dry-run", action="store_true", help="create workspace only")
    args = parser.parse_args()

    channel = load_yaml("config/channel.yaml")
    pipeline_cfg = load_yaml("config/pipeline.yaml")
    workdir = create_episode_workspace(PROJECT_ROOT, args.episode_id)

    print(f"Project: {channel['channel']['working_name']}")
    print(f"Episode: {args.episode_id}")
    print(f"Workspace: {workdir}")
    print(f"Reference image: {channel['narrator']['reference_image']}")
    print("Configured stages:")
    for stage in pipeline_cfg["pipeline"]["stages"]:
        print(f" - {stage}")

    if args.dry_run or pipeline_cfg["pipeline"].get("dry_run", True):
        print("\nDRY RUN: external APIs are not called.")
        return 0

    raise NotImplementedError(
        "Provider stages are intentionally not implemented in v1 starter. "
        "Follow docs/PHASE.md one PHASE at a time."
    )

if __name__ == "__main__":
    raise SystemExit(main())
