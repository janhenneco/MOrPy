"""Grid orchestration for multi-model execution.

This module provides:
- run_models_local: local parallel orchestration using existing launch/wait APIs.
- run_models_mpi: simple rank-split parallel execution using mpi4py.
- run_models: backend dispatcher.

Design goals:
- Keep behavior consistent with run.py by delegating per-model execution there.
- Keep orchestration simple (FIFO queue, bounded concurrency).
- Remain compatible with observer-based persistence/status adapters.
"""

from __future__ import annotations

import uuid
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeoutError

import os
import signal
import threading
import subprocess
import time
from collections import deque # double-ended queue --> for efficiency
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Literal, Mapping

from .config import MesaConfig
from .model import Model, ModelState
from .options import DefaultsOptions
from .run import launch_model, wait_for_model, terminate_run_process
from .run_types import RunHandle, RunResult, StateTransition
from .repository import Tracker

QueuePolicy = Literal["fifo"] # First In, First Out
GridBackend = Literal["local", "mpi"]
ResumeMatchPolicy = Literal["id_only", "id_or_path"]
ResumeFailedPolicy = Literal["rerun", "skip"]
ResumeCancelledPolicy = Literal["rerun", "skip"]


@dataclass
class GridRunItem:
    """Container for one model and optional per-model environment.

    Attributes:
        model: Model object to run.
        env: Optional shell environment for this model.
    """
    model: Model
    env: Mapping[str, str] | None = None


@dataclass
class GridRunResult:
    """Aggregate results for a grid run.

    Attributes:
        total: Total number of models scheduled in the grid run.
        completed: Number of successfully completed model runs.
        failed: Number of failed model runs.
        cancelled: Number of cancelled model runs.
        results: Terminal RunResult entries for all processed models.
        backend: Execution backend, local or mpi.
        duration_seconds: Grid-run wall-clock duration in seconds.
    """
    total: int
    completed: int
    failed: int
    cancelled: int
    results: list[RunResult]
    backend: GridBackend
    duration_seconds: float

@dataclass
class GridRunHandle:
    """Handle for a launched non-blocking grid run."""
    grid_id: str
    backend: GridBackend
    submitted_at: datetime
    future: Future[GridRunResult]
    _executor: ThreadPoolExecutor
    _stop_event: threading.Event = field(default_factory=threading.Event, repr=False)
    _running_processes: dict[str, tuple[GridRunItem, RunHandle, subprocess.Popen]] = field(default_factory=dict, repr=False)
    _running_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _tracker: Tracker | None = field(default=None, repr=False)

@dataclass
class ResumePolicy:
    enabled: bool = True
    match_policy: ResumeMatchPolicy = "id_or_path"
    skip_completed: bool = True
    failed_policy: ResumeFailedPolicy = "rerun"
    cancelled_policy: ResumeCancelledPolicy = "rerun"
    hydrate_timestamps: bool = True

@dataclass
class ReconcileSummary:
    total_items: int
    runnable_items: int
    skipped_items: int
    reassigned_model_ids: int
    state_counts: dict[str, int] = field(default_factory=dict)
    skipped_by_reason: dict[str, int] = field(default_factory=dict)

def _normalize_path(value: Path | str | None) -> str | None:
    if value is None:
        return None
    try:
        return str(Path(value).expanduser().resolve())
    except Exception:
        return str(Path(value).expanduser())

def _coerce_model_state(state_text: str | None) -> ModelState | None:
    if not state_text:
        return None
    text = state_text.strip().lower()
    try:
        return ModelState(text)
    except ValueError:
        return None

def _setdefault_inc(counter: dict[str, int], key: str) -> None:
    counter[key] = counter.get(key, 0) + 1

def _schedule_decision_for_state(state_text: str, policy: ResumePolicy) -> tuple[bool, str | None]:
    state_norm = state_text.strip().lower()

    if state_norm == "completed":
        if policy.skip_completed:
            return False, "completed"
        return True, None

    if state_norm == "failed":
        if policy.failed_policy == "skip":
            return False, "failed"
        return True, None

    if state_norm == "cancelled":
        if policy.cancelled_policy == "skip":
            return False, "cancelled"
        return True, None

    # draft, queued, preparing, running, restart, paused, unknown -> runnable
    return True, None

def _reconcile_items_with_repository(
    items: list[GridRunItem],
    tracker: Tracker,
    policy: ResumePolicy,
) -> tuple[list[GridRunItem], ReconcileSummary]:
    rows = tracker.repo.list_model_rows()

    rows_by_id = {row.model_id: row for row in rows}
    rows_by_path: dict[str, object] = {}
    for row in rows:
        row_path = _normalize_path(getattr(row, "model_path", None))
        if row_path is not None:
            rows_by_path[row_path] = row

    runnable: list[GridRunItem] = []
    skipped: list[tuple[GridRunItem, str]] = []
    state_counts: dict[str, int] = {}
    skipped_by_reason: dict[str, int] = {}
    reassigned = 0

    for item in items:
        model = item.model
        matched_row = rows_by_id.get(model.model_id)

        if matched_row is None and policy.match_policy == "id_or_path":
            model_path_norm = _normalize_path(model.model_path)
            if model_path_norm is not None:
                matched_row = rows_by_path.get(model_path_norm)

                # Rebind ephemeral model_id to persisted DB identity
                if matched_row is not None and model.model_id != matched_row.model_id:
                    model.model_id = matched_row.model_id
                    reassigned += 1

        if matched_row is not None:
            db_state = getattr(matched_row, "state", None)
            parsed_state = _coerce_model_state(db_state)
            if parsed_state is not None:
                model.state = parsed_state

            if policy.hydrate_timestamps:
                # Only hydrate fields that actually exist on both objects.
                for attr_name in ("started_at", "updated_at", "finished_at", "snapshot_taken_at"):
                    if hasattr(matched_row, attr_name):
                        attr_value = getattr(matched_row, attr_name)
                        if attr_value is not None and hasattr(model, attr_name):
                            setattr(model, attr_name, attr_value)

        effective_state = model.state.value if getattr(model, "state", None) is not None else "unknown"
        _setdefault_inc(state_counts, effective_state)

        run_it, skip_reason = _schedule_decision_for_state(effective_state, policy)
        if run_it:
            runnable.append(item)
        else:
            skipped.append((item, skip_reason or "policy_skip"))
            _setdefault_inc(skipped_by_reason, skip_reason or "policy_skip")

    summary = ReconcileSummary(
        total_items=len(items),
        runnable_items=len(runnable),
        skipped_items=len(skipped),
        reassigned_model_ids=reassigned,
        state_counts=state_counts,
        skipped_by_reason=skipped_by_reason,
    )
    return runnable, summary

def _exception_result(
    item: GridRunItem,
    exc: Exception,
    *,
    backend: GridBackend,
    command_name: str,
    sync_before_run: bool,
    return_code: int = 1
    ) -> RunResult:
    """Private function to gracefully deal with runs part of a grid run that fail."""
    now = datetime.now(timezone.utc)
    if item.model.model_path is not None:
        model_path = Path(item.model.model_path)
    else:
        model_path = Path(".")
    return RunResult(
        success=False,
        terminal_state="failed",
        return_code=return_code,
        duration_seconds=0.0,
        model_id=item.model.model_id,
        model_name=item.model.name,
        model_path=model_path,
        command=[command_name],
        cwd=model_path,
        start_time=now,
        end_time=now,
        stdout="",
        stderr=str(exc),
        sync_performed=sync_before_run,
        metadata={
            "backend": backend,
            "error_type": type(exc).__name__,
        },
    )


def _summarize(
    *,
    results: list[RunResult],
    total: int,
    backend: GridBackend,
    duration_seconds: float,
    ) -> GridRunResult:
    completed = sum(1 for r in results if r.terminal_state == "completed")
    failed = sum(1 for r in results if r.terminal_state == "failed")
    cancelled = sum(1 for r in results if r.terminal_state == "cancelled")
    return GridRunResult(
        total=total,
        completed=completed,
        failed=failed,
        cancelled=cancelled,
        results=results,
        backend=backend,
        duration_seconds=duration_seconds,
    )

def _cancelled_result(
    item: GridRunItem,
    *,
    backend: GridBackend,
    command_name: str,
    sync_before_run: bool,
    reason: str,
    return_code: int = 130,
    ) -> RunResult:
    now = datetime.now(timezone.utc)
    if item.model.model_path is not None:
        model_path = Path(item.model.model_path)
    else:
        model_path = Path(".")
    return RunResult(
        success=False,
        terminal_state="cancelled",
        return_code=return_code,
        duration_seconds=0.0,
        model_id=item.model.model_id,
        model_name=item.model.name,
        model_path=model_path,
        command=[command_name],
        cwd=model_path,
        start_time=now,
        end_time=now,
        stdout="",
        stderr=reason,
        sync_performed=sync_before_run,
        metadata={
            "backend": backend,
            "cancel_reason": reason,
        },
    )

def _is_timeout_reason(reason: str | None) -> bool:
    if reason is None:
        return False
    text = reason.strip().lower()
    return "timeout" in text

_RESTART_REQUEST_TAG = "stop_grid restart request"
def _should_mark_restart(reason: str | None) -> bool:
    if _is_timeout_reason(reason):
        return True
    if reason is None:
        return False
    return _RESTART_REQUEST_TAG in reason.strip().lower()


def _mark_model_restart(
    item: GridRunItem,
    *,
    observer,
    reason: str,
    run_id: str | None,
    ) -> None:
    previous_state = item.model.state.value
    if item.model.state == ModelState.RESTART:
        return
    now = datetime.now(timezone.utc)
    item.model.state = ModelState.RESTART
    item.model.updated_at = now
    transition = StateTransition(
        model_id=item.model.model_id,
        from_state=previous_state,
        to_state=ModelState.RESTART.value,
        at=now,
        reason=reason,
        run_id=run_id,
    )
    if observer is not None:
        observer.on_state_transition(transition)


def _cancel_pending_items(
    pending_items: deque[GridRunItem],
    *,
    results: list[RunResult],
    backend: GridBackend,
    command_name: str,
    sync_before_run: bool,
    stop_reason: str,
    observer,
    restart_triggered: bool,
) -> None:
    while pending_items:
        pending_item = pending_items.popleft()
        cancel_result = _cancelled_result(
            pending_item,
            backend=backend,
            command_name=command_name,
            sync_before_run=sync_before_run,
            reason=f"Cancelled before launch: {stop_reason}",
        )
        results.append(cancel_result)
        if observer is not None:
            observer.on_process_finished(cancel_result)
        if restart_triggered:
            _mark_model_restart(
                pending_item,
                observer=observer,
                reason=f"Marked restart after stop request ({stop_reason})",
                run_id=cancel_result.metadata.get("run_id"),
            )


def _cancel_running_item(
    *,
    item: GridRunItem,
    handle: RunHandle,
    process: subprocess.Popen,
    backend: GridBackend,
    command_name: str,
    sync_before_run: bool,
    capture_output: bool,
    tracker: Tracker | None,
    observer,
    stop_reason: str,
    restart_triggered: bool,
) -> RunResult:
    try:
        terminate_run_process(process, force=True)
        result = wait_for_model(
            model=item.model,
            handle=handle,
            process=process,
            timeout=None,
            capture_output=capture_output,
            tracker=tracker,
            cancel_requested=True,
            cancel_reason=stop_reason,
        )
    except Exception as exc:
        result = _cancelled_result(
            item,
            backend=backend,
            command_name=command_name,
            sync_before_run=sync_before_run,
            reason=f"{stop_reason}; finalise error: {exc}",
        )
        if observer is not None:
            observer.on_process_finished(result)

    if restart_triggered:
        _mark_model_restart(
            item,
            observer=observer,
            reason=f"Marked restart after stop request ({stop_reason})",
            run_id=result.metadata.get("run_id"),
        )

    return result


def _collect_run_result(
    *,
    item: GridRunItem,
    handle: RunHandle,
    process: subprocess.Popen,
    timeout: float | None,
    capture_output: bool,
    tracker: Tracker | None,
    backend: GridBackend,
    command_name: str,
    sync_before_run: bool,
    observer,
    return_code_on_error: int = 1,
) -> RunResult:
    try:
        return wait_for_model(
            model=item.model,
            handle=handle,
            process=process,
            timeout=timeout,
            capture_output=capture_output,
            tracker=tracker,
        )
    except Exception as exc:
        result = _exception_result(
            item,
            exc,
            backend=backend,
            command_name=command_name,
            sync_before_run=sync_before_run,
            return_code=return_code_on_error,
        )
        if observer is not None:
            observer.on_process_finished(result)
        return result

def _prepare_tracker_for_grid(
    tracker: Tracker | None,
    timeout: float | None,
) -> None:
    if tracker is None:
        return
    tracker.repo.clear_grid_stop_request()
    if timeout is None:
        tracker.repo.clear_grid_timeout()
    else:
        tracker.repo.set_grid_timeout(timeout)


def _cleanup_tracker_after_grid(tracker: Tracker | None) -> None:
    if tracker is None:
        return
    tracker.repo.clear_grid_stop_request()
    tracker.repo.clear_grid_timeout()


def _poll_repo_stop_request(
    *,
    tracker: Tracker | None,
    timeout: float | None,
    last_db_check: float,
    db_check_interval_seconds: float,
    cached_stop_requested: bool,
    cached_stop_reason: str | None,
) -> tuple[bool, str | None, float]:
    if tracker is None:
        return cached_stop_requested, cached_stop_reason, last_db_check

    now_check = time.monotonic()
    if (now_check - last_db_check) < db_check_interval_seconds:
        return cached_stop_requested, cached_stop_reason, last_db_check

    deadline = tracker.repo.get_grid_timeout_deadline()
    if deadline is not None and datetime.now(timezone.utc) >= deadline:
        if not tracker.repo.is_grid_stop_requested():
            if timeout is not None:
                tracker.repo.request_grid_stop(reason=f"Grid timeout after {timeout} seconds")
            else:
                tracker.repo.request_grid_stop(reason="Grid timeout")

    stop_requested = tracker.repo.is_grid_stop_requested()
    stop_reason = tracker.repo.get_grid_stop_reason() if stop_requested else None
    return stop_requested, stop_reason, now_check



def _pid_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Exists but not owned by current user.
        return True
    except Exception:
        return False
    return True


def _wait_pid_exit(pid: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _pid_exists(pid):
            return True
        time.sleep(0.05)
    return not _pid_exists(pid)


def _terminate_pid_tree(pid: int, *, force: bool, grace_seconds: float) -> bool:
    if not _pid_exists(pid):
        return True

    if force:
        try:
            os.killpg(pid, signal.SIGKILL)
        except Exception:
            try:
                os.kill(pid, signal.SIGKILL)
            except Exception:
                pass
        return _wait_pid_exit(pid, max(grace_seconds, 0.25))

    try:
        os.killpg(pid, signal.SIGTERM)
    except Exception:
        try:
            os.kill(pid, signal.SIGTERM)
        except Exception:
            pass

    if _wait_pid_exit(pid, grace_seconds):
        return True

    try:
        os.killpg(pid, signal.SIGKILL)
    except Exception:
        try:
            os.kill(pid, signal.SIGKILL)
        except Exception:
            pass
    return _wait_pid_exit(pid, max(grace_seconds, 0.25))

def _mark_recovered_cancelled(
    *,
    tracker: Tracker,
    model_id: str,
    from_state: str,
    latest_run: RunResult,
    reason: str,
) -> None:
    now = datetime.now(timezone.utc)
    run_id = latest_run.metadata.get("run_id")
    transition = StateTransition(
        model_id=model_id,
        from_state=from_state,
        to_state="cancelled",
        at=now,
        reason=reason,
        run_id=run_id,
    )
    tracker.observer.on_state_transition(transition)

    metadata = dict(latest_run.metadata)
    metadata["cancel_mode"] = "recovery"

    start_time = latest_run.start_time
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    else:
        start_time = start_time.astimezone(timezone.utc)

    duration = max((now - start_time).total_seconds(), 0.0)

    result = RunResult(
        success=False,
        terminal_state="cancelled",
        return_code=130,
        duration_seconds=duration,
        model_id=latest_run.model_id,
        model_name=latest_run.model_name,
        model_path=latest_run.model_path,
        command=latest_run.command,
        cwd=latest_run.cwd,
        start_time=start_time,
        end_time=now,
        stdout="",
        stderr=reason,
        sync_performed=latest_run.sync_performed,
        metadata=metadata,
    )
    tracker.observer.on_process_finished(result)
    if _should_mark_restart(reason):
        restart_transition = StateTransition(
            model_id=model_id,
            from_state="cancelled",
            to_state=ModelState.RESTART.value,
            at=now,
            reason=f"Marked restart after stop handling ({reason})",
            run_id=run_id,
        )
        tracker.observer.on_state_transition(restart_transition)
    tracker.live_tracker.unregister(model_id)

def _stop_from_repository(
    *,
    tracker: Tracker,
    force: bool,
    grace_seconds: float,
    skip_model_ids: set[str] | None = None,
) -> dict[str, object]:
    skip = skip_model_ids or set()
    running_states = {"running", "preparing", "queued"}

    candidates: list[str] = []
    terminated_model_ids: list[str] = []
    already_exited_model_ids: list[str] = []
    missing_pid_model_ids: list[str] = []
    failed_model_ids: list[str] = []
    errors: list[str] = []
    recovery_reason = tracker.repo.get_grid_stop_reason() or "Cancelled by stop_grid recovery path"

    for row in tracker.repo.list_model_rows():
        if row.model_id in skip:
            continue
        state = (row.state or "").lower()
        if state not in running_states:
            continue

        candidates.append(row.model_id)
        latest_run = tracker.repo.get_latest_run(row.model_id)
        if latest_run is None:
            missing_pid_model_ids.append(row.model_id)
            continue

        pid_text = latest_run.metadata.get("pid", "")
        if not pid_text.isdigit():
            missing_pid_model_ids.append(row.model_id)
            continue

        pid = int(pid_text)
        if not _pid_exists(pid):
            already_exited_model_ids.append(row.model_id)
            continue

        try:
            ok = _terminate_pid_tree(pid, force=force, grace_seconds=grace_seconds)
            if not ok:
                failed_model_ids.append(row.model_id)
                continue
            _mark_recovered_cancelled(
                tracker=tracker,
                model_id=row.model_id,
                from_state=state or "running",
                latest_run=latest_run,
                reason=recovery_reason,
            )
            terminated_model_ids.append(row.model_id)
        except Exception as exc:
            failed_model_ids.append(row.model_id)
            errors.append(f"{row.model_id}: {type(exc).__name__}: {exc}")

    return {
        "candidates": candidates,
        "terminated_model_ids": terminated_model_ids,
        "already_exited_model_ids": already_exited_model_ids,
        "missing_pid_model_ids": missing_pid_model_ids,
        "failed_model_ids": failed_model_ids,
        "errors": errors,
    }

def run_models_local(
    items: list[GridRunItem],
    *,
    max_workers: int,
    queue_policy: QueuePolicy = "fifo",
    sync_before_run: bool = True,
    default_options: DefaultsOptions | None = None,
    config: MesaConfig | None = None,
    allow_unknown_options: bool = False,
    command_name: str = "rn",
    log_file_name: str = "log.out",
    capture_output: bool = True,
    timeout: float | None = None,
    tracker: Tracker | None = None,
    stop_event: threading.Event | None = None,
    running_processes: dict[str, tuple[GridRunItem, RunHandle, subprocess.Popen]] | None = None,
    running_lock: threading.Lock | None = None
    ) -> GridRunResult:
    """Run many models locally with limit on parallel runs.

    Uses launch_model + wait_for_model so model lifecycle and
    observer behaviour remains aligned with single-model runs.

    Args:
        items: list of GridRunItem objects containing the models to run.
        queue_policy: QueyePolicy type. Currently only 'fifo' (= First In, First Out) available.
        max_workers: Maximum number of models to run in parallel.
            WARNING: make sure that OMP_NUM_THREADS x max_workers does not exceed
            your machine's number of available threads.
        sync_before_run: If True (default), the function calls work_setup.sync_model_with_disk
            to update the inlist attributes of Model in case the user made any changes to
            the inlist files themselves. This ensures that the inlist files themselves remain
            the ground truth.
        default_options: DefaultOptions object. Should be passed if sync_before_run == True.
        config: MesaConfig object. Will be reconstructed on the fly 
            if not passed.
        allow_unknown_options: If True, give a warning about inlist options that are not found in the defaults
            files when syncing Model.inlists with inlists in the model directory. If False, raise an exception 
            when inlist options are found that are not found in the defaults files.
        command_name: Name of the "rn" script. Can be used for restarts by specifying "re"
            or can be used for custom-named "rn" scripts.
        capture_output: If True, capture stdout/stderr and include them in RunResult.
            If False, wait without collecting output (stdout/stderr in result are empty strings).
        timeout: Maximum time in seconds to wait before aborting.
            If exceeded, the process is killed and RunTimeoutError is raised.
        tracker: Optional Tracker object for in-memory information through
            tracker.live_tracker and StateTransitions via the tracker.observer
    Returns:
        GridRunResult
    """

    if max_workers < 1:
        raise ValueError("max_workers must be >= 1")
    if queue_policy != "fifo":
        raise ValueError(f"Unsupported queue_policy: {queue_policy}")

    t0 = time.perf_counter()
    pending = deque(items)
    running: list[tuple[GridRunItem, RunHandle, subprocess.Popen, float]] = []
    results: list[RunResult] = []

    observer = tracker.observer if tracker is not None else None
    db_stop_requested = False
    db_stop_reason: str | None = None
    last_db_check = 0.0
    db_check_interval_seconds = 0.2

    _prepare_tracker_for_grid(tracker, timeout)

    try:
        while pending or running:
            stop_by_event = stop_event is not None and stop_event.is_set()
            db_stop_requested, db_stop_reason, last_db_check = _poll_repo_stop_request(
                tracker=tracker,
                timeout=timeout,
                last_db_check=last_db_check,
                db_check_interval_seconds=db_check_interval_seconds,
                cached_stop_requested=db_stop_requested,
                cached_stop_reason=db_stop_reason,
            )
            stop_by_db = db_stop_requested

            if stop_by_db and stop_event is not None:
                stop_event.set()

            stop_requested = stop_by_event or stop_by_db
            stop_reason = db_stop_reason or "Cancelled by grid stop request"
            restart_triggered = _should_mark_restart(stop_reason)

            while pending and len(running) < max_workers:
                if stop_requested:
                    break
                item = pending.popleft()
                try:
                    handle, process = launch_model(
                        model=item.model,
                        env=item.env,
                        sync_before_run=sync_before_run,
                        default_options=default_options,
                        config=config,
                        allow_unknown_options=allow_unknown_options,
                        command_name=command_name,
                        log_file_name=log_file_name,
                        tracker=tracker
                    )
                    running.append((item, handle, process, time.monotonic()))
                    if running_processes is not None and running_lock is not None:
                        with running_lock:
                            running_processes[handle.run_id] = (item, handle, process)
                except Exception as exc:
                    result = _exception_result(
                        item,
                        exc,
                        backend="local",
                        command_name=command_name,
                        sync_before_run=sync_before_run,
                    )
                    results.append(result)
                    if observer is not None:
                        observer.on_process_finished(result)

            if stop_requested:
                _cancel_pending_items(
                    pending,
                    results=results,
                    backend="local",
                    command_name=command_name,
                    sync_before_run=sync_before_run,
                    stop_reason=stop_reason,
                    observer=observer,
                    restart_triggered=restart_triggered,
                )

                for idx in range(len(running) - 1, -1, -1):
                    item, handle, process, _ = running[idx]
                    result = _cancel_running_item(
                        item=item,
                        handle=handle,
                        process=process,
                        backend="local",
                        command_name=command_name,
                        sync_before_run=sync_before_run,
                        capture_output=capture_output,
                        tracker=tracker,
                        observer=observer,
                        stop_reason=stop_reason,
                        restart_triggered=restart_triggered,
                    )

                    results.append(result)
                    running.pop(idx)
                    if running_processes is not None and running_lock is not None:
                        with running_lock:
                            running_processes.pop(handle.run_id, None)

                continue

            if not running:
                continue

            progressed = False
            now = time.monotonic()

            for idx in range(len(running) - 1, -1, -1):
                item, handle, process, launched_at = running[idx]

                timed_out = (
                    timeout is not None
                    and tracker is None
                    and process.poll() is None
                    and (now - launched_at) >= timeout
                )

                if timed_out:
                    result = _collect_run_result(
                        item=item,
                        handle=handle,
                        process=process,
                        timeout=0.0,
                        capture_output=capture_output,
                        tracker=tracker,
                        backend="local",
                        command_name=command_name,
                        sync_before_run=sync_before_run,
                        observer=observer,
                        return_code_on_error=124,
                    )

                    results.append(result)
                    running.pop(idx)
                    if running_processes is not None and running_lock is not None:
                        with running_lock:
                            running_processes.pop(handle.run_id, None)
                    progressed = True
                    continue

                if process.poll() is None:
                    continue

                result = _collect_run_result(
                    item=item,
                    handle=handle,
                    process=process,
                    timeout=None,
                    capture_output=capture_output,
                    tracker=tracker,
                    backend="local",
                    command_name=command_name,
                    sync_before_run=sync_before_run,
                    observer=observer,
                )

                results.append(result)
                running.pop(idx)
                if running_processes is not None and running_lock is not None:
                    with running_lock:
                        running_processes.pop(handle.run_id, None)
                progressed = True

            if not progressed:
                time.sleep(0.1)
    finally:
        _cleanup_tracker_after_grid(tracker)

    return _summarize(
        results=results,
        total=len(items),
        backend="local",
        duration_seconds=time.perf_counter() - t0,
    )

def run_models_mpi(
    items: list[GridRunItem],
    *,
    queue_policy: QueuePolicy = "fifo",
    sync_before_run: bool = True,
    default_options: DefaultsOptions | None = None,
    config: MesaConfig | None = None,
    allow_unknown_options: bool = False,
    command_name: str = "rn",
    log_file_name: str = "log.out",
    capture_output: bool = True,
    timeout: float | None = None,
    tracker: Tracker | None = None,
    ) -> GridRunResult:
    """Run many models distributed across MPI ranks.

    Work distribution is simple round-robin by rank for predictability.

    Should be run as `mpirun -n <<MAX_WORKERS>> python mr_script.py` or 
    `srun -n <<MAX_WORKERS>> python mr_script.py`, where <<MAX_WORKERS>>
    is an integer number equivalent to `max_workers` in run_models_local.

    Args:
        items: list of GridRunItem objects containing the models to run.
        queue_policy: QueyePolicy type. Currently only 'fifo' (=First In, First Out) available.
        sync_before_run: If True (default), the function calls work_setup.sync_model_with_disk
            to update the inlist attributes of Model in case the user made any changes to
            the inlist files themselves. This ensures that the inlist files themselves remain
            the ground truth.
        default_options: DefaultOptions object. Should be passed if sync_before_run == True.
        config: MesaConfig object. Will be reconstructed on the fly 
            if not passed.
        allow_unknown_options: If True, give a warning about inlist options that are not found in the defaults
            files when syncing Model.inlists with inlists in the model directory. If False, raise an exception 
            when inlist options are found that are not found in the defaults files.
        command_name: Name of the "rn" script. Can be used for restarts by specifying "re"
            or can be used for custom-named "rn" scripts.
        capture_output: If True, capture stdout/stderr and include them in RunResult.
            If False, wait without collecting output (stdout/stderr in result are empty strings).
        timeout: Maximum time in seconds to wait before aborting.
            If exceeded, the process is killed and RunTimeoutError is raised.
        tracker: Optional Tracker object for in-memory information through
            tracker.live_tracker and StateTransitions via the tracker.observer
    Returns:
        GridRunResult
    """
    if queue_policy != "fifo":
        raise ValueError(f"Unsupported queue_policy: {queue_policy}")

    try:
        from mpi4py import MPI  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "run_models_mpi requires mpi4py. Install it or use backend='local'."
        ) from exc

    t0 = time.perf_counter()
    comm = MPI.COMM_WORLD
    rank = comm.Get_rank()
    size = comm.Get_size()

    if tracker is not None and rank == 0:
        _prepare_tracker_for_grid(tracker, timeout)

    local_items = deque(items[rank::size])
    local_results: list[RunResult] = []
    observer = tracker.observer if tracker is not None else None

    db_stop_requested = False
    db_stop_reason: str | None = None
    last_db_check = 0.0
    db_check_interval_seconds = 0.2
    stop_requested = False

    while local_items:
        db_stop_requested, db_stop_reason, last_db_check = _poll_repo_stop_request(
            tracker=tracker,
            timeout=timeout,
            last_db_check=last_db_check,
            db_check_interval_seconds=db_check_interval_seconds,
            cached_stop_requested=db_stop_requested,
            cached_stop_reason=db_stop_reason,
        )

        if db_stop_requested:
            stop_requested = True
            stop_reason = db_stop_reason or "Cancelled by grid stop request"
            restart_triggered = _should_mark_restart(stop_reason)
            _cancel_pending_items(
                local_items,
                results=local_results,
                backend="mpi",
                command_name=command_name,
                sync_before_run=sync_before_run,
                stop_reason=stop_reason,
                observer=observer,
                restart_triggered=restart_triggered,
            )
            break

        item = local_items.popleft()

        try:
            handle, process = launch_model(
                model=item.model,
                env=item.env,
                sync_before_run=sync_before_run,
                default_options=default_options,
                config=config,
                allow_unknown_options=allow_unknown_options,
                command_name=command_name,
                log_file_name=log_file_name,
                tracker=tracker
            )
        except Exception as exc:
            result = _exception_result(
                item,
                exc,
                backend="mpi",
                command_name=command_name,
                sync_before_run=sync_before_run,
            )
            local_results.append(result)
            if observer is not None:
                observer.on_process_finished(result)
            continue

        launched_at = time.monotonic()

        while True:
            if process.poll() is not None:
                result = _collect_run_result(
                    item=item,
                    handle=handle,
                    process=process,
                    timeout=None,
                    capture_output=capture_output,
                    tracker=tracker,
                    backend="mpi",
                    command_name=command_name,
                    sync_before_run=sync_before_run,
                    observer=observer,
                )
                local_results.append(result)
                break

            db_stop_requested, db_stop_reason, last_db_check = _poll_repo_stop_request(
                tracker=tracker,
                timeout=timeout,
                last_db_check=last_db_check,
                db_check_interval_seconds=db_check_interval_seconds,
                cached_stop_requested=db_stop_requested,
                cached_stop_reason=db_stop_reason,
            )

            if db_stop_requested:
                stop_requested = True
                stop_reason = db_stop_reason or "Cancelled by grid stop request"
                restart_triggered = _should_mark_restart(stop_reason)
                result = _cancel_running_item(
                    item=item,
                    handle=handle,
                    process=process,
                    backend="mpi",
                    command_name=command_name,
                    sync_before_run=sync_before_run,
                    capture_output=capture_output,
                    tracker=tracker,
                    observer=observer,
                    stop_reason=stop_reason,
                    restart_triggered=restart_triggered,
                )

                local_results.append(result)
                break

            if tracker is None and timeout is not None and (time.monotonic() - launched_at) >= timeout:
                result = _collect_run_result(
                    item=item,
                    handle=handle,
                    process=process,
                    timeout=0.0,
                    capture_output=capture_output,
                    tracker=tracker,
                    backend="mpi",
                    command_name=command_name,
                    sync_before_run=sync_before_run,
                    observer=observer,
                    return_code_on_error=124,
                )

                local_results.append(result)
                break

            time.sleep(0.1)

        if stop_requested:
            stop_reason = db_stop_reason or "Cancelled by grid stop request"
            restart_triggered = _should_mark_restart(stop_reason)
            _cancel_pending_items(
                local_items,
                results=local_results,
                backend="mpi",
                command_name=command_name,
                sync_before_run=sync_before_run,
                stop_reason=stop_reason,
                observer=observer,
                restart_triggered=restart_triggered,
            )
            break

    gathered = comm.gather(local_results, root=0)

    if rank != 0:
        return GridRunResult(
            total=0,
            completed=0,
            failed=0,
            cancelled=0,
            results=[],
            backend="mpi",
            duration_seconds=time.perf_counter() - t0,
        )

    try:
        flat_results: list[RunResult] = []
        for chunk in gathered:
            flat_results.extend(chunk)
        return _summarize(
            results=flat_results,
            total=len(items),
            backend="mpi",
            duration_seconds=time.perf_counter() - t0,
        )
    finally:
        _cleanup_tracker_after_grid(tracker)


def run_grid(
    items: Iterable[GridRunItem],
    *,
    backend: GridBackend = "local",
    max_workers: int = 1,
    queue_policy: QueuePolicy = "fifo",
    sync_before_run: bool = True,
    default_options: DefaultsOptions | None = None,
    config: MesaConfig | None = None,
    allow_unknown_options: bool = False,
    command_name: str = "rn",
    log_file_name: str = "log.out",
    capture_output: bool = True,
    timeout: float | None = None,
    tracker: Tracker | None = None,
    resume_policy: ResumePolicy | None = None,
    ) -> GridRunResult:
    """Run a grid of models with local workers or MPI.

    Dispatches to run_models_local or run_models_mpi based on backend.

    Args:
        items: GridRunItem values for models to run.
        backend: local for subprocess-based execution, mpi for mpi4py execution.
        max_workers: Maximum parallel workers for local backend.
        queue_policy: Queue policy (currently fifo only).
        sync_before_run: Sync model inlists from disk before each launch.
        default_options: Parsed defaults used during sync_before_run.
        config: MesaConfig object.
        allow_unknown_options: Whether unknown inlist options are tolerated during sync.
        command_name: Run script name, typically rn or re.
        log_file_name: Log-file name written by run scripts.
        capture_output: Whether to capture stdout/stderr in results.
        timeout: Optional timeout in seconds.
        tracker: Optional persistence/live-status tracker.
        resume_policy: Optional repository-based resume policy.

    Returns:
        GridRunResult with per-model results and aggregate counts.
    """
    item_list = list(items)

    if resume_policy is not None and resume_policy.enabled:
        if tracker is None:
            raise ValueError("resume_policy requires tracker to be provided.")
        item_list, _ = _reconcile_items_with_repository(item_list, tracker, resume_policy)

    if len(item_list) == 0:
        return GridRunResult(
            total=0,
            completed=0,
            failed=0,
            cancelled=0,
            results=[],
            backend=backend,
            duration_seconds=0.0,
        )

    if backend == "local":
        return run_models_local(
            item_list,
            max_workers=max_workers,
            queue_policy=queue_policy,
            sync_before_run=sync_before_run,
            default_options=default_options,
            config=config,
            allow_unknown_options=allow_unknown_options,
            command_name=command_name,
            log_file_name=log_file_name,
            capture_output=capture_output,
            timeout=timeout,
            tracker=tracker
        )

    if backend == "mpi":
        return run_models_mpi(
            item_list,
            queue_policy=queue_policy,
            sync_before_run=sync_before_run,
            default_options=default_options,
            config=config,
            allow_unknown_options=allow_unknown_options,
            command_name=command_name,
            log_file_name=log_file_name,
            capture_output=capture_output,
            timeout=timeout,
            tracker=tracker
        )

    raise ValueError(f"Unsupported backend: {backend}")

def launch_grid(
    items: Iterable[GridRunItem],
    *,
    backend: GridBackend = "local",
    max_workers: int = 1,
    queue_policy: QueuePolicy = "fifo",
    sync_before_run: bool = True,
    default_options: DefaultsOptions | None = None,
    config: MesaConfig | None = None,
    allow_unknown_options: bool = False,
    command_name: str = "rn",
    log_file_name: str = "log.out",
    capture_output: bool = True,
    timeout: float | None = None,
    tracker: Tracker | None = None,
    resume_policy: ResumePolicy | None = None
    ) -> GridRunHandle:
    """Launch a grid run in the background and return immediately."""
    item_list = list(items)

    if resume_policy is not None and resume_policy.enabled:
        if tracker is None:
            raise ValueError("resume_policy requires tracker to be provided.")
        item_list, _ = _reconcile_items_with_repository(item_list, tracker, resume_policy)

    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mesa-grid")
    stop_event = threading.Event()
    running_processes: dict[str, tuple[GridRunItem, RunHandle, subprocess.Popen]] = {}
    running_lock = threading.Lock()

    if backend == "local":
        future = executor.submit(
            run_models_local,
            item_list,
            max_workers=max_workers,
            queue_policy=queue_policy,
            sync_before_run=sync_before_run,
            default_options=default_options,
            config=config,
            allow_unknown_options=allow_unknown_options,
            command_name=command_name,
            log_file_name=log_file_name,
            capture_output=capture_output,
            timeout=timeout,
            tracker=tracker,
            stop_event=stop_event,
            running_processes=running_processes,
            running_lock=running_lock
        )
    else:
        future = executor.submit(
            run_grid,
            item_list,
            backend=backend,
            max_workers=max_workers,
            queue_policy=queue_policy,
            sync_before_run=sync_before_run,
            default_options=default_options,
            config=config,
            allow_unknown_options=allow_unknown_options,
            command_name=command_name,
            log_file_name=log_file_name,
            capture_output=capture_output,
            timeout=timeout,
            tracker=tracker,
            resume_policy=resume_policy
        )

    return GridRunHandle(
        grid_id=uuid.uuid4().hex,
        backend=backend,
        submitted_at=datetime.now(timezone.utc),
        future=future,
        _executor=executor,
        _stop_event=stop_event,
        _running_processes=running_processes,
        _running_lock=running_lock,
        _tracker=tracker
    )


def wait_for_grid(
    handle: GridRunHandle,
    *,
    timeout: float | None = None,
    shutdown_executor: bool = True,
    ) -> GridRunResult:
    """Wait for a launched grid run to complete and return its result."""
    try:
        result = handle.future.result(timeout=timeout)
        return result
    except FutureTimeoutError as exc:
        raise TimeoutError(
            f"Grid run {handle.grid_id} did not finish within {timeout} seconds."
        ) from exc
    finally:
        if shutdown_executor and handle.future.done():
            handle._executor.shutdown(wait=False)

def stop_grid(
    handle: GridRunHandle | None = None,
    *,
    tracker: Tracker | None = None,
    force: bool = True,
    grace_seconds: float = 3.0,
    recover_from_dbfile: bool = True,
    restart: bool = False,
    ) -> dict[str, object]:
    """Stop a launched grid in live mode and/or repository recovery mode.

    Behavior:
        - If handle is provided, performs live-session cooperative cancellation.
        - If recover_from_dbfile=True and tracker is available, performs
          best-effort recovery cancellation using all active models in the DB.

    Note:
        In this project design, one DB file corresponds to one grid context, so
        repository recovery targets all active models in that DB.
    """
    if handle is None and tracker is None:
        raise ValueError("Provide at least one of: handle or tracker.")

    active_tracker = tracker if tracker is not None else (handle._tracker if handle is not None else None)

    stop_request_persisted = False
    if active_tracker is not None:
        reason = _RESTART_REQUEST_TAG if restart else "stop_grid called"
        active_tracker.repo.request_grid_stop(reason=reason)
        stop_request_persisted = True

    mode_parts: list[str] = []
    live_summary: dict[str, object] | None = None
    recovery_summary: dict[str, object] | None = None

    if handle is not None:
        mode_parts.append("live")
        handle._stop_event.set()
        cancelled_future = handle.future.cancel()
        handle._executor.shutdown(wait=False, cancel_futures=True)

        terminated_model_ids: list[str] = []
        termination_errors: list[str] = []

        with handle._running_lock:
            active_entries = list(handle._running_processes.values())

        for item, _, process in active_entries:
            try:
                terminate_run_process(process, force=force, grace_seconds=grace_seconds)
                terminated_model_ids.append(item.model.model_id)
            except Exception as exc:
                termination_errors.append(
                    f"{item.model.model_id}: {type(exc).__name__}: {exc}"
                )

        live_summary = {
            "grid_id": handle.grid_id,
            "future_cancelled": cancelled_future,
            "future_done": handle.future.done(),
            "terminated_model_ids": terminated_model_ids,
            "termination_errors": termination_errors,
        }
    if recover_from_dbfile and active_tracker is not None:
        mode_parts.append("recovery")
        skip_ids: set[str] = set()
        if live_summary is not None:
            for model_id in live_summary.get("terminated_model_ids", []):
                if isinstance(model_id, str):
                    skip_ids.add(model_id)
        recovery_summary = _stop_from_repository(
            tracker=active_tracker,
            force=force,
            grace_seconds=grace_seconds,
            skip_model_ids=skip_ids,
        )

    return {
        "requested": True,
        "mode": "+".join(mode_parts) if mode_parts else "none",
        "live": live_summary,
        "recovery": recovery_summary,
        "stop_request_persisted": stop_request_persisted,
        "restart": restart
    }