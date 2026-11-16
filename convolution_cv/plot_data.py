"""Presentation-only masks. These never modify numerical results or acceptance rules."""

import numpy as np


def finite_line(values, mask=None):
    values = np.asarray(values, dtype=float)
    valid = np.isfinite(values)
    if mask is not None:
        valid &= mask
    return np.where(valid, values, np.nan)


def kinetic_masks(result, scan):
    center = getattr(result, f"{scan}_lgk_r")
    lower = getattr(result, f"{scan}_lgk_r_min")
    upper = getattr(result, f"{scan}_lgk_r_max")
    # New bounds use +inf; retain recognition of old in-memory sentinel results.
    unbounded = np.isposinf(upper) | ((upper == 100.0) if result.error_analysis is None else False)
    valid = np.isfinite(center)
    bounded = valid & np.isfinite(lower) & np.isfinite(upper) & ~unbounded
    accepted = np.zeros(len(center), dtype=bool)
    accepted[getattr(result, f"chosen_{scan}_indices")] = True
    return valid, bounded, unbounded, accepted
