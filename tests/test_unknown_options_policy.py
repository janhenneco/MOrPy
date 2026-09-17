from pathlib import Path

import pytest
import morpy as mrun


DATA_DIR = Path(__file__).parent / "data_for_tests"


def make_fake_mesa_dir(tmp_path, version_raw: str = "r24.08.1") -> Path:
    mesa_dir = tmp_path / "mesa"
    (mesa_dir / "data").mkdir(parents=True)
    (mesa_dir / "data" / "version_number").write_text(version_raw, encoding="utf-8")
    return mesa_dir


def make_defaults(config: mrun.MesaConfig) -> mrun.DefaultsOptions:
    return mrun.build_defaults_options(
        defaults_dir=DATA_DIR / "r24.08.1" / "defaults",
        config=config,
    )


def write_inlist_with_unknown_option(path: Path) -> None:
    path.write_text(
        "&controls\n"
        "   initial_mass = 1.0d0\n"
        "   definitely_not_a_real_option = 42\n"
        "/\n",
        encoding="utf-8",
    )


def test_parse_inlist_strict_mode_raises_on_unknown_option(tmp_path):
    mesa_dir = make_fake_mesa_dir(tmp_path)
    config = mrun.MesaConfig.setup(mesa_dir=mesa_dir)
    defaults = make_defaults(config)

    inlist_path = tmp_path / "inlist"
    write_inlist_with_unknown_option(inlist_path)

    with pytest.raises(ValueError, match="Unknown options found"):
        mrun.parse_inlist(
            source_path=inlist_path,
            config=config,
            default_options=defaults,
            allow_unknown_options=False,
        )


def test_parse_inlist_allow_mode_warns_and_keeps_unknown_option(tmp_path):
    mesa_dir = make_fake_mesa_dir(tmp_path)
    config = mrun.MesaConfig.setup(mesa_dir=mesa_dir)
    defaults = make_defaults(config)

    inlist_path = tmp_path / "inlist"
    write_inlist_with_unknown_option(inlist_path)

    with pytest.warns(RuntimeWarning, match="Unknown inlist options found"):
        inlist = mrun.parse_inlist(
            source_path=inlist_path,
            config=config,
            default_options=defaults,
            allow_unknown_options=True,
        )

    assert "initial_mass" in inlist.options
    assert "definitely_not_a_real_option" in inlist.options


def test_parse_inlist_case_insensitively_canonicalizes_known_options(tmp_path):
    mesa_dir = make_fake_mesa_dir(tmp_path)
    config = mrun.MesaConfig.setup(mesa_dir=mesa_dir)
    defaults = make_defaults(config)

    inlist_path = tmp_path / "inlist"
    inlist_path.write_text(
        "&controls\n"
        "   INITIAL_MASS = 1.0d0\n"
        "   OVERSHOOT_F(2) = 0.014d0\n"
        "   UNKNOWN_Option = 42\n"
        "/\n",
        encoding="utf-8",
    )

    with pytest.warns(RuntimeWarning, match="Unknown inlist options found"):
        inlist = mrun.parse_inlist(
            source_path=inlist_path,
            config=config,
            default_options=defaults,
            allow_unknown_options=True,
        )

    assert "initial_mass" in inlist.options
    assert "overshoot_f(2)" in inlist.options
    assert "UNKNOWN_Option" in inlist.options


def test_import_inlists_from_dir_strict_mode_raises(tmp_path):
    mesa_dir = make_fake_mesa_dir(tmp_path)
    config = mrun.MesaConfig.setup(mesa_dir=mesa_dir)
    defaults = make_defaults(config)

    inlist_dir = tmp_path / "inlists"
    inlist_dir.mkdir()
    write_inlist_with_unknown_option(inlist_dir / "inlist_1")

    model = mrun.Model.empty(name="m_strict")

    with pytest.raises(ValueError, match="Unknown options found"):
        mrun.import_inlists_from_dir(
            model=model,
            source_dir=inlist_dir,
            default_options=defaults,
            config=config,
        )


def test_import_inlists_from_dir_allow_mode_warns_and_imports(tmp_path):
    mesa_dir = make_fake_mesa_dir(tmp_path)
    config = mrun.MesaConfig.setup(mesa_dir=mesa_dir)
    defaults = make_defaults(config)

    inlist_dir = tmp_path / "inlists"
    inlist_dir.mkdir()
    write_inlist_with_unknown_option(inlist_dir / "inlist_1")

    model = mrun.Model.empty(name="m_allow")

    with pytest.warns(RuntimeWarning, match="Unknown inlist options found"):
        mrun.import_inlists_from_dir(
            model=model,
            source_dir=inlist_dir,
            default_options=defaults,
            config=config,
            allow_unknown_options=True,
        )

    assert "inlist_1" in model.inlists
    assert "definitely_not_a_real_option" in model.inlists["inlist_1"].options