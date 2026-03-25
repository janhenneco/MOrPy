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