import logging
from pathlib import Path

import pytest

import morpy as mrun


DATA_DIR = Path(__file__).parent / "data_for_tests"


def make_config(tmp_path, version_name: str) -> mrun.MesaConfig:
    mesa_dir = tmp_path / version_name
    mesa_dir.mkdir(parents=True, exist_ok=True)
    return mrun.MesaConfig.setup(version_name=version_name, mesa_dir=mesa_dir)


def build_defaults(tmp_path, version_name: str):
    config = make_config(tmp_path, version_name)
    defaults = mrun.build_defaults_options(
        defaults_dir=DATA_DIR / version_name / "defaults",
        config=config,
    )
    return config, defaults


def morpy_messages(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == "morpy"]


def write_unknown_option_inlist(path: Path) -> None:
    path.write_text(
        "&controls\n"
        "   initial_mass = 1.0d0\n"
        "   definitely_not_a_real_option = 42\n"
        "/\n",
        encoding="utf-8",
    )


def test_no_pgbinary_defaults_logs_info(tmp_path, morpy_caplog):
    # r12778 predates the separate pgbinary defaults file.
    build_defaults(tmp_path, "r12778")

    records = [r for r in morpy_caplog.records if r.name == "morpy"]
    assert len(records) == 1
    assert records[0].levelno == logging.INFO
    assert "does not have a separate default PGBINARY namelist" in records[0].getMessage()


def test_pgbinary_defaults_present_does_not_log(tmp_path, morpy_caplog):
    build_defaults(tmp_path, "r24.08.1")

    assert morpy_messages(morpy_caplog) == []


def test_unknown_option_allowed_logs_info_with_details(tmp_path, morpy_caplog):
    config, defaults = build_defaults(tmp_path, "r24.08.1")
    inlist_path = tmp_path / "inlist"
    write_unknown_option_inlist(inlist_path)

    morpy_caplog.clear()
    mrun.parse_inlist(
        source_path=inlist_path,
        config=config,
        default_options=defaults,
        allow_unknown_options=True,
    )

    records = [r for r in morpy_caplog.records if r.name == "morpy"]
    assert len(records) == 1
    assert records[0].levelno == logging.INFO
    message = records[0].getMessage()
    assert "unknown option was detected" in message
    assert "controls: definitely_not_a_real_option" in message


def test_unknown_option_strict_raises_and_does_not_log(tmp_path, morpy_caplog):
    config, defaults = build_defaults(tmp_path, "r24.08.1")
    inlist_path = tmp_path / "inlist"
    write_unknown_option_inlist(inlist_path)

    morpy_caplog.clear()
    with pytest.raises(ValueError, match="Unknown options found"):
        mrun.parse_inlist(
            source_path=inlist_path,
            config=config,
            default_options=defaults,
            allow_unknown_options=False,
        )

    assert morpy_messages(morpy_caplog) == []


def test_known_options_only_does_not_log(tmp_path, morpy_caplog):
    config, defaults = build_defaults(tmp_path, "r24.08.1")
    inlist_path = tmp_path / "inlist"
    inlist_path.write_text(
        "&controls\n   initial_mass = 1.0d0\n/\n", encoding="utf-8"
    )

    morpy_caplog.clear()
    mrun.parse_inlist(
        source_path=inlist_path,
        config=config,
        default_options=defaults,
        allow_unknown_options=True,
    )

    assert morpy_messages(morpy_caplog) == []


def test_remove_missing_option_logs_info(tmp_path, morpy_caplog):
    build_defaults(tmp_path, "r24.08.1")
    inlist = mrun.Inlist.empty(name="inlist_test")

    morpy_caplog.clear()
    removed = inlist.remove_option("initial_mass")

    assert removed is False
    records = [r for r in morpy_caplog.records if r.name == "morpy"]
    assert len(records) == 1
    assert records[0].levelno == logging.INFO
    message = records[0].getMessage()
    assert "'initial_mass'" in message
    assert "'inlist_test'" in message
    assert "nothing was removed" in message


def test_remove_existing_option_does_not_log(tmp_path, morpy_caplog):
    _, defaults = build_defaults(tmp_path, "r24.08.1")
    inlist = mrun.Inlist.empty(name="inlist_test")
    inlist.set_option(
        name="initial_mass", value=1.0, defaults=defaults, namelist="controls"
    )

    morpy_caplog.clear()
    removed = inlist.remove_option("initial_mass")

    assert removed is True
    assert morpy_messages(morpy_caplog) == []


def test_print_info_msgs_toggles_info_output(tmp_path, morpy_caplog):
    build_defaults(tmp_path, "r24.08.1")
    inlist = mrun.Inlist.empty(name="inlist_test")
    logger = logging.getLogger("morpy")

    try:
        mrun.print_info_msgs(False)
        assert logger.level == logging.WARNING
        morpy_caplog.clear()
        inlist.remove_option("missing_option")
        assert morpy_messages(morpy_caplog) == []

        mrun.print_info_msgs(True)
        assert logger.level == logging.INFO
        inlist.remove_option("missing_option")
        assert len(morpy_messages(morpy_caplog)) == 1
    finally:
        mrun.print_info_msgs(True)
