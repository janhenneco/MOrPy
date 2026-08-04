"""SQLite-backed persistence and live-process registry for run metadata.

This module provides:

- RunRepository protocol: persistence API consumed by observers/status.
- SQLiteRunRepository: concrete SQLAlchemy + SQLite implementation.
- LiveProcessRegistry: in-memory registry for currently running subprocesses.
- RepositoryObserver: adapter that writes run events into the repository.

Persistence and live process tracking are intentionally separated:
the database stores durable history, while the live registry stores active
Popen handles that cannot be persisted meaningfully.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol
import threading

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from .run_types import RunHandle, RunResult, StateTransition


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _dump_json(value: object) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _load_json_dict(text: str | None) -> dict[str, str]:
    if not text:
        return {}
    loaded = json.loads(text)
    if isinstance(loaded, dict):
        return {str(k): str(v) for k, v in loaded.items()}
    return {}


def _load_json_list(text: str | None) -> list[str]:
    if not text:
        return []
    loaded = json.loads(text)
    if isinstance(loaded, list):
        return [str(v) for v in loaded]
    return []


def _ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)

class Base(DeclarativeBase):
    """Base class that is required for SQL database interaction."""
    pass


class ModelRow(Base):
    """SQL database row for one model."""
    __tablename__ = "models"

    model_id: Mapped[str] = mapped_column(String, primary_key=True)
    model_name: Mapped[str] = mapped_column(String, nullable=False)
    model_path: Mapped[str | None] = mapped_column(String, nullable=True)
    state: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    snapshot_taken_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    file_snapshot_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class RunRow(Base):
    """SQL database row for one run."""
    __tablename__ = "runs"

    run_id: Mapped[str] = mapped_column(String, primary_key=True)
    model_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    model_name: Mapped[str] = mapped_column(String, nullable=False)
    model_path: Mapped[str] = mapped_column(String, nullable=False)
    command_json: Mapped[str] = mapped_column(Text, nullable=False)
    cwd: Mapped[str] = mapped_column(String, nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    success: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    terminal_state: Mapped[str | None] = mapped_column(String, nullable=True)
    return_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    stdout: Mapped[str | None] = mapped_column(Text, nullable=True)
    stderr: Mapped[str | None] = mapped_column(Text, nullable=True)
    sync_performed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    log_file_name: Mapped[str | None] = mapped_column(String, nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class StateTransitionRow(Base):
    """SQL database row for one model state transition."""
    __tablename__ = "state_transitions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    run_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    from_state: Mapped[str] = mapped_column(String, nullable=False)
    to_state: Mapped[str] = mapped_column(String, nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)

class GridControlRow(Base):
    """Single-row control table for project-scoped grid stop requests."""
    __tablename__ = "grid_control"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stop_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class RunRepository(Protocol):
    def upsert_model(self, model) -> None: ...
    def record_state_transition(self, transition: StateTransition) -> None: ...
    def record_run_started(self, handle: RunHandle) -> None: ...
    def record_run_finished(self, result: RunResult) -> None: ...
    def list_recent_runs(self, *, limit: int = 100) -> list[RunResult]: ...
    def get_model_run_history(self, model_id: str) -> list[RunResult]: ...
    def get_model_row(self, model_id: str) -> ModelRow | None: ...
    def list_model_rows(self) -> list[ModelRow]: ...
    def get_latest_run(self, model_id: str) -> RunResult | None: ...
    def get_latest_transition(self, model_id: str) -> StateTransition | None: ...
    def ensure_grid_control_row(self) -> None: ...
    def request_grid_stop(self, *, reason: str | None = None) -> None: ...
    def clear_grid_stop_request(self) -> None: ...
    def is_grid_stop_requested(self) -> bool: ...


class SQLiteRunRepository:
    """SQLite-backed implementation of RunRepository using SQLAlchemy.
    
    Responsibilities:
        Create schema on first use.
        Upsert current model snapshot records.
        Append state transition events.
        Record run start and terminal run results.
        Rehydrate RunResult and StateTransition read models from rows.
    
    Notes:
        JSON-like fields are serialized to compact JSON text for SQLite storage.
        Timestamp columns are stored as timezone-aware datetimes.
        Writes are transaction-scoped using SessionLocal.begin().
    """
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.engine = create_engine(f"sqlite:///{self.db_path}", future=True)
        self.SessionLocal = sessionmaker(self.engine, expire_on_commit=False, class_=Session)
        Base.metadata.create_all(self.engine)

    def upsert_model(self, model) -> None:
        with self.SessionLocal.begin() as session:
            row = session.get(ModelRow, model.model_id)
            if row is None:
                row = ModelRow(model_id=model.model_id, model_name=model.name)
                session.add(row)

            row.model_name = model.name
            row.model_path = str(model.model_path) if model.model_path is not None else None
            row.state = model.state.value if getattr(model, "state", None) is not None else None
            row.created_at = getattr(model, "created_at", None)
            row.started_at = getattr(model, "started_at", None)
            row.updated_at = getattr(model, "updated_at", None)
            row.finished_at = getattr(model, "finished_at", None)
            row.snapshot_taken_at = getattr(model, "snapshot_taken_at", None)
            row.file_snapshot_json = _dump_json(getattr(model, "file_snapshot", {}))

    def add_models_to_repo(self, models) -> None:
        for item in models:
            self.upsert_model(item)

    def ensure_grid_control_row(self) -> None:
        with self.SessionLocal.begin() as session:
            row = session.get(GridControlRow, 1)
            if row is None:
                row = GridControlRow(
                    id=1,
                    stop_requested=False,
                    requested_at=None,
                    reason=None,
                )
                session.add(row)

    def request_grid_stop(self, *, reason: str | None = None) -> None:
        with self.SessionLocal.begin() as session:
            row = session.get(GridControlRow, 1)
            if row is None:
                row = GridControlRow(id=1)
                session.add(row)
            row.stop_requested = True
            row.requested_at = _utc_now()
            row.reason = reason

    def clear_grid_stop_request(self) -> None:
        with self.SessionLocal.begin() as session:
            row = session.get(GridControlRow, 1)
            if row is None:
                row = GridControlRow(id=1)
                session.add(row)
            row.stop_requested = False
            row.requested_at = None
            row.reason = None

    def is_grid_stop_requested(self) -> bool:
        with self.SessionLocal() as session:
            row = session.get(GridControlRow, 1)
            if row is None:
                return False
            return bool(row.stop_requested)

    def record_state_transition(self, transition: StateTransition) -> None:
        with self.SessionLocal.begin() as session:
            session.add(
                StateTransitionRow(
                    model_id=transition.model_id,
                    run_id=transition.run_id,
                    from_state=transition.from_state,
                    to_state=transition.to_state,
                    at=transition.at,
                    reason=transition.reason,
                    metadata_json=_dump_json(transition.metadata),
                )
            )

            row = session.get(ModelRow, transition.model_id)
            if row is None:
                row = ModelRow(
                    model_id=transition.model_id,
                    model_name=transition.model_id,
                )
                session.add(row)

            row.state = transition.to_state
            row.updated_at = transition.at
            if transition.to_state == "running" and row.started_at is None:
                row.started_at = transition.at
            if transition.to_state in {"completed", "failed", "cancelled"}:
                row.finished_at = transition.at

    def record_run_started(self, handle: RunHandle) -> None:
        with self.SessionLocal.begin() as session:
            row = session.get(RunRow, handle.run_id)
            if row is None:
                row = RunRow(
                    run_id=handle.run_id,
                    model_id=handle.model_id,
                    model_name=handle.model_name,
                    model_path=str(handle.model_path),
                    command_json=_dump_json(handle.command),
                    cwd=str(handle.cwd),
                    start_time=handle.start_time,
                    pid=handle.pid,
                    log_file_name=handle.log_file_name,
                    metadata_json=_dump_json({"run_id": handle.run_id, "pid": str(handle.pid)}),
                )
                session.add(row)
            else:
                row.model_id = handle.model_id
                row.model_name = handle.model_name
                row.model_path = str(handle.model_path)
                row.command_json = _dump_json(handle.command)
                row.cwd = str(handle.cwd)
                row.start_time = handle.start_time
                row.pid = handle.pid
                row.log_file_name = handle.log_file_name
            
            model_row = session.get(ModelRow, handle.model_id)
            if model_row is None:
                model_row = ModelRow(model_id=handle.model_id, model_name=handle.model_name)
                session.add(model_row)

            model_row.model_name = handle.model_name
            model_row.model_path = str(handle.model_path)
            model_row.state = "running"
            model_row.started_at = handle.start_time if model_row.started_at is None else model_row.started_at
            model_row.updated_at = handle.start_time

    def record_run_finished(self, result: RunResult) -> None:
        run_id = result.metadata.get("run_id")
        with self.SessionLocal.begin() as session:
            row = session.get(RunRow, run_id) if run_id else None
            if row is None:
                row = RunRow(
                    run_id=run_id or f"{result.model_id}:{result.start_time.isoformat()}",
                    model_id=result.model_id,
                    model_name=result.model_name,
                    model_path=str(result.model_path),
                    command_json=_dump_json(result.command),
                    cwd=str(result.cwd),
                    start_time=result.start_time,
                )
                session.add(row)

            row.model_id = result.model_id
            row.model_name = result.model_name
            row.model_path = str(result.model_path)
            row.command_json = _dump_json(result.command)
            row.cwd = str(result.cwd)
            row.start_time = result.start_time
            row.end_time = result.end_time
            row.success = result.success
            row.terminal_state = result.terminal_state
            row.return_code = result.return_code
            row.duration_seconds = result.duration_seconds
            row.stdout = result.stdout
            row.stderr = result.stderr
            row.sync_performed = result.sync_performed
            if "pid" in result.metadata:
                try:
                    row.pid = int(result.metadata["pid"])
                except ValueError:
                    row.pid = None
            row.metadata_json = _dump_json(result.metadata)

            model_row = session.get(ModelRow, result.model_id)
            if model_row is not None:
                model_row.state = result.terminal_state
                model_row.updated_at = result.end_time
                model_row.finished_at = result.end_time
                if model_row.started_at is None:
                    model_row.started_at = result.start_time

    def list_recent_runs(self, *, limit: int = 100) -> list[RunResult]:
        with self.SessionLocal() as session:
            stmt = select(RunRow).order_by(RunRow.start_time.desc()).limit(limit)
            return [self._row_to_run_result(row) for row in session.scalars(stmt)]

    def get_model_run_history(self, model_id: str) -> list[RunResult]:
        with self.SessionLocal() as session:
            stmt = (
                select(RunRow)
                .where(RunRow.model_id == model_id)
                .order_by(RunRow.start_time.desc())
            )
            return [self._row_to_run_result(row) for row in session.scalars(stmt)]

    def get_model_row(self, model_id: str) -> ModelRow | None:
        with self.SessionLocal() as session:
            return session.get(ModelRow, model_id)

    def list_model_rows(self) -> list[ModelRow]:
        with self.SessionLocal() as session:
            stmt = select(ModelRow).order_by(ModelRow.model_name.asc())
            return list(session.scalars(stmt))

    def get_latest_run(self, model_id: str) -> RunResult | None:
        with self.SessionLocal() as session:
            stmt = (
                select(RunRow)
                .where(RunRow.model_id == model_id)
                .order_by(RunRow.start_time.desc())
                .limit(1)
            )
            row = session.scalars(stmt).first()
            return self._row_to_run_result(row) if row is not None else None

    def get_latest_transition(self, model_id: str) -> StateTransition | None:
        with self.SessionLocal() as session:
            stmt = (
                select(StateTransitionRow)
                .where(StateTransitionRow.model_id == model_id)
                .order_by(StateTransitionRow.at.desc(), StateTransitionRow.id.desc())
                .limit(1)
            )
            row = session.scalars(stmt).first()
            if row is None:
                return None
            return StateTransition(
                model_id=row.model_id,
                from_state=row.from_state,
                to_state=row.to_state,
                at=_ensure_utc(row.at) or _utc_now(),
                reason=row.reason,
                run_id=row.run_id,
                metadata=_load_json_dict(row.metadata_json),
            )

    def _row_to_run_result(self, row: RunRow) -> RunResult:
        return RunResult(
            success=bool(row.success) if row.success is not None else False,
            terminal_state=row.terminal_state or "failed",
            return_code=row.return_code if row.return_code is not None else 1,
            duration_seconds=row.duration_seconds if row.duration_seconds is not None else 0.0,
            model_id=row.model_id,
            model_name=row.model_name,
            model_path=Path(row.model_path),
            command=_load_json_list(row.command_json),
            cwd=Path(row.cwd),
            start_time=_ensure_utc(row.start_time) or _utc_now(),
            end_time=_ensure_utc(row.end_time) or _ensure_utc(row.start_time) or _utc_now(),
            stdout=row.stdout or "",
            stderr=row.stderr or "",
            sync_performed=bool(row.sync_performed) if row.sync_performed is not None else False,
            metadata=_load_json_dict(row.metadata_json),
        )


@dataclass
class LiveProcessEntry:
    handle: RunHandle
    process: subprocess.Popen
    registered_at: datetime = field(default_factory=_utc_now)


class LiveProcessRegistry:
    """In-memory registry of currently running subprocesses by model_id.

    This registry is the real-time companion to SQLite history:

        - register stores a launched process with its RunHandle.
        - get returns None if unknown or if the process already exited.
        - list_running_model_ids returns only currently alive processes.
        - terminate supports graceful shutdown with optional force-kill fallback.
        
    Lifecycle behavior:
        - Stale entries are pruned lazily during lookups.
        - Registry content is process-local and not durable.
    """

    def __init__(self) -> None:
        self._entries: dict[str, LiveProcessEntry] = {}
        self._lock = threading.RLock()

    def register(self, handle: RunHandle, process: subprocess.Popen) -> None:
        with self._lock:
            self._entries[handle.model_id] = LiveProcessEntry(handle=handle, process=process)

    def unregister(self, model_id: str) -> None:
        with self._lock:
            self._entries.pop(model_id, None)

    def get(self, model_id: str) -> LiveProcessEntry | None:
        with self._lock:
            entry = self._entries.get(model_id)
            if entry is None:
                return None
            if entry.process.poll() is not None:
                self._entries.pop(model_id, None)
                return None
            return entry

    def is_running(self, model_id: str) -> bool:
        return self.get(model_id) is not None

    def list_running_model_ids(self) -> list[str]:
        with self._lock:
            model_ids: list[str] = []
            for model_id in list(self._entries.keys()):
                if self.get(model_id) is not None:
                    model_ids.append(model_id)
            return model_ids

    def terminate(self, model_id: str, *, force: bool = False, grace_seconds: float = 3.0) -> bool:
        entry = self.get(model_id)
        if entry is None:
            return False

        if force:
            entry.process.kill()
            entry.process.wait()
            self.unregister(model_id)
            return True

        entry.process.terminate()
        try:
            entry.process.wait(timeout=grace_seconds)
        except subprocess.TimeoutExpired:
            entry.process.kill()
            entry.process.wait()

        self.unregister(model_id)
        return True


class RepositoryObserver:
    """Observer adapter that persists run lifecycle events.

    This class implements the RunObserver callback shape and delegates each event
    to a RunRepository implementation:

        on_state_transition -> record_state_transition
        on_process_started -> record_run_started
        on_process_finished -> record_run_finished
    
    Use this observer when running models so status queries can reconstruct
    current and historical state from repository data.
    """

    def __init__(self, repo: RunRepository) -> None:
        self.repo = repo

    def on_state_transition(self, transition: StateTransition) -> None:
        self.repo.record_state_transition(transition)

    def on_process_started(self, handle: RunHandle) -> None:
        self.repo.record_run_started(handle)

    def on_process_finished(self, result: RunResult) -> None:
        self.repo.record_run_finished(result)

@dataclass
class Tracker:
    """Tracker object that holds the SQL repository (SQLiteRunRepository)
    instance that keeps track of the running models, the 
    live_tracker (LiveProcessRegistry) that tracks additional in-memory
    information about the models (only available if initiated in same Python
    session) and the observer object (RunObserver) that registers state changes.

    Attributes:
        repo: SQLiteRunRepository object
        live_tracker: LiveProcessRegistry object
        overver: RunObserver object
    """
    repo: SQLiteRunRepository
    live_tracker: LiveProcessRegistry
    observer: RepositoryObserver

    @classmethod
    def create(cls, db_path: str | Path) -> "Tracker":
        """Method to initialise the Tracker object. 

        Args:
            db_path: Path to the location where the SQL database file
            should be written to.
        """
        repo = SQLiteRunRepository(db_path=db_path)
        return cls(
            repo = repo,
            observer = RepositoryObserver(repo),
            live_tracker = LiveProcessRegistry()
        )

# class ModelRepository(SQLiteRunRepository):
#     """Repository to keep track of initiated, running, and
#     finished MESA models written on the disk as a SQL database
#     file for persistence.

#     This class is a wrapper for the internally used 
#     SQLiteRunRepository class.

#     When a RepositoryObserver is active, changed to the state 
#     (running, completed, ...) of models will be recorded in the
#     repository.

#     Since the repository is persistent, re-initialising the same
#     SQL database file (db_path) will append new models. To create
#     a completely new database file (e.g. when you rerun a grid
#     because sonething was wrong with the models and you don't
#     want to keep info about the old models), simply remove the 
#     database file:
#     ```
#     if DB_PATH.exists():
#         DB_PATH.unlink()
#     ```
#     if DB_PATH is a pathlib.Path object, or
#     ```
#     if os.path.exists(DB_PATH):
#         os.unlink(DB_PATH)
#     ```
#     if DB_PATH is a regular string. 
#     DB_PATH holds the location of the SQL database file passed
#     to ModelRepo(db_path=DB_PATH).

#     Usage:
#     ```
#     repo = ModelRepository(db_path=DB_PATH)
#     ```
#     (Call before model/grid launch/run calls.)
#     """
#     pass

# class LiveModelTracker(LiveProcessRegistry):
#     """Live tracker for currently running models.

#     This object tracks live process handles for model objects 
#     currently in the RAM and loses its function if the 
#     Python session is closed.

#     It should be run alongside any model or grid launch/run 
#     functions.

#     This class is a wrapper for the internally used
#     LiveProcessRegistry class.

#     Usage:
#     ```
#     live_tracker = LiveModelTracker()
#     ```
#     (Call before model/grid launch/run calls.)
#     """
#     pass

# class ModelObserver(RepositoryObserver):
#     """An observer that detects and records the lifecycles of 
#     model runs in the model repository (the SQL database file).

#     This class is a wrapper for the internally used
#     RepositoryObserver class.


#     Usage:
#     ```
#     observer = ModelObserver(repo=repo)
#     ```
#     with repo a ModelRepository object.
#     (Call before model/grid launch/run calls.)
#     """
#     pass