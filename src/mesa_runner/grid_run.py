"""Grid orchestration contracts for multi-model execution.

This module defines input/output data structures and execution contracts
for running multiple models with a local backend (and later an MPI backend).

Grid orchestration should delegate per-model execution to run.py so lifecycle
behavior remains consistent between single and batch workflows.
"""

from dataclasses import dataclass
from typing import Mapping, Literal
from .run_types import RunResult, RunObserver

@dataclass
class GridRunItem:
    model: object
    env: Mapping[str, str] | None = None

@dataclass
class GridRunResult:
    total: int
    completed: int
    failed: int
    cancelled: int
    results: list[RunResult]

def run_models_local(
    items: list[GridRunItem],
    *,
    max_workers: int,
    queue_policy: Literal["fifo"] = "fifo",
    sync_before_run: bool = True,
    default_options=None,
    config=None,
    allow_unknown_options: bool = False,
    observer: RunObserver | None = None,
) -> GridRunResult:
    """Local parallel execution. Must delegate per-item execution to run_model."""
    ...