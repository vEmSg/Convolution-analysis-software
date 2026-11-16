"""Optional back-simulation artifacts, separate from legacy analysis exports."""
import base64
from html import escape
import json

import pandas as pd
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg

from .back_simulation import draw_comparison
from .CV_simulator import kinetic_description


def save_back_simulation(sim, folder, view, outdated, check_cancelled):
    destination = folder / "7_back_simulation"
    destination.mkdir()
    physical = sim.simulation
    payload = dict(analysis_id=sim.analysis_id, parameters=physical.metadata,
        diagnostics=physical.diagnostics, settings_edited_since_simulation=bool(outdated),
        smoothing=view["smoothing"], effective_smoothing_span_mv=view["effective_span_mv"],
        effective_smoothing_points=view["effective_points"], smoothing_warnings=view["warnings"],
        raw_metrics=view["raw_metrics"], displayed_metrics=view["displayed_metrics"],
        residual_definition="experiment minus simulation; no fitting, offsets or rescaling",
        selected_start_index=sim.selected_start, backward_start_index=sim.backward_start,
        selected_end_index_exclusive=len(physical.current_a))
    (destination / "settings_and_metrics.json").write_text(
        json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    frame = pd.DataFrame({
        "Time (s)": physical.time_s, "Potential (V)": physical.potential_v,
        "Experimental BG-subtracted current (A)": sim.measured_current,
        "Simulated current (A)": physical.current_a,
        "Raw residual (A)": sim.measured_current-physical.current_a,
        "Displayed experimental current (A)": view["measured"],
        "Displayed simulated current (A)": view["predicted"],
        "Displayed residual (A)": view["residual"],
        "Simulated surface O (mol/cm^3)": physical.surface_o,
        "Simulated surface R (mol/cm^3)": physical.surface_r,
    })
    check_cancelled()
    frame.to_csv(destination / "simulation_history.csv", index=False)
    frame.iloc[sim.selected_start:].to_csv(destination / "selected_cycle_comparison.csv", index=False)
    images = []
    for residual, stem in ((False, "cv_comparison"), (True, "residuals")):
        figure = Figure(figsize=(9, 6), layout="constrained")
        FigureCanvasAgg(figure)
        draw_comparison(figure.add_subplot(), sim, view, residual)
        for extension in ("png", "svg", "pdf"):
            check_cancelled()
            figure.savefig(destination / f"{stem}.{extension}", dpi=180, bbox_inches="tight")
        content = base64.b64encode((destination / f"{stem}.png").read_bytes()).decode("ascii")
        links = " · ".join(f'<a href="7_back_simulation/{stem}.{ext}">{ext.upper()}</a>' for ext in ("png", "svg", "pdf"))
        images.append(f'<article><h3>{"Residuals" if residual else "CV comparison"}</h3><img alt="{stem}" src="data:image/png;base64,{content}"><p>{links}</p></article>')
        figure.clear()
    raw, displayed = view["raw_metrics"], view["displayed_metrics"]
    rows = "".join(f'<tr><th>{label.title()}</th><td>{raw[label]["rmse_a"]*1e6:.5g}</td>'
                   f'<td>{displayed[label]["rmse_a"]*1e6:.5g}</td></tr>' for label in ("selected_cycle", "forward", "backward"))
    peak_rows = []
    for scan in ("forward", "backward"):
        peak = raw[scan]
        if peak["peak_current_difference_a"] is None:
            peak_rows.append(f'<tr><th>{scan.title()}</th><td colspan="2">Interior peak not identified</td></tr>')
        else:
            peak_rows.append(f'<tr><th>{scan.title()}</th><td>{peak["peak_current_difference_a"]*1e6:.5g}</td>'
                             f'<td>{peak["peak_potential_difference_v"]*1000:.5g}</td></tr>')
    warnings = "".join(f'<li>{escape(message)}</li>' for message in physical.diagnostics["warnings"] + view["warnings"])
    smoothing = (f'SG {view["smoothing"]["smoothing_window_mv"]:g} mV, order {view["smoothing"]["smoothing_order"]}'
                 if view["smoothing"]["smoothing_enabled"] else "No smoothing")
    stale = '<p class="notice">Settings changed after simulation; these are the last completed simulation parameters.</p>' if outdated else ""
    html = f'''<section><h2>Back simulation · cycle {sim.selected_cycle}</h2>{stale}
<p>Planar {escape(kinetic_description(physical.metadata))}. Initial species {physical.metadata['initial_species']} only;
estimated bulk = {physical.metadata['initial_concentration_mol_cm3']*1e6:.6g} mM. Full imported history through the selected cycle was simulated without resets.</p>
<p>{escape(smoothing)} applied equally to both plotted traces. Raw metrics use unsmoothed BG-subtracted data.
No fitting, current scaling, potential shifting or baseline adjustment. Residual = experiment − simulation.</p>
<table><tr><th>Region</th><th>Raw RMSE (µA)</th><th>Displayed RMSE (µA)</th></tr>{rows}</table>
<p>Raw maximum absolute residual: {raw['selected_cycle']['max_absolute_error_a']*1e6:.5g} µA.</p>
<p>Raw peak differences (experiment − simulation):</p><table><tr><th>Scan</th><th>Δ peak current (µA)</th><th>Δ peak potential (mV)</th></tr>{''.join(peak_rows)}</table>
<ul>{warnings}</ul><div class="figures">{''.join(images)}</div>
<p><a href="7_back_simulation/selected_cycle_comparison.csv">Selected-cycle data</a> ·
<a href="7_back_simulation/simulation_history.csv">Simulation history</a> ·
<a href="7_back_simulation/settings_and_metrics.json">Settings, diagnostics and peak differences</a></p></section>'''
    return payload, html
