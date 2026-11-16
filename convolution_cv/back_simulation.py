"""Back-simulation inputs, comparison and plot/export presentation.

No fitting, alignment, offset subtraction, current rescaling or error filtering.
Smoothing is a separate view transformation applied equally to both traces.
"""
from dataclasses import dataclass
from types import SimpleNamespace
import hashlib
import json

import numpy as np

from .CV_simulator import simulate_cv, CVSimulation
from .engine import calculate_k_s
from .smoothing import parse_smoothing, smooth_current


@dataclass
class BackSimulation:
    analysis_id: str
    simulation: CVSimulation
    measured_current: np.ndarray
    selected_start: int
    backward_start: int
    selected_cycle: int
    smoothing_defaults: dict


def analysis_signature(result):
    """Tie a comparison to its numerical main result, not mutable input files."""
    cfg = result.config
    identity = [getattr(cfg, name) for name in (
        "n_e", "diameter", "cv_cycles_n", "diffusion_o", "diffusion_r", "temperature", "scan_rate")]
    identity += [result.e0, calculate_k_s(result).k_s, result.delta_e,
                 float(result.original_conc_o[0]), float(result.original_conc_r[0])]
    digest = hashlib.sha256(json.dumps(identity).encode())
    for array in (result.potential, result.processed_current, result.background_corrected_current):
        if array is None:
            raise ValueError("This analysis lacks the background-subtracted snapshot. Run the main analysis again.")
        digest.update(np.asarray(array, dtype="<f8").tobytes())
    digest.update(repr(list(result.segments.items())).encode())
    return digest.hexdigest()


def simulation_inputs(result):
    cfg = result.config
    k_s = calculate_k_s(result).k_s
    if not np.isfinite(k_s) or k_s <= 0 or not np.isfinite(result.e0):
        raise ValueError("Back simulation requires finite E0 and positive finite k_s.")
    initial = (result.original_conc_o[0], result.original_conc_r[0])
    if not np.all(np.isfinite(initial)):
        raise ValueError("Cannot estimate initial bulk from nonfinite reconstructed concentrations.")
    bulk = float(max(initial))
    if not np.isfinite(bulk) or bulk <= 0:
        raise ValueError("The estimated initial concentration must be positive; no clipping or substitute is applied.")
    first_direction = next(iter(result.segments.values()))
    if first_direction not in {"anodic", "cathodic"}:
        raise ValueError("Cannot infer the initial species from the first scan.")
    return dict(e0=result.e0, k_s=k_s, diffusion_o=cfg.diffusion_o, diffusion_r=cfg.diffusion_r,
                temperature=cfg.temperature, area=np.pi*(cfg.diameter/2)**2, n_e=cfg.n_e,
                initial_concentration=bulk, initial_species="R" if first_direction == "anodic" else "O")


def run_back_simulation(result, alpha=.5, solver=None, cancel_event=None, progress_callback=None,
                        kinetic_model="BV", lambda_eV=None):
    identity = analysis_signature(result)
    cfg = result.config
    ranges = list(result.segments)
    start = ranges[2*(cfg.cv_cycles_n-1)][0]
    backward, end = ranges[2*(cfg.cv_cycles_n-1)+1]
    simulation = simulate_cv(result.potential[:end], result.delta_e/cfg.scan_rate,
        **simulation_inputs(result), alpha=alpha, solver=solver, cancel_event=cancel_event,
        progress_callback=progress_callback, kinetic_model=kinetic_model, lambda_eV=lambda_eV)
    simulation.metadata.update(selected_cycle=cfg.cv_cycles_n,
        concentration_source="max(full-trace CO[0], CR[0]); single species inferred from first scan",
        time_convention="uniform dt = first potential step / configured scan rate; exact imported E samples",
        history="from first imported sample through end of selected cycle; no resets")
    steps = np.abs(np.diff(result.potential[:end]))
    if not np.allclose(steps, result.delta_e, rtol=.01, atol=1e-12):
        simulation.diagnostics["warnings"].append(
            "Potential spacing varies or contains duplicate vertices: uniform timing follows the analysis convention, not measured timestamps.")
    simulation.diagnostics["warnings"].append(
        "Initial bulk is estimated from normalized concentrations, not independently measured; one starting species is assumed.")
    return BackSimulation(identity, simulation, result.background_corrected_current[:end].copy(),
        start, backward, cfg.cv_cycles_n,
        {key: getattr(cfg, key) for key in ("smoothing_enabled", "smoothing_window_mv", "smoothing_order")})


def comparison_metrics(sim, measured, predicted):
    start, split, end = sim.selected_start, sim.backward_start, len(predicted)
    def region(a, b):
        residual = measured[a:b]-predicted[a:b]
        return dict(rmse_a=float(np.sqrt(np.mean(residual**2))),
                    max_absolute_error_a=float(np.max(np.abs(residual))), samples=len(residual))
    metrics = {"selected_cycle": region(start, end), "forward": region(start, split),
               "backward": region(split, end)}
    for name, a, b in (("forward", start, split), ("backward", split, end)):
        positive = sim.simulation.potential_v[b-1] > sim.simulation.potential_v[a]
        sign = 1 if positive else -1
        indices = [a+int(np.argmax(sign*values[a:b])) for values in (measured, predicted)]
        if all(a < j < b-1 and sign*values[j] > 0 for j, values in zip(indices, (measured, predicted))):
            exp, model = indices
            metrics[name]["peak_current_difference_a"] = float(measured[exp]-predicted[model])
            metrics[name]["peak_potential_difference_v"] = float(sim.simulation.potential_v[exp]-sim.simulation.potential_v[model])
        else:
            metrics[name]["peak_current_difference_a"] = None
            metrics[name]["peak_potential_difference_v"] = None
    return metrics


def comparison_view(sim, smoothing=None):
    settings = parse_smoothing(sim.smoothing_defaults if smoothing is None else smoothing)
    config = SimpleNamespace(**settings, validate=lambda: None)
    measured, points, span, warnings = smooth_current(sim.simulation.potential_v, sim.measured_current, config)
    predicted, _, _, _ = smooth_current(sim.simulation.potential_v, sim.simulation.current_a, config)
    return dict(measured=measured, predicted=predicted, residual=measured-predicted,
                smoothing=settings, effective_points=points, effective_span_mv=span,
                warnings=warnings, raw_metrics=comparison_metrics(sim, sim.measured_current, sim.simulation.current_a),
                displayed_metrics=comparison_metrics(sim, measured, predicted))


def draw_comparison(axis, sim, view, residual=False):
    from .chart_style import COLORS, CURVE_WIDTH, style_axis
    from .plotting import _legend, _micro_units
    axis.clear()
    region = slice(sim.selected_start, None)
    potential = sim.simulation.potential_v[region]
    if residual:
        axis.plot(potential, view["residual"][region], color=COLORS["blue"], linewidth=CURVE_WIDTH)
        axis.axhline(0, color=COLORS["gray"], linestyle="--", linewidth=1)
    else:
        axis.plot(potential, view["measured"][region], color=COLORS["orange"],
                  linewidth=CURVE_WIDTH, alpha=.8, label="Experiment · BG subtracted")
        axis.plot(potential, view["predicted"][region], color=COLORS["blue"],
                  linewidth=CURVE_WIDTH, linestyle="--",
                  label=f"Simulation · planar {sim.simulation.metadata.get('model', 'BV')}")
    smooth = "SG" if view["smoothing"]["smoothing_enabled"] else "unsmoothed"
    style_axis(axis, f"{'Residuals' if residual else 'Back simulation'} · cycle {sim.selected_cycle} · {smooth}",
               ylabel="Experiment − simulation (µA)" if residual else "Current (µA)")
    _micro_units(axis)
    if not residual:
        _legend(axis)
