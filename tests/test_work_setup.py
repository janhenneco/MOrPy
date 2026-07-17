from pathlib import Path

import morpy as mrun


DATA_DIR = Path(__file__).parent / "data_for_tests"


def make_fake_mesa_dir(tmp_path, version_raw: str = "r24.08.1") -> Path:
    mesa_dir = tmp_path / "mesa"
    (mesa_dir / "data").mkdir(parents=True)
    (mesa_dir / "data" / "version_number").write_text(version_raw, encoding="utf-8")

    for mode in ("star", "binary"):
        work = mesa_dir / mode / "work"
        work.mkdir(parents=True)
        (work / "rn").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        (work / "re").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")

    return mesa_dir


def make_defaults(config: mrun.MesaConfig) -> mrun.DefaultsOptions:
    return mrun.build_defaults_options(
        defaults_dir=DATA_DIR / "r24.08.1" / "defaults",
        config=config,
    )


def build_star_model(name: str, defaults: mrun.DefaultsOptions, n_inlists: int = 1) -> mrun.Model:
    model = mrun.Model.empty(name=name)
    for idx in range(n_inlists):
        inlist = mrun.Inlist.empty(name=f"inlist_{idx}")
        inlist.set_option(name="change_net", value=True, defaults=defaults, namelist="star_job")
        inlist.set_option(name="initial_mass", value=1.5 + idx, defaults=defaults, namelist="controls")
        model.add_inlist(inlist)
    return model


def test_create_modeldir_sets_snapshot_fields(tmp_path):
    mesa_dir = make_fake_mesa_dir(tmp_path)
    config = mrun.MesaConfig.setup(mesa_dir=mesa_dir)
    defaults = make_defaults(config)

    project = tmp_path / "project"
    project.mkdir()

    model = build_star_model(name="m1", defaults=defaults, n_inlists=1)
    model_dir = mrun.create_modeldir(model=model, projectdir_path=project, config=config)

    assert model_dir == project / "m1"
    assert model.model_path == model_dir
    assert model.snapshot_taken_at is not None
    assert set(model.file_snapshot.keys()) == {"inlist_0"}


def test_sync_model_with_disk_no_drift(tmp_path):
    mesa_dir = make_fake_mesa_dir(tmp_path)
    config = mrun.MesaConfig.setup(mesa_dir=mesa_dir)
    defaults = make_defaults(config)

    project = tmp_path / "project"
    project.mkdir()

    model = build_star_model(name="m2", defaults=defaults, n_inlists=1)
    mrun.create_modeldir(model=model, projectdir_path=project, config=config)

    changed = mrun.sync_model_with_disk(model=model, default_options=defaults, config=config)

    assert changed is False
    assert model.updated_at is None


def test_sync_model_with_disk_reloads_on_drift(tmp_path):
    mesa_dir = make_fake_mesa_dir(tmp_path)
    config = mrun.MesaConfig.setup(mesa_dir=mesa_dir)
    defaults = make_defaults(config)

    project = tmp_path / "project"
    project.mkdir()

    model = build_star_model(name="m3", defaults=defaults, n_inlists=1)
    mrun.create_modeldir(model=model, projectdir_path=project, config=config)

    old_snapshot = dict(model.file_snapshot)
    inlist_path = model.model_path / "inlist_0"
    inlist_path.write_text(
        inlist_path.read_text(encoding="utf-8") + "\n! manual drift\n",
        encoding="utf-8",
    )

    changed = mrun.sync_model_with_disk(model=model, default_options=defaults, config=config)

    assert changed is True
    assert model.updated_at is not None
    assert model.file_snapshot != old_snapshot
    assert set(model.inlists.keys()) == {"inlist_0"}


def test_sync_model_with_disk_handles_removed_inlist(tmp_path):
    mesa_dir = make_fake_mesa_dir(tmp_path)
    config = mrun.MesaConfig.setup(mesa_dir=mesa_dir)
    defaults = make_defaults(config)

    project = tmp_path / "project"
    project.mkdir()

    model = build_star_model(name="m4", defaults=defaults, n_inlists=2)
    mrun.create_modeldir(model=model, projectdir_path=project, config=config)

    (model.model_path / "inlist_1").unlink()

    changed = mrun.sync_model_with_disk(model=model, default_options=defaults, config=config)

    assert changed is True
    assert set(model.inlists.keys()) == {"inlist_0"}