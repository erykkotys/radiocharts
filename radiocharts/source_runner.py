from __future__ import annotations

import argparse
import sys

from radiocharts.collector import collect_source


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("source")
    args = p.parse_args()
    try:
        msg = collect_source(args.source)
        print(msg, flush=True)
        return 0
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
