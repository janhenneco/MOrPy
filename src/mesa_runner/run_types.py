"""Shared runtime data types for model execution workflows.

This module contains lightweight, dependency-safe contracts shared across
run, grid orchestration, persistence, and status layers.

- RunHandle for launched-process tracking.
- RunResult for terminal run outcomes.
- StateTransition for lifecycle event records.
- RunObserver protocol for event subscribers.
"""

from dataclasses import dataclass, field
from typing import Literal
from typing import Protocol
from datetime import datetime
from pathlib import Path

# Terminal state label for a model run.
# Semantics:
# - "completed": run finished successfully.
# - "failed": run finished with an error or non-zero return code.
# - "cancelled": run was stopped intentionally (for example user interruption).
RunTerminalState = Literal["completed", "failed", "cancelled"]


@dataclass
class RunResult:
    """Contains the results of a completed MESA model run.

    Attributes:
        success: True if the run completed successfully.
        terminal_state: Terminal outcome label for the run.
        return_code: Process return code from the run command.
        duration_seconds: Elapsed runtime in seconds.
        model_id: Stable model identifier.
        model_name: Human-readable model name.
        model_path: Path to the model work directory used for this run.
        command: Command argv used to launch the run.
        cwd: Working directory for process execution.
        start_time: UTC timestamp when execution started.
        end_time: UTC timestamp when execution ended.
        stdout: Captured standard output.
        stderr: Captured standard error.
        sync_performed: Whether a pre-run disk-to-memory inlist sync was performed.
        metadata: Optional extra key-value metadata (for example run_id, pid, backend tags).
        """
    success: bool
    terminal_state: RunTerminalState
    return_code: int
    duration_seconds: float
    model_id: str
    model_name: str
    model_path: Path
    command: list[str]
    cwd: Path
    start_time: datetime
    end_time: datetime
    stdout: str
    stderr: str
    sync_performed: bool
    metadata: dict[str, str] = field(default_factory=dict)

@dataclass
class RunHandle:
    """Contains tracking information for a launched MESA model run.

    Attributes:
        run_id: Unique identifier for this run instance.
        model_id: Stable model identifier.
        model_name: Human-readable model name.
        model_path: Path to the model work directory used for this run.
        command: Command argv used to launch the run.
        cwd: Working directory for process execution.
        start_time: UTC timestamp when execution started.
        pid: Operating-system process ID of the launched run.
        log_file_name: Name of the terminal log file.
        sync_performed: True if sync of inlist was performed with disk
    """
    run_id: str
    model_id: str
    model_name: str
    model_path: Path
    command: list[str]
    cwd: Path
    start_time: datetime
    pid: int
    log_file_name: str
    sync_performed: bool

@dataclass
class StateTransition:
    """Contains the payload for a model lifecycle state transition event.

    Attributes:
        model_id: Stable model identifier for the model whose state changed.
        from_state: Previous lifecycle state label.
        to_state: New lifecycle state label.
        at: UTC timestamp when the transition occurred.
        reason: Optional human-readable reason for the transition.
        run_id: Optional run identifier associated with this transition.
        metadata: Optional extra key-value metadata for persistence, logging, or status systems.
    """
    model_id: str
    from_state: str
    to_state: str
    at: datetime
    reason: str | None = None
    run_id: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)

class RunObserver(Protocol):
    """Observer interface for model run lifecycle events.

    Methods:
        on_state_transition: Called whenever a model state changes.
        on_process_started: Called after a run process is successfully launched.
        on_process_finished: Called when a run reaches a terminal result.
    """
    def on_state_transition(self, transition: StateTransition) -> None:
        """Handle a model state transition event."""
        ...

    def on_process_started(self, handle: RunHandle) -> None:
        """Handle notification that a run process has started."""
        ...

    def on_process_finished(self, result: RunResult) -> None:
        """Handle notification that a run process has finished."""
        ...