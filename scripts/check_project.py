from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
required = [
    "README.md",
    "AGENTS.md",
    "HANDOFF.md",
    "docs/SPEC.md",
    "docs/PHASE.md",
    "assets/reference/daibutsuame_reference.jpeg",
    "config/channel.yaml",
]

missing = [x for x in required if not (ROOT / x).exists()]
if missing:
    print("Missing files:")
    for x in missing:
        print(" -", x)
    raise SystemExit(1)

print("Project starter check: OK")
