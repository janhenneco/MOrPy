from pathlib import Path

import pytest

import mesa_runner as mrun
from mesa_runner.options import Inlist


DATA_DIR = Path(__file__).parent / "data_for_tests"


def make_config(tmp_path, version_name: str) -> mrun.MesaConfig:
    mesa_dir = tmp_path / version_name
    mesa_dir.mkdir(parents=True, exist_ok=True)
    return mrun.MesaConfig.setup(version_name=version_name, mesa_dir=mesa_dir)


@pytest.fixture
def defaults_r24081(tmp_path):
    version_name = "r24.08.1"
    config = make_config(tmp_path, version_name)
    defaults = mrun.build_defaults_options(
        defaults_dir=DATA_DIR / version_name / "defaults",
        config=config,
    )
    return config, defaults


@pytest.fixture
def defaults_r12778(tmp_path):
    version_name = "r12778"
    config = make_config(tmp_path, version_name)
    with pytest.warns(RuntimeWarning, match="pgbinary.defaults"):
        defaults = mrun.build_defaults_options(
            defaults_dir=DATA_DIR / version_name / "defaults",
            config=config,
        )
    return config, defaults


def pick_logical_option(defaults: mrun.DefaultsOptions):
    for defaults_file in defaults.iter_files():
        for opt in defaults_file.options.values():
            if opt.default_option.strip().lower() in {".true.", ".false."}:
                return opt
    raise AssertionError("No logical default option found in defaults.")


def test_find_option_ambiguous_name_requires_namelist(defaults_r24081):
    _, defaults = defaults_r24081

    with pytest.raises(ValueError, match="multiple namelists"):
        defaults.find_option("history_interval")


def test_set_option_bool_is_coerced_to_fortran_logical(defaults_r24081):
    config, defaults = defaults_r24081
    inlist = Inlist.empty(source_path=Path("inlist_test"), mesa_version=config.mesa_version)

    logical_opt = pick_logical_option(defaults)
    new_opt = inlist.set_option(
        name=logical_opt.name,
        value=True,
        defaults=defaults,
        namelist=logical_opt.namelist,
    )

    assert new_opt.current_value == ".true."
    assert inlist.options[logical_opt.name].current_value == ".true."


def test_set_option_float_coercion(defaults_r24081):
    config, defaults = defaults_r24081
    inlist = Inlist.empty(source_path=Path("inlist_test"), mesa_version=config.mesa_version)

    # initial_mass is a well-known numeric controls option
    new_opt = inlist.set_option(
        name="initial_mass",
        value=10,
        defaults=defaults,
        namelist="controls",
    )

    assert new_opt.current_value == "10"
    assert inlist.options["initial_mass"].current_value == "10"


def test_set_options_bulk_grouped_and_flat(defaults_r24081):
    config, defaults = defaults_r24081
    inlist = Inlist.empty(source_path=Path("inlist_test"), mesa_version=config.mesa_version)

    inlist.set_options(
        defaults=defaults,
        controls={"initial_mass": 12, "max_model_number": 500},
    )

    assert inlist.options["initial_mass"].current_value == "12"
    assert inlist.options["max_model_number"].current_value == "500"


def test_set_options_flat_ambiguous_raises(defaults_r24081):
    config, defaults = defaults_r24081
    inlist = Inlist.empty(source_path=Path("inlist_test"), mesa_version=config.mesa_version)

    with pytest.raises(ValueError, match="multiple namelists"):
        inlist.set_options(defaults=defaults, options={"history_interval": 5})


def test_set_option_overwrites_existing_option_when_same_name(defaults_r12778):
    config, defaults = defaults_r12778

    # Parse an existing inlist first, then overwrite one known option.
    inlist = mrun.parse_inlist(
        source_path=DATA_DIR / "r12778" / "inlists" / "inlist_massive_1",
        config=config,
        default_options=defaults,
    )

    before = inlist.options["retry_hold"]
    after = inlist.set_option(
        name="retry_hold",
        value=20,
        defaults=defaults,
        namelist="controls",
    )

    assert inlist.options["retry_hold"].current_value == "20"
    assert after.current_value == "20"
    assert after is inlist.options["retry_hold"]
    assert before is not after

def test_mesaoption_to_python_value_current(defaults_r24081):
    config, defaults = defaults_r24081
    inlist = Inlist.empty(source_path=Path("inlist_test"), mesa_version=config.mesa_version)

    # set integer-valued option
    opt = inlist.set_option(
        name="max_model_number",
        value=500,
        defaults=defaults,
        namelist="controls",
    )

    assert opt.current_value == "500"
    assert opt.to_python_value() == 500


def test_mesaoption_to_python_value_default_when_no_current(defaults_r24081):
    _, defaults = defaults_r24081
    opt = defaults.controls.options["initial_mass"]  # default is "1" in this dataset

    assert opt.current_value is None
    assert opt.to_python_value() == 1


def test_inlist_get_python_value(defaults_r24081):
    config, defaults = defaults_r24081
    inlist = Inlist.empty(source_path=Path("inlist_test"), mesa_version=config.mesa_version)

    inlist.set_option(
        name="change_net",
        value=True,
        defaults=defaults,
        namelist="star_job",
    )

    assert inlist.get_python_value("change_net") is True