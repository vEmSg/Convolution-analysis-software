import tkinter as tk
from tkinter import ttk

from ...smoothing import DEFAULTS, parse_smoothing
from ...plotting import draw_preprocessing
from ..widgets import SingleFigure, wrap_to_width, ScrollFrame
from ..state import Stage


class ReviewStage(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=18)
        self.app = app
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        ttk.Label(self, text="Review preprocessing", style="StageTitle.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            self,
            text="Confirm background correction, smoothing, scan detection, and cycle selection before running the full calculation.",
            style="Subtitle.TLabel",
            wraplength=950,
        ).grid(row=1, column=0, sticky="w", pady=(2, 12))

        content = ttk.Panedwindow(self, orient="horizontal")
        content.grid(row=2, column=0, sticky="nsew")
        figure_holder = ttk.Frame(content)
        detail_scroll = ScrollFrame(content, width=320)
        details = detail_scroll.inner
        content.add(figure_holder, weight=4)
        content.add(detail_scroll, weight=2)
        figure_holder.rowconfigure(0, weight=1)
        figure_holder.columnconfigure(0, weight=1)
        self.figure = SingleFigure(figure_holder, figsize=(8, 5.5))
        self.figure.grid(row=0, column=0, sticky="nsew")

        self._setting_smoothing = False
        self._smoothing_job = None
        smoothing = ttk.LabelFrame(details, text="Smoothing", padding=10)
        smoothing.pack(fill="x", pady=(0, 16))
        self.smoothing_vars = {key: tk.StringVar(value=value) for key, value in DEFAULTS.items()}
        ttk.Radiobutton(smoothing, text="No smoothing", variable=self.smoothing_vars["smoothing_enabled"],
                        value="False").grid(row=0, column=0, columnspan=2, sticky="w", pady=3)
        ttk.Radiobutton(smoothing, text="Savitzky–Golay (SG)", variable=self.smoothing_vars["smoothing_enabled"],
                        value="True").grid(row=1, column=0, columnspan=2, sticky="w", pady=3)
        self.smoothing_entries = []
        for row, (key, label) in enumerate((("smoothing_window_mv", "Window (mV)"),
                                           ("smoothing_order", "Polynomial order")), start=2):
            ttk.Label(smoothing, text=label).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=4)
            entry = ttk.Entry(smoothing, textvariable=self.smoothing_vars[key], width=7)
            entry.grid(row=row, column=1, sticky="w", pady=4)
            self.smoothing_entries.append(entry)
        smoothing.columnconfigure(0, weight=1)
        self.smoothing_info = tk.StringVar(value="Full potential span; preview updates automatically.")
        hint = ttk.Label(smoothing, textvariable=self.smoothing_info, style="Caption.TLabel", justify="left", width=1)
        hint.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        wrap_to_width(hint, smoothing, 24)
        self.smoothing_error = tk.StringVar()
        error = ttk.Label(smoothing, textvariable=self.smoothing_error, style="Error.TLabel", justify="left", width=1)
        error.grid(row=5, column=0, columnspan=2, sticky="ew")
        wrap_to_width(error, smoothing, 24)

        ttk.Label(details, text="Detected structure", style="SectionTitle.TLabel").pack(anchor="w")
        self.info_variable = tk.StringVar(value="Generate a preview from Configure.")
        info = ttk.Label(details, textvariable=self.info_variable, justify="left", width=25)
        info.pack(anchor="w", fill="x", pady=(6, 14))
        wrap_to_width(info, details, 22)
        ttk.Label(details, text="Warnings", style="SectionTitle.TLabel").pack(anchor="w")
        self.warning_variable = tk.StringVar()
        ttk.Label(
            details, textvariable=self.warning_variable, style="Warning.TLabel",
            justify="left", wraplength=340,
        ).pack(anchor="w", fill="x", pady=(6, 0))

        buttons = ttk.Frame(self)
        buttons.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        ttk.Button(buttons, text="<- Edit Parameters", command=lambda: app.show_stage(2)).pack(side="left")
        ttk.Button(buttons, text="Refresh Preview", command=app.refresh_preview).pack(side="left", padx=6)
        self.run_button = ttk.Button(
            buttons, text="Run Convolution Analysis ->", command=app.run_main_analysis,
            style="Primary.TButton",
        )
        self.run_button.pack(side="right")
        for variable in self.smoothing_vars.values():
            variable.trace_add("write", self._smoothing_changed)

    def smoothing_values(self):
        return {key: variable.get() for key, variable in self.smoothing_vars.items()}

    def set_smoothing(self, values):
        self._setting_smoothing = True
        try:
            if self._smoothing_job is not None:
                self.after_cancel(self._smoothing_job)
                self._smoothing_job = None
            for key, variable in self.smoothing_vars.items():
                variable.set(str(values.get(key, DEFAULTS[key])))
            self._sync_smoothing_fields()
        finally:
            self._setting_smoothing = False

    def _sync_smoothing_fields(self):
        enabled = self.smoothing_vars["smoothing_enabled"].get().lower() in {"true", "1"}
        for entry in self.smoothing_entries:
            entry.configure(state="normal" if enabled else "disabled")

    def validate_smoothing(self):
        try:
            return parse_smoothing(self.smoothing_values())
        except ValueError as exc:
            self.preview_failed(str(exc))
            return None

    def preview_failed(self, message):
        self.smoothing_error.set(message + " Preview has not been updated.")
        self.run_button.configure(state="disabled")

    def _smoothing_changed(self, *_args):
        if self._setting_smoothing:
            return
        self._sync_smoothing_fields()
        self.app.mark_main_parameters_edited()
        self.run_button.configure(state="disabled")
        self.smoothing_info.set("Updating preview…")
        if self._smoothing_job is not None:
            self.after_cancel(self._smoothing_job)
        self._smoothing_job = self.after(350, self._refresh_smoothing)

    def _refresh_smoothing(self):
        self._smoothing_job = None
        if not self.app.state.calculating and self.app.state.stage == Stage.REVIEW:
            self.app.refresh_preview(auto=True)

    def show_preview(self, preview, selected_cycle: int) -> None:
        self.figure.redraw(lambda axis: draw_preprocessing(axis, preview, selected_cycle))
        self.smoothing_error.set("")
        self.run_button.configure(state="normal")
        self.smoothing_info.set(
            f"Effective span: {preview.smoothing_effective_mv:g} mV ({preview.smoothing_points} samples), "
            f"order {preview.smoothing_order}." if preview.smoothing_enabled else
            "No smoothing: using background-corrected current directly.")
        self.info_variable.set(
            f"Points: {len(preview.potential):,}\n"
            f"Detected scans: {len(preview.segments)}\n"
            f"Complete cycles: {len(preview.segments) // 2}\n"
            f"Selected cycle: {selected_cycle}\n"
            f"Potential step: {preview.delta_e:.8g} V\n"
            f"Calculated time step: {preview.delta_t:.8g} s"
        )
        self.warning_variable.set(
            "\n".join(preview.warnings) if preview.warnings else "No preprocessing warnings."
        )
