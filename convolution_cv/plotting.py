"""Reusable plotting functions for the desktop UI and saved figures."""

from pathlib import Path
import math
import textwrap
from typing import Iterable

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import FuncFormatter
from matplotlib.collections import PolyCollection
from matplotlib.lines import Line2D

from .engine import calculate_k_s
from .models import AnalysisResult, PreprocessingPreview
from .plot_data import finite_line, kinetic_masks
from .chart_style import COLORS, CURVE_WIDTH, FONT, TYPE, legend_columns, position_title
from .chart_style import style_axis as _style_axis


def _micro_units(axis):
    """Readable display units only: line/table data remain in their original units."""
    axis.yaxis.set_major_formatter(FuncFormatter(lambda value, position: f"{value * 1e6:g}"))


def _plot_note(axis, text):
    # A dedicated caption below the axis, never a box over scientific data.
    width = max(30, int(axis.figure.get_figwidth() * 72 * 0.80 / (TYPE["note"] * 0.53)))
    # Preserve math expressions in the quantitative caption; wrap prose notices.
    text = "\n".join(line if "$" in line else textwrap.fill(line, width)
                     for line in text.splitlines())
    axis.annotate(text, xy=(0, 0), xycoords="axes fraction", xytext=(0, -76),
                  textcoords="offset points", va="top", fontsize=TYPE["note"],
                  fontfamily=FONT, math_fontfamily="dejavusans", color="#454b54",
                  linespacing=1.3, annotation_clip=False, gid="plot-caption")


def _legend(axis, kinetics=False):
    handles, labels = axis.get_legend_handles_labels()
    samples = any(label.endswith(" accepted") for label in labels)
    visible = [(handle, label) for handle, label in zip(handles, labels)
               if not label.endswith((" accepted", " non-accepted"))]
    handles, labels = map(list, zip(*visible)) if visible else ([], [])
    labels = [label.replace(" — error-limit window", " window").replace(" error-limit window", " window")
              .replace("lgkR", r"$k_{\mathrm{R}}$").replace("lgkO", r"$k_{\mathrm{O}}$")
              for label in labels]
    if kinetics and not (any("Forward" in label for label in labels) and any("Backward" in label for label in labels)):
        labels = [label.replace("Forward ", "").replace("Backward ", "").replace("accepted", "Accepted samples") for label in labels]
    if samples:
        handles = [Line2D([], [], color=handle.get_color(), linestyle=handle.get_linestyle(),
                          linewidth=handle.get_linewidth()) if isinstance(handle, Line2D) else handle
                   for handle in handles]
        # Neutral, same-color keys explain opacity/size without assigning a new
        # scientific series color to acceptance. Data markers retain curve colors.
        handles.extend([
            Line2D([], [], marker="o", linestyle="none", color="#454b54", markersize=2.5, alpha=0.22),
            Line2D([], [], marker="o", linestyle="none", color="#454b54", markersize=4.5, alpha=1),
        ])
        labels.extend(["Not accepted", "Accepted"])
    if handles:
        columns = legend_columns(axis, len(handles))
        axis.legend(handles, labels, prop={"family": FONT, "size": TYPE["legend"], "math_fontfamily": "dejavusans"},
                    loc="lower left", bbox_to_anchor=(0, 1.015), frameon=False,
                    ncol=columns, handlelength=2,
                    borderaxespad=0, columnspacing=1.2, labelspacing=0.5, markerscale=1.6)
        position_title(axis, math.ceil(len(handles) / columns))


def _sample_points(axis, result, scan, values, color, branch=""):
    accepted = kinetic_masks(result, scan)[3]
    potential = getattr(result, f"{scan}_potential")
    valid = np.isfinite(potential) & np.isfinite(values)
    prefix = f"{scan.title()} {branch}".strip()
    for mask, size, alpha, status in ((valid & ~accepted, 6, 0.22, "non-accepted"),
                                      (valid & accepted, 20, 1.0, "accepted")):
        axis.scatter(potential[mask], values[mask], s=size, color=color, alpha=alpha,
                     zorder=5, linewidths=0, label=f"{prefix} {status}")


class _UpperClippedBand(PolyCollection):
    """Upper-unbounded intervals follow the visible ceiling, including after zoom.

    The artist never contributes its display ceiling to data limits. Sentinel
    values and input arrays are not changed, and undefined samples split polygons.
    """
    def __init__(self, axis, potential, lower, upper, unbounded, valid, **kwargs):
        self._band_axis = axis
        self._potential, self._lower, self._upper = potential, lower, upper
        self._unbounded, self._valid = unbounded, valid
        super().__init__([], **kwargs)
        self._update_vertices()

    def _update_vertices(self):
        top = self._band_axis.get_ylim()[1]
        upper = np.where(self._unbounded, top, self._upper)
        edges = np.flatnonzero(np.diff(np.r_[False, self._valid, False]))
        vertices = []
        for start, end in edges.reshape(-1, 2):
            x = self._potential[start:end]
            vertices.append(np.column_stack((np.r_[x, x[::-1]],
                np.r_[self._lower[start:end], upper[start:end][::-1]])))
        self.set_verts(vertices)

    def draw(self, renderer):
        self._update_vertices()
        super().draw(renderer)


def _kinetic_band(axis, potential, center, lower, upper, unbounded, color, alpha, label):
    valid = (np.isfinite(potential) & np.isfinite(center) & np.isfinite(lower)
             & (unbounded | np.isfinite(upper)))
    bounded = valid & ~unbounded
    # Only actual finite bounds influence autoscaling, never sentinel 100 (or
    # the oxidation branch's shifted sentinel).
    for values, mask in ((lower, valid), (upper, bounded)):
        if np.any(mask):
            axis.update_datalim(np.column_stack((potential[mask], values[mask])))
    axis.autoscale_view()
    band = _UpperClippedBand(axis, potential, lower, upper, unbounded, valid,
                            facecolor=color, alpha=alpha, linewidth=0, zorder=1)
    band.set_gid(label)
    axis.add_collection(band, autolim=False)


def selected_cycle_start(result: AnalysisResult) -> int:
    keys = list(result.segments.keys())
    return keys[2 * (result.config.cv_cycles_n - 1)][0]


def selected_scan_bounds(result: AnalysisResult, scan: str) -> tuple[int, int]:
    if scan not in {"forward", "backward"}:
        raise ValueError("scan must be 'forward' or 'backward'.")
    keys = list(result.segments.keys())
    offset = 0 if scan == "forward" else 1
    return keys[2 * (result.config.cv_cycles_n - 1) + offset]


def selected_backward_bounds(result: AnalysisResult) -> tuple[int, int]:
    return selected_scan_bounds(result, "backward")


def selected_cycle_bounds(result: AnalysisResult) -> tuple[int, int]:
    """Half-open bounds of exactly the selected cycle's two scans."""
    return selected_scan_bounds(result, "forward")[0], selected_scan_bounds(result, "backward")[1]


def _included_scans(kinetics_scan: str) -> tuple[str, ...]:
    if kinetics_scan == "forward":
        return ("forward",)
    if kinetics_scan == "backward":
        return ("backward",)
    if kinetics_scan == "both":
        return ("forward", "backward")
    raise ValueError("kinetics_scan must be 'backward', 'forward', or 'both'.")


def error_potential_window(
    result: AnalysisResult,
    scan: str = "backward",
) -> tuple[float, float] | None:
    """Return one scan's inclusive potential window selected by the error limit."""

    if scan == "forward":
        indices = np.asarray(result.chosen_forward_indices, dtype=int)
        potential = result.forward_potential
    elif scan == "backward":
        indices = np.asarray(result.chosen_backward_indices, dtype=int)
        potential = result.backward_potential
    else:
        raise ValueError("scan must be 'forward' or 'backward'.")
    indices = indices[(indices >= 0) & (indices < len(potential))]
    if not len(indices):
        return None
    selected = potential[indices]
    selected = selected[np.isfinite(selected)]
    if not len(selected):
        return None
    return float(np.min(selected)), float(np.max(selected))


def _fill_concentration_uncertainty_by_scan(
    axis,
    result: AnalysisResult,
    concentration: np.ndarray,
    sigma: np.ndarray,
    start: int,
    color: str,
) -> None:
    """Draw one band per monotonic scan so overlapping bands alpha-composite."""

    stop = start + len(concentration)
    for segment_start, segment_end in result.segments:
        draw_start = max(segment_start, start)
        draw_end = min(segment_end, stop)
        if draw_end - draw_start < 2:
            continue
        local = slice(draw_start - start, draw_end - start)
        axis.fill_between(
            result.potential[draw_start:draw_end],
            concentration[local] - sigma[local],
            concentration[local] + sigma[local],
            color=color,
            alpha=0.22,
            linewidth=0,
        )


def draw_import(axis, potential: np.ndarray, current: np.ndarray) -> None:
    axis.clear()
    axis.plot(potential, current, color=COLORS["blue"], linewidth=CURVE_WIDTH)
    _style_axis(axis, "Raw voltammogram", ylabel="Current (µA)")
    _micro_units(axis)


def draw_preprocessing(axis, preview: PreprocessingPreview, selected_cycle: int = 1) -> None:
    segments = list(preview.segments)
    if (isinstance(selected_cycle, bool) or not isinstance(selected_cycle, (int, np.integer))
            or not 1 <= selected_cycle <= len(segments) // 2):
        raise ValueError("Select a complete CV cycle available in the preprocessing preview.")
    first_scan = 2 * (selected_cycle - 1)
    selected = slice(segments[first_scan][0], segments[first_scan + 1][1])
    potential = preview.potential[selected]
    axis.clear()
    axis.plot(
        potential, preview.raw_current[selected], color=COLORS["orange"],
        linewidth=1.6, alpha=1, label="Raw",
    )
    if preview.background_current is not None:
        axis.plot(
            potential, preview.background_current[selected], color=COLORS["gray"],
            linewidth=1.6, alpha=1, label="Blank CV",
        )
    axis.plot(
        potential, preview.corrected_current[selected], color=COLORS["blue"],
        linewidth=2, alpha=0.35, label="Background corrected",
    )
    axis.plot(
        potential, preview.smoothed_current[selected], color=COLORS["blue"],
        linewidth=CURVE_WIDTH, alpha=1, label="SG smoothed" if preview.smoothing_enabled else "Unsmoothed",
    )
    _style_axis(axis, "Preprocessing", ylabel="Current (µA)")
    _micro_units(axis)
    _legend(axis)


def draw_processed_cv(
    axis,
    result: AnalysisResult,
    highlight_error: bool = False,
    kinetics_scan: str = "backward",
) -> None:
    axis.clear()
    start, end = selected_cycle_bounds(result)
    axis.plot(
        result.potential[start:end], result.processed_current[start:end],
        color=COLORS["blue"], linewidth=CURVE_WIDTH, alpha=0.22 if highlight_error else 1,
    )
    if highlight_error:
        for scan in _included_scans(kinetics_scan):
            current = getattr(result, f"{scan}_current")
            _sample_points(axis, result, scan, current, COLORS["blue"])
    _style_axis(axis, "Processed voltammogram", ylabel="Current (µA)")
    _micro_units(axis)
    _legend(axis)


def _draw_concentration(
    axis,
    result: AnalysisResult,
    species: str,
    show_error: bool = False,
    kinetics_scan: str = "backward",
) -> None:
    axis.clear()
    start, end = selected_cycle_bounds(result)
    if species == "O":
        concentration = result.original_conc_o[start:end]
        sigma = result.original_sigma_o[start:end]
        color = COLORS["blue"]
    else:
        concentration = result.original_conc_r[start:end]
        sigma = result.original_sigma_r[start:end]
        color = COLORS["green"]
    potential = result.potential[start:end]
    axis.plot(potential, concentration, color=color, linewidth=CURVE_WIDTH, alpha=0.22 if show_error else 1)
    if show_error:
        _fill_concentration_uncertainty_by_scan(
            axis, result, concentration, sigma, start, color
        )
        full_concentration = (
            result.original_conc_o if species == "O" else result.original_conc_r
        )
        for scan in _included_scans(kinetics_scan):
            scan_start, scan_end = selected_scan_bounds(result, scan)
            scan_concentration = full_concentration[scan_start:scan_end]
            _sample_points(axis, result, scan, scan_concentration, color)
    _style_axis(
        axis,
        f"{'Oxidized' if species == 'O' else 'Reduced'} species",
        ylabel=rf"$c_\mathrm{{{species}}}$ (µmol cm⁻³)",
    )
    _micro_units(axis)
    _legend(axis)


def draw_concentration_o(
    axis,
    result: AnalysisResult,
    show_error: bool = False,
    kinetics_scan: str = "backward",
) -> None:
    _draw_concentration(axis, result, "O", show_error, kinetics_scan)


def draw_concentration_r(
    axis,
    result: AnalysisResult,
    show_error: bool = False,
    kinetics_scan: str = "backward",
) -> None:
    _draw_concentration(axis, result, "R", show_error, kinetics_scan)


def draw_lgk(
    axis,
    result: AnalysisResult,
    show_error: bool = False,
    kinetics_scan: str = "backward",
    embedded: bool = False,
) -> None:
    if kinetics_scan not in {"backward", "forward", "both"}:
        raise ValueError("kinetics_scan must be 'backward', 'forward', or 'both'.")
    axis.clear()
    if kinetics_scan in {"forward", "both"}:
        potential = result.forward_potential
        finite_r = np.isfinite(potential) & np.isfinite(result.forward_lgk_r)
        finite_o = np.isfinite(potential) & np.isfinite(result.forward_lgk_o)
        axis.plot(
            potential, finite_line(result.forward_lgk_r, finite_r),
            color=COLORS["blue"], linewidth=CURVE_WIDTH, linestyle="--",
            label="Forward lgkR",
        )
        axis.plot(
            potential, finite_line(result.forward_lgk_o, finite_o),
            color=COLORS["orange"], linewidth=CURVE_WIDTH, linestyle="--",
            label="Forward lgkO",
        )

    if kinetics_scan in {"backward", "both"}:
        potential = result.backward_potential
        finite_r = np.isfinite(potential) & np.isfinite(result.backward_lgk_r_original)
        finite_o = np.isfinite(potential) & np.isfinite(result.backward_lgk_o_original)
        axis.plot(
            potential, finite_line(result.backward_lgk_r_original, finite_r),
            color=COLORS["blue"], linewidth=CURVE_WIDTH, label="Backward lgkR",
        )
        axis.plot(
            potential, finite_line(result.backward_lgk_o_original, finite_o),
            color=COLORS["orange"], linewidth=CURVE_WIDTH, label="Backward lgkO",
        )

    unbounded_count = 0
    if show_error:
        for line in axis.lines:
            line.set_alpha(0.22)
        for scan in _included_scans(kinetics_scan):
            potential = getattr(result, f"{scan}_potential")
            unbounded = kinetic_masks(result, scan)[2]
            unbounded_count += int(np.count_nonzero(unbounded))
            center_r = (
                result.forward_lgk_r
                if scan == "forward" else result.backward_lgk_r
            )
            center_o = (
                result.forward_lgk_o
                if scan == "forward" else result.backward_lgk_o
            )
            minimum_r = getattr(result, f"{scan}_lgk_r_min")
            maximum_r = getattr(result, f"{scan}_lgk_r_max")
            minimum_o = getattr(result, f"{scan}_lgk_o_min")
            maximum_o = getattr(result, f"{scan}_lgk_o_max")
            band_alpha = 0.11 if kinetics_scan == "both" else 0.15
            _kinetic_band(axis, potential, center_r, minimum_r, maximum_r, unbounded,
                          COLORS["blue"], band_alpha, f"{scan}-r-uncertainty")
            _kinetic_band(axis, potential, center_o, minimum_o, maximum_o, unbounded,
                          COLORS["orange"], band_alpha, f"{scan}-o-uncertainty")
            # Mark the displayed curves, not a differently normalized trace.
            displayed_r = result.backward_lgk_r_original if scan == "backward" else center_r
            displayed_o = result.backward_lgk_o_original if scan == "backward" else center_o
            _sample_points(axis, result, scan, displayed_r, COLORS["blue"], "lgkR")
            _sample_points(axis, result, scan, displayed_o, COLORS["orange"], "lgkO")

    axis.axvline(result.e0, color="#94a3b8", linestyle=(0, (4, 4)), linewidth=0.9)
    notes = []
    if kinetics_scan in {"backward", "both"}:
        try:
            k_s = calculate_k_s(result)
        except (ValueError, OverflowError):
            if not embedded:
                notes.append(r"$k_s$ unavailable at $E^0$")
        else:
            axis.scatter([k_s.nearest_potential], [k_s.lgk_s], color="#18283e", s=45, zorder=6,
                         edgecolor="white", linewidth=1)
            if not embedded:
                notes.append(rf"$E^0$ = {result.e0:.4f} V     $k_s$ = {k_s.k_s:.3g} cm s$^{{-1}}$ · backward-derived")
    scan_title = {
        "backward": "backward scan",
        "forward": "forward scan",
        "both": "both scans",
    }[kinetics_scan]
    _style_axis(
        axis, f"Kinetics · {scan_title}", ylabel="log₁₀[k / (cm s⁻¹)]"
    )
    if unbounded_count:
        notes.append(f"{unbounded_count:,} upper-unbounded intervals; bands clip at the plot ceiling. Undefined values remain gaps.")
    if notes:
        _plot_note(axis, "\n".join(notes))
    if not any(np.any(np.isfinite(line.get_ydata())) for line in axis.lines[:-1]):
        axis.text(0.5, 0.5, "No finite kinetics for this scan", transform=axis.transAxes,
                  ha="center", fontsize=TYPE["legend"])
    _legend(axis, kinetics=True)


def draw_result_grid(
    axes: Iterable,
    result: AnalysisResult,
    show_error: bool = False,
    kinetics_scan: str = "backward",
) -> None:
    axes = list(axes)
    draw_processed_cv(
        axes[0], result, highlight_error=show_error, kinetics_scan=kinetics_scan
    )
    draw_concentration_o(
        axes[1], result, show_error=show_error, kinetics_scan=kinetics_scan
    )
    draw_concentration_r(
        axes[2], result, show_error=show_error, kinetics_scan=kinetics_scan
    )
    draw_lgk(
        axes[3], result, show_error=show_error, kinetics_scan=kinetics_scan
    )


def save_result_figures(
    result: AnalysisResult,
    figures_folder: Path,
    data_name: str,
    include_error: bool = True,
    kinetics_scan: str = "backward",
    error_kinetics_scan: str = "backward",
    progress_callback=None,
    check_cancelled=None,
) -> None:
    figures_folder.mkdir(parents=True, exist_ok=False)
    plotters = [
        ("processed_cv", draw_processed_cv),
        ("concentration_o", draw_concentration_o),
        ("concentration_r", draw_concentration_r),
        ("lgk_vs_e", draw_lgk),
    ]
    for suffix, plotter in plotters:
        if check_cancelled:
            check_cancelled()
        if progress_callback:
            progress_callback(f"Saving {suffix.replace('_', ' ')}")
        figure, axis = plt.subplots(figsize=(9, 6), dpi=150, layout="constrained")
        try:
            plotter(axis, result, kinetics_scan=kinetics_scan)
            for extension in ("png", "svg", "pdf"):
                figure.savefig(figures_folder / f"{data_name}_{suffix}.{extension}", dpi=300, bbox_inches="tight")
        finally:
            plt.close(figure)
    if include_error:
        for suffix, plotter in plotters:
            if check_cancelled:
                check_cancelled()
            if progress_callback:
                progress_callback(f"Saving {suffix.replace('_', ' ')} uncertainty")
            figure, axis = plt.subplots(figsize=(9, 6), dpi=150, layout="constrained")
            try:
                if plotter is draw_processed_cv:
                    plotter(axis, result, highlight_error=True, kinetics_scan=error_kinetics_scan)
                else:
                    plotter(axis, result, show_error=True, kinetics_scan=error_kinetics_scan)
                for extension in ("png", "svg", "pdf"):
                    figure.savefig(figures_folder / f"{data_name}_{suffix}_with_error.{extension}",
                                   dpi=300, bbox_inches="tight")
            finally:
                plt.close(figure)
