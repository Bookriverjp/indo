"""PHASE 10: 確認の関門の状態表示・承認・差し戻し・確認画面。

  python -m pipeline.qa status  EP0001_nishi_daak
  python -m pipeline.qa approve EP0001_nishi_daak research [--note "メモ"]
  python -m pipeline.qa reject  EP0001_nishi_daak script --note "理由"
  python -m pipeline.qa serve   EP0001_nishi_daak [--port 8765]    # ブラウザで http://127.0.0.1:8765/
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pipeline.config import PROJECT_ROOT
from pipeline.qa.gates import GATES, STATE_LABEL, decide, evaluate, write_report


def main(argv: list[str] | None = None, project_root: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description="QA gates")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("status"); p.add_argument("episode_id")
    for name in ("approve", "reject"):
        p = sub.add_parser(name)
        p.add_argument("episode_id")
        p.add_argument("gate", choices=list(GATES))
        p.add_argument("--note", default="")
        p.add_argument("--by", default="owner")
    p = sub.add_parser("serve"); p.add_argument("episode_id"); p.add_argument("--port", type=int, default=8765)
    p.add_argument("--by", default="owner")
    args = parser.parse_args(argv)
    root = project_root or PROJECT_ROOT

    try:
        if args.command in ("approve", "reject"):
            decide(root, args.episode_id, args.gate, "approved" if args.command == "approve" else "rejected",
                   args.note, by=args.by)
        if args.command == "serve":
            from pipeline.qa.server import make_server

            srv = make_server(root, args.episode_id, port=args.port, by=args.by)
            print(f"確認画面: http://127.0.0.1:{srv.server_address[1]}/  （終了は Ctrl+C）")
            try:
                srv.serve_forever()
            except KeyboardInterrupt:
                pass
            return 0
        gates = evaluate(root, args.episode_id)
        write_report(root, args.episode_id)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    for g in gates:
        print(f"{g['gate']:9s} {g['label']}: {STATE_LABEL[g['state']]}")
        for e in g["errors"]:
            print(f"    NG  {e}")
        for w in g["warnings"]:
            print(f"    警告 {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
