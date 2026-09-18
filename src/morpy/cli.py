"""This module defines CLI commands for `morpy`.
"""

import argparse
from pathlib import Path
from .repository import Tracker
from .status import print_grid_status
from .grid_run import stop_grid, cancel_model, find_active_model_id_by_pid

def _build_tracker(project_dir: str, db_name: str) -> Tracker:
    db_path = Path(project_dir) / db_name
    return Tracker.create(db_path=db_path)

def main_status() -> None:
    '''Function that defines the `morpy_status` CLI command.
    Makes use of status.print_grid_status().
    '''
    parser = argparse.ArgumentParser(prog="morpy_status", description="Print MOrPy grid status.")
    parser.add_argument("project_dir", help="Path to the project directory.")
    parser.add_argument("db_name", help="Database filename inside project_dir.")
    parser.add_argument("refresh_seconds", type=float, help="Refresh interval for status in seconds.")
    args = parser.parse_args()

    tracker = _build_tracker(args.project_dir, args.db_name)
    print_grid_status(tracker, refresh_seconds=args.refresh_seconds, clear_screen=True)


def main_stop() -> None:
    '''Function that defines the `morpy_stop` CLI command.
    Makes use of grid_run.stop_grid().
    '''
    parser = argparse.ArgumentParser(prog="morpy_stop", description="Stop a running MOrPy grid.")
    parser.add_argument("project_dir", help="Path to the project directory.")
    parser.add_argument("db_name", help="Database filename inside project_dir.")
    args = parser.parse_args()

    tracker = _build_tracker(args.project_dir, args.db_name)
    stop_grid(tracker=tracker)


def main_cancel_model() -> None:
    '''Function that defines the `morpy_cancel_model` CLI command.
    Makes use of grid_run.cancel_model().
    '''
    parser = argparse.ArgumentParser(prog="morpy_cancel_model", description="Cancel a single MOrPy model.")
    parser.add_argument("project_dir", help="Path to the project directory.")
    parser.add_argument("db_name", help="Database filename inside project_dir.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--model-id", help="model_id of the model to cancel (shown in morpy_status as 'id=...').")
    group.add_argument("--pid", type=int, help="Process ID of the model to cancel (shown in morpy_status as 'PID=...').")
    parser.add_argument(
        "--no-force", dest="force", action="store_false", default=True,
        help="Use SIGTERM only, without escalating to SIGKILL if the process does not exit in time."
    )
    parser.add_argument("--grace-seconds", type=float, default=3.0, help="Grace period in seconds before escalating to SIGKILL.")
    args = parser.parse_args()

    tracker = _build_tracker(args.project_dir, args.db_name)

    model_id = args.model_id
    if model_id is None:
        model_id = find_active_model_id_by_pid(tracker, args.pid)
        if model_id is None:
            raise SystemExit(f"No active model found with pid={args.pid}.")

    result = cancel_model(model_id, tracker=tracker, force=args.force, grace_seconds=args.grace_seconds)
    print(result)