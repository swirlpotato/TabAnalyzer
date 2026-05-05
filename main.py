from __future__ import annotations

import argparse
from pathlib import Path

from tab_analyzer.gp_loader import load_gp_file, summarize_song
from tab_analyzer.ui import run_app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze Guitar Pro tabs for scales and chord candidates.")
    parser.add_argument("file", nargs="?", help="Path to a .gp3/.gp4/.gp5/.gpx file")
    parser.add_argument("--summary", action="store_true", help="Print a text analysis summary instead of opening the UI")
    parser.add_argument("--max-measures", type=int, default=12, help="Number of measures to print in summary mode")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    initial_file = Path(args.file) if args.file else None

    if args.summary:
        if initial_file is None:
            raise SystemExit("No input file was provided.")
        song = load_gp_file(initial_file)
        print(summarize_song(song, max_measures=args.max_measures))
        return 0

    return run_app(initial_file)


if __name__ == "__main__":
    raise SystemExit(main())
