"""Optional Results workspace; simulation and plot smoothing are independent."""
import tkinter as tk
from tkinter import ttk, messagebox

import numpy as np

from ...back_simulation import comparison_view, draw_comparison, simulation_inputs
from ...smoothing import DEFAULTS, parse_smoothing
from ...CV_simulator import normalize_model, kinetic_description
from ..widgets import FigureGrid, ScrollFrame, wrap_to_width


class ComparisonFigure(FigureGrid):
    PLOTS = (("CV comparison", "CV"), ("Residuals", "Residuals"))

    def __init__(self, master):
        self.view = None
        super().__init__(master)
        self.selection.set("CV")

    def set_comparison(self, simulation, view):
        self.result, self.view = simulation, view
        self.refresh()

    def clear(self):
        self.view = None
        super().clear()
        self.figure.texts[0].set_text("Back simulation")
        self.figure.texts[1].set_text("Run back simulation to compare\nwith your BG-subtracted CV.")

    def refresh(self):
        if self.result is None or self.view is None:
            return
        simulation, view, residual = self.result, self.view, self.selection.get() == "Residuals"
        self.figure.clear()
        self.axes = [self.figure.add_subplot()]
        self.drawer = lambda axes: draw_comparison(axes[0], simulation, view, residual)
        self.drawer(self.axes)
        self.axes[0].set_title("", loc="left")
        self.toolbar.update()
        self.canvas.draw_idle()


class BackSimulationTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=(0, 8, 0, 0))
        self.app, self.analysis, self.simulation = app, None, None
        self.view = None
        self._loading, self._plot_job = False, None
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)
        sidebar = ttk.Frame(self)
        sidebar.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        sidebar.rowconfigure(0, weight=1)
        sidebar.columnconfigure(0, weight=1)
        scroll = ScrollFrame(sidebar, width=310)
        scroll.grid(row=0, column=0, sticky="nsew")
        body = scroll.inner
        ttk.Label(body, text="Planar diffusion", style="SectionTitle.TLabel").pack(anchor="w", pady=(0, 8))
        self.input_summary = tk.StringVar(value="Run the main analysis first.")
        label = ttk.Label(body, textvariable=self.input_summary, width=1, justify="left")
        label.pack(fill="x", pady=(0, 12))
        wrap_to_width(label, body, 24)
        model_row = ttk.Frame(body)
        model_row.pack(fill="x", pady=(0, 10))
        ttk.Label(model_row, text="Kinetic model").pack(side="left")
        self.kinetic_model = tk.StringVar(value="B-V")
        self.model_selector = ttk.Combobox(model_row, textvariable=self.kinetic_model,
                                          values=("B-V", "MHL"), state="readonly", width=8)
        self.model_selector.pack(side="right", padx=(6, 12))
        row = ttk.Frame(body)
        row.pack(fill="x", pady=(0, 14))
        ttk.Label(row, text="Transfer coefficient α").pack(side="left")
        self.alpha = tk.StringVar(value="0.5")
        self.alpha_entry = ttk.Entry(row, textvariable=self.alpha, width=6)
        self.alpha_entry.pack(side="right", padx=(6, 12))
        lambda_row = ttk.Frame(body)
        lambda_row.pack(fill="x", pady=(0, 14))
        ttk.Label(lambda_row, text="Reorganization λ (eV)").pack(side="left")
        self.lambda_eV = tk.StringVar(value="")
        self.lambda_entry = ttk.Entry(lambda_row, textvariable=self.lambda_eV, width=6, state="disabled")
        self.lambda_entry.pack(side="right", padx=(6, 12))
        smooth = ttk.LabelFrame(body, text="Comparison smoothing", padding=10)
        smooth.pack(fill="x", pady=(0, 12))
        self.smoothing_vars = {key: tk.StringVar(value=value) for key, value in DEFAULTS.items()}
        for row, (label, value) in enumerate((("No smoothing", "False"), ("Savitzky–Golay (SG)", "True"))):
            ttk.Radiobutton(smooth, text=label, variable=self.smoothing_vars["smoothing_enabled"],
                            value=value).grid(row=row, column=0, columnspan=2, sticky="w", pady=3)
        self.smoothing_entries = []
        for row, (key, label) in enumerate((("smoothing_window_mv", "Window (mV)"), ("smoothing_order", "Polynomial order")), 2):
            ttk.Label(smooth, text=label).grid(row=row, column=0, sticky="w", pady=4)
            entry = ttk.Entry(smooth, textvariable=self.smoothing_vars[key], width=6)
            entry.grid(row=row, column=1, sticky="e", padx=(8, 0), pady=4)
            self.smoothing_entries.append(entry)
        smooth.columnconfigure(0, weight=1)
        self.smoothing_info = tk.StringVar(value="Applied equally to both traces; does not change the simulation.")
        label = ttk.Label(smooth, textvariable=self.smoothing_info, style="Caption.TLabel", width=1, justify="left")
        label.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        wrap_to_width(label, smooth, 24)
        self.error = tk.StringVar()
        self.status = tk.StringVar()
        self.metrics = tk.StringVar()
        for variable, style in ((self.error, "Error.TLabel"), (self.status, "Warning.TLabel"), (self.metrics, "Caption.TLabel")):
            label = ttk.Label(body, textvariable=variable, style=style, width=1, justify="left")
            label.pack(fill="x", pady=(0, 10))
            wrap_to_width(label, body, 24)
        ttk.Button(body, text="Model & numerical notices", command=self.show_notices,
                   style="Quiet.TButton").pack(anchor="w", pady=4)
        buttons = ttk.Frame(sidebar)
        buttons.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        self.run_button = ttk.Button(buttons, text="Run back simulation", command=self.run, style="Primary.TButton")
        self.run_button.pack(fill="x", pady=(0, 8))
        ttk.Button(buttons, text="Reset simulation settings", command=self.reset_settings).pack(fill="x")
        self.figure = ComparisonFigure(self)
        self.figure.grid(row=0, column=1, sticky="nsew")
        self.alpha.trace_add("write", self._alpha_changed)
        self.kinetic_model.trace_add("write", self._alpha_changed)
        self.lambda_eV.trace_add("write", self._alpha_changed)
        for variable in self.smoothing_vars.values():
            variable.trace_add("write", self._smoothing_changed)

    def set_analysis(self, result):
        if result is self.analysis:
            return
        self.clear()
        self.analysis = result
        self.reset_settings()
        try:
            p = simulation_inputs(result)
            self.input_summary.set(
                f"E⁰: {p['e0']:.6g} V\nkₛ: {p['k_s']:.6g} cm/s\n"
                f"Initial species: {p['initial_species']} only\nEstimated bulk: {p['initial_concentration']*1e6:.6g} mM\n"
                f"Cycle: {result.config.cv_cycles_n} (earlier history retained)\n"
                "D, T, n and area inherited from analysis. No fitting.")
        except ValueError as exc:
            self.input_summary.set(str(exc))

    def clear(self):
        if self._plot_job is not None:
            self.after_cancel(self._plot_job)
            self._plot_job = None
        self.analysis = self.simulation = self.view = None
        self.figure.clear()
        for variable in (self.error, self.status, self.metrics):
            variable.set("")
        self.input_summary.set("Run the main analysis first.")

    def reset_settings(self):
        self._loading = True
        self.kinetic_model.set("B-V")
        self.alpha.set("0.5")
        self.lambda_eV.set("")
        for key, variable in self.smoothing_vars.items():
            variable.set(str(getattr(self.analysis.config, key) if self.analysis else DEFAULTS[key]))
        self._loading = False
        self._alpha_changed()
        self._smoothing_changed()

    def _alpha_changed(self, *_args):
        if self._loading:
            return
        is_bv = self.kinetic_model.get() == "B-V"
        self.alpha_entry.configure(state="normal" if is_bv else "disabled")
        self.lambda_entry.configure(state="disabled" if is_bv else "normal")
        stale = False
        if self.simulation:
            try:
                values = self.kinetics_values()
                metadata = self.simulation.simulation.metadata
                stale = values["kinetic_model"] != metadata.get("model", "BV")
                parameter = "alpha" if values["kinetic_model"] == "BV" else "lambda_eV"
                stale = stale or values[parameter] != metadata[parameter]
            except ValueError:
                stale = True
        self.app.state.simulation_outdated = stale
        if stale:
            self.app.state.saved_path = None
        self.sync_status()
        self.app._update_shell_state()

    def sync_status(self):
        if self.simulation and (self.app.state.simulation_outdated or self.app.state.result_outdated):
            self.status.set(f"Settings changed: showing the last completed simulation "
                            f"({kinetic_description(self.simulation.simulation.metadata)}). Run again to update.")
        elif self.simulation:
            self.status.set("Comparison uses estimated bulk concentration and planar diffusion.")
        else:
            self.status.set("Run simulation to compare with the BG-subtracted CV.")

    def smoothing_values(self):
        return parse_smoothing({key: var.get() for key, var in self.smoothing_vars.items()})

    def _smoothing_changed(self, *_args):
        if self._loading:
            return
        enabled = self.smoothing_vars["smoothing_enabled"].get().lower() in {"true", "1"}
        for entry in self.smoothing_entries:
            entry.configure(state="normal" if enabled else "disabled")
        if self.simulation:
            self.app.state.saved_path = None
            self.view = None
            self.figure.drawer = None
        if self._plot_job:
            self.after_cancel(self._plot_job)
        self._plot_job = self.after(350, self.refresh_plot)

    def refresh_plot(self):
        self._plot_job = None
        if self.simulation is None:
            return
        try:
            self.view = comparison_view(self.simulation, self.smoothing_values())
            self.figure.set_comparison(self.simulation, self.view)
            self.error.set("")
            raw, displayed = self.view["raw_metrics"], self.view["displayed_metrics"]
            peaks = []
            for scan in ("forward", "backward"):
                peak = raw[scan]
                if peak["peak_current_difference_a"] is None:
                    peaks.append(f"{scan.title()} peak: not identified")
                else:
                    peaks.append(f"{scan.title()} peak ΔI: {peak['peak_current_difference_a']*1e6:.4g} µA; "
                                 f"ΔE: {peak['peak_potential_difference_v']*1000:.4g} mV")
            self.metrics.set(
                f"Unsmoothed comparison\nRMSE: {raw['selected_cycle']['rmse_a']*1e6:.4g} µA\n"
                f"Max |residual|: {raw['selected_cycle']['max_absolute_error_a']*1e6:.4g} µA\n"
                f"Forward RMSE: {raw['forward']['rmse_a']*1e6:.4g} µA\n"
                f"Backward RMSE: {raw['backward']['rmse_a']*1e6:.4g} µA\n\n"
                f"Displayed RMSE: {displayed['selected_cycle']['rmse_a']*1e6:.4g} µA\n\n"
                "Raw peak differences (experiment − simulation)\n" + "\n".join(peaks))
            self.smoothing_info.set(
                f"Both traces: {self.view['effective_span_mv']:g} mV, {self.view['effective_points']} samples. "
                "Simulation unchanged." if self.view["smoothing"]["smoothing_enabled"] else
                "Both traces unsmoothed. Simulation unchanged.")
        except ValueError as exc:
            self.view = None
            self.figure.clear()
            self.metrics.set("")
            self.error.set(str(exc) + " Comparison not displayed or exportable.")
        self.app._update_shell_state()

    def show_simulation(self, simulation):
        self.simulation = simulation
        self._alpha_changed()
        self.refresh_plot()
        self.sync_status()

    def run(self):
        try:
            values = self.kinetics_values()
            self.smoothing_values()
            self.error.set("")
            self.app.run_back_simulation(**values)
        except ValueError as exc:
            self.error.set(str(exc))

    def kinetics_values(self):
        model = normalize_model(self.kinetic_model.get())
        if model == "BV":
            try:
                alpha = float(self.alpha.get())
            except ValueError as exc:
                raise ValueError("Enter alpha between 0 and 1.") from exc
            if not np.isfinite(alpha) or not 0 < alpha < 1:
                raise ValueError("Alpha must be between 0 and 1.")
            return {"kinetic_model": "BV", "alpha": alpha}
        try:
            lam = float(self.lambda_eV.get())
        except ValueError as exc:
            raise ValueError("Enter a positive reorganization energy λ in eV.") from exc
        if not np.isfinite(lam) or lam <= 0:
            raise ValueError("Enter a positive reorganization energy λ in eV.")
        return {"kinetic_model": "MHL", "lambda_eV": lam}

    def show_notices(self):
        if self.simulation:
            warnings = self.simulation.simulation.diagnostics["warnings"]
            extra = self.view["warnings"] if self.view else []
            messagebox.showinfo("Back simulation", "\n\n".join(warnings + extra))
        else:
            messagebox.showinfo("Back simulation", "Planar diffusion with B-V (alpha) or MHL (lambda in eV), with one initial species. "
                                "MHL follows the reference's symmetric constant-DOS MHC integral. "
                                "No fitting, charging current or iR correction. Earlier cycles are simulated, not reset.")
