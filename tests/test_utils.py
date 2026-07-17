import math
import pytest

from morpy.utils import (
    python_float_to_fortran_string,
    fortran_float_string_to_float,
    fortran_value_to_python_value
)


# =============================================================================
# python_float_to_fortran_string
# =============================================================================

def test_python_float_to_fortran_string_regular_decimal():
    assert python_float_to_fortran_string(2.13) == "2.13d0"


def test_python_float_to_fortran_string_integer_like_float():
    assert python_float_to_fortran_string(2.0) == "2d0"


def test_python_float_to_fortran_string_small_decimal():
    assert python_float_to_fortran_string(0.02) == "0.02d0"


def test_python_float_to_fortran_string_scientific_notation_positive():
    assert python_float_to_fortran_string(2e-5) == "2d-5"


def test_python_float_to_fortran_string_scientific_notation_negative():
    assert python_float_to_fortran_string(-2e-5) == "-2d-5"


def test_python_float_to_fortran_string_negative_regular():
    assert python_float_to_fortran_string(-2.13) == "-2.13d0"


def test_python_float_to_fortran_string_respects_sig():
    # .3g(2.12345) -> "2.12"
    assert python_float_to_fortran_string(2.12345, sig=3) == "2.12d0"


def test_python_float_to_fortran_string_rejects_non_finite_inf():
    with pytest.raises(ValueError, match="finite"):
        python_float_to_fortran_string(math.inf)


def test_python_float_to_fortran_string_rejects_non_finite_nan():
    with pytest.raises(ValueError, match="finite"):
        python_float_to_fortran_string(math.nan)


# =============================================================================
# fortran_float_string_to_float
# =============================================================================

def test_fortran_float_string_to_float_lower_d():
    assert fortran_float_string_to_float("2d-1") == pytest.approx(0.2)


def test_fortran_float_string_to_float_upper_d_and_whitespace():
    assert fortran_float_string_to_float("   -1.23D+2  ") == pytest.approx(-123.0)


def test_fortran_float_string_to_float_plain_decimal():
    assert fortran_float_string_to_float("2.13") == pytest.approx(2.13)


def test_fortran_float_string_to_float_invalid_raises():
    with pytest.raises(ValueError):
        fortran_float_string_to_float("not_a_number")


# =============================================================================
# Round-trip sanity
# =============================================================================

@pytest.mark.parametrize("value", [0.0, 2.0, 2.13, -2.13, 2e-5, -2e-5, 1.23456789e12])
def test_round_trip_python_to_fortran_to_python(value):
    text = python_float_to_fortran_string(value)
    back = fortran_float_string_to_float(text)
    assert back == pytest.approx(value)

# =============================================================================
# fortran_value_to_python_value
# =============================================================================
@pytest.mark.parametrize(
    "raw, expected",
    [
        (".true.", True),
        (".false.", False),
        ("  .TRUE.  ", True),
        ("10", 10),
        ("-3", -3),
        ("10d0", 10.0),
        ("1e1", 10.0),
        ("2.5", 2.5),
        ("'abc'", "abc"),
        ('"abc"', "abc"),
        ("'Jan''s model'", "Jan's model"),
        ("not_a_number", "not_a_number"),
    ],
)
def test_fortran_value_to_python_value(raw, expected):
    assert fortran_value_to_python_value(raw) == expected