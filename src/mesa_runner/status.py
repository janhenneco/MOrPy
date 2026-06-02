"""Status view contracts for live and persisted model execution state.

This module defines status-oriented read models and query contracts for
reporting current and recent run state, combining repository data with
optional live process tracking.
"""

from dataclasses import dataclass
from datetime import datetime

@dataclass
class ModelStatusView:
    model_id: str
    model_name: str
    state: str
    started_at: datetime | None
    updated_at: datetime | None
    finished_at: datetime | None
    run_id: str | None
    pid: int | None
    return_code: int | None

def get_model_status(model_id: str, repo: RunRepository, *, live_registry=None) -> ModelStatusView:
    ...

def list_active_status(repo: RunRepository, *, live_registry=None) -> list[ModelStatusView]:
    ...