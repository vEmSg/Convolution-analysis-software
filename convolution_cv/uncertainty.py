"""Referenced concentration errors and eight-corner kinetic sensitivity bounds.

Current sigma is the per-sample standard deviation after background subtraction,
BEFORE optional CV smoothing. The error model does not apply smoothing or its
noise correlations. Background measurement noise must be included in that input.
The multiD law and independent E0/concentration ranges are empirical approximations.
"""
from itertools import product

import numpy as np
from scipy.signal import fftconvolve

from .models import BACKGROUND_CAPACITANCE, ConcentrationError, ErrorAnalysisDetails

R = 8.3145
F = 96485.0
ERROR_MODEL_VERSION = "endpoint-discrete-multid-geomean-e0-v4"
# SI Eq. S23, with the existing effective-D and estimated-bulk conventions.
MULTID_COEFFICIENT = 0.4520
MULTID_TIME_FACTOR = 6.0
MULTID_EXPONENT = 1.049


class ReferencedNoise:
    """Unsmoothed discrete covariance with full-history reference subtraction.

    Input-current samples are independent. Their contributions to the curve and
    its reference are shared: sum_j (w_i,j - w_ref,j)**2 retains that covariance.
    FFT cross products avoid constructing a dense convolution matrix.
    """
    def __init__(self, sample_count, delta_t):
        self.n = sample_count
        m = np.arange(self.n)
        self.kernel = 2 * np.sqrt(delta_t) / (np.sqrt(m + 1) + np.sqrt(m))
        self.diagonal = np.cumsum(self.kernel**2)
        self.cache = {}

    def variance(self, reference):
        if reference not in self.cache:
            row = np.zeros(self.n)
            row[:reference + 1] = self.kernel[:reference + 1][::-1]
            cross = fftconvolve(self.kernel, row, mode="full")[:self.n]
            variance = np.maximum(self.diagonal + self.diagonal[reference] - 2*cross, 0)
            variance[reference] = 0.0
            self.cache[reference] = variance
        return self.cache[reference]

    def charging_response(self, direction):
        return fftconvolve(direction, self.kernel, mode="full")[:self.n]


def concentration_errors(result, zero_index):
    config = result.config
    dt = result.delta_e / config.scan_rate
    times = np.arange(len(result.potential)) * dt
    bulk = float(max(result.original_conc_o[0], result.original_conc_r[0]))
    effective_d = float(np.sqrt(config.diffusion_o) * np.sqrt(config.diffusion_r))
    details = ErrorAnalysisDetails(ERROR_MODEL_VERSION, bulk, effective_d, float("nan"), zero_index, {})
    if not config.uncertainty_configured:
        return details
    geometry = ReferencedNoise(len(result.potential), dt)
    direction = np.zeros(len(times))
    for (start, end), label in result.segments.items():
        direction[start:end] = 1 if label == "anodic" else -1
    charging = geometry.charging_response(direction)
    multid = MULTID_COEFFICIENT * bulk * (
        np.sqrt(MULTID_TIME_FACTOR * effective_d * times) / config.diameter
    )**MULTID_EXPONENT
    area = np.pi * (config.diameter / 2)**2
    keys = list(result.segments)
    forward = keys[2 * (config.cv_cycles_n - 1)]
    backward = keys[2 * (config.cv_cycles_n - 1) + 1]
    for scope, (start, end) in (("original", (0, len(times))), ("forward", forward), ("backward", backward)):
        for species, diffusion, sigma_d in (("o", config.diffusion_o, config.sigma_diffusion_o),
                                            ("r", config.diffusion_r, config.sigma_diffusion_r)):
            conc = getattr(result, f"{scope}_conc_{species}")
            reference = result.concentration_reference_indices[f"{scope}_{species}"]
            g = 1 / (config.n_e * F * area * np.sqrt(np.pi * diffusion))
            current = g * config.sigma_current * np.sqrt(geometry.variance(reference)[start:end])
            capacitance = np.zeros(len(conc))
            if config.background_mode == BACKGROUND_CAPACITANCE:
                capacitance = g * config.scan_rate * config.sigma_cdl * np.abs(
                    charging[start:end] - charging[reference])
            parameters = np.abs(conc) * np.hypot(2*config.sigma_diameter/config.diameter, .5*sigma_d/diffusion)
            non_multid = np.sqrt(current**2 + capacitance**2 + parameters**2)
            details.concentrations[f"{scope}_{species}"] = ConcentrationError(
                reference, current, capacitance, parameters, non_multid,
                multid[start:end].copy(), np.hypot(non_multid, multid[start:end]))
    co, cr = result.backward_conc_o[zero_index], result.backward_conc_r[zero_index]
    if np.isfinite(co) and np.isfinite(cr) and co > 0 and cr > 0:
        eo = details.concentrations["backward_o"].total[zero_index]
        er = details.concentrations["backward_r"].total[zero_index]
        details.e0_error = float(R*config.temperature/(config.n_e*F) * np.hypot(eo/co, er/cr))
    return details


def rate_bounds(co, cr, current, potential, e0, error_o, error_r, config, error_e0=0.0):
    """Return independent reduction/oxidation (center, lower, upper) arrays.

    Nonpositive concentrations at corners are retained for compatibility with
    the agreed rectangular sensitivity domain. Only positive rates are valid.
    """
    co, cr, current, potential = np.broadcast_arrays(co, cr, current, potential)
    beta = config.n_e * F / (R * config.temperature)
    area = np.pi * (config.diameter/2)**2
    numerator = -current / (config.n_e * F * area)
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        q = np.exp(beta*(potential-e0))
        center_r = np.log10(numerator/(co-q*cr))
        center_r = np.where((numerator != 0) & (co-q*cr != 0) & (np.sign(numerator) == np.sign(co-q*cr)), center_r, np.nan)
        center_o = center_r + np.log10(q)
    shape = co.shape
    r = np.stack((center_r, np.full(shape, np.nan), np.full(shape, np.nan)), axis=-1)
    o = np.stack((center_o, np.full(shape, np.nan), np.full(shape, np.nan)), axis=-1)
    if not np.isfinite(error_e0) or error_e0 < 0:
        return r, o
    lo_r, lo_o = np.full(shape, np.inf), np.full(shape, np.inf)
    hi_r, hi_o = np.full(shape, -np.inf), np.full(shape, -np.inf)
    q_min, q_max = np.full(shape, np.inf), np.full(shape, -np.inf)
    valid_any = np.zeros(shape, dtype=bool)
    finite_domain = np.isfinite(error_o) & np.isfinite(error_r)
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        for a, b, c in product((-1, 1), repeat=3):
            exponent = beta*(potential-e0-c*error_e0)
            exponential = np.exp(exponent)
            denominator = co+a*error_o - exponential*(cr+b*error_r)
            finite_domain &= np.isfinite(denominator) & np.isfinite(exponential) & (exponential > 0)
            q_min = np.minimum(q_min, denominator)
            q_max = np.maximum(q_max, denominator)
            valid = (numerator != 0) & (denominator != 0) & (np.sign(numerator) == np.sign(denominator))
            lr = np.log10(np.abs(numerator)) - np.log10(np.abs(denominator))
            lo = lr + exponent/np.log(10)
            valid &= np.isfinite(lr) & np.isfinite(lo)
            valid_any |= valid
            lo_r = np.minimum(lo_r, np.where(valid, lr, np.inf))
            lo_o = np.minimum(lo_o, np.where(valid, lo, np.inf))
            hi_r = np.maximum(hi_r, np.where(valid, lr, -np.inf))
            hi_o = np.maximum(hi_o, np.where(valid, lo, -np.inf))
    usable = finite_domain & valid_any
    singular = usable & (q_min <= 0) & (q_max >= 0)
    r[..., 1] = np.where(usable, lo_r, np.nan)
    o[..., 1] = np.where(usable, lo_o, np.nan)
    r[..., 2] = np.where(singular, np.inf, np.where(usable, hi_r, np.nan))
    o[..., 2] = np.where(singular, np.inf, np.where(usable, hi_o, np.nan))
    return r, o


def accepted_indices(reduction, oxidation, limit):
    """A shared displayed point is accepted only if BOTH branch widths pass."""
    wr = reduction[:, 2] - reduction[:, 1]
    wo = oxidation[:, 2] - oxidation[:, 1]
    mask = (np.isfinite(reduction).all(axis=1) & np.isfinite(oxidation).all(axis=1)
            & (wr < limit) & (wo < limit))
    return np.flatnonzero(mask)


def error_metadata(result):
    details = result.error_analysis
    if details is None:
        return {"model_version": ERROR_MODEL_VERSION, "performed": False}
    dt = result.delta_e/result.config.scan_rate
    return {
        "model_version": details.model_version,
        "performed": result.config.uncertainty_configured,
        "estimated_bulk_concentration_mol_cm3": details.estimated_bulk_concentration,
        "bulk_estimator": "max(full-trace CO[0], full-trace CR[0])",
        "effective_diffusion_cm2_s": details.effective_diffusion,
        "multiD_diffusion_rule": "sqrt(DO*DR)",
        "multiD_coefficient": MULTID_COEFFICIENT, "multiD_exponent": MULTID_EXPONENT,
        "multiD_time_factor": MULTID_TIME_FACTOR,
        "multiD_equation_reference": "SI Eq. S23",
        "errorE0_v": details.e0_error,
        "zero_current_backward_index": details.zero_current_index,
        "concentration_reference_indices": {key: value.reference_index for key, value in details.concentrations.items()},
        "concentration_reference_times_s": {key: value.reference_index*dt for key, value in details.concentrations.items()},
        "concentration_reference_potentials_v": {key: float(result.potential[value.reference_index])
                                                for key, value in details.concentrations.items()},
        "normalization_version": result.normalization_version,
        "current_noise_definition": "independent input samples after background subtraction, before smoothing; unsmoothed discrete propagation",
        "smoothing_uncertainty_applied": False,
        "kinetic_selection": "both oxidation and reduction widths strictly below limit; finite centers and bounds",
        "interpretation": "estimated concentration errors and independently varied sensitivity bounds, not confidence intervals",
    }


def error_columns(result, scope):
    """Explicit error component columns; legacy sigma columns remain total-error aliases."""
    details = result.error_analysis
    scopes = ("forward", "backward") if scope == "cycle" else (scope,)
    keys = list(result.segments)
    first = 2*(result.config.cv_cycles_n-1)
    ranges = {"original": (0, len(result.potential)), "forward": keys[first], "backward": keys[first+1]}
    indices = np.concatenate([np.arange(*ranges[s]) for s in scopes])
    columns = {"Elapsed_time(s)": indices * result.delta_e/result.config.scan_rate}
    for species in ("o", "r"):
        for component in ("current", "capacitance", "parameters", "non_multiD", "multiD", "total"):
            pieces = []
            for s in scopes:
                errors = details.concentrations.get(f"{s}_{species}") if details else None
                pieces.append(getattr(errors, component) if errors else np.full(len(getattr(result, f"{s}_conc_{species}")), np.nan))
            name = f"Error_{species.upper()}_{component}(mol/cm^3)"
            if component == "total":
                name = f"errorC{species.upper()}total(mol/cm^3)"
            columns[name] = np.concatenate(pieces)
    return columns
