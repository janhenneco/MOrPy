"""Work-directory setup, synchronization, and export utilities for models.

This module handles disk-facing model directory operations.

- importing inlists from disk into Model objects,
- creating model work directories with links/scripts/assets,
- syncing in-memory Model inlists with on-disk files,
- exporting self-contained runnable work directories.

It forms the bridge between in-memory model objects and MESA-compatible
directory layouts on disk.
"""

from pathlib import Path
import shutil
import os
from typing import Literal
import uuid
import hashlib
from datetime import datetime, timezone
from .parser import parse_inlist, build_defaults_options_from_config
from .model import Model
from .options import DefaultsOptions
from .config import MesaConfig, require_active_config

# Custom type for MESA workdir mode: star or binary
WorkdirMode = Literal["star", "binary"]

def import_inlists_from_dir(model: Model, 
                            source_dir: Path | str, 
                            default_options: DefaultsOptions,
                            config: MesaConfig | None = None,
                            *,
                            allow_unknown_options : bool = False
                            ) -> None:
    """Function that looks for files with 'inlist' in their name in a given directory (non-recursively),
        parses them, and adds them to model.inlists.
    
    Args:
        model: Model object which inlists attribute will be populated by the parsed inlists
        source_dir: path to the directory in which the function will look for inlists
        config: MesaConfig object
        default_options: DefaultsOptions object
        allow_unknown_options: If True, give a warning about inlist options that are not found in the defaults files. 
            If False, raise an exception when inlist options are found that re not found in the defaults files.
    Returns:
        None
    Raises:
        FileNotFoundError is source_dir does not exist.
    """
    if config is None:
        config = require_active_config()

    source_dir = Path(source_dir)
    if not source_dir.is_dir():
        raise FileNotFoundError(f"Inlist directory does not exist: {source_dir}")
    
    inlist_paths = sorted(p for p in source_dir.iterdir() if p.is_file() and "inlist" in p.name.lower())

    for path in inlist_paths:
        model.add_inlist(parse_inlist(source_path=path, config=config, default_options=default_options, allow_unknown_options=allow_unknown_options))

    return

def _link_into_model_dir(
    model_dir: Path,
    project_dir: Path,
    name: str,
    *,
    overwrite: bool = False,
    require_exists: bool = True,
) -> Path:
    """Helper function that creates symbolic links for files in the project directory
        that are shared by all models. This makes sure that e.g. the history_columns.list
        files are read by MESA and that the rn and re
    """


    src = project_dir / name
    dst = model_dir / name

    if require_exists and not src.exists():
        raise FileNotFoundError(f"Shared asset not found in project dir: {src}")

    # Handle existing destination
    if dst.exists() or dst.is_symlink():
        if not overwrite:
            raise FileExistsError(f"Path already exists in model dir: {dst}")
        if dst.is_symlink() or dst.is_file():
            dst.unlink()
        elif dst.is_dir():
            shutil.rmtree(dst)
        else:
            raise OSError(f"Cannot replace unsupported path type: {dst}")

    # Use relative symlink so project tree remains movable
    rel_target = Path(os.path.relpath(src, start=model_dir))
    dst.symlink_to(rel_target, target_is_directory=src.is_dir())
    return dst

def detect_workdir_mode(model: Model) -> WorkdirMode:
    """Infer whether a model should run in star or binary work mode.

    Args:
        model: Model object.

    Returns:
        "star" or "binary".

    Raises:
        ValueError: If neither star nor binary namelist options are detected.
    """
    saw_binary = False
    saw_star = False

    binary_namelists = {"binary_job"}
    star_namelists = {"star_job"}

    for inlist in model.inlists.values():
        for opt in inlist.options.values():
            if opt.namelist in binary_namelists:
                saw_binary = True
            elif opt.namelist in star_namelists:
                saw_star = True

    if saw_binary:
        return "binary"
    if saw_star:
        return "star"

    raise ValueError(
        f"Could not infer workdir mode for model '{model.name}'. "
        "No star or binary namelist options were found."
    )

def _columns_files_for_mode(mode: WorkdirMode) -> list[str]:
    """Return optional files always needed"""
    if mode == "binary":
        return [
            "binary_history_columns.list",
            "history_columns.list",
            "profile_columns.list",
        ]
    return ["history_columns.list", "profile_columns.list"]

_SHEBANG = b"#!/bin/bash\n"

def _ensure_shebang(path: Path) -> None:
    """Prepend a shebang line to a script file if it doesn't already have one.

    Work-directory scripts (clean, mk, rn, re) shipped by some older MESA
    releases have no shebang line. The OS then refuses to exec them directly
    ("Exec format error"), even though a shell interprets them fine when
    invoked explicitly (e.g. `bash clean`).
    """
    content = path.read_bytes()
    if content.startswith(b"#!"):
        return
    path.write_bytes(_SHEBANG + content)

def _ensure_scripts_in_project_dir(projectdir_path: Path, mode: WorkdirMode, config: MesaConfig) -> None:
    """Ensure rn and re scripts exist in projectdir. If not, copy from MESA_DIR."""
    for script_name in ["rn", "re"]:
        script_path = projectdir_path / script_name

        # Already present in projectdir, skip
        if script_path.exists():
            continue

        # Determine source in MESA_DIR based on mode
        if mode == "binary":
            src = config.mesa_dir / "binary" / "work" / script_name
        else:
            src = config.mesa_dir / "star" / "work" / script_name

        if not src.exists():
            raise FileNotFoundError(
                f"Script '{script_name}' not found in {src}. "
                f"Ensure MESA is built or provide {script_name} in project directory."
            )

        # Copy to projectdir, preserving permissions
        shutil.copy2(src, script_path)
        _ensure_shebang(script_path)

def _hash_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    """Return SHA-256 hash of a file."""
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            hasher.update(chunk)
    return hasher.hexdigest()

def _snapshot_model_inlists(model_dir: Path | str) -> dict[str, str]:
    """Create a stable snapshot of inlist files in a model directory.

    Snapshot format:
        { "<filename>": "<sha256>" }
    """
    model_dir = Path(model_dir)
    snapshot: dict[str, str] = {}

    inlist_files = sorted(
        p for p in model_dir.iterdir() if p.is_file() and "inlist" in p.name.lower()
    )
    for path in inlist_files:
        snapshot[path.name] = _hash_file(path)

    return snapshot

def sync_model_with_disk(model: Model, default_options: DefaultsOptions, config: MesaConfig | None = None, *, allow_unknown_options: bool = False) -> bool:
    """Ensure model.inlists matches current files in model.model_path.

    Disk is treated as source of truth. If drift is detected compared to the
    stored model.file_snapshot, model.inlists is reloaded from disk.

    Returns:
        True if a reload was performed, False if model was already in sync.
    """
    if config is None:
        config = require_active_config()

    if model.model_path is None:
        raise ValueError(
            f"Model '{model.name}' has no model_path; cannot sync from disk."
        )

    model_dir = Path(model.model_path)
    if not model_dir.is_dir():
        raise FileNotFoundError(f"Model directory does not exist: {model_dir}")

    current_snapshot = _snapshot_model_inlists(model_dir)

    # Fast no-op path.
    if model.file_snapshot == current_snapshot:
        return False

    # Rebuild in-memory inlists from disk so removals are handled as well.
    model.inlists.clear()
    import_inlists_from_dir(
        model=model,
        source_dir=model_dir,
        default_options=default_options,
        config=config, 
        allow_unknown_options=allow_unknown_options
    )

    now = datetime.now(timezone.utc)
    model.file_snapshot = current_snapshot
    model.snapshot_taken_at = now
    model.updated_at = now
    return True

def create_modeldir(model: Model, 
                    projectdir_path: Path | str, 
                    overwrite: bool = False,
                    reuse_existing: bool = True,
                    include_additional_options: bool = False,
                    include_comment_blocks: bool = True, 
                    config: MesaConfig | None = None,) -> Path:
    """Function to create a model directory in storage for a given Model object. This model
        directory contains the inlists and rn & re scripts appropriate to run it.
    
    Args:
        model: Model object to be written to the model directory
        projectdir_path: path to the project directory in which this model directory will be placed.
            This can technically be any path, but in order to run the run the model, the mdoel directory should
            be placed inside a project directory containing the /src folder and Fortran executable.
        overwrite: Overwrite the model directory if it already exists in the project directory.
            Set this to False for restarts of existing grids.
        reuse_existing: Reuse existing model directories if they exist. Set to True for restarts
            of existing grids.
        include_additional_options: If present, include unclassified namelist blocks in all inlists written to storage
            (see options.Inlist and options.Unclassifiednamelist documentation)
        include_comment_blocks: Add Inlist.comment_block to the top of the inlist files
            if it exists.
        config: MesaConfig object. Automatically detected from active config if None.
    Returns:
        Path to model directory.
    Raises:
        FileNotFoundError if projectdir_path does not exist.
        OSError if rm command fails when clearing out model_dirs that need to be overwritten.
        ValueError if model has no inlists.
        FileExistsError if path directory already exists and overwite=False or if file exists at same path.
    """

    if config is None:
        config = require_active_config()

    projectdir_path = Path(projectdir_path)
    if not projectdir_path.is_dir():
        raise FileNotFoundError(f"project directory does not exist: {projectdir_path}")
    
    if not bool(model.inlists):
         raise ValueError(f"Model '{model.name}' has no inlists to write. Add inlists before calling create_modeldir().")
    
    model_dir = projectdir_path / model.name

    if model_dir.exists():
        if reuse_existing:
            model.model_path = model_dir
            model.file_snapshot = _snapshot_model_inlists(model_dir)
            model.snapshot_taken_at = datetime.now(timezone.utc)
            return model_dir
        if not overwrite:
            raise FileExistsError(f"Cannot create model directory because path exists and is not a directory: {model_dir}\n " \
                                  "If you wish to reuse existing model directories for grid reruns, use `reuse_exisiting = True`.")
    
        

    mode = detect_workdir_mode(model)

    # Ensure rn/re exist in project dir; if missing, copy from MESA_DIR work template
    _ensure_scripts_in_project_dir(projectdir_path=projectdir_path, mode=mode, config=config)

    # executable is allowed to be missing (dangling symlink is okay)
    executable = "binary" if mode == "binary" else "star"

    # Create tmp dir that will only be commited if nothing fails, deleted if something fails
    tmp_dir = projectdir_path / f".{model.name}.tmp-{uuid.uuid4().hex}"
    committed = False
    try:
        tmp_dir.mkdir(parents=False, exist_ok=False)

        # write inlists into temp
        for inlist in model.inlists.values():
            inlist.write(output_path=tmp_dir, include_additional_options=include_additional_options, include_comment_block=include_comment_blocks)

        # symlink executable (may be dangling until compile)
        _link_into_model_dir(
            model_dir=tmp_dir,
            project_dir=projectdir_path,
            name=executable,
            overwrite=False,
            require_exists=False,
        )

        # symlink optional assets if present
        for asset in _columns_files_for_mode(mode):
            if (projectdir_path / asset).exists():
                _link_into_model_dir(
                    model_dir=tmp_dir,
                    project_dir=projectdir_path,
                    name=asset,
                    overwrite=False,
                    require_exists=True,
                )

        # copy rn/re into temp and make executable
        for script_name in ("rn", "re"):
            src_script = projectdir_path / script_name
            dst_script = tmp_dir / script_name
            shutil.copy2(src_script, dst_script)
            dst_script.chmod(0o755)
        
        if overwrite:
            backup_dir = projectdir_path / f".{model.name}.bak-{uuid.uuid4().hex}"

            if model_dir.exists():
                # 1) Move current good dir out of the way (fast rename, same parent fs)
                model_dir.replace(backup_dir)
            try:
                # 2) Promote temp to official target
                tmp_dir.replace(model_dir)
            except Exception:
                # 3) Roll back if promotion failed
                if backup_dir.exists() and not model_dir.exists():
                    backup_dir.replace(model_dir)
                raise
            else:
                # 4) New target committed; remove backup
                if backup_dir.exists():
                    shutil.rmtree(backup_dir)

        else:
            if model_dir.exists():
                raise FileExistsError(
                    f"{model_dir} already exists. Use overwrite=True to replace it."
                )
            tmp_dir.replace(model_dir)

        committed = True
        model.model_path = model_dir
        now = datetime.now(timezone.utc)
        model.file_snapshot = _snapshot_model_inlists(model_dir)
        model.snapshot_taken_at = now
        return model_dir

    finally:
        # rollback temp on any failure before commit
        if not committed and tmp_dir.exists():
            shutil.rmtree(tmp_dir)

def export_modeldir(
    model_dir: Path | str,
    export_dir: Path | str,
    projectdir_path: Path | str,
    *,
    keep_executable_symlinks: bool = False,
    overwrite: bool = False
) -> Path:
    """Function that creates a self-contained MESA work directory for a given model
        directory and project directory. This function creates a copy of the model
        directroy and copies over all the files and folders from the project directory
        required to compile and run this model on its own. This essentially creates
        a portable copy of the model directory, e.g. for sharing with others.

    Args:
        model_dir: Location of the model directory
        export_dir: Full target directory path for the exported workdir
        projectdir_path: Location of the project directory which contains the model
            directory.
        keep_executable_symlinks: if True, also copy over the Fortran executables
            into the exported workdir. Only recommended if you plan to run the model
            again locally, not recommended when moving the model elsewhere and/or
            sharing it.
        overwite: If True, overwrite export_dir if it exists already.
    Returns:
        Path to the exported workdir.
    """

    model_dir = Path(model_dir)
    export_dir = Path(export_dir)
    projectdir_path = Path(projectdir_path)

    if not model_dir.is_dir():
        raise FileNotFoundError(f"Model directory does not exist: {model_dir}")
    if not projectdir_path.is_dir():
        raise FileNotFoundError(f"Project directory does not exist: {projectdir_path}")
    
    if not overwrite and  export_dir.exists():
        raise FileExistsError(f"Export directory already exists: {export_dir}")
    
    # To allow for overwriting, we're using the same tmp dir structre
    # as in create_modeldir.
    # First, check if the export_dir's parent is a valid directory
    # (we need to place the tmp dir there)
    export_parent = export_dir.parent
    if not export_parent.exists():
        raise FileNotFoundError(f"Export directory parent does not exist: {export_parent}")
    if not export_parent.is_dir():
        raise FileNotFoundError(f"Export directory parent is not a directory: {export_parent}")

    # Chech that tmp_dir does not exist yet
    tmp_dir = export_parent / f".{export_dir.name}.tmp-{uuid.uuid4().hex}"
    committed = False
    backup_dir = export_parent / f".{export_dir.name}.bak-{uuid.uuid4().hex}"

    try:
        tmp_dir.mkdir(parents=False, exist_ok=False)
        
        executable_names = {"star", "binary"}

        # 1) Copy model_dir content; dereference non-executable symlinks
        for src in model_dir.iterdir():
            dst = tmp_dir / src.name

            if src.is_symlink():
                if src.name in executable_names:
                    if keep_executable_symlinks:
                        dst.symlink_to(src.readlink())
                    continue

                resolved = src.resolve(strict=True)
                if resolved.is_dir():
                    shutil.copytree(resolved, dst, symlinks=False)
                else:
                    shutil.copy2(resolved, dst)
                continue

            if src.is_dir():
                shutil.copytree(src, dst, symlinks=False)
            elif src.is_file():
                shutil.copy2(src, dst)

        # 2) Always copy required build scaffold from projectdir (mandatory)
        for name in ("src", "mk", "make", "clean"):
            src = projectdir_path / name
            dst = tmp_dir / name

            if not src.exists():
                raise FileNotFoundError(
                    f"Required build scaffold entry is missing in project directory: {src}"
                )

            if src.is_dir():
                shutil.copytree(src, dst, symlinks=False)
            elif src.is_file():
                shutil.copy2(src, dst)
            else:
                raise OSError(f"Unsupported scaffold path type: {src}")
        
        if overwrite:
            if export_dir.exists():
                export_dir.replace(backup_dir)
            try:
                tmp_dir.replace(export_dir)
            except Exception:
                # Rollback if export_dir wasn't created successfully
                if backup_dir.exists() and not export_dir.exists():
                    backup_dir.replace(export_dir)
                raise
            else:
                if backup_dir.exists():
                    shutil.rmtree(backup_dir)
        else:
            # overwrite = False --> export_dir should not exists, as checked at beginning
            tmp_dir.replace(export_dir)
        
        committed = True
        return export_dir
    
    finally:
        # If we failed before promotion of tmp_dir, clean up tmp_dir
        if not committed and tmp_dir.exists():
            shutil.rmtree(tmp_dir)

    return export_dir




    
