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


def _is_fortran_logical(text: str | None) -> bool:
    if text is None:
        return False
    return text.strip().lower() in {".true.", ".false."}


def _is_quoted_string(text: str | None) -> bool:
    if text is None:
        return False
    stripped = text.strip()
    return len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in {"'", '"'}


def _looks_like_float_default(text: str | None) -> bool:
    if text is None:
        return False
    stripped = text.strip().lower()
    if stripped in {"", ".true.", ".false."}:
        return False
    return any(ch in stripped for ch in (".", "d", "e"))


def _quote_fortran_string(text: str) -> str:
    escaped = text.replace("'", "''")
    return f"'{escaped}'"


def python_value_to_inlist_value(value: object, default_option: str | None = None) -> str:
    """Convert a Python value into a MESA inlist value string.

    The default value is used as a hint for how to serialize the input.
    """
    if isinstance(value, bool):
        return ".true." if value else ".false."

    if isinstance(value, int) and not isinstance(value, bool):
        if _looks_like_float_default(default_option):
            return python_float_to_fortran_string(float(value))
        return str(value)

    if isinstance(value, float):
        return python_float_to_fortran_string(value)

    if isinstance(value, str):
        text = value.strip()

        if _is_fortran_logical(default_option):
            lowered = text.lower()
            if lowered in {"true", ".true."}:
                return ".true."
            if lowered in {"false", ".false."}:
                return ".false."

        if _is_quoted_string(default_option):
            if _is_quoted_string(text):
                return text
            return _quote_fortran_string(text)

        return normalize_inlist_value_for_output(text)

    raise TypeError(
        "Unsupported value type for inlist option. "
        f"Got {type(value).__name__}."
    )

def fortran_value_to_python_value(text: str) -> bool | int | float | str:
    """Convert a raw Fortran/MESA inlist value string to a Python value."""
    t = text.strip()
    low = t.lower()

    if low == ".true.":
        return True
    if low == ".false.":
        return False

    if len(t) >= 2 and t[0] == t[-1] and t[0] in {"'", '"'}:
        inner = t[1:-1]
        if t[0] == "'":
            inner = inner.replace("''", "'")
        return inner

    try:
        # float-like tokens: 1.0, 1d0, 1e0
        if any(ch in low for ch in (".", "d", "e")):
            return fortran_float_string_to_float(t)
        # otherwise try int
        return int(t)
    except ValueError:
        return t