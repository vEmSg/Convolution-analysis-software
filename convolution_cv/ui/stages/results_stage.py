import tkinter as tk
from tkinter import ttk, messagebox

import numpy as np

from ...engine import calculate_k_s, calculate_k_s_error
from ...plotting import error_potential_window
from ..parameter_schema import ERROR_PARAMETERS
from ...formatting import format_e0, format_k_s
from ..widgets import FigureGrid, ParameterForm, ScrollFrame, PageTabs
from .simulation_tab import BackSimulationTab


class ResultsStage(ttk.Frame):
    KINETICS_SCAN_OPTIONS = {
        "Backward (default)": "backward",
        "Forward": "forward",
        "Both": "both",
    }

    def __init__(self, master, app):
        super().__init__(master, padding=(24, 20))
        self.app = app
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        heading = ttk.Frame(self)
        heading.grid(row=0, column=0, sticky="ew")
        heading.columnconfigure(0, weight=1)
        ttk.Label(heading, text="Results", style="StageTitle.TLabel").grid(row=0, column=0, sticky="w")
        self.save_state_variable = tk.StringVar(value="No result")
        heading_actions = ttk.Frame(heading)
        heading_actions.grid(row=0, column=1, sticky="e")
        ttk.Button(heading_actions, text="Edit parameters", command=lambda: app.show_stage(2)).pack(side="left", padx=(0, 8))
        ttk.Button(heading_actions, text="Save results…", command=app.save_latest_result,
                   style="Primary.TButton").pack(side="left")

        cards = ttk.Frame(self, style="Surface.TFrame")
        cards.grid(row=1, column=0, sticky="ew", pady=(16, 16))
        for column in range(3):
            cards.columnconfigure(column, weight=1)
        self.e0_variable = tk.StringVar(value="--")
        self.k_s_variable = tk.StringVar(value="--")
        self.analysis_variable = tk.StringVar(value="No analysis")
        self.metric_labels = [
            self._card(cards, 0, "Formal potential · E⁰", self.e0_variable),
            self._card(cards, 1, "Rate constant · kₛ", self.k_s_variable),
            self._card(cards, 2, "Analysis", self.analysis_variable),
        ]

        self.notebook = PageTabs(self)
        self.notebook.grid(row=2, column=0, sticky="nsew")

        main_tab = ttk.Frame(self.notebook, padding=(0, 8, 0, 0))
        main_tab.rowconfigure(1, weight=1)
        main_tab.columnconfigure(0, weight=1)
        result_controls = ttk.Frame(main_tab)
        result_controls.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        result_controls.columnconfigure(0, weight=1)
        self.k_s_detail_variable = tk.StringVar()
        kinetics_controls = ttk.Frame(result_controls)
        kinetics_controls.grid(row=0, column=0, sticky="w")
        ttk.Button(result_controls, text="Method & notices", command=self.show_details, style="Quiet.TButton").grid(row=0, column=1, sticky="e")
        ttk.Label(
            kinetics_controls, text="Scan"
        ).pack(side="left", padx=(0, 5))
        self.kinetics_scan_variable = tk.StringVar(value="Backward (default)")
        self.kinetics_scan_selector = ttk.Combobox(
            kinetics_controls,
            textvariable=self.kinetics_scan_variable,
            values=list(self.KINETICS_SCAN_OPTIONS),
            state="readonly",
            width=17,
        )
        self.kinetics_scan_selector.pack(side="left")
        self.kinetics_scan_selector.bind(
            "<<ComboboxSelected>>", self._kinetics_scan_changed
        )
        self.displayed_main_result = None
        self.main_figures = FigureGrid(main_tab)
        self.main_figures.grid(row=1, column=0, sticky="nsew")
        self.notebook.add(main_tab, text="Main Results")

        error_tab = ttk.Frame(self.notebook, padding=(0, 8, 0, 0))
        error_tab.columnconfigure(1, weight=1)
        error_tab.rowconfigure(0, weight=1)
        self.error_controls = ttk.Frame(error_tab)
        self.error_controls.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        self.error_controls.rowconfigure(1, weight=1)
        self.error_controls.columnconfigure(0, weight=1)
        inspector_header = ttk.Frame(self.error_controls)
        inspector_header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(inspector_header, text="Error inputs", style="SectionTitle.TLabel").pack(side="left")
        ttk.Button(inspector_header, text="Clear", command=app.restore_error_defaults, style="Quiet.TButton").pack(side="right")
        form_scroll = ScrollFrame(self.error_controls, width=310)
        form_scroll.grid(row=1, column=0, sticky="nsew")
        controls = form_scroll.inner
        self.error_form = ParameterForm(controls, ERROR_PARAMETERS, on_change=app.mark_error_parameters_edited,
                                        inspector=True, entry_width=8)
        self.error_form.pack(fill="x")
        error_buttons = ttk.Frame(self.error_controls)
        error_buttons.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        ttk.Button(
            error_buttons, text="Run error analysis", command=self.run_error,
            style="Primary.TButton",
        ).pack(fill="x", pady=(0, 8))
        ttk.Button(error_buttons, text="Apply selection limit", command=self.apply_limit).pack(
            fill="x"
        )
        self.error_summary_variable = tk.StringVar(value="Run error analysis to display uncertainty.")
        ttk.Label(controls, text="Current: before smoothing, including background noise.\nCapacitance: absolute. Diameter and diffusion: relative (%).\nError model ignores smoothing.",
                  style="Caption.TLabel", justify="left", wraplength=250).pack(anchor="w", padx=12, pady=(4, 12))
        ttk.Button(controls, text="View selection details…", style="Quiet.TButton",
                   command=lambda: messagebox.showinfo("Selection details", self.error_summary_variable.get())).pack(anchor="w", padx=4)

        error_plot_area = ttk.Frame(error_tab)
        error_plot_area.grid(row=0, column=1, sticky="nsew")
        error_plot_area.columnconfigure(0, weight=1)
        error_plot_area.rowconfigure(1, weight=1)
        error_plot_header = ttk.Frame(error_plot_area)
        error_plot_header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        error_plot_header.columnconfigure(0, weight=1)
        error_kinetics_controls = ttk.Frame(error_plot_header)
        error_kinetics_controls.grid(row=0, column=1, sticky="e")
        self.inputs_button = ttk.Button(error_plot_header, text="Hide inputs", command=self.toggle_error_controls, style="Quiet.TButton")
        self.inputs_button.grid(row=0, column=0, sticky="w")
        ttk.Label(
            error_kinetics_controls, text="Scan"
        ).pack(side="left", padx=(0, 5))
        self.error_kinetics_scan_variable = tk.StringVar(value="Backward (default)")
        self.error_kinetics_scan_selector = ttk.Combobox(
            error_kinetics_controls,
            textvariable=self.error_kinetics_scan_variable,
            values=list(self.KINETICS_SCAN_OPTIONS),
            state="readonly",
            width=17,
        )
        self.error_kinetics_scan_selector.pack(side="left")
        self.error_kinetics_scan_selector.bind(
            "<<ComboboxSelected>>", self._error_kinetics_scan_changed
        )
        self.error_figures = FigureGrid(error_plot_area)
        self.error_figures.grid(row=1, column=0, sticky="nsew")
        self.displayed_error_result = None
        self.notebook.add(error_tab, text="Error Analysis")
        self.simulation_tab = BackSimulationTab(self.notebook, app)
        self.notebook.add(self.simulation_tab, text="Back Simulation")

    def _card(self, master, column, title, variable):
        frame = ttk.Frame(master, padding=(16, 10), style="Surface.TFrame")
        frame.grid(row=0, column=column, sticky="nsew")
        ttk.Label(frame, text=title, style="MetricTitle.TLabel").pack(anchor="w", pady=(0, 4))
        value_label = ttk.Label(frame, textvariable=variable, style="Status.TLabel" if column == 2 else "ResultValue.TLabel")
        value_label.pack(anchor="w")
        if column == 2:
            ttk.Label(frame, textvariable=self.save_state_variable, style="MetricTitle.TLabel").pack(anchor="w", pady=(2, 0))
        return value_label

    def set_error_values(self, values) -> None:
        self.error_form.set_values(values)

    def show_result(self, result, saved=False, outdated=False) -> None:
        self.simulation_tab.set_analysis(result)
        if self.displayed_main_result is not result:
            self.displayed_error_result = None
            self.error_figures.clear()
            self.error_summary_variable.set("Run error analysis to display uncertainty.")
        self.displayed_main_result = result
        try:
            k_s = calculate_k_s(result)
        except (ValueError, OverflowError):
            k_s = None
        error = self.displayed_error_result
        self.e0_variable.set(format_e0(result.e0, error.error_e0 if error is not None else None))
        self.k_s_variable.set(format_k_s(k_s.k_s if k_s else None,
                                      calculate_k_s_error(error) if error is not None else None))
        self.analysis_variable.set("Outdated" if outdated else "Completed")
        self.save_state_variable.set("Saved" if saved else "Not saved")
        self.k_s_detail_variable.set(
            f"Cycle {result.config.cv_cycles_n} · E⁰ and kₛ from backward scan · {len(result.warnings)} method notice(s)"
        )
        self._redraw_main_figures()

    def _kinetics_scan_changed(self, _event=None) -> None:
        self._redraw_main_figures()

    def _redraw_main_figures(self) -> None:
        if self.displayed_main_result is None:
            return
        scan = self.KINETICS_SCAN_OPTIONS[self.kinetics_scan_variable.get()]
        self.main_figures.set_result(self.displayed_main_result, kinetics_scan=scan)

    def show_error_result(self, result) -> None:
        self.displayed_error_result = result
        self.e0_variable.set(format_e0(result.e0, result.error_e0))
        try:
            k_s = calculate_k_s(result).k_s
        except (ValueError, OverflowError):
            k_s = None
        self.k_s_variable.set(format_k_s(k_s, calculate_k_s_error(result)))
        self._redraw_error_figures()
        self._update_error_summary()

    def _error_kinetics_scan_changed(self, _event=None) -> None:
        self._redraw_error_figures()
        self._update_error_summary()

    def _redraw_error_figures(self) -> None:
        if self.displayed_error_result is None:
            return
        scan = self.KINETICS_SCAN_OPTIONS[
            self.error_kinetics_scan_variable.get()
        ]
        self.error_figures.set_result(self.displayed_error_result, show_error=True, kinetics_scan=scan)

    def _update_error_summary(self) -> None:
        result = self.displayed_error_result
        if result is None:
            return
        selection = self.KINETICS_SCAN_OPTIONS[
            self.error_kinetics_scan_variable.get()
        ]
        scans = ("forward", "backward") if selection == "both" else (selection,)
        lines = [f"E0: {format_e0(result.e0, result.error_e0)}"]
        if result.error_analysis is not None:
            details = result.error_analysis
            lines.extend([f"Estimated bulk: {details.estimated_bulk_concentration*1e6:.6g} mM",
                          f"MultiD D = sqrt(DO*DR): {details.effective_diffusion:.6g} cm²/s",
                          "Estimated errors and sensitivity bounds; both kinetic widths must pass."])
        for scan in scans:
            potential = getattr(result, f"{scan}_potential")
            chosen = getattr(result, f"chosen_{scan}_indices")
            center = (
                result.forward_lgk_r
                if scan == "forward" else result.backward_lgk_r
            )
            window = error_potential_window(result, scan)
            window_text = (
                f"{window[0]:.6g} to {window[1]:.6g} V"
                if window is not None else "None"
            )
            nonfinite = int(np.count_nonzero(~np.isfinite(center)))
            lines.append(
                f"{scan.title()}: {len(chosen):,} / {len(potential):,} accepted; "
                f"window {window_text}; non-finite {nonfinite:,}"
            )

        lines.append(f"Error limit in lgk: {result.config.lgk_error_limit:.6g}")
        if "backward" in scans:
            try:
                k_s = calculate_k_s(result)
            except (ValueError, OverflowError):
                self.error_summary_variable.set("\n".join(lines + ["kₛ unavailable at nearest E0 sample."]))
                return
            width = max(result.backward_lgk_r_max[k_s.index] - result.backward_lgk_r_min[k_s.index],
                        result.backward_lgk_o_max[k_s.index] - result.backward_lgk_o_min[k_s.index])
            accepted = k_s.index in set(map(int, result.chosen_backward_indices))
            lines.extend(
                [
                    f"kₛ: {format_k_s(k_s.k_s, calculate_k_s_error(result))}",
                    "kₛ error uses the larger deviation of the four-bound envelope; not a confidence interval.",
                    f"kₛ point passes backward limit: {'Yes' if accepted else 'No'}",
                    f"Backward kinetic width at kₛ point (log10 units): {width:.6g}",
                ]
            )
        self.error_summary_variable.set("\n".join(lines))

    def toggle_error_controls(self):
        if self.error_controls.winfo_manager():
            self.error_controls.grid_remove()
            self.inputs_button.configure(text="Show inputs")
        else:
            self.error_controls.grid()
            self.inputs_button.configure(text="Hide inputs")

    def clear(self):
        self.simulation_tab.clear()
        self.displayed_main_result = self.displayed_error_result = None
        self.main_figures.clear()
        self.error_figures.clear()
        for variable in (self.e0_variable, self.k_s_variable):
            variable.set("—")
        self.error_summary_variable.set("Run error analysis to display uncertainty.")

    def show_details(self):
        result = self.app.state.current_result
        if result is None:
            return
        try:
            k_s = calculate_k_s(result)
            method = f"kₛ: {k_s.method}.\nE used: {k_s.nearest_potential:.6f} V\nlgkR: {k_s.lgk_r:.6g}; lgkO: {k_s.lgk_o:.6g}"
        except (ValueError, OverflowError):
            method = "kₛ is undefined at the nearest E0 sample."
        anchor = "initial point" if result.config.cv_cycles_n == 1 else "selected cycle's final point"
        messagebox.showinfo("Warnings and method", method + "\n\n" + ("\n\n".join(result.warnings) or "No calculation warnings.") +
                            f"\n\nEndpoint normalization: O = 0 at the negative endpoint; R = 0 at the positive endpoint. "
                            f"The full trace references the {anchor} and selected turning point. "
                            "Kinetics references each stored scan's own endpoints. Negative concentrations are retained. "
                            "Upper-unbounded intervals extend to the visible plot ceiling; that edge is not a finite bound. "
                            "Accepted samples are larger and opaque; other samples are translucent.")

    def run_error(self) -> None:
        values = self.error_form.validate()
        if values is not None:
            self.app.run_error_analysis(values)

    def apply_limit(self) -> None:
        definition = next(
            item for item in ERROR_PARAMETERS if item.key == "lgk_error_limit"
        )
        try:
            value = definition.parse(self.error_form.variables[definition.key].get())
        except ValueError as exc:
            self.error_form.show_errors({definition.key: str(exc)})
            return
        self.error_form.show_errors({})
        self.app.apply_error_limit(value)
