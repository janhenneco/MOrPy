from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Mapping
import os
import stat
import subprocess
import time


WorkdirMode = Literal["star", "binary"]


@dataclass
class CommandResult:
    command_path: Path
    return_code: int
    duration_seconds: float
    stdout: str
    stderr: str

    def to_dict(self, *, max_output_chars: int | None = None) -> dict:
        def _clip(text: str) -> str:
            if max_output_chars is None or len(text) <= max_output_chars:
                return text
            return text[:max_output_chars] + " ... [truncated]"

        return {
            "command_path": str(self.command_path),
            "return_code": self.return_code,
            "duration_seconds": self.duration_seconds,
            "stdout": _clip(self.stdout),
            "stderr": _clip(self.stderr),
        }


@dataclass
class CompileResult:
    success: bool
    return_code: int
    duration_seconds: float
    mode: str
    executable_path: Path | None
    clean_result: CommandResult | None
    mk_result: CommandResult
    model_scripts_updated: list[Path]

    def to_dict(
        self,
        *,
        flatten: bool = True,
        max_output_chars: int | None = None,
    ) -> dict:
        out = {
            "success": self.success,
            "return_code": self.return_code,
            "duration_seconds": self.duration_seconds,
            "mode": self.mode,
            "executable_path": str(self.executable_path) if self.executable_path else None,
            "model_scripts_updated": [str(p) for p in self.model_scripts_updated],
        }

        if flatten:
            clean = (
                self.clean_result.to_dict(max_output_chars=max_output_chars)
                if self.clean_result is not None
                else None
            )
            mk = self.mk_result.to_dict(max_output_chars=max_output_chars)

            if clean is None:
                out["clean"] = None
            else:
                for k, v in clean.items():
                    out[f"clean_{k}"] = v

            for k, v in mk.items():
                out[f"mk_{k}"] = v
        else:
            out["clean_result"] = (
                self.clean_result.to_dict(max_output_chars=max_output_chars)
                if self.clean_result is not None
                else None
            )
            out["mk_result"] = self.mk_result.to_dict(max_output_chars=max_output_chars)

        return out

    def pretty(self, max_output_chars: int = 400) -> str:
        d = self.to_dict(flatten=True, max_output_chars=max_output_chars)
        lines = [f"{k}: {v}" for k, v in d.items()]
        return "\n".join(lines)

    def __str__(self) -> str:
        # Nice default for print(out) in notebooks/terminal.
        return self.pretty(max_output_chars=300)


_PROJECT_LEVEL_NAMES = {
    "src",
    "make",
    "clean",
    "mk",
    "rn",
    "re",
    "star",
    "binary",
    "history_columns.list",
    "profile_columns.list",
    "binary_history_columns.list",
}


def _ensure_executable(path: Path) -> None:
    """Private helper function to add execute bits to a file."""
    if not path.exists():
        raise FileNotFoundError(f"Path does not exist: {path}")
    if path.is_dir():
        raise IsADirectoryError(f"Expected a file, got a directory: {path}")

    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _looks_like_model_dir(path: Path) -> bool:
    """Private helper function to detect model directories in projectdir."""
    if not path.is_dir():
        return False
    if path.name.startswith("."):
        return False
    if path.name in _PROJECT_LEVEL_NAMES:
        return False

    # Model dirs contain one or more inlist files in this codebase.
    has_inlist = any(
        child.is_file() and "inlist" in child.name.lower()
        for child in path.iterdir()
    )
    return has_inlist


def _collect_model_dirs(projectdir_path: Path) -> list[Path]:
    """Private helper function to collect model directories in projectdir."""
    return sorted(
        [p for p in projectdir_path.iterdir() if _looks_like_model_dir(p)],
        key=lambda p: p.name,
    )


def _make_model_scripts_executable(projectdir_path: Path) -> list[Path]:
    """Private helper function to make rn/re executable inside model directories."""
    updated: list[Path] = []

    for model_dir in _collect_model_dirs(projectdir_path):
        for script_name in ("rn", "re"):
            script_path = model_dir / script_name
            if script_path.exists() and script_path.is_file():
                _ensure_executable(script_path)
                updated.append(script_path)

    return updated


def _run_script(
    script_path: Path,
    *,
    cwd: Path,
    env: Mapping[str, str] | None = None,
    timeout: float | None = None,
) -> CommandResult:
    """Private helper function to run build script and capture output."""
    start = time.perf_counter()

    merged_env = os.environ.copy()
    if env is not None:
        merged_env.update(env)

    completed = subprocess.run(
        [str(script_path)],
        cwd=cwd,
        env=merged_env,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )

    duration = time.perf_counter() - start

    return CommandResult(
        command_path=script_path,
        return_code=completed.returncode,
        duration_seconds=duration,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def compile_project(
    projectdir_path: Path | str,
    mode: WorkdirMode,
    *,
    clean_rebuild: bool = True,
    env: Mapping[str, str] | None = None,
    timeout: float | None = None,
) -> CompileResult:
    """Compile a MESA project directory.

    Args:
        projectdir_path: path to project directory containing clean/mk scripts.
        mode: "star" or "binary".
        clean_rebuild: if True run clean then mk, else run mk only.
        env: optional extra environment variables passed to subprocess.
        timeout: optional timeout in seconds for each command.

    Returns:
        CompileResult with command outputs and final executable path.
    """

    if mode not in ("star", "binary"):
        raise ValueError(f"mode must be 'star' or 'binary', got: {mode!r}")

    projectdir_path = Path(projectdir_path)
    if not projectdir_path.is_dir():
        raise FileNotFoundError(f"Project directory does not exist: {projectdir_path}")

    clean_path = projectdir_path / "clean"
    mk_path = projectdir_path / "mk"

    if clean_rebuild and not clean_path.is_file():
        raise FileNotFoundError(f"clean script not found: {clean_path}")
    if not mk_path.is_file():
        raise FileNotFoundError(f"mk script not found: {mk_path}")

    if clean_rebuild:
        _ensure_executable(clean_path)
    _ensure_executable(mk_path)

    model_scripts_updated = _make_model_scripts_executable(projectdir_path)

    total_start = time.perf_counter()

    clean_result: CommandResult | None = None
    if clean_rebuild:
        clean_result = _run_script(
            clean_path,
            cwd=projectdir_path,
            env=env,
            timeout=timeout,
        )

    # Run mk after clean (or directly for incremental builds).
    mk_result = _run_script(
        mk_path,
        cwd=projectdir_path,
        env=env,
        timeout=timeout,
    )

    executable_path = projectdir_path / mode
    executable_out: Path | None = None

    success = True
    return_code = 0

    if clean_result is not None and clean_result.return_code != 0:
        success = False
        return_code = clean_result.return_code

    if mk_result.return_code != 0:
        success = False
        return_code = mk_result.return_code

    # If mk succeeded, executable should exist and be executable.
    if mk_result.return_code == 0:
        if not executable_path.exists():
            success = False
            if return_code == 0:
                return_code = 1
        else:
            _ensure_executable(executable_path)
            executable_out = executable_path
    else:
        if executable_path.exists():
            executable_out = executable_path

    total_duration = time.perf_counter() - total_start

    return CompileResult(
        success=success,
        return_code=return_code,
        duration_seconds=total_duration,
        mode=mode,
        executable_path=executable_out,
        clean_result=clean_result,
        mk_result=mk_result,
        model_scripts_updated=model_scripts_updated,
    )