from pathlib import Path

import pytest
import morpy as mrun
import morpy.project_setup as ps


def make_fake_mesa_dir(tmp_path, version_raw: str = "r24.08.1") -> Path:
    mesa_dir = tmp_path / "mesa"
    (mesa_dir / "data").mkdir(parents=True)
    (mesa_dir / "data" / "version_number").write_text(version_raw, encoding="utf-8")

    for mode in ("star", "binary"):
        work = mesa_dir / mode / "work"
        (work / "src").mkdir(parents=True)

        # Distinguish template src by mode
        if mode == "binary":
            (work / "src" / "run_binary_extras.f90").write_text("! binary extras\n", encoding="utf-8")
        else:
            (work / "src" / "run_star_extras.f90").write_text("! star extras\n", encoding="utf-8")

        for name in ("make", "clean", "mk", "rn", "re"):
            (work / name).write_text(f"{name}\n", encoding="utf-8")

        (work / "history_columns.list").write_text("star history\n", encoding="utf-8")
        (work / "profile_columns.list").write_text("star profile\n", encoding="utf-8")
        if mode == "binary":
            (work / "binary_history_columns.list").write_text("binary history\n", encoding="utf-8")

    return mesa_dir


def test_create_projectdir_star_defaults(tmp_path):
    mesa_dir = make_fake_mesa_dir(tmp_path)
    config = mrun.MesaConfig.setup(mesa_dir=mesa_dir)

    project = tmp_path / "proj_star"
    out = mrun.create_projectdir(projectdir_path=project, mode="star", config=config)

    assert out == project
    for name in ("src", "make", "clean", "mk", "rn", "re"):
        assert (project / name).exists()

    assert (project / "history_columns.list").is_file()
    assert (project / "profile_columns.list").is_file()
    assert not (project / "binary_history_columns.list").exists()


def test_create_projectdir_binary_defaults(tmp_path):
    mesa_dir = make_fake_mesa_dir(tmp_path)
    config = mrun.MesaConfig.setup(mesa_dir=mesa_dir)

    project = tmp_path / "proj_binary"
    mrun.create_projectdir(projectdir_path=project, mode="binary", config=config)

    for name in ("src", "make", "clean", "mk", "rn", "re"):
        assert (project / name).exists()

    assert (project / "history_columns.list").is_file()
    assert (project / "profile_columns.list").is_file()
    assert (project / "binary_history_columns.list").is_file()


def test_create_projectdir_respects_include_columns_false(tmp_path):
    mesa_dir = make_fake_mesa_dir(tmp_path)
    config = mrun.MesaConfig.setup(mesa_dir=mesa_dir)

    project = tmp_path / "proj_no_cols"
    mrun.create_projectdir(
        projectdir_path=project,
        mode="binary",
        include_columns_files=False,
        config=config,
    )

    assert not (project / "history_columns.list").exists()
    assert not (project / "profile_columns.list").exists()
    assert not (project / "binary_history_columns.list").exists()


def test_create_projectdir_custom_src_overrides_template_src(tmp_path):
    mesa_dir = make_fake_mesa_dir(tmp_path)
    config = mrun.MesaConfig.setup(mesa_dir=mesa_dir)

    custom_src = tmp_path / "custom_src"
    custom_src.mkdir()
    (custom_src / "my_custom_file.f90").write_text("! custom\n", encoding="utf-8")

    project = tmp_path / "proj_custom_src"
    mrun.create_projectdir(
        projectdir_path=project,
        mode="star",
        src_path=custom_src,
        config=config,
    )

    assert (project / "src" / "my_custom_file.f90").is_file()
    # Star template marker should not be present when src is overridden.
    assert not (project / "src" / "run_star_extras.f90").exists()


def test_create_projectdir_binary_custom_src_requires_run_binary_extras(tmp_path):
    mesa_dir = make_fake_mesa_dir(tmp_path)
    config = mrun.MesaConfig.setup(mesa_dir=mesa_dir)

    custom_src = tmp_path / "bad_binary_src"
    custom_src.mkdir()
    (custom_src / "something_else.f90").write_text("! no extras\n", encoding="utf-8")

    with pytest.raises(FileNotFoundError, match="run_binary_extras"):
        mrun.create_projectdir(
            projectdir_path=tmp_path / "proj_bad_binary_src",
            mode="binary",
            src_path=custom_src,
            config=config,
        )


def test_create_projectdir_is_idempotent_for_existing_valid_dir(tmp_path):
    mesa_dir = make_fake_mesa_dir(tmp_path)
    config = mrun.MesaConfig.setup(mesa_dir=mesa_dir)

    project = tmp_path / "proj_idempotent"
    first = mrun.create_projectdir(projectdir_path=project, mode="star", config=config)
    second = mrun.create_projectdir(projectdir_path=project, mode="star", config=config)

    assert first == second == project


def test_create_projectdir_rolls_back_on_failure(tmp_path, monkeypatch):
    mesa_dir = make_fake_mesa_dir(tmp_path)
    config = mrun.MesaConfig.setup(mesa_dir=mesa_dir)
    project = tmp_path / "proj_rollback"

    real_copy_entry = ps._copy_entry

    def failing_copy_entry(src: Path, dst: Path) -> None:
        if dst.name == "mk":
            raise RuntimeError("forced copy failure")
        real_copy_entry(src, dst)

    monkeypatch.setattr(ps, "_copy_entry", failing_copy_entry)

    with pytest.raises(RuntimeError, match="forced copy failure"):
        mrun.create_projectdir(projectdir_path=project, mode="star", config=config)

    assert not project.exists()
    leftovers = list(tmp_path.glob(".proj_rollback.tmp-*"))
    assert leftovers == []