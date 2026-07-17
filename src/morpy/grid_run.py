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

import subprocess
import time
from collections import deque # double-ended queue --> for efficiency
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Literal, Mapping

from .config import MesaConfig
from .model import Model
from .options import DefaultsOptions
from .run import launch_model, run_model, wait_for_model
from .run_types import RunHandle, RunObserver, RunResult
from .repository import LiveProcessRegistry

QueuePolicy = Literal["fifo"] # First In, First Out
GridBackend = Literal["local", "mpi"]


@dataclass
class GridRunItem:
    """Object to be passed to grid run functions.
    Attributes:
        model: Model object
        env: Optional shell environment for this model.
            For example, this allows you to assign a different 
            number of threads to a specific model: 
            `GridRunItem(model=model_a, env={"OMP_NUM_THREADS": "2"})`
    """
    model: Model
    env: Mapping[str, str] | None = None


@dataclass
class GridRunResult:
    """Results of grid run function.
    Attributes:
        total: Total number of models in grid run.
        completed: Number of successfully completed model runs.
        failed: Number of failed model runs.
        results: List of run_types.RunResult objects for each model.
        backend: GridBackend used for this grid run: 'local' (subprocesses) 
            or 'mpi' (mpi4pi)
        duration: Duration of this grid run in seconds. 
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
    observer: RunObserver | None = None,
    live_tracker: LiveProcessRegistry | None = None,
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
        observer: RunObserver object that observes StateTransitions for status and repository admin.
        live_tracker: LiveProcessRegistry object that serves as an 
            in-memory registry for currently running models.
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

    while pending or running:
        while pending and len(running) < max_workers:
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
                    observer=observer,
                    live_tracker=live_tracker
                )
                running.append((item, handle, process, time.monotonic()))
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

        if not running:
            continue

        progressed = False
        now = time.monotonic()

        # Iterate backwards so we can pop safely by index.
        for idx in range(len(running) - 1, -1, -1):
            item, handle, process, launched_at = running[idx]

            # Hard per-model timeout from launch time in local grid mode.
            timed_out = (
                timeout is not None
                and process.poll() is None
                and (now - launched_at) >= timeout
            )

            if timed_out:
                try:
                    # timeout=0 forces immediate timeout path if still alive.
                    result = wait_for_model(
                        model=item.model,
                        handle=handle,
                        process=process,
                        timeout=0.0,
                        capture_output=capture_output,
                        observer=observer,
                        live_tracker=live_tracker
                    )
                except Exception as exc:
                    result = _exception_result(
                        item,
                        exc,
                        backend="local",
                        command_name=command_name,
                        sync_before_run=sync_before_run,
                        return_code=124,
                    )
                    if observer is not None:
                        observer.on_process_finished(result)

                results.append(result)
                running.pop(idx)
                progressed = True
                continue

            if process.poll() is None:
                continue

            try:
                result = wait_for_model(
                    model=item.model,
                    handle=handle,
                    process=process,
                    timeout=None,
                    capture_output=capture_output,
                    observer=observer,
                    live_tracker=live_tracker
                )
            except Exception as exc:
                result = _exception_result(
                    item,
                    exc,
                    backend="local",
                    command_name=command_name,
                    sync_before_run=sync_before_run,
                )
                if observer is not None:
                    observer.on_process_finished(result)

            results.append(result)
            running.pop(idx)
            progressed = True

        if not progressed:
            time.sleep(0.1)

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
    observer: RunObserver | None = None, 
    live_tracker: LiveProcessRegistry | None = None,
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
        observer: RunObserver object that observes StateTransitions for status and repository admin.
        live_tracker: LiveProcessRegistry object that serves as an 
            in-memory registry for currently running models.
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

    local_items = items[rank::size]
    local_results: list[RunResult] = []

    for item in local_items:
        try:
            result = run_model(
                model=item.model,
                env=item.env,
                sync_before_run=sync_before_run,
                default_options=default_options,
                config=config,
                allow_unknown_options=allow_unknown_options,
                command_name=command_name,
                log_file_name=log_file_name,
                capture_output=capture_output,
                timeout=timeout,
                observer=observer,
                live_tracker=live_tracker
            )
        except Exception as exc:
            result = _exception_result(
                item,
                exc,
                backend="mpi",
                command_name=command_name,
                sync_before_run=sync_before_run,
            )
            if observer is not None:
                observer.on_process_finished(result)
        local_results.append(result)

    gathered = comm.gather(local_results, root=0)

    if rank != 0:
        # Non-root returns an empty summary by design.
        return GridRunResult(
            total=0,
            completed=0,
            failed=0,
            cancelled=0,
            results=[],
            backend="mpi",
            duration_seconds=time.perf_counter() - t0,
        )

    flat_results: list[RunResult] = []
    for chunk in gathered:
        flat_results.extend(chunk)

    return _summarize(
        results=flat_results,
        total=len(items),
        backend="mpi",
        duration_seconds=time.perf_counter() - t0,
    )


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
    observer: RunObserver | None = None,
    live_tracker: LiveProcessRegistry | None = None,
) -> GridRunResult:
    """Run a grid of MESA models locally (using subroutines) or with MPI (using mpi4py).
     This fuction dispatches either the run_models_local or run_models_mpi functions.
     
     Args:
        items: list of GridRunItem objects containing the models to run.
        backend: "local" for concurrent.futures (default), "mpi" for mpi4py.
        queue_policy: QueyePolicy type. Currently only 'fifo' (=First In, First Out) available.
        max_workers: Maximun number of models to run in parallel. Only used when backend = "local".
            See run_models_mpi documentation for setting number of MPI workers.
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
        observer: RunObserver object that observes StateTransitions for status and repository admin.
        live_tracker: LiveProcessRegistry object that serves as an 
            in-memory registry for currently running models.
    Returns:
        GridRunResult

     """
    item_list = list(items)

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
            observer=observer,
            live_tracker=live_tracker
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
            observer=observer,
            live_tracker=live_tracker
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
    observer: RunObserver | None = None,
    live_tracker: LiveProcessRegistry | None = None,
) -> GridRunHandle:
    """Launch a grid run in the background and return immediately."""
    item_list = list(items)

    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mesa-grid")
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
        observer=observer,
        live_tracker=live_tracker,
    )

    return GridRunHandle(
        grid_id=uuid.uuid4().hex,
        backend=backend,
        submitted_at=datetime.now(timezone.utc),
        future=future,
        _executor=executor,
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
    handle: GridRunHandle,
    *,
    live_tracker: LiveProcessRegistry | None = None,
    force: bool = True,
) -> dict[str, object]:
    """Function to stop a grid that was launched by the launch_grid() function.
        Will attempt to kill the executor, cancel the grid future and hunt down
        and kill the MESA processes registered in the live tracker. 
    """
    cancelled_future = handle.future.cancel()

    # Prevent new tasks from starting in this executor.
    handle._executor.shutdown(wait=False, cancel_futures=True)

    terminated_model_ids: list[str] = []
    if live_tracker is not None:
        for model_id in live_tracker.list_running_model_ids():
            if live_tracker.terminate(model_id, force=force):
                terminated_model_ids.append(model_id)

    return {
        "grid_id": handle.grid_id,
        "future_cancelled": cancelled_future,
        "future_done": handle.future.done(),
        "terminated_model_ids": terminated_model_ids,
    }