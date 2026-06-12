"""Single-model run orchestration for foreground and background execution.

This module provides:

- launch_model_process for non-blocking process launch.
- wait_for_model_process for completion and result finalization.
- run_model as the blocking convenience wrapper.

It performs preflight checks, optional model/inlist sync, lifecycle state
updates, timeout handling, and observer event emission.
"""

import os
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from .errors import (
    ExecutableMissingError,
    ModelPathMissingError,
    RunLaunchError,
    RunScriptMissingError,
    RunTimeoutError,
)
from .model import Model, ModelState
from .run_types import RunHandle, RunObserver, RunResult, StateTransition
from .work_setup import sync_model_with_disk, WorkdirMode, detect_workdir_mode
from .options import DefaultsOptions
from .config import MesaConfig
from .repository import LiveProcessRegistry

def _set_model_state(
    model: Model,
    new_state: ModelState,
    *,
    reason: str | None = None,
    run_id: str | None = None
) -> StateTransition:
    """Private method to change the state of a Model object.

    Args:
        model: Model object to change the ModelState of.
        new_state: Desired new ModelState for the given Model object.
        reason: Optional reason for state change passed on to the returned
            StateTransition object
        run_id: Identification number of the run associated with this model
    Returns:
        StateTransition
    """

    previous_state = model.state
    now = datetime.now(timezone.utc)

    model.state = new_state
    model.updated_at = now

    if new_state == ModelState.RUNNING and model.started_at is None:
        model.started_at = now

    if new_state in (
        ModelState.COMPLETED,
        ModelState.FAILED,
        ModelState.CANCELLED,
    ):
        model.finished_at = now

    return StateTransition(
        model_id=model.model_id,
        from_state=previous_state.value,
        to_state=new_state.value,
        at=now,
        reason=reason,
        run_id=run_id,
    )


def _resolve_model_dir(model: Model) -> Path:
    """Private helper function to resolve model directory associated with Model object."""
    if model.model_path is None:
        raise ModelPathMissingError(
            f"Model '{model.name}' has no model_path. "
            "Create a model directory first with create_modeldir()."
        )
    model_dir = Path(model.model_path)
    if not model_dir.is_dir():
        raise ModelPathMissingError(f"Model directory does not exist: {model_dir}")
    return model_dir


def _resolve_run_script(model_dir: Path, command_name: str) -> Path:
    """Private helper function to locate rn script in the model directory."""
    script = model_dir / command_name
    if not script.is_file():
        raise RunScriptMissingError(
            f"Run script '{command_name}' not found in model directory: {script}"
        )
    return script


def _resolve_executable(model_dir: Path, mode: WorkdirMode) -> Path:
    '''Private helper to locate symlink to Fortran executable and check consistency with WorkdirMode.'''
    star = model_dir / "star"
    binary = model_dir / "binary"

    if star.exists() and binary.exists():
        if mode == 'star':
            return star
        elif mode == 'binary':
            return binary
    if star.exists():
        if mode == 'star':
            return star
        else:
            raise ExecutableMissingError(f"'star' executable found but WorkdirMode is not 'star' for model directory: {model_dir}")
    if binary.exists():
        if mode == 'binary':
            return binary
        else:
            raise ExecutableMissingError(f"'binary' executable found but WorkdirMode is not 'binary' for model directory: {model_dir}")
    raise ExecutableMissingError(
        f"Neither 'star' nor 'binary' executable found in model directory: {model_dir}")


def _emit_transition(
    model: Model,
    new_state: ModelState,
    *,
    observer: RunObserver | None,
    reason: str | None = None,
    run_id: str | None = None
) -> StateTransition:
    """Private wrapper around _set_model_state that notifies the observer."""
    transition = _set_model_state(model, new_state, reason=reason, run_id=run_id)
    if observer is not None:
        observer.on_state_transition(transition)
    return transition

def launch_model_process(
    model: Model,
    *,
    env: Mapping[str, str] | None = None,
    sync_before_run: bool = True,
    default_options: DefaultsOptions | None = None,
    config: MesaConfig  | None = None,
    allow_unknown_options: bool = False,
    command_name: str = "rn",
    log_file_name: str = "log.out",
    observer: RunObserver | None = None,
    live_registry: LiveProcessRegistry | None = None,
) -> tuple[RunHandle, subprocess.Popen]:
    """Function to launch a single model in a non-blocking way. 
        The function performs preflight checks, starts the MESA model run and
        immediately returns with the RunHandle and process ID for tracking.
        Use this if you want to run a MESA model "in the background".
    
    Args:
        model: Model to launch.
        env: Optional runtime environment to launch the MESA model into.
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
        log_file_name: Name of the terminal log file that will be placed inside the model directory.
            Default is "log.out"
        observer: RunObserver object that observes StateTransitions for status and repository admin.
    Returns:
        Tuple containing RunHandle and subprocess ID.
    Raises:
        ValueError: If sync_before_run is True and no DefaultsOptions object is passed
        RunLaunchError: If model failed to launch
    """

    model_dir = _resolve_model_dir(model)
    script_path = _resolve_run_script(model_dir, command_name)
    mode = detect_workdir_mode(model)
    _resolve_executable(model_dir, mode)

    _emit_transition(model, ModelState.PREPARING, observer=observer)

    if sync_before_run:
        if default_options is None:
            raise ValueError(
                "default_options is required when sync_before_run=True "
                "because sync_model_with_disk needs it."
            )
        sync_model_with_disk(
            model=model,
            default_options=default_options,
            config=config,
            allow_unknown_options=allow_unknown_options,
        )

    run_id = uuid.uuid4().hex
    merged_env = os.environ.copy()
    if env is not None:
        merged_env.update(env)

    log_path = model_dir / log_file_name
    log_file = log_path.open("w", encoding="utf-8", buffering=1)

    try:
        process = subprocess.Popen(
            [str(script_path)],
            cwd=model_dir,
            env=merged_env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except OSError as exc:
        _emit_transition(
            model,
            ModelState.FAILED,
            observer=observer,
            reason=f"Launch error: {exc}",
            run_id=run_id,
        )
        raise RunLaunchError(f"Failed to launch run command '{script_path}': {exc}") from exc
    else:
        log_file.close()

    handle = RunHandle(
        run_id=run_id,
        model_id=model.model_id,
        model_name=model.name,
        model_path=model_dir,
        command=[str(script_path)],
        cwd=model_dir,
        start_time=datetime.now(timezone.utc),
        pid=process.pid,
        log_file_name=log_file_name,
        sync_performed=sync_before_run
    )

    _emit_transition(model, ModelState.RUNNING, observer=observer, run_id=run_id)

    if observer is not None:
        observer.on_process_started(handle)
    
    if live_registry is not None:
        live_registry.register(handle, process)

    return handle, process

def wait_for_model_process(
    model: Model,
    handle: RunHandle,
    process: subprocess.Popen,
    *,
    timeout: float | None = None,
    capture_output: bool = True,
    observer: RunObserver | None = None,
    live_registry: LiveProcessRegistry | None = None,
) -> RunResult:
    """Wait for a launched model process to finish and return its final run result.

    This function is the completion step of the non-blocking workflow:

    1. launch_model_process() starts the run and returns immediately
       with (RunHandle, process).
    2. wait_for_model_process() blocks until that process exits
       (or times out), finalizes model state, and builds a RunResult.

    Behavior:
        - Waits for process completion.
        - Optionally captures stdout/stderr.
        - Updates model state to COMPLETED, FAILED, or CANCELLED.
        - Emits observer callbacks for final state and finished result.
        - Returns a RunResult with return code, timing, output, and metadata.

    Args:
        model: Model associated with this run.
        handle: RunHandle returned by launch_model_process; contains run_id and launch metadata.
        process: Subprocess object returned by launch_model_process.
        timeout: Maximum time in seconds to wait before aborting.
            If exceeded, the process is killed and RunTimeoutError is raised.
        capture_output: If True, capture stdout/stderr and include them in RunResult.
            If False, wait without collecting output (stdout/stderr in result are empty strings).
        observer: Optional RunObserver receiving state-transition and process-finished events.

    Returns:
        RunResult describing the terminal outcome of the run.

    Raises:
        RunTimeoutError: If timeout is reached before process completion.
    """
    
    start_perf = time.perf_counter()

    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.wait()
        _emit_transition(
            model,
            ModelState.FAILED,
            observer=observer,
            reason=f"Timeout after {timeout}s",
            run_id=handle.run_id,
        )
        if live_registry is not None:
            live_registry.unregister(model.model_id)
        raise RunTimeoutError(
            f"Run timed out for model '{model.name}' after {timeout} seconds."
        ) from exc
    
    except KeyboardInterrupt:
        process.terminate()
        process.wait()
        _emit_transition(
            model,
            ModelState.CANCELLED,
            observer=observer,
            reason="Interrupted by user",
            run_id=handle.run_id,
        )
        end_time = datetime.now(timezone.utc)
        result = RunResult(
            success=False,
            terminal_state="cancelled",
            return_code=130,
            duration_seconds=time.perf_counter() - start_perf,
            model_id=model.model_id,
            model_name=model.name,
            model_path=handle.model_path,
            command=handle.command,
            cwd=handle.cwd,
            start_time=handle.start_time,
            end_time=end_time,
            stdout="",
            stderr="Interrupted by user",
            sync_performed=handle.sync_performed,
            metadata={"run_id": handle.run_id, "pid": str(handle.pid)},
        )
        if observer is not None:
            observer.on_process_finished(result)
        if live_registry is not None:
            live_registry.unregister(model.model_id)

        return result

    return_code = int(process.returncode or 0)
    end_time = datetime.now(timezone.utc)
    duration = time.perf_counter() - start_perf

    if return_code == 0:
        terminal_state = "completed"
        _emit_transition(model, ModelState.COMPLETED, observer=observer, run_id=handle.run_id)
    else:
        terminal_state = "failed"
        _emit_transition(
            model,
            ModelState.FAILED,
            observer=observer,
            reason=f"Non-zero return code: {return_code}",
            run_id=handle.run_id,
        )

    log_path = handle.model_path / handle.log_file_name
    if capture_output and log_path.exists():
        stdout = log_path.read_text(encoding="utf-8", errors="replace")
    else:
        stdout = ""
    stderr = ""

    result = RunResult(
        success=(return_code == 0),
        terminal_state=terminal_state,
        return_code=return_code,
        duration_seconds=duration,
        model_id=model.model_id,
        model_name=model.name,
        model_path=handle.model_path,
        command=handle.command,
        cwd=handle.cwd,
        start_time=handle.start_time,
        end_time=end_time,
        stdout=stdout,
        stderr=stderr,
        sync_performed=handle.sync_performed,
        metadata={"run_id": handle.run_id, "pid": str(handle.pid)},
    )

    if observer is not None:
        observer.on_process_finished(result)
    if live_registry is not None:
        live_registry.unregister(model.model_id)
    
    return result

def run_model(
    model: Model,
    *,
    env: Mapping[str, str] | None = None,
    sync_before_run: bool = True,
    default_options: DefaultsOptions | None = None,
    config: MesaConfig  | None = None,
    allow_unknown_options: bool = False,
    command_name: str = "rn",
    log_file_name: str = "log.out",
    capture_output: bool = True,
    timeout: float | None = None,
    observer: RunObserver | None = None,
    live_registry: LiveProcessRegistry | None = None,
) -> RunResult:
    
    """Function to launch a single model in a blocking way. 
        The function calls launch_model_process and 
        wait_for_model_process immediately afterwards.
        It will only return once the model has finished running.
        Use this to run a MESA model "on the foreground" as you
        would do with a regular MESA "./rn" call in the terminal.
    
    Args:
        model: Model to run.
        env: Optional runtime environment to launch the MESA model into.
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
    Returns:
        RunResult object containing information about the run after finishing.
    """
    handle, process = launch_model_process(
        model=model,
        env=env,
        sync_before_run=sync_before_run,
        default_options=default_options,
        config=config,
        allow_unknown_options=allow_unknown_options,
        command_name=command_name,
        log_file_name=log_file_name,
        observer=observer,
        live_registry=live_registry
    )

    result = wait_for_model_process(
        model=model,
        handle=handle,
        process=process,
        timeout=timeout,
        capture_output=capture_output,
        observer=observer, 
        live_registry=live_registry
    )

    return result
