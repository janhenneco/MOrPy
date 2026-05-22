import pytest

from mesa_runner.config import MesaVersion
from mesa_runner.model import Model
from mesa_runner.options import Inlist, MesaOption


def make_version():
    return MesaVersion.parse_mesa_version("r24.08.1")


def make_option(name: str, *, current: str = "1.0d0", namelist: str = "controls") -> MesaOption:
    return MesaOption(
        name=name,
        default_option="0.0d0",
        current_value=current,
        description=f"desc-{name}",
        namelist=namelist,
    )


def make_inlist(name: str = "inlist_test") -> Inlist:
    v = make_version()
    il = Inlist.empty(name=name, mesa_version=v)
    il.options["initial_mass"] = make_option("initial_mass", current="15.0d0")
    il.options["overshoot_f(1)"] = make_option("overshoot_f(1)", current="0.02")
    return il


def make_model(name: str = "m1") -> Model:
    v = make_version()
    model = Model.empty(name=name, mesa_version=v)
    model.add_inlist(make_inlist("inlist_main"))
    return model


def test_inlist_copy_deep_isolates_mesaoption_mutation():
    original = make_inlist("inlist_a")
    copied = original.copy()

    copied.options["initial_mass"].current_value = "30.0d0"
    copied.options["overshoot_f(1)"].description = "changed"

    assert original.options["initial_mass"].current_value == "15.0d0"
    assert original.options["overshoot_f(1)"].description != "changed"


def test_inlist_copy_shallow_shares_mesaoption_instances():
    original = make_inlist("inlist_b")
    copied = original.copy(deep_copy=False)

    copied.options["initial_mass"].current_value = "31.0d0"

    # shallow copy should share MesaOption objects
    assert original.options["initial_mass"].current_value == "31.0d0"


def test_model_copy_default_deep_isolates_nested_inlists():
    original = make_model("m_original")
    copied = original.copy()

    copied.inlists["inlist_main"].options["initial_mass"].current_value = "40.0d0"
    copied.inlists["inlist_main"].options["new_param"] = make_option("new_param", current="123")

    assert original.inlists["inlist_main"].options["initial_mass"].current_value == "15.0d0"
    assert "new_param" not in original.inlists["inlist_main"].options


def test_model_copy_shallow_shares_nested_inlists():
    original = make_model("m_original2")
    copied = original.copy(deep_copy=False)

    copied.inlists["inlist_main"].options["initial_mass"].current_value = "50.0d0"

    # shallow copy should share inlist/option objects
    assert original.inlists["inlist_main"].options["initial_mass"].current_value == "50.0d0"


def test_model_copy_uses_new_name_and_preserves_mesa_version():
    original = make_model("base")
    copied = original.copy(name="base_clone")

    assert copied.name == "base_clone"
    assert copied.mesa_version == original.mesa_version
    assert copied.model_id != original.model_id


def test_inlist_copy_name_override():
    original = make_inlist("orig_inlist")
    copied = original.copy(name="copied_inlist")

    assert copied.name == "copied_inlist"
    assert original.name == "orig_inlist"