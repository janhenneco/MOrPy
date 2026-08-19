"""Status read models backed by repository data plus optional live process map."""

import time
from dataclasses import dataclass
from datetime import datetime, timezone
import shutil

from .repository import LiveProcessRegistry, RunRepository, Tracker


@dataclass
class ModelStatus:
    """Instance that holds run information about one model.

    Attributes:
        model_id: Unique ID of model
        model_name: Name of the model, i.e. Model.name
        state: Lifecycle state for this model: running, completed, ...
        pid: Process ID of the model
        return_code: 0 for no errors, 1 for errors
        run_id: Unique ID for model run
        started_at/updated_at/finished_at: lifecycle timestamps
        model_path: Location of the model's model directory
        backend: Backend used to run this model grid, if part of a grid at all   
        last_error: last found error fot this model, if any
    """
    model_id: str
    model_name: str
    state: str
    pid: int | None
    return_code: int | None
    run_id: str | None
    started_at: datetime | None
    updated_at: datetime | None
    finished_at: datetime | None
    model_path: str | None
    backend: str | None
    last_error: str | None

def _resolve_model_status(
    model_id: str,
    repo: RunRepository,
    *,
    live_tracker: LiveProcessRegistry | None = None
    ) -> ModelStatus:
    """Return ModelStatus object associated with a specific model_id."""
    model_row = repo.get_model_row(model_id)
    latest_run = repo.get_latest_run(model_id)
    latest_transition = repo.get_latest_transition(model_id)
    live_entry = live_tracker.get(model_id) if live_tracker is not None else None

    if model_row is None and latest_run is None and latest_transition is None and live_entry is None:
        raise KeyError(f"No status information found for model_id '{model_id}'.")

    model_name = (
        live_entry.handle.model_name
        if live_entry is not None
        else latest_run.model_name
        if latest_run is not None and latest_run.model_name
        else model_row.model_name
        if model_row is not None
        else model_id
    )

    state = (
        "running"
        if live_entry is not None
        else model_row.state
        if model_row is not None and model_row.state is not None
        else latest_transition.to_state
        if latest_transition is not None
        else latest_run.terminal_state
        if latest_run is not None
        else "unknown"
    )

    run_id = (
        live_entry.handle.run_id
        if live_entry is not None
        else latest_run.metadata.get("run_id")
        if latest_run is not None
        else latest_transition.run_id
        if latest_transition is not None
        else None
    )

    pid = (
        live_entry.process.pid
        if live_entry is not None
        else int(latest_run.metadata["pid"])
        if latest_run is not None and latest_run.metadata.get("pid", "").isdigit()
        else None
    )

    return_code = (
        None
        if live_entry is not None
        else latest_run.return_code
        if latest_run is not None
        else None
    )

    started_at = (
        live_entry.handle.start_time
        if live_entry is not None
        else model_row.started_at
        if model_row is not None
        else latest_run.start_time
        if latest_run is not None
        else None
    )

    updated_at = (
        model_row.updated_at
        if model_row is not None
        else latest_transition.at
        if latest_transition is not None
        else latest_run.end_time
        if latest_run is not None
        else None
    )

    finished_at = (
        model_row.finished_at
        if model_row is not None
        else latest_run.end_time
        if latest_run is not None and latest_run.terminal_state in {"completed", "failed", "cancelled"}
        else None
    )

    model_path = (
        str(live_entry.handle.model_path)
        if live_entry is not None
        else model_row.model_path
        if model_row is not None
        else str(latest_run.model_path)
        if latest_run is not None
        else None
    )

    backend = (
        latest_run.metadata.get("backend")
        if latest_run is not None
        else None
    )

    last_error = None
    if latest_run is not None and latest_run.stderr.strip():
        last_error = latest_run.stderr.strip().replace("\n", " ")
        if len(last_error) > 160:
            last_error = last_error[:157] + "..."

    if state in {"running", "queued", "preparing", "restart"}:
        return_code = None

    return ModelStatus(
        model_id=model_id,
        model_name=model_name,
        state=state,
        pid=pid,
        return_code=return_code,
        run_id=run_id,
        started_at=started_at,
        updated_at=updated_at,
        finished_at=finished_at,
        model_path=model_path,
        backend=backend,
        last_error=last_error,
    )

def _build_resume_summary(rows: list[ModelStatus]) -> dict[str, int]:
    counts: dict[str, int] = {
        "total": 0,
        "completed": 0,
        "running": 0,
        "preparing": 0,
        "queued": 0,
        "restart": 0,
        "failed": 0,
        "cancelled": 0,
        "draft": 0,
        "paused": 0,
        "unknown": 0,
        "resume_candidates_strict": 0,
        "resume_candidates_with_retries": 0,
    }

    strict_states = {"draft", "queued", "preparing", "running", "restart", "paused", "unknown"}
    retry_extra_states = {"failed", "cancelled"}

    for row in rows:
        state = (row.state or "unknown").strip().lower()
        counts["total"] += 1
        if state in counts:
            counts[state] += 1
        else:
            counts["unknown"] += 1

        if state in strict_states:
            counts["resume_candidates_strict"] += 1
        if state in strict_states or state in retry_extra_states:
            counts["resume_candidates_with_retries"] += 1

    return counts

def grid_status(tracker: Tracker) -> list[ModelStatus]:
    """Return a list of ModelStatus objects."""
    repo = tracker.repo
    live_tracker = tracker.live_tracker
    rows = [_resolve_model_status(model_row.model_id, repo, live_tracker=live_tracker) for model_row in repo.list_model_rows()]
    rows.sort(key=lambda row: (row.model_name.lower(), row.model_id))
    return rows

def print_grid_status(
    tracker: Tracker,
    refresh_seconds: float | None = None,
    notebook: bool = False,
    clear_screen: bool = True,
    show_resume_summary: bool = True
) -> None:
    """Print the status of all grid models once or as a refreshing view.

    Args:
        tracker: Tracker object with Model repo and live tracker.
        refresh_seconds: If None, print once (snapshot). If >0 , refresh
            with specified interval
        notebook: Set to True for clear screen functionality in Jupyter notebooks
        clear_screen: If True (and not notebook), clear terminal between refreshes.
    """
    
    if refresh_seconds is not None and refresh_seconds <= 0:
        raise ValueError("refresh_seconds must be > 0")

    def _state_order(state: str) -> int:
        if state == "running":
            return 0
        if state == "restart":
            return 1
        if state in {"queued", "preparing"}:
            return 2
        if state in {"completed", "failed", "cancelled"}:
            return 3
        return 4

    def _clear_output() -> None:
        if notebook:
            try:
                from IPython.display import clear_output as ipy_clear_output
                ipy_clear_output(wait=True)
                return
            except Exception:
                # Fall back to ANSI if IPython is unavailable.
                pass
        if clear_screen:
            print("\033[H\033[2J\033[3J", end="")  # also clears scrollback (3J)

    
    def _render_once() -> None:
        rows = grid_status(tracker)
    
        if not rows:
            print("No models found.", flush=True)
            return
    
        rows.sort(key=lambda r: (_state_order(r.state), r.model_name.lower(), r.model_id))
    
        if show_resume_summary:
            summary = _build_resume_summary(rows)
            print(
                "Summary: "
                f"total={summary['total']}  "
                f"completed={summary['completed']}  "
                f"strict_resume={summary['resume_candidates_strict']}  "
                f"resume_with_retries={summary['resume_candidates_with_retries']}  "
                f"failed={summary['failed']}  "
                f"cancelled={summary['cancelled']}",
                flush=True,
            )
            print("", flush=True)
    
        now = datetime.now().astimezone()
        offset = now.strftime('%z')
        offset = offset[:3] + ":" + offset[3:]
        print(f"[{now:%Y-%m-%d %H:%M:%S} UTC{offset}]\n")
    
        # Build one formatted cell string per row: "MODEL STATE PID/RC"
        model_w = max(len("MODEL"), *(len(r.model_name) for r in rows))
        state_w = max(len("STATE"), *(len(r.state) for r in rows))
    
        def _cell(r) -> str:
            pid = "" if r.pid is None else str(r.pid)
            rc = "" if r.return_code is None else str(r.return_code)
            pidrc = f"{pid}/{rc}" if (pid or rc) else ""
            return f"{r.model_name:<{model_w}} {r.state:<{state_w}} {pidrc}"
    
        cells = [_cell(r) for r in rows]
        cell_w = max(len(c) for c in cells) + 2  # padding between columns
    
        term_size = shutil.get_terminal_size(fallback=(120, 40))
        # Reserve a few lines for summary/timestamp/prompt
        available_lines = max(term_size.lines - 6, 5)
        max_cols = max(term_size.columns // cell_w, 1)
        n_cols = min(max_cols, -(-len(cells) // available_lines))  # ceil division for rows-per-col
        n_cols = max(n_cols, 1)
        n_rows_per_col = -(-len(cells) // n_cols)  # ceil
    
        # Pad cells list to fill the grid evenly
        padded = cells + [""] * (n_rows_per_col * n_cols - len(cells))
    
        for row_i in range(n_rows_per_col):
            line_parts = []
            for col_i in range(n_cols):
                idx = col_i * n_rows_per_col + row_i
                line_parts.append(f"{padded[idx]:<{cell_w}}")
            print("".join(line_parts) + "\033[K", flush=True)

    if refresh_seconds is None:
        _render_once()
        return

    try:
        print("\033[?1049h", end="")  # enter alt screen
        while True:
            print("\033[H", end="")  # just move cursor home, no need to clear — new content overwrites old
            _render_once()
            time.sleep(refresh_seconds)
    except KeyboardInterrupt:
        print("\nStopped status refresh.", flush=True)


