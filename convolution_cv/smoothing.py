"""Shared preview/analysis smoothing; potential windows are full spans in mV."""

import numpy as np
from scipy.signal import savgol_filter


DEFAULTS = {"smoothing_enabled": "True", "smoothing_window_mv": "20", "smoothing_order": "2"}


def parse_smoothing(values):
    enabled_text = str(values.get("smoothing_enabled", "True")).lower()
    if enabled_text not in {"true", "false", "1", "0"}:
        raise ValueError("Choose no smoothing or SG smoothing.")
    enabled = enabled_text in {"true", "1"}
    try:
        window = float(values.get("smoothing_window_mv", 20))
        order = float(values.get("smoothing_order", 2))
        if not np.isfinite(window) or window <= 0:
            raise ValueError("SG window must be positive and finite (mV).")
        if not np.isfinite(order) or order < 0 or not order.is_integer():
            raise ValueError("SG order must be a non-negative integer.")
    except (ValueError, TypeError) as exc:
        if enabled:
            raise ValueError("Enter a positive window in mV and a non-negative integer order.") from exc
        window, order = 20.0, 2
    return dict(smoothing_enabled=enabled, smoothing_window_mv=window, smoothing_order=int(order))


def smooth_current(potential, current, config):
    """Return (trace, odd sample count, effective span, spacing warnings).

    Use the median nonzero absolute step across scans; choose the nearest odd
    neighborhood by full endpoint-to-endpoint span (ties round up). Never shrink
    an oversized window or raise it to accommodate an invalid polynomial order.
    """
    config.validate()
    if not config.smoothing_enabled:
        return np.asarray(current).copy(), 0, 0.0, []
    steps = np.abs(np.diff(potential))
    steps = steps[np.isfinite(steps) & (steps > 0)]
    if not len(steps):
        raise ValueError("SG smoothing needs distinct potential samples.")
    step_mv = float(np.median(steps)) * 1000
    points = 2 * int(np.floor(config.smoothing_window_mv / (2 * step_mv) + 0.5 + 1e-10)) + 1
    if points < 3:
        raise ValueError(f"SG window is too narrow for this data. Use at least {2 * step_mv:g} mV.")
    if points > len(current):
        raise ValueError(f"SG window needs {points} samples, but the trace has only {len(current)}. Reduce the window.")
    if config.smoothing_order >= points:
        raise ValueError(f"SG order must be less than the effective window ({points} samples).")
    warnings = []
    if not np.allclose(steps, step_mv / 1000, rtol=0.01, atol=1e-12):
        warnings.append("Potential spacing varies: the SG window uses the median step; local spans are approximate.")
    return savgol_filter(current, points, config.smoothing_order), points, (points - 1) * step_mv, warnings
