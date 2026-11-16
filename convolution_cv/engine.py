from dataclasses import replace
from io import BytesIO
from pathlib import Path
from typing import Callable, Iterable, Optional, Tuple

import numpy as np
import pandas as pd
from scipy.signal import fftconvolve
from .smoothing import smooth_current
from .normalization import concentration_references, NORMALIZATION_VERSION
from .uncertainty import concentration_errors, rate_bounds, accepted_indices

from .models import (
    AnalysisConfig,
    AnalysisResult,
    BACKGROUND_CAPACITANCE,
    BACKGROUND_CV,
    CVInspection,
    KsResult,
    KsError,
    PreprocessingPreview,
    SegmentMap,
    SourceSnapshot,
)


R = 8.3145
F = 96485.0


def find_monotonic_intervals(values: Iterable[float]) -> SegmentMap:
    values = list(values)
    if len(values) < 2:
        return {}

    result = {}
    start = 0
    trend = None
    for index in range(1, len(values)):
        difference = values[index] - values[index - 1]
        if difference == 0:
            continue
        current_trend = "anodic" if difference > 0 else "cathodic"
        if trend is None:
            trend = current_trend
        elif current_trend != trend:
            result[(start, index)] = trend
            start = index
            trend = current_trend
    if trend is not None:
        result[(start, len(values))] = trend
    return result


def inspect_cv(
    cv_path: str,
    potential_column: str = "Potential/V",
    current_column: str = "Current/A",
) -> CVInspection:
    """Validate a CSV and return data/metadata without running the analysis."""

    path = Path(cv_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"CV input file does not exist: {path}")

    source = SourceSnapshot(path, path.read_bytes())
    frame = pd.read_csv(BytesIO(source.content), skipinitialspace=True)
    required = [potential_column, current_column]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(
            "The selected potential/current columns were not found. "
            f"Missing: {', '.join(missing)}. Available columns: {', '.join(map(str, frame.columns))}"
        )

    numeric = frame[required].apply(pd.to_numeric, errors="coerce").dropna()
    if len(numeric) < 3:
        raise ValueError("CV file must contain at least 3 valid rows.")
    potential = numeric[potential_column].to_numpy(dtype=float)
    current = numeric[current_column].to_numpy(dtype=float)
    if not np.all(np.isfinite(potential)) or not np.all(np.isfinite(current)):
        raise ValueError("CV input contains non-finite potential or current values.")
    segments = find_monotonic_intervals(potential)
    if not segments:
        raise ValueError("No monotonic CV scan segments could be detected.")
    warnings = []
    discarded = len(frame) - len(numeric)
    if discarded:
        warnings.append(f"{discarded} row(s) with nonnumeric or missing values were discarded.")
    steps = np.abs(np.diff(potential))
    nonzero_steps = steps[steps > 0]
    if len(nonzero_steps) and not np.allclose(
        nonzero_steps, nonzero_steps[0], rtol=1e-3, atol=1e-12
    ):
        warnings.append(
            "Potential spacing is not uniform; the current method still uses the first step."
        )
    return CVInspection(
        input_path=path,
        columns=[str(value) for value in frame.columns],
        potential_column=potential_column,
        current_column=current_column,
        total_rows=len(frame),
        valid_rows=len(numeric),
        discarded_rows=discarded,
        potential=potential,
        current=current,
        segments=segments,
        warnings=warnings,
        source=source,
    )


def _validate_background_potential(
    experiment_potential: np.ndarray,
    background: CVInspection,
) -> None:
    if len(background.potential) != len(experiment_potential):
        raise ValueError(
            "Background CV potential does not exactly match the experiment: "
            f"the experiment has {len(experiment_potential)} valid points, while the "
            f"background has {len(background.potential)}."
        )
    if not np.array_equal(background.potential, experiment_potential):
        mismatch = int(np.flatnonzero(background.potential != experiment_potential)[0])
        raise ValueError(
            "Background CV potential does not exactly match the experiment. "
            f"First mismatch at row {mismatch + 2}: experiment = "
            f"{experiment_potential[mismatch]:.12g} V, background = "
            f"{background.potential[mismatch]:.12g} V."
        )


def inspect_background_cv(
    experiment: CVInspection,
    background_cv_path: str,
) -> CVInspection:
    """Validate a background CV for exact point-to-point subtraction."""

    background = inspect_cv(background_cv_path)
    _validate_background_potential(experiment.potential, background)
    return background


def _load_cv(
    path: Path,
    potential_column: str = "Potential/V",
    current_column: str = "Current/A",
) -> Tuple[np.ndarray, np.ndarray]:
    inspection = inspect_cv(str(path), potential_column, current_column)
    return inspection.potential, inspection.current


def _correct_background(
    potential: np.ndarray,
    current: np.ndarray,
    segments: SegmentMap,
    config: AnalysisConfig,
    background: CVInspection | None = None,
) -> np.ndarray:
    if config.background_mode == BACKGROUND_CV:
        background = background or inspect_cv(config.background_cv_path)
        _validate_background_potential(potential, background)
        return current - background.current
    if config.background_mode != BACKGROUND_CAPACITANCE:
        raise ValueError("Background correction mode is not recognized.")

    direction = np.zeros(len(potential), dtype=float)
    for (start, end), label in segments.items():
        direction[start:end] = 1.0 if label == "anodic" else -1.0
    charging_current = direction * config.double_layer_capacity * config.scan_rate
    return current - charging_current


def _preprocess(
    potential: np.ndarray,
    current: np.ndarray,
    config: AnalysisConfig,
    background: CVInspection | None = None,
) -> Tuple[float, SegmentMap, np.ndarray]:
    delta_e = abs(float(potential[1] - potential[0]))
    if delta_e == 0:
        raise ValueError("The first two potential values must be different.")

    segments = find_monotonic_intervals(potential)
    if not segments:
        raise ValueError("No monotonic CV scan segments could be detected.")

    corrected = _correct_background(potential, current, segments, config, background)
    smoothed, _, _, _ = smooth_current(potential, corrected, config)
    return delta_e, segments, smoothed


def preview_preprocessing(
    cv_path: str,
    config: AnalysisConfig,
    potential_column: str = "Potential/V",
    current_column: str = "Current/A",
) -> PreprocessingPreview:
    """Return the traces and metadata required by the Review stage."""

    config.validate()
    inspection = inspect_cv(cv_path, potential_column, current_column)
    potential = inspection.potential
    current = inspection.current
    delta_e = abs(float(potential[1] - potential[0]))
    if delta_e == 0:
        raise ValueError("The first two potential values must be different.")
    background = (
        inspect_background_cv(inspection, config.background_cv_path)
        if config.background_mode == BACKGROUND_CV else None
    )
    corrected = _correct_background(
        potential, current, inspection.segments, config, background
    )
    smoothed, points, effective_mv, smoothing_warnings = smooth_current(potential, corrected, config)
    return PreprocessingPreview(
        input_path=inspection.input_path,
        potential=potential,
        raw_current=current,
        corrected_current=corrected,
        smoothed_current=smoothed,
        delta_e=delta_e,
        delta_t=delta_e / config.scan_rate,
        segments=inspection.segments,
        warnings=list(inspection.warnings) + (list(background.warnings) if background else []) + smoothing_warnings,
        source=inspection.source,
        background_source=background.source if background else None,
        smoothing_enabled=config.smoothing_enabled,
        smoothing_window_mv=config.smoothing_window_mv,
        smoothing_order=config.smoothing_order,
        smoothing_points=points,
        smoothing_effective_mv=effective_mv,
        background_current=background.current.copy() if background else None,
    )


def _surface_concentration(
    current: np.ndarray,
    delta_e: float,
    config: AnalysisConfig,
    diffusion_coefficient: float,
    final_sign: float,
) -> np.ndarray:
    """Unshifted full-history convolution; endpoint referencing is applied later."""
    area = np.pi * (config.diameter / 2.0) ** 2
    delta_t = delta_e / config.scan_rate
    constant = 1.0 / (
        np.sqrt(np.pi) * F * area * np.sqrt(diffusion_coefficient) * config.n_e
    )
    sample_number = np.arange(1, len(current) + 1)
    kernel = 2.0 * (
        np.sqrt(sample_number * delta_t) - np.sqrt((sample_number - 1) * delta_t)
    )
    convolved = fftconvolve(-current, kernel, mode="full")[: len(current)]
    concentration = final_sign * constant * convolved
    return concentration


def _find_zero_current_potential(potential: np.ndarray, current: np.ndarray) -> float:
    closest = int(np.argmin(np.abs(current)))
    fitting_n = 5
    start = max(0, closest - fitting_n)
    end = min(len(current), closest + fitting_n + 1)
    fit_potential = potential[start:end]
    fit_current = current[start:end]
    if len(fit_potential) < 2:
        raise ValueError("Not enough points near zero current to estimate E0.")
    slope, intercept = np.polyfit(fit_potential, fit_current, 1)
    if slope == 0:
        raise ValueError("The fitted current near zero has zero slope; E0 cannot be estimated.")
    return float(-intercept / slope)


def _pointwise_logk(
    conc_o: np.ndarray,
    conc_r: np.ndarray,
    current: np.ndarray,
    potential: np.ndarray,
    e0: float,
    config: AnalysisConfig,
) -> Tuple[np.ndarray, np.ndarray]:
    area = np.pi * (config.diameter / 2.0) ** 2
    exponential = np.exp(
        config.n_e * F * (potential - e0) / (R * config.temperature)
    )
    numerator = -current / (area * config.n_e * F)
    denominator = conc_o - conc_r * exponential
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        lgk_r = np.log10(numerator / denominator)
        lgk_o = lgk_r + np.log10(exponential)
    return lgk_r, lgk_o


def _logk_with_error_point(
    conc_o, conc_r, current, potential, e0, sigma_o, sigma_r, config,
    oxidation, error_e0=0.0,
):
    reduction, oxidation_values = rate_bounds(
        conc_o, conc_r, current, potential, e0, sigma_o, sigma_r, config, error_e0
    )
    return tuple(oxidation_values if oxidation else reduction)


def _kinetic_error_arrays(
    conc_o, conc_r, current, potential, e0, sigma_o, sigma_r, config, error_e0=0.0,
):
    return rate_bounds(conc_o, conc_r, current, potential, e0, sigma_o, sigma_r, config, error_e0)


def analyze_cv(
    cv_path: str,
    config: AnalysisConfig,
    progress_callback: Optional[Callable[[str], None]] = None,
    potential_column: str = "Potential/V",
    current_column: str = "Current/A",
    expected_input_sha256: str | None = None,
    expected_background_sha256: str | None = None,
) -> AnalysisResult:
    """Run the existing scientific workflow in memory without writing output files."""

    def progress(message: str) -> None:
        if progress_callback is not None:
            progress_callback(message)

    progress("Validating input")
    config.validate()
    input_path = Path(cv_path).expanduser().resolve()
    inspection = inspect_cv(str(input_path), potential_column, current_column)
    potential, raw_current = inspection.potential, inspection.current
    if expected_input_sha256 and inspection.source.sha256 != expected_input_sha256:
        raise ValueError("The input file changed after review. Refresh the preprocessing preview.")
    background = (
        inspect_background_cv(inspection, config.background_cv_path)
        if config.background_mode == BACKGROUND_CV else None
    )
    if expected_background_sha256 and (
        background is None or background.source.sha256 != expected_background_sha256
    ):
        raise ValueError("The background file changed after review. Refresh the preprocessing preview.")
    progress("Correcting background")
    delta_e, segments, processed_current = _preprocess(potential, raw_current, config, background)

    progress("Calculating surface concentrations")
    original_o = _surface_concentration(
        processed_current, delta_e, config, config.diffusion_o, final_sign=-1.0
    )
    original_r = _surface_concentration(
        processed_current, delta_e, config, config.diffusion_r, final_sign=1.0
    )

    segment_keys = list(segments.keys())
    forward_index = 2 * (config.cv_cycles_n - 1)
    backward_index = forward_index + 1
    if backward_index >= len(segment_keys):
        detected_cycles = len(segment_keys) // 2
        raise ValueError(
            f"Requested CV cycle {config.cv_cycles_n}, but only {detected_cycles} complete "
            "cycle(s) were detected."
        )

    forward_start, forward_end = segment_keys[forward_index]
    backward_start, backward_end = segment_keys[backward_index]
    references = concentration_references(potential, segments, config.cv_cycles_n)
    original_o = original_o - original_o[references["original_o"]]
    original_r = original_r - original_r[references["original_r"]]
    forward_potential = potential[forward_start:forward_end]
    forward_current = processed_current[forward_start:forward_end]
    backward_potential = potential[backward_start:backward_end]
    backward_current = processed_current[backward_start:backward_end]

    forward_o = original_o[forward_start:forward_end]
    forward_o = forward_o - original_o[references["forward_o"]]
    forward_r = original_r[forward_start:forward_end]
    forward_r = forward_r - original_r[references["forward_r"]]
    backward_o = original_o[backward_start:backward_end]
    backward_o = backward_o - original_o[references["backward_o"]]
    backward_r = original_r[backward_start:backward_end]
    backward_r = backward_r - original_r[references["backward_r"]]

    progress("Calculating electron-transfer kinetics")
    zero_current_potential = _find_zero_current_potential(backward_potential, backward_current)
    zero_index = int(np.argmin(np.abs(backward_potential - zero_current_potential)))
    ratio = backward_o[zero_index] / backward_r[zero_index]
    if not np.isfinite(ratio) or ratio <= 0:
        raise ValueError("Concentration ratio near zero current is not positive; E0 is undefined.")
    e0 = float(
        backward_potential[zero_index]
        - np.log(ratio) * R * config.temperature / (config.n_e * F)
    )

    forward_lgk_r, forward_lgk_o = _pointwise_logk(
        forward_o, forward_r, forward_current, forward_potential, e0, config
    )
    backward_lgk_r_original, backward_lgk_o_original = _pointwise_logk(
        backward_o, backward_r, backward_current, backward_potential, e0, config
    )

    # Central estimates are independent of whether uncertainty was requested.
    original_sigma_o = np.full_like(original_o, np.nan)
    original_sigma_r = np.full_like(original_r, np.nan)
    forward_sigma_o = np.full_like(forward_o, np.nan)
    forward_sigma_r = np.full_like(forward_r, np.nan)
    backward_sigma_o = np.full_like(backward_o, np.nan)
    backward_sigma_r = np.full_like(backward_r, np.nan)
    forward_error_r, forward_error_o = _kinetic_error_arrays(
        forward_o, forward_r, forward_current, forward_potential, e0,
        forward_sigma_o, forward_sigma_r, config)
    backward_error_r, backward_error_o = _kinetic_error_arrays(
        backward_o, backward_r, backward_current, backward_potential, e0,
        backward_sigma_o, backward_sigma_r, config)
    chosen_forward = chosen_backward = np.array([], dtype=int)
    warnings = list(inspection.warnings)
    if background:
        warnings.extend(f"Background: {warning}" for warning in background.warnings)
    forward_nonfinite = int(np.count_nonzero(~np.isfinite(forward_error_r[:, 0])))
    if forward_nonfinite:
        warnings.append(
            f"{forward_nonfinite} forward-scan point(s) produced non-finite lgk values "
            "and were retained as NaN in exported tables."
        )
    backward_nonfinite = int(np.count_nonzero(~np.isfinite(backward_error_r[:, 0])))
    if backward_nonfinite:
        warnings.append(
            f"{backward_nonfinite} reverse-scan point(s) produced non-finite lgk values and "
            "were retained as NaN in exported tables."
        )

    progress("Preparing results")
    result = AnalysisResult(
        input_path=input_path,
        potential_column=potential_column,
        current_column=current_column,
        config=config,
        delta_e=delta_e,
        segments=segments,
        potential=potential,
        processed_current=processed_current,
        original_conc_o=original_o,
        original_conc_r=original_r,
        original_sigma_o=original_sigma_o,
        original_sigma_r=original_sigma_r,
        forward_potential=forward_potential,
        forward_current=forward_current,
        forward_conc_o=forward_o,
        forward_conc_r=forward_r,
        forward_sigma_o=forward_sigma_o,
        forward_sigma_r=forward_sigma_r,
        backward_potential=backward_potential,
        backward_current=backward_current,
        backward_conc_o=backward_o,
        backward_conc_r=backward_r,
        backward_sigma_o=backward_sigma_o,
        backward_sigma_r=backward_sigma_r,
        e0=e0,
        forward_lgk_r=forward_lgk_r,
        forward_lgk_o=forward_lgk_o,
        forward_lgk_r_min=forward_error_r[:, 1],
        forward_lgk_r_max=forward_error_r[:, 2],
        forward_lgk_o_min=forward_error_o[:, 1],
        forward_lgk_o_max=forward_error_o[:, 2],
        chosen_forward_indices=chosen_forward,
        backward_lgk_r_original=backward_lgk_r_original,
        backward_lgk_o_original=backward_lgk_o_original,
        backward_lgk_r=backward_error_r[:, 0],
        backward_lgk_r_min=backward_error_r[:, 1],
        backward_lgk_r_max=backward_error_r[:, 2],
        backward_lgk_o=backward_error_o[:, 0],
        backward_lgk_o_min=backward_error_o[:, 1],
        backward_lgk_o_max=backward_error_o[:, 2],
        chosen_backward_indices=chosen_backward,
        warnings=warnings,
        source=inspection.source,
        background_source=background.source if background else None,
        concentration_reference_indices=references,
        normalization_version=NORMALIZATION_VERSION,
        background_corrected_current=_correct_background(
            potential, raw_current, segments, config, background).copy(),
    )

    progress("Calculating uncertainty")
    return _update_error_analysis(result)


def calculate_k_s(result: AnalysisResult) -> KsResult:
    """Calculate k_s exactly as the current plotting code estimates it."""

    index = int(np.argmin(np.abs(result.backward_potential - result.e0)))
    lgk_r = float(result.backward_lgk_r_original[index])
    lgk_o = float(result.backward_lgk_o_original[index])
    finite = [value for value in (lgk_r, lgk_o) if np.isfinite(value)]
    if not finite:
        raise ValueError("k_s is undefined because both lgk values nearest E0 are non-finite.")
    lgk_s = float(np.mean(finite))
    return KsResult(
        e0=float(result.e0),
        nearest_potential=float(result.backward_potential[index]),
        index=index,
        lgk_r=lgk_r,
        lgk_o=lgk_o,
        lgk_s=lgk_s,
        k_s=float(10.0**lgk_s),
    )


def calculate_k_s_error(result: AnalysisResult) -> KsError:
    """Use the existing four log bounds at the unchanged central k_s sample.

    This is a conservative sensitivity envelope, not independent-error propagation
    or a statistical confidence interval. Selection limits do not affect it.
    """
    if not result.config.uncertainty_configured:
        return KsError("not_calculated")
    try:
        center = calculate_k_s(result)
    except (ValueError, OverflowError):
        return KsError("unavailable", reason="Central k_s is unavailable.")
    index = center.index
    if not all(np.isfinite(v) for v in (center.lgk_r, center.lgk_o, center.k_s)) or center.k_s <= 0:
        return KsError("unavailable", index, reason="Both central kinetic branches must be finite.")
    rl, ru = float(result.backward_lgk_r_min[index]), float(result.backward_lgk_r_max[index])
    ol, ou = float(result.backward_lgk_o_min[index]), float(result.backward_lgk_o_max[index])
    if result.error_analysis is None and ru == 100.0:
        ru = ou = float("inf")  # Compatibility with historical sentinel results.
    if (not np.isfinite(rl) or not np.isfinite(ol)
            or not (np.isfinite(ru) or np.isposinf(ru))
            or not (np.isfinite(ou) or np.isposinf(ou)) or rl > ru or ol > ou):
        return KsError("unavailable", index, reason="Required branch bounds are undefined or invalid.")
    log_lower, log_upper = rl/2 + ol/2, ru/2 + ou/2
    with np.errstate(over="ignore", under="ignore"):
        lower = float(np.power(10.0, log_lower))
        upper = float(np.power(10.0, log_upper))
    if np.isposinf(ru) or np.isposinf(ou):
        return KsError("unbounded", index, lower if np.isfinite(lower) and lower > 0 else None,
                       float("inf"), float("inf"), log_lower, log_upper,
                       "At least one upper branch bound is unbounded.")
    if not np.isfinite(lower) or not np.isfinite(upper) or lower <= 0 or upper <= 0:
        return KsError("unavailable", index, log10_lower=log_lower, log10_upper=log_upper,
                       reason="Finite log bounds exceed the representable linear rate range.")
    error = max(center.k_s - lower, upper - center.k_s, 0.0)
    return KsError("finite", index, lower, upper, error, log_lower, log_upper)


def recalculate_error_analysis(
    result: AnalysisResult,
    *,
    sigma_current: float,
    sigma_cdl: float,
    sigma_diameter: float,
    sigma_diffusion_o: float,
    sigma_diffusion_r: float,
    lgk_error_limit: float,
) -> AnalysisResult:
    """Recalculate uncertainty from an existing main result without rerunning convolution."""

    config = replace(
        result.config,
        uncertainty_configured=True,
        sigma_current=float(sigma_current),
        sigma_cdl=float(sigma_cdl),
        sigma_diameter=float(sigma_diameter),
        sigma_diffusion_o=float(sigma_diffusion_o),
        sigma_diffusion_r=float(sigma_diffusion_r),
        lgk_error_limit=float(lgk_error_limit),
    )
    config.validate()
    return _update_error_analysis(replace(result, config=config))


def _update_error_analysis(result):
    config = result.config
    zero_potential = _find_zero_current_potential(result.backward_potential, result.backward_current)
    zero_index = int(np.argmin(np.abs(result.backward_potential-zero_potential)))
    details = concentration_errors(result, zero_index)
    updates = {"error_analysis": details}
    for scope in ("original", "forward", "backward"):
        for species in ("o", "r"):
            component = details.concentrations.get(f"{scope}_{species}")
            updates[f"{scope}_sigma_{species}"] = (component.total if component else
                np.full_like(getattr(result, f"{scope}_conc_{species}"), np.nan))
    for scan in ("forward", "backward"):
        reduction, oxidation = _kinetic_error_arrays(
            getattr(result, f"{scan}_conc_o"), getattr(result, f"{scan}_conc_r"),
            getattr(result, f"{scan}_current"), getattr(result, f"{scan}_potential"),
            result.e0, updates[f"{scan}_sigma_o"], updates[f"{scan}_sigma_r"],
            config, details.e0_error)
        for branch, values in (("r", reduction), ("o", oxidation)):
            updates[f"{scan}_lgk_{branch}_min"] = values[:, 1]
            updates[f"{scan}_lgk_{branch}_max"] = values[:, 2]
        updates[f"chosen_{scan}_indices"] = accepted_indices(reduction, oxidation, config.lgk_error_limit)
    warnings = [w for w in result.warnings if not w.startswith("Error model:")]
    if config.uncertainty_configured:
        warnings.append("Error model: empirical multiD errors use estimated bulk = max(initial CO, initial CR) "
                        "and D = sqrt(DO*DR); one initial redox form is assumed dominant. "
                        "Concentration and E0 ranges are varied independently; bounds are sensitivity estimates.")
        if not np.isfinite(details.e0_error):
            warnings.append("Error model: E0 error is undefined; kinetic bounds are unavailable.")
    return replace(result, **updates, warnings=warnings)


def select_error_limit(result: AnalysisResult, error_limit: float) -> AnalysisResult:
    """Reselect acceptable points without recalculating uncertainty arrays."""

    if not np.isfinite(error_limit) or error_limit < 0:
        raise ValueError("Error limit in lgk must be a non-negative finite value.")
    config = replace(result.config, lgk_error_limit=float(error_limit))
    choices = {}
    for scan in ("forward", "backward"):
        reduction = np.column_stack([getattr(result, f"{scan}_lgk_r{suffix}") for suffix in ("", "_min", "_max")])
        oxidation = np.column_stack([getattr(result, f"{scan}_lgk_o{suffix}") for suffix in ("", "_min", "_max")])
        choices[scan] = accepted_indices(reduction, oxidation, error_limit)
    chosen_forward, chosen_backward = choices["forward"], choices["backward"]
    return replace(
        result,
        config=config,
        chosen_forward_indices=chosen_forward,
        chosen_backward_indices=chosen_backward,
    )
