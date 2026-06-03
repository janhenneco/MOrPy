"""Status read models backed by repository data plus optional live process map."""

from __future__ import annotations

import time
from dataclasses import dataclass
import os
from datetime import datetime, timezone

from .repository import LiveProcessRegistry, RunRepository


@dataclass
class ModelStatusView:
    """Normalized status row for UI, CLI, and monitoring consumers.

    Attributes:
        state: best current lifecycle state after live-over-durable merge.
        run_id: active run id if live, otherwise most recent known run id.
        pid: active process id when available; None for non-running models.
        return_code: terminal return code for completed/failed runs.
        started_at/updated_at/finished_at: lifecycle timestamps from best source.
        duration_seconds: latest run duration when known.
        backend: execution backend tag from run metadata (for example local or mpi).
        last_error: compact stderr summary from the latest run, if any.
    """
    model_id: str
    model_name: str
    state: str
    run_id: str | None
    pid: int | None
    return_code: int | None
    started_at: datetime | None
    updated_at: datetime | None
    finished_at: datetime | None
    duration_seconds: float | None
    backend: str | None
    model_path: str | None
    last_error: str | None


def _short_error(text: str, max_len: int = 160) -> str:
    text = text.strip().replace("\n", " ")
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def get_model_status(
    model_id: str,
    repo: RunRepository,
    *,
    live_registry: LiveProcessRegistry | None = None
) -> ModelStatusView:
    """Return best-available status for one model by merging multiple sources.

    Merge precedence:
        1. LiveProcessRegistry (if process is currently alive)
        2. Model row current snapshot
        3. Latest state transition
        4. Latest run terminal data
    
    Raises:
        KeyError if no information exists in any source for the given model_id.
    
    This function is intended as the canonical single-model status resolver.
    """
    model_row = repo.get_model_row(model_id)
    latest_run = repo.get_latest_run(model_id)
    latest_transition = repo.get_latest_transition(model_id)
    live_entry = live_registry.get(model_id) if live_registry is not None else None

    if model_row is None and latest_run is None and latest_transition is None and live_entry is None:
        raise KeyError(f"No status information found for model_id '{model_id}'.")

    model_name = (
        model_row.model_name
        if model_row is not None
        else latest_run.model_name
        if latest_run is not None
        else live_entry.handle.model_name
        if live_entry is not None
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

    started_at = (
        model_row.started_at
        if model_row is not None
        else latest_run.start_time
        if latest_run is not None
        else live_entry.handle.start_time
        if live_entry is not None
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

    duration_seconds = None if latest_run is None else latest_run.duration_seconds
    backend = None if latest_run is None else latest_run.metadata.get("backend")

    model_path = (
        str(live_entry.handle.model_path)
        if live_entry is not None
        else model_row.model_path
        if model_row is not None
        else str(latest_run.model_path)
        if latest_run is not None
        else None
    )

    last_error = None
    if latest_run is not None and latest_run.stderr.strip():
        last_error = _short_error(latest_run.stderr)

    
    return ModelStatusView(
        model_id=model_id,
        model_name=model_name,
        state=state,
        run_id=run_id,
        pid=pid,
        return_code=return_code,
        started_at=started_at,
        updated_at=updated_at,
        finished_at=finished_at,
        duration_seconds=duration_seconds,
        backend=backend,
        model_path=model_path,
        last_error=last_error
    )


def list_active_status(
    repo: RunRepository,
    *,
    live_registry: LiveProcessRegistry | None = None
) -> list[ModelStatusView]:
    """Return status rows for models that are likely active.

    Selection criteria:
        - Any model currently alive in LiveProcessRegistry.
        - Any model whose persisted state is queued, preparing, or running.
        - The returned rows are resolved through get_model_status to ensure the same 
            merge logic and field semantics as single-model queries.
    """
    active_ids: set[str] = set()

    if live_registry is not None:
        active_ids.update(live_registry.list_running_model_ids())

    for row in repo.list_model_rows():
        if row.state in {"queued", "preparing", "running"}:
            active_ids.add(row.model_id)

    return [get_model_status(model_id, repo, live_registry=live_registry) for model_id in sorted(active_ids)]

def list_models_status_snapshot(
    repo: RunRepository,
    *,
    live_registry: LiveProcessRegistry | None = None,
) -> list[ModelStatusView]:
    """Return a deterministic full snapshot for all models known to the repository.

    Behavior:
        - Produces one ModelStatusView per persisted model row.
        - Enriches each row with live process data when available.
        - Sorts output by model_name (case-insensitive), then model_id.
    
    This is suitable for dashboards, periodic reporting, and table displays.
    """
    out: list[ModelStatusView] = []

    for model_row in repo.list_model_rows():
        latest_run = repo.get_latest_run(model_row.model_id)
        live_entry = live_registry.get(model_row.model_id) if live_registry is not None else None

        is_live = live_entry is not None
        state = "running" if is_live else (model_row.state or (latest_run.terminal_state if latest_run else "unknown"))

        run_id = (
            live_entry.handle.run_id
            if is_live
            else (latest_run.metadata.get("run_id") if latest_run else None)
        )
        pid = (
            live_entry.process.pid
            if is_live
            else (
                int(latest_run.metadata["pid"])
                if latest_run and latest_run.metadata.get("pid", "").isdigit()
                else None
            )
        )

        return_code = None if is_live else (latest_run.return_code if latest_run else None)

        started_at = model_row.started_at or (latest_run.start_time if latest_run else None)
        updated_at = model_row.updated_at or (latest_run.end_time if latest_run else None)
        finished_at = None if is_live else (model_row.finished_at or (latest_run.end_time if latest_run else None))

        duration_seconds = None if latest_run is None else latest_run.duration_seconds
        backend = None if latest_run is None else latest_run.metadata.get("backend")
        model_path = model_row.model_path
        last_error = None
        if latest_run is not None and latest_run.stderr.strip():
            last_error = _short_error(latest_run.stderr)

        out.append(
            ModelStatusView(
                model_id=model_row.model_id,
                model_name=model_row.model_name,
                state=state,
                run_id=run_id,
                pid=pid,
                return_code=return_code,
                started_at=started_at,
                updated_at=updated_at,
                finished_at=finished_at,
                duration_seconds=duration_seconds,
                backend=backend,
                model_path=model_path,
                last_error=last_error,
            )
        )

    # deterministic display order
    out.sort(key=lambda r: (r.model_name.lower(), r.model_id))
    return out


def stream_models_status(
    repo: RunRepository,
    *,
    live_registry: LiveProcessRegistry | None = None,
    interval_seconds: float = 2.0,
):
    """Yield repeated all-model snapshots at a fixed polling interval.

    Args:
        interval_seconds: Refresh interval, must be greater than zero.
    Yields:
        List of ModelStatusView objects from list_models_status_snapshot.
    
    Use this generator as the backend for custom live monitors.
    """
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be > 0")

    while True:
        yield list_models_status_snapshot(repo, live_registry=live_registry)
        time.sleep(interval_seconds)

def live_status(
    repo: RunRepository,
    *,
    live_registry: LiveProcessRegistry | None = None,
    interval_seconds: float = 3.0,
    clear_screen: bool = False,
) -> None:
    """Print a continuously updating status view for all models.

    This convenience function consumes stream_models_status and prints compact
    rows containing model name, state, pid, and return code.

    Control:
        - Stops on keyboard interrupt: Stop with Ctrl+C (Linux) or Cmd+. (MacOS).
        - Optional clear_screen mode redraws in-place style output.

    """
    try:
        for rows in stream_models_status(
            repo,
            live_registry=live_registry,
            interval_seconds=interval_seconds,
        ):
            if clear_screen:
                # ANSI clear + cursor home
                print("\033[2J\033[H", end="")

            stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            print(f"\n[{stamp}]")
            print([(r.model_name, r.state, r.pid, r.return_code) for r in rows], flush=True)
    except KeyboardInterrupt:
        print("\nStopped live status.")

def reconcile_stale_runs(
    repo: RunRepository,
    *,
    stale_states: set[str] | None = None,
    terminal_state: str = "cancelled",
    reason: str = "Reconciled: process not found after interruption.",
) -> list[str]:
    """Mark stale 'running' models as terminal if their PID is no longer alive.

    Call this after an interrupted grid run to clean up stale DB state.
    Returns a list of model_ids that were reconciled.

    Args:
        repo: RunRepository to read from and write corrections to.
        stale_states: Set of state labels to consider for reconciliation.
            Defaults to {"running", "preparing"}.
        terminal_state: State to write for stale models. Default "cancelled".
        reason: Reason string written to the state transition record.
    Returns:
        List of model_ids that were corrected.
    """
    if stale_states is None:
        stale_states = {"running", "preparing"}

    reconciled: list[str] = []
    now = datetime.now(timezone.utc)

    for model_row in repo.list_model_rows():
        if model_row.state not in stale_states:
            continue

        latest_run = repo.get_latest_run(model_row.model_id)
        pid: int | None = None
        if latest_run is not None and latest_run.metadata.get("pid", "").isdigit():
            pid = int(latest_run.metadata["pid"])

        pid_alive = False
        if pid is not None:
            try:
                os.kill(pid, 0)
                pid_alive = True
            except (ProcessLookupError, PermissionError):
                pid_alive = False

        if not pid_alive:
            from .run_types import StateTransition
            transition = StateTransition(
                model_id=model_row.model_id,
                from_state=model_row.state,
                to_state=terminal_state,
                at=now,
                reason=reason,
                run_id=latest_run.metadata.get("run_id") if latest_run else None,
            )
            repo.record_state_transition(transition)
            reconciled.append(model_row.model_id)

    return reconciled