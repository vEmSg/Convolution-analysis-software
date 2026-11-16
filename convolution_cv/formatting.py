"""Presentation-only formatting shared by desktop and readable reports."""

from decimal import Decimal, ROUND_HALF_UP, localcontext
from math import isfinite


def _rounded(value: Decimal, exponent: int) -> str:
    with localcontext() as context:
        context.prec = max(28, value.adjusted() - exponent + 3)
        rounded = value.quantize(Decimal(1).scaleb(exponent), rounding=ROUND_HALF_UP)
    if rounded == 0:
        rounded = abs(rounded)  # Avoid displaying a negative zero.
    return format(rounded, "f")


def format_e0(e0_v: float, error_v: float | None = None) -> str:
    """Format E0 in V and its optional error in mV, using unrounded error thresholds.

    <= 0.5 mV: four E0 decimals. Above that, use three decimals until 10 mV,
    two until 100 mV, one until 1000 mV, then progressively coarser rounding.
    None means error analysis has not been run; NaN/inf mean unavailable error.
    """
    if not isfinite(e0_v):
        return "Unavailable"
    value = Decimal(str(e0_v))
    if error_v is None:
        return f"{_rounded(value, -4)} V"
    if not isfinite(error_v) or error_v < 0:
        return f"{_rounded(value, -4)} V ± unavailable"
    error = Decimal(str(error_v))
    exponent = -4 if error <= Decimal("0.0005") else max(-3, error.adjusted())
    return f"{_rounded(value, exponent)} V ± {_rounded(error * 1000, -1)} mV"


def format_k_s(k_s: float | None, error=None) -> str:
    """Three significant digits alone; two in error, at least two in the center.

    Minimum two center digits overrides matching the error's decimal place when
    the error is very large. Non-finite bounds never become a finite ± value.
    """
    if k_s is None or not isfinite(k_s) or k_s <= 0:
        return "Unavailable"
    value = Decimal(str(k_s))
    status = error.status if error is not None else "not_calculated"
    step = value.adjusted() - 2
    error_value = None
    if status == "finite":
        raw_error = error.symmetric_error_cm_per_s
        if raw_error is None or not isfinite(raw_error) or raw_error < 0:
            status = "unavailable"
        elif raw_error == 0:
            error_value = Decimal("0")
        else:
            raw = Decimal(str(raw_error))
            error_value = Decimal(_rounded(raw, raw.adjusted() - 1))
            # Re-evaluate after carry: 9.99 -> 10 (two significant digits).
            error_step = error_value.adjusted() - 1
            error_value = Decimal(_rounded(error_value, error_step))
            step = min(error_step, value.adjusted() - 1)
    rounded = Decimal(_rounded(value, step))
    if status != "finite" or error_value == 0:
        step = rounded.adjusted() - 2  # Three digits even across 9.999 -> 10.0.
        rounded = Decimal(_rounded(value, step))
    power = rounded.adjusted()
    if status == "finite" and error_value is not None and error_value > 0:
        # Keep both coefficients below 10, so e.g. an error of 0.10 stays
        # explicitly two-significant-digit '1.0', not an ambiguous '100'.
        power = max(power, error_value.adjusted())
    superscript = str(power).translate(str.maketrans("-0123456789", "⁻⁰¹²³⁴⁵⁶⁷⁸⁹"))
    scale = f" × 10{superscript}" if power else ""
    center_text = _rounded(rounded.scaleb(-power), step - power)
    if status == "finite" and error_value is not None:
        error_text = "0" if error_value == 0 else _rounded(
            error_value.scaleb(-power), error_value.adjusted() - 1 - power)
        return f"({center_text} ± {error_text}){scale} cm/s"
    suffix = "" if status == "not_calculated" else f" · error {status}"
    return f"{center_text}{scale} cm/s{suffix}"
