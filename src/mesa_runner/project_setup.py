from pathlib import Path
from typing import Literal
import shutil
import uuid
from .config import MesaConfig, require_active_config

WorkdirMode = Literal["star", "binary"]

_REQUIRED_CONTENT = ("src", "make", "clean", "mk", "rn", "re")

def _columns_files_for_mode(mode: WorkdirMode) -> list[str]:
    """Return optional files always needed"""
    if mode == "binary":
        return [
            "binary_history_columns.list",
            "history_columns.list",
            "profile_columns.list",
        ]
    return ["history_columns.list", "profile_columns.list"]

def _copy_entry(src: Path, dst: Path) -> None:
    """Private helper function for copying directories and files"""
    if src.is_dir():
        shutil.copytree(src, dst, symlinks=False)
    elif src.is_file():
        shutil.copy2(src, dst)
    else:
        raise OSError(f"Unsupported path type: {src}")
    
def _validate_existing_projectdir(projectdir_path: Path) -> None:
    """Private helper function to validate if project directory creation was successful"""
    missing = [name for name in _REQUIRED_CONTENT if not (projectdir_path / name).exists()]
    if missing:
        missing_txt = ", ".join(missing)
        raise FileNotFoundError(
            f"Project directory exists but is missing required entries: {missing_txt}"
        )

def _has_run_binary_extras(src_dir: Path) -> bool:
    """Return True if src contains a file named run_binary_extras, ignoring extension."""
    for path in src_dir.rglob("*"):
        if not path.is_file():
            continue
        # Match run_binary_extras, run_binary_extras.f90, run_binary_extras.F90, etc.
        if path.name.split(".", 1)[0].lower() == "run_binary_extras":
            return True
    return False

def create_projectdir(
    projectdir_path: Path | str,
    mode: WorkdirMode,
    *,
    include_columns_files: bool = True,
     src_path: Path | str | None = None,
    config: MesaConfig | None = None,
) -> Path:
    """Create a MESA project directory from star/work or binary/work.

    Args:
        projectdir_path: path to the project directory that needs to be created
        mode: "star" or "binary"
        include_columns_files: add the applicable *_columns.list files to the project dir
        src_path: use this src folder instead of the default one
        config: MesaConfig
    Returns:
        projectdir_path: path to project directory when successfull

    Returns:
        Path to the project directory.
    """
    if config is None:
        config = require_active_config()

    if mode not in ("star", "binary"):
        raise ValueError(f"mode must be 'star' or 'binary', got: {mode!r}")

    projectdir_path = Path(projectdir_path)
    work_template = config.mesa_dir / mode / "work"
    defaults_template = config.mesa_dir / mode / "defaults"

    if not work_template.is_dir():
        raise FileNotFoundError(f"Template work directory does not exist: {work_template}")

    # Idempotent path: existing directory is validated then returned.
    if projectdir_path.exists():
        if not projectdir_path.is_dir():
            raise FileExistsError(
                f"Cannot create project directory because path exists and is not a directory: "
                f"{projectdir_path}"
            )
        _validate_existing_projectdir(projectdir_path)
        return projectdir_path

    projectdir_path.parent.mkdir(parents=True, exist_ok=True)

    custom_src: Path | None = None
    if src_path is not None:
        custom_src = Path(src_path)
        if not custom_src.is_dir():
            raise FileNotFoundError(f"Provided src_path is not a directory: {custom_src}")

        if mode == "binary" and not _has_run_binary_extras(custom_src):
            raise FileNotFoundError(
                "Binary mode with custom src requires a run_binary_extras file "
                "in the provided src directory."
            )

    tmp_dir = projectdir_path.parent / f".{projectdir_path.name}.tmp-{uuid.uuid4().hex}"
    committed = False
    try:
        tmp_dir.mkdir(parents=False, exist_ok=False)

        # Required scaffold
        for name in _REQUIRED_CONTENT:
            if name == "src":
                continue
            src = work_template / name
            if not src.exists():
                raise FileNotFoundError(
                    f"Required template entry not found in {work_template}: {name}"
                )
            _copy_entry(src, tmp_dir / name)

        src_to_copy = custom_src if custom_src is not None else (work_template / "src")
        if not src_to_copy.exists():
            raise FileNotFoundError(f"src directory not found: {src_to_copy}")
        _copy_entry(src_to_copy, tmp_dir / "src")

        # Optional assets
        if include_columns_files:
            for name in _columns_files_for_mode(mode):
                src = defaults_template / name
                if src.exists():
                    _copy_entry(src, tmp_dir / name)

        # Atomic promotion
        tmp_dir.replace(projectdir_path)
        committed = True
        return projectdir_path

    finally:
        if not committed and tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)
    
