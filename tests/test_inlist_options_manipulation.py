from pathlib import Path

import pytest

import morpy as mrun
from morpy.options import Inlist


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
def defaults_r12778(tmp_path, morpy_caplog):
    version_name = "r12778"
    config = make_config(tmp_path, version_name)
    defaults = mrun.build_defaults_options(
        defaults_dir=DATA_DIR / version_name / "defaults",
        config=config,
    )
    assert any(
        "does not have a separate default PGBINARY namelist" in record.message
        for record in morpy_caplog.records
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
    _, defaults = defaults_r24081
    inlist = Inlist.empty(name="inlist_test", source_path=Path("inlist_test"))

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
    _, defaults = defaults_r24081
    inlist = Inlist.empty(name="inlist_test", source_path=Path("inlist_test"))

    # initial_mass is a well-known numeric controls option
    new_opt = inlist.set_option(
        name="initial_mass",
        value=10,
        defaults=defaults,
        namelist="controls",
    )

    assert new_opt.current_value == "10"
    assert inlist.options["initial_mass"].current_value == "10"


def test_set_option_case_insensitively_uses_canonical_name(defaults_r24081):
    _, defaults = defaults_r24081
    inlist = Inlist.empty(name="inlist_test", source_path=Path("inlist_test"))

    inlist.set_option(
        name="INITIAL_MASS",
        value=10,
        defaults=defaults,
        namelist="controls",
    )
    inlist.set_option(
        name="initial_mass",
        value=12,
        defaults=defaults,
        namelist="controls",
    )

    assert list(inlist.options) == ["initial_mass"]
    assert inlist.options["initial_mass"].current_value == "12"
    assert inlist.get_python_value("INITIAL_MASS") == 12
    assert inlist.remove_option("INITIAL_MASS") is True
    assert not inlist.options


def test_set_option_case_insensitively_preserves_array_index(defaults_r24081):
    _, defaults = defaults_r24081
    inlist = Inlist.empty(name="inlist_test", source_path=Path("inlist_test"))

    inlist.set_option(
        name="OVERSHOOT_F(2)",
        value=0.014,
        defaults=defaults,
        namelist="controls",
    )

    assert "overshoot_f(2)" in inlist.options


def test_set_options_bulk_grouped_and_flat(defaults_r24081):
    _, defaults = defaults_r24081
    inlist = Inlist.empty(name="inlist_test", source_path=Path("inlist_test"))

    inlist.set_options(
        defaults=defaults,
        controls={"initial_mass": 12, "max_model_number": 500},
    )

    assert inlist.options["initial_mass"].current_value == "12"
    assert inlist.options["max_model_number"].current_value == "500"


def test_set_options_flat_ambiguous_raises(defaults_r24081):
    _, defaults = defaults_r24081
    inlist = Inlist.empty(name="inlist_test", source_path=Path("inlist_test"))

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
    _, defaults = defaults_r24081
    inlist = Inlist.empty(name="inlist_test", source_path=Path("inlist_test"))

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
    _, defaults = defaults_r24081
    inlist = Inlist.empty(name="inlist_test", source_path=Path("inlist_test"))

    inlist.set_option(
        name="change_net",
        value=True,
        defaults=defaults,
        namelist="star_job",
    )

    assert inlist.get_python_value("change_net") is True

def test_options_equal_can_ignore_default_valued_presence(defaults_r24081):
    _, defaults = defaults_r24081

    a = Inlist.empty(name="a")
    b = Inlist.empty(name="b")

    # Same effective value, different representation:
    # a omits option; b includes it at default value.
    default_opt = defaults.controls.options["initial_mass"]
    b.options["initial_mass"] = mrun.MesaOption(
        name="initial_mass",
        default_option=default_opt.default_option,
        description=default_opt.description,
        namelist="controls",
        current_value=default_opt.default_option,
    )

    assert a._options_equal(b, ignore_default_valued=True) is True
    assert a._options_equal(b, ignore_default_valued=False) is False


def test_sync_with_source_ignores_removed_default_options_when_enabled(
    tmp_path,
    defaults_r24081,
):
    config, defaults = defaults_r24081

    source = tmp_path / "inlist_test"
    source.write_text(
        "&controls\n"
        "   initial_mass = 1 ! DEFAULT\n"
        "/ ! end of controls namelist\n",
        encoding="utf-8",
    )

    inlist = mrun.parse_inlist(source_path=source, config=config, default_options=defaults)

    # Remove the whole block (do not leave an empty known block behind).
    source.write_text("", encoding="utf-8")

    changed = inlist.sync_with_source(
        config=config,
        default_options=defaults,
        on_difference="decouple",
        ignore_default_valued_options=True,
    )

    assert changed is False
    assert inlist.source_path == source


def test_parse_inlist_tracks_empty_known_namelists(tmp_path, defaults_r24081):
    config, defaults = defaults_r24081

    source = tmp_path / "inlist_empty_blocks"
    source.write_text(
        "&star_job\n"
        "/ ! end of star_job namelist\n"
        "\n"
        "&eos\n"
        "/ ! end of eos namelist\n"
        "\n"
        "&controls\n"
        "   initial_mass = 1\n"
        "/ ! end of controls namelist\n"
        "\n"
        "&unknown_block\n"
        "/ ! end of unknown_block namelist\n",
        encoding="utf-8",
    )

    inlist = mrun.parse_inlist(source_path=source, config=config, default_options=defaults)

    assert "star_job" in inlist.empty_namelists
    assert "eos" in inlist.empty_namelists
    assert "controls" not in inlist.empty_namelists
    assert len(inlist.additional_options) == 1
    assert inlist.additional_options[0].name == "unknown_block"


def test_write_preserves_empty_known_namelists_from_parsed_inlist(tmp_path, defaults_r24081):
    config, defaults = defaults_r24081

    source = tmp_path / "inlist_with_empty_known_blocks"
    source.write_text(
        "&star_job\n"
        "/ ! end of star_job namelist\n"
        "\n"
        "&eos\n"
        "/ ! end of eos namelist\n",
        encoding="utf-8",
    )

    parsed = mrun.parse_inlist(source_path=source, config=config, default_options=defaults)
    assert "star_job" in parsed.empty_namelists
    assert "eos" in parsed.empty_namelists

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    written_path = parsed.write(output_path=out_dir)

    written_text = written_path.read_text(encoding="utf-8")
    assert "&star_job" in written_text
    assert "/ ! end of star_job namelist" in written_text
    assert "&eos" in written_text
    assert "/ ! end of eos namelist" in written_text

    reparsed = mrun.parse_inlist(source_path=written_path, config=config, default_options=defaults)
    assert "star_job" in reparsed.empty_namelists
    assert "eos" in reparsed.empty_namelists


def test_sync_with_source_detects_empty_namelist_drift(tmp_path, defaults_r24081):
    config, defaults = defaults_r24081

    source = tmp_path / "inlist_empty_drift"
    source.write_text(
        "&star_job\n"
        "/ ! end of star_job namelist\n"
        "\n"
        "&controls\n"
        "   initial_mass = 1\n"
        "/ ! end of controls namelist\n",
        encoding="utf-8",
    )

    inlist = mrun.parse_inlist(source_path=source, config=config, default_options=defaults)
    assert "star_job" in inlist.empty_namelists

    # Remove only the empty known block; keep options identical.
    source.write_text(
        "&controls\n"
        "   initial_mass = 1\n"
        "/ ! end of controls namelist\n",
        encoding="utf-8",
    )

    changed = inlist.sync_with_source(
        default_options=defaults,
        config=config,
        on_difference="decouple",
    )

    assert changed is True
    assert inlist.source_path == source
    assert "star_job" not in inlist.empty_namelists