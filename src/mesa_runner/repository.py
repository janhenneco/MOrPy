"""Persistence abstraction and adapter hooks for run metadata.

This module defines the RunRepository protocol used to store run lifecycle
events and results, plus RepositoryObserver, which adapts run events to
repository writes.

It keeps storage concerns decoupled from run orchestration logic.
"""

from typing import Protocol
from .run_types import RunResult, RunHandle, StateTransition

class RunRepository(Protocol):
    def upsert_model(self, model) -> None: ...
    def record_state_transition(self, transition: StateTransition) -> None: ...
    def record_run_started(self, handle: RunHandle) -> None: ...
    def record_run_finished(self, result: RunResult) -> None: ...
    def list_recent_runs(self, *, limit: int = 100) -> list[RunResult]: ...
    def get_model_run_history(self, model_id: str) -> list[RunResult]: ...

# observer adapter for persistence
class RepositoryObserver:
    def __init__(self, repo: RunRepository) -> None:
        self.repo = repo

    def on_state_transition(self, transition: StateTransition) -> None:
        self.repo.record_state_transition(transition)

    def on_process_started(self, handle: RunHandle) -> None:
        self.repo.record_run_started(handle)

    def on_process_finished(self, result: RunResult) -> None:
        self.repo.record_run_finished(result)