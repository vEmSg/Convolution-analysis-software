"""Offline reports and file guides for saved analysis results."""

import base64
import json
from dataclasses import asdict
from html import escape
from urllib.parse import quote

import numpy as np
import pandas as pd

from .uncertainty import error_columns
from .formatting import format_e0, format_k_s
from .models import KsError
from .plot_data import kinetic_masks


PARAMETERS = {
    "cv_cycles_n": ("Selected CV cycle", ""), "n_e": ("Transferred electrons", ""),
    "diameter": ("Electrode diameter", "cm"), "scan_rate": ("Scan rate", "V/s"),
    "temperature": ("Temperature", "K"), "diffusion_o": ("Diffusion coefficient O", "cm²/s"),
    "diffusion_r": ("Diffusion coefficient R", "cm²/s"),
    "double_layer_capacity": ("Double-layer capacitance", "F"),
    "sigma_current": ("Current uncertainty", "A"), "sigma_cdl": ("Capacitance uncertainty", "F"),
    "sigma_diameter": ("Diameter uncertainty (absolute)", "cm"),
    "sigma_diffusion_o": ("Diffusion uncertainty O (absolute)", "cm²/s"),
    "sigma_diffusion_r": ("Diffusion uncertainty R (absolute)", "cm²/s"),
    "lgk_error_limit": ("Maximum lgk interval width (strictly less than)", ""),
}

GUIDE = """# Saved analysis guide

Open `Overview.html` to review results, figures and calculation settings offline.
Figures are embedded in the report, which can be printed to PDF from a browser.
Share the complete run folder to preserve its data and figure download links.

## Files and units

- `data/processed_trace.csv`: complete processed current and full-trace-referenced concentrations.
- `data/forward_kinetics.csv` and `data/backward_kinetics.csv`: selected-scan concentrations,
  rate constants, and uncertainty and selection status when included in the export.
- `1_processed_CVs/`: complete processed potential/current trace.
- `2_original_conc/`: complete trace with full-trace-referenced concentrations.
- `3_processed_conc/`: selected forward and backward scans with scan-specific concentrations.
- `4_original_lgk/`: E0 and forward/backward logarithmic rate constants.
- `5_error_and_final_results/`: concentration-error components, rate bounds and selected results.
- `6_plots/`: individual PNG, SVG and PDF figures; `with_error` identifies uncertainty figures.
- `7_back_simulation/`: simulation data, comparison figures, settings and metrics, when included.
- `input/`: original input CSV files, including the measured blank, when input copies are enabled.
- `summary.json`: full-precision results, errors, accepted counts and potential windows.
- `manifest.json`: calculation settings, input hashes, software version and save status.

CSV units are V, A, mol/cm³ and cm/s. Plots display current in µA and concentration
in µmol/cm³. Logarithmic rates are log10[k / (cm/s)].

## Concentration references and smoothing

O is referenced to zero at the negative potential endpoint and R at the positive
endpoint. For the full trace, cycle 1 uses the initial sample and its turning sample;
later cycles use the selected cycle's final sample and turning sample. Kinetics
references each selected scan separately using its own endpoints. Negative
concentrations are retained.

CV and concentration plots show the selected cycle with full-trace-referenced
concentrations. Full-trace tables retain all imported cycles. The
`concentration_normalization` metadata records all six reference indices,
potentials and times; indices refer to the cleaned imported trace and start at zero.

Optional Savitzky–Golay smoothing uses a 20 mV full potential window and order 2
by default. The window is converted to the nearest odd sample count using the
median nonzero potential increment. The span is (sample count − 1) times that
increment. Timing uses the first potential increment divided by scan rate.

## Error analysis

Current uncertainty is the per-sample noise standard deviation after background
subtraction and before smoothing. Include measured-blank noise in this input.
Propagation uses the unsmoothed discrete convolution weights and accounts for
covariance from reference subtraction. Capacitance uncertainty contributes in
capacitance-correction mode. Diameter and diffusion uncertainties and the
nonplanar-diffusion contribution complete the concentration-error estimate.

The nonplanar contribution follows SI Eq. S23:
0.4520 × bulk × (sqrt(6Dt)/d)^1.049, using elapsed time from the first imported
sample, D = sqrt(DO × DR), and bulk = max(initial CO, initial CR).
`Sigma_Conc` columns contain total estimated concentration errors; `Error_*`
columns identify the individual contributions.

At each potential, oxidation and reduction rates are recalculated using combinations
of the upper and lower estimated surface concentrations and formal potential.
The minimum and maximum valid rates define the bounds for each branch. These are
sensitivity bounds reflecting the estimated errors in concentration and E0.

Accepted samples have finite centers and bounds for both branches, with each log10
interval width strictly below the selected limit. Accepted points are larger and
opaque; other points are translucent in the same curve color. The reported
potential window spans the lowest and highest accepted potentials and may include
rejected samples. Selection preserves the central E0 and k_s values.

Unbounded upper intervals reach the plot ceiling. They are stored as +inf in the
numbered CSV tables and as blank upper bounds with `unbounded_upper` status in
`data/`. Undefined values appear as gaps in plots and blank numeric CSV cells.
Non-finite JSON values are null, with status fields identifying their meaning.
Uncalculated errors remain blank; the manifest records unconfigured uncertainty
inputs as null and `uncertainty_configured` as false.

## E0 and k_s

E0 and k_s are derived from the backward scan. E0 is reported in V with its error
in mV. The displayed error is rounded to 0.1 mV; E0 retains four decimal places
for errors up to 0.5 mV and follows the error magnitude for larger errors.

At the sample nearest E0, k_s is the geometric mean of the two directional rates.
Its lower and upper bounds are the geometric means of the corresponding
directional bounds. The symmetric error is
max(k_s − k_s_lower, k_s_upper − k_s). The error has two significant digits and
k_s uses matching decimal precision, retaining at least two significant digits.
Without error analysis, k_s has three significant digits.

`k_s_uncertainty` preserves the unrounded bounds, error and status. An unbounded
upper branch gives an unbounded error; undefined required bounds give an unavailable
error. `k_s_error_width` records the maximum directional log10 interval width at
the k_s sample. It is separate from the symmetric error in cm/s.

## Back simulation

Back simulation uses the extracted E0 and k_s with the configured diffusion
coefficients, electron number, temperature and electrode area under planar diffusion.
Choose B-V (default α = 0.5) or MHL (λ in eV). One species is initially present:
R for an initial anodic sweep or O for an initial cathodic sweep, with bulk
concentration estimated as max(initial CO, initial CR).

The full imported history through the selected cycle is simulated. Comparison
smoothing applies the same No smoothing/SG setting to measured and simulated
currents before selecting the displayed cycle. Exports preserve raw and displayed
currents, residuals and metrics separately. Residuals and peak differences are
experimental minus simulated. Peak differences are null when an interior peak
of the expected sign is unavailable. Settings, diagnostics and source hashes
identify the simulation used in the saved comparison.
"""


def _number(value):
    return "Unavailable" if value is None else f"{value:.6g}"


def write_readable_report(result, folder, data_name, manifest, include_error, simulation_html=""):
    data = folder / "data"
    data.mkdir()
    pd.DataFrame({
        "Potential (V)": result.potential, "Processed current (A)": result.processed_current,
        "O concentration, full-trace normalized (mol/cm^3)": result.original_conc_o,
        "R concentration, full-trace normalized (mol/cm^3)": result.original_conc_r,
        **(error_columns(result, "original") if include_error else {}),
    }).to_csv(data / "processed_trace.csv", index=False)
    scan_rows = []
    for scan in ("forward", "backward"):
        valid, bounded, unbounded, accepted = kinetic_masks(result, scan)
        columns = {
            "Potential (V)": getattr(result, f"{scan}_potential"),
            "Processed current (A)": getattr(result, f"{scan}_current"),
            "O concentration, scan normalized (mol/cm^3)": getattr(result, f"{scan}_conc_o"),
            "R concentration, scan normalized (mol/cm^3)": getattr(result, f"{scan}_conc_r"),
            "lgkR": getattr(result, f"{scan}_lgk_r"), "lgkO": getattr(result, f"{scan}_lgk_o"),
        }
        if include_error:
            columns.update(error_columns(result, scan))
            for branch in ("r", "o"):
                columns[f"lgk{branch.upper()} lower"] = getattr(result, f"{scan}_lgk_{branch}_min")
                columns[f"lgk{branch.upper()} upper"] = np.where(unbounded, np.nan, getattr(result, f"{scan}_lgk_{branch}_max"))
            columns["Uncertainty status"] = np.where(~valid, "undefined_center", np.where(unbounded, "unbounded_upper", np.where(bounded, "bounded", "undefined_bounds")))
            columns["Accepted by width limit"] = accepted
        pd.DataFrame(columns).replace([np.inf, -np.inf], np.nan).to_csv(data / f"{scan}_kinetics.csv", index=False)
        indices = getattr(result, f"chosen_{scan}_indices")
        potential = getattr(result, f"{scan}_potential")
        window = f"{potential[indices].min():.6g} to {potential[indices].max():.6g} V" if len(indices) else "None"
        scan_rows.append(f"<tr><th>{scan.title()}</th><td>{accepted.sum():,} / {len(potential):,}</td><td>{window}</td><td>{unbounded.sum():,}</td></tr>")
    (folder / "FILE_GUIDE.md").write_text(GUIDE, encoding="utf-8")
    summary = json.loads((folder / "summary.json").read_text())
    presentation = manifest["presentation"]
    warnings = list(result.warnings)
    if presentation["settings_edited_since_calculation"]:
        warnings.insert(0, "Settings were edited after calculation. This report contains the last successful result and its recorded settings.")
    for source in (result.source, result.background_source):
        if source and source.current_status() != "unchanged":
            warnings.append(f"{source.path.name}: source is now {source.current_status()}. The original bytes used for calculation are preserved in this export when input copying is enabled.")
    warning_html = "".join(f"<li>{escape(warning)}</li>" for warning in warnings) or "<li>No calculation warnings.</li>"
    config = asdict(result.config)
    param_rows = "".join(f"<tr><th>{label}</th><td>{config[key]:.8g}</td><td>{unit}</td></tr>" for key, (label, unit) in PARAMETERS.items() if include_error or not (key.startswith("sigma_") or key == "lgk_error_limit"))
    smoothing_text = (f'SG · {result.config.smoothing_window_mv:g} mV full span · order {result.config.smoothing_order}'
                      if result.config.smoothing_enabled else 'None (background-corrected current)')
    param_rows += f'<tr><th>Smoothing</th><td colspan="2">{smoothing_text}</td></tr>'
    figures = []
    titles = {"processed_cv": "Processed CV", "concentration_o": "Surface concentration O", "concentration_r": "Surface concentration R", "lgk_vs_e": "Electron-transfer kinetics"}
    for error in ([False, True] if include_error else [False]):
        for suffix, title in titles.items():
            stem = f"{data_name}_{suffix}" + ("_with_error" if error else "")
            content = base64.b64encode((folder / "6_plots" / f"{stem}.png").read_bytes()).decode("ascii")
            links = " · ".join(f'<a href="6_plots/{quote(stem)}.{ext}">{ext.upper()}</a>' for ext in ("png", "svg", "pdf"))
            figures.append(f'<article><h3>{title}{" · uncertainty" if error else ""}</h3><img alt="{title}" src="data:image/png;base64,{content}"><p>{links}</p></article>')
    uncertainty = (f'<h2>Error analysis</h2><p>Width limit: {result.config.lgk_error_limit:g}. Accepted samples are larger and opaque; other samples are translucent in the same curve color. Unbounded upper intervals extend to the plot ceiling.</p><table><tr><th>Scan</th><th>Accepted</th><th>Potential window</th><th>Unbounded intervals</th></tr>{"".join(scan_rows)}</table><p>Backward kₛ sample passes the limit: {summary["k_s_point_within_error_limit"]}. Width at that sample: {_number(summary["k_s_error_width"])}.</p>' if include_error else '<h2>Error analysis</h2><p>Not performed or not requested for this export. Uncalculated errors are left blank; see the file guide.</p>')
    if include_error and result.error_analysis is not None:
        details = result.error_analysis
        uncertainty += (f'<p>Estimated E0 error: {_number(summary["errorE0_v"])} V. '
                        f'Estimated bulk concentration: {details.estimated_bulk_concentration * 1e6:.6g} mM. '
                        f'Effective multiD diffusion coefficient: {details.effective_diffusion:.6g} cm²/s. '
                        f'Model: {escape(details.model_version)}. These are estimated errors and sensitivity bounds.</p>')
    k_s_display = format_k_s(summary["k_s_cm_per_s"],
                           KsError(**summary["k_s_uncertainty"]) if include_error else None)
    e0_display = format_e0(result.e0, result.error_e0 if include_error else None)
    source_hash = result.source.sha256 if result.source else "Not captured"
    html = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(result.input_path.stem)} — Analysis</title>
<style>body{{margin:0;background:#f2f5f9;color:#223047;font:15px/1.6 system-ui,sans-serif}}main{{max-width:1120px;margin:auto;padding:40px 24px}}h1{{font-size:32px;line-height:1.2}}h2{{margin-top:36px}}h3{{margin:0;font-size:16px}}a{{color:#1767a4}}.muted{{color:#526478}}.cards,.figures{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}.card,article,section{{background:white;border:1px solid #dce4ee;border-radius:12px;padding:20px}}.value{{font-size:28px;font-weight:650}}img{{width:100%;height:auto}}table{{width:100%;border-collapse:collapse;background:white}}th,td{{text-align:left;border-bottom:1px solid #dce4ee;padding:10px;overflow-wrap:anywhere}}th{{font-weight:600}}code{{overflow-wrap:anywhere}}.notice{{border-left:4px solid #cb912a}}@media(max-width:700px){{.cards,.figures{{grid-template-columns:1fr}}main{{padding:20px 12px}}}}@media print{{body{{background:white}}main{{padding:0}}article,section,.card{{break-inside:avoid}}a{{color:inherit}}}}</style></head><body><main>
<p class="muted">CONVOLUTION ANALYSIS · {escape(manifest['created_at_utc'])}</p><h1>{escape(result.input_path.name)}</h1><p>Cycle {result.config.cv_cycles_n} · {len(result.potential):,} samples · {escape(result.config.background_mode.replace('_', ' '))}</p>
<div class="cards"><div class="card">Formal potential E0<div class="value">{escape(e0_display)}</div></div><div class="card">Standard rate constant kₛ<div class="value">{escape(k_s_display)}</div></div></div>
<p>kₛ: {escape(summary['k_s_method'])}. Sample potential: {_number(summary['k_s_nearest_potential_v'])} V. E0 and kₛ are derived from the backward scan.</p>
<section class="notice"><h3>Warnings and result status</h3><ul>{warning_html}</ul></section>
{uncertainty}<h2>Figures</h2><p>Main kinetics: {presentation['main_scan']}. Error display: {presentation['error_scan'] if include_error else 'not requested'}. CV and concentration plots show only cycle {result.config.cv_cycles_n}. Endpoint normalization sets O to zero at the negative endpoint and R at the positive endpoint. The full trace references {'the initial point and first turning point' if result.config.cv_cycles_n == 1 else 'the selected cycle’s final point and turning point'}; kinetics uses each selected scan’s own endpoints. Negative concentrations are retained. See FILE_GUIDE.md and the manifest for reference details.</p><div class="figures">{''.join(figures)}</div>
{simulation_html}<h2>Data downloads</h2><p><a href="data/processed_trace.csv">Processed trace</a> · <a href="data/forward_kinetics.csv">Forward kinetics</a> · <a href="data/backward_kinetics.csv">Backward kinetics</a> · <a href="FILE_GUIDE.md">File guide</a></p>
<h2>Calculation settings</h2><table><tr><th>Parameter</th><th>Value</th><th>Unit</th></tr>{param_rows}</table>
<h2>Reproducibility</h2><p>Input SHA-256: <code>{source_hash}</code></p><p><a href="manifest.json">Manifest</a> · <a href="summary.json">Numerical summary</a></p><details><summary>Method and file guide</summary><pre style="white-space:pre-wrap;font:inherit">{escape(GUIDE)}</pre></details>
</main></body></html>'''
    (folder / "Overview.html").write_text(html, encoding="utf-8")
