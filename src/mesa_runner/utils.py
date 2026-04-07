import math

def python_float_to_fortran_string(value: float, sig: int = 15) -> str:
    """Convert Python float to compact Fortran double notation."""
    if not math.isfinite(value):
        raise ValueError("Value must be finite.")

    s = format(value, f".{sig}g")  # compact decimal/scientific form

    if "e" in s or "E" in s:
        mantissa, exp = s.lower().split("e", 1)
        return f"{mantissa}d{int(exp)}"

    return f"{s}d0"

def fortran_float_string_to_float(text: str) -> float:
    return float(text.strip().lower().replace("d", "e"))

def normalize_inlist_value_for_output(value: str, sig: int = 15) -> str:
    """Normalize a value for writing to an inlist.

    - Numeric-like values are rewritten to compact Fortran d notation.
    - .true./.false. are normalized to lowercase.
    - Non-numeric strings are returned stripped.
    """
    text = value.strip()
    lowered = text.lower()

    if lowered in {".true.", ".false."}:
        return lowered

    try:
        number = fortran_float_string_to_float(text)
    except ValueError:
        return text

    return python_float_to_fortran_string(number, sig=sig)


def normalize_inlist_value_for_compare(value: str | None, sig: int = 15) -> str:
    """Canonical form for robust equality checks."""
    if value is None:
        return ""

    text = value.strip()
    if text == "":
        return ""

    lowered = text.lower()
    if lowered in {".true.", ".false."}:
        return lowered

    try:
        number = fortran_float_string_to_float(text)
    except ValueError:
        # Keep non-numeric comparison strict except for outer whitespace.
        return text

    # Stable representation for equality comparison.
    return f"{number:.16e}"


def inlist_values_match(left: str | None, right: str | None, sig: int = 15) -> bool:
    return normalize_inlist_value_for_compare(left, sig=sig) == normalize_inlist_value_for_compare(right, sig=sig)