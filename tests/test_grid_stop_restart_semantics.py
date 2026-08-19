from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pytest

from morpy.grid_run import (
    _RESTART_REQUEST_TAG,
    _cancel_pending_items,
    _cancel_running_item,
    stop_grid,
)
from morpy.model import ModelState
from morpy.run_types import RunHandle, RunResult


@dataclass
class DummyModel:
    model_id: str
    name: str
    state: ModelState = ModelState.DRAFT
    model_path: Path | None = None
    updated_at: datetime | None = None


class DummyObserver:
    def __init__(self) -> None:
        self.transitions = []
        self.finished = []

    def on_state_transition(self, transition) -> None:
        self.transitions.append(transition)

    def on_process_started(self, handle) -> None:  # pragma: no cover - unused in this test module
        pass

    def on_process_finished(self, result) -> None:
        self.finished.append(result)


class DummyRepo:
    def __init__(self) -> None:
        self.stop_reasons: list[str] = []

    def request_grid_stop(self, reason: str) -> None:
        self.stop_reasons.append(reason)


class DummyTracker:
    def __init__(self, repo: DummyRepo) -> None:
        self.repo = repo


class DummyProcess:
    pass


def _make_item(model_id: str, state: ModelState = ModelState.DRAFT):
    model = DummyModel(model_id=model_id, name=f"model-{model_id}", state=state)
    return type("Item", (), {"model": model, "env": None})()


def _make_handle(model_id: str) -> RunHandle:
    now = datetime.now(timezone.utc)
    return RunHandle(
        run_id=f"run-{model_id}",
        model_id=model_id,
        model_name=f"model-{model_id}",
        model_path=Path("."),
        command=["rn"],
        cwd=Path("."),
        start_time=now,
        pid=12345,
        log_file_name="log.out",
        sync_performed=True,
    )


@pytest.mark.parametrize("backend", ["local", "mpi"])
def test_cancel_pending_items_marks_restart_when_requested(backend):
    pending = deque([
        _make_item("a1", state=ModelState.QUEUED),
        _make_item("a2", state=ModelState.QUEUED),
    ])
    observer = DummyObserver()
    results: list[RunResult] = []

    _cancel_pending_items(
        pending,
        results=results,
        backend=backend,
        command_name="rn",
        sync_before_run=True,
        stop_reason=_RESTART_REQUEST_TAG,
        observer=observer,
        restart_triggered=True,
    )

    assert len(results) == 2
    assert len(observer.finished) == 2
    assert len(observer.transitions) == 2
    assert all(r.terminal_state == "cancelled" for r in results)
    assert all(r.metadata["backend"] == backend for r in results)
    assert all("Cancelled before launch" in r.stderr for r in results)


@pytest.mark.parametrize("backend", ["local", "mpi"])
def test_cancel_pending_items_leaves_draft_items_untouched(backend):
    pending = deque([_make_item("a1"), _make_item("a2")])  # default state=DRAFT
    observer = DummyObserver()
    results: list[RunResult] = []

    _cancel_pending_items(
        pending,
        results=results,
        backend=backend,
        command_name="rn",
        sync_before_run=True,
        stop_reason=_RESTART_REQUEST_TAG,
        observer=observer,
        restart_triggered=True,
    )

    assert results == []
    assert observer.finished == []
    assert observer.transitions == []

@pytest.mark.parametrize("backend", ["local", "mpi"])
def test_cancel_pending_items_does_not_mark_restart_without_trigger(backend):
    pending = deque([_make_item("b1", state=ModelState.QUEUED)])
    observer = DummyObserver()
    results: list[RunResult] = []

    item = pending[0]

    _cancel_pending_items(
        pending,
        results=results,
        backend=backend,
        command_name="rn",
        sync_before_run=True,
        stop_reason="Cancelled by grid stop request",
        observer=observer,
        restart_triggered=False,
    )

    assert len(results) == 1
    assert results[0].terminal_state == "cancelled"
    assert item.model.state == ModelState.QUEUED
    assert observer.transitions == []


@pytest.mark.parametrize("backend", ["local", "mpi"])
def test_cancel_running_item_marks_restart_for_both_backends(monkeypatch, backend):
    observer = DummyObserver()
    item = _make_item("c1", state=ModelState.RUNNING)
    handle = _make_handle("c1")
    process = DummyProcess()

    called = {"terminated": 0, "cancel_requested": None, "cancel_reason": None}

    def fake_terminate_run_process(proc, force=True):
        assert proc is process
        assert force is True
        called["terminated"] += 1

    def fake_wait_for_model(**kwargs):
        called["cancel_requested"] = kwargs.get("cancel_requested")
        called["cancel_reason"] = kwargs.get("cancel_reason")
        now = datetime.now(timezone.utc)
        return RunResult(
            success=False,
            terminal_state="cancelled",
            return_code=130,
            duration_seconds=0.0,
            model_id=item.model.model_id,
            model_name=item.model.name,
            model_path=Path("."),
            command=["rn"],
            cwd=Path("."),
            start_time=now,
            end_time=now,
            stdout="",
            stderr="cancelled",
            sync_performed=True,
            metadata={"run_id": "rid-c1", "backend": backend},
        )

    monkeypatch.setattr("morpy.grid_run.terminate_run_process", fake_terminate_run_process)
    monkeypatch.setattr("morpy.grid_run.wait_for_model", fake_wait_for_model)

    result = _cancel_running_item(
        item=item,
        handle=handle,
        process=process,
        backend=backend,
        command_name="rn",
        sync_before_run=True,
        capture_output=True,
        tracker=None,
        observer=observer,
        stop_reason=_RESTART_REQUEST_TAG,
        restart_triggered=True,
    )

    assert called["terminated"] == 1
    assert called["cancel_requested"] is True
    assert called["cancel_reason"] == _RESTART_REQUEST_TAG
    assert result.terminal_state == "cancelled"
    assert item.model.state == ModelState.RESTART
    assert len(observer.transitions) == 1


@pytest.mark.parametrize(
    ("restart", "expected_reason"),
    [
        (False, "stop_grid called"),
        (True, _RESTART_REQUEST_TAG),
    ],
)
def test_stop_grid_persists_reason_tag_for_restart_option(restart, expected_reason):
    repo = DummyRepo()
    tracker = DummyTracker(repo)

    summary = stop_grid(handle=None, tracker=tracker, recover_from_dbfile=False, restart=restart)

    assert summary["requested"] is True
    assert summary["stop_request_persisted"] is True
    assert summary["restart"] is restart
    assert repo.stop_reasons == [expected_reason]
