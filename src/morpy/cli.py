"""This module defines CLI functions for `morpy`.
"""

import argparse
from pathlib import Path
from .repository import Tracker
from .status import print_grid_status
from .grid_run import stop_grid

def _build_tracker(project_dir: str, db_name: str) -> Tracker:
    db_path = Path(project_dir) / db_name
    return Tracker.create(db_path=db_path)

def main_status() -> None:
    parser = argparse.ArgumentParser(prog="morpy_status", description="Print MOrPy grid status.")
    parser.add_argument("project_dir", help="Path to the project directory.")
    parser.add_argument("db_name", help="Database filename inside project_dir.")
    parser.add_argument("refresh_seconds", type=float, help="Refresh interval for status in seconds.")
    args = parser.parse_args()

    tracker = _build_tracker(args.project_dir, args.db_name)
    print_grid_status(tracker, refresh_seconds=args.refresh_seconds, clear_screen=True)


def main_stop() -> None:
    parser = argparse.ArgumentParser(prog="morpy_stop", description="Stop a running MOrPy grid.")
    parser.add_argument("project_dir", help="Path to the project directory.")
    parser.add_argument("db_name", help="Database filename inside project_dir.")
    args = parser.parse_args()

    tracker = _build_tracker(args.project_dir, args.db_name)
    stop_grid(tracker=tracker)