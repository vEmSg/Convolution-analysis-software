"""Application shell for the four-stage convolution-analysis workflow."""

import json
import logging
import math
import multiprocessing as mp
import queue
import traceback
import os
import sys
import subprocess
import webbrowser
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import pandas as pd

from ..engine import (
    analyze_cv,
    inspect_cv,
    inspect_background_cv,
    preview_preprocessing,
    recalculate_error_analysis,
    select_error_limit,
)
from ..reporting import export_analysis_result, ExportCancelled
from ..back_simulation import run_back_simulation, comparison_view
from ..CV_simulator import SimulationCancelled
from .parameter_schema import (
    ERROR_PARAMETERS,
    build_analysis_config,
    default_error_values,
    empty_parameter_values,
    load_preset,
    preset_payload,
)
from .stages import ConfigureStage, ImportStage, ResultsStage, ReviewStage
from .state import SessionState, Stage
from .theme import configure_theme


LOGGER = logging.getLogger("convolution_analysis")


def _analysis_worker(
    cv_path,
    config,
    potential_column,
    current_column,
    result_queue,
    expected_input_sha256=None,
    expected_background_sha256=None,
):
    """Run the numerical engine in a process isolated from the Tk event loop."""

    try:
        result = analyze_cv(
            cv_path,
            config,
            progress_callback=lambda message: result_queue.put(("progress", message)),
            potential_column=potential_column,
            current_column=current_column,
            expected_input_sha256=expected_input_sha256,
            expected_background_sha256=expected_background_sha256,
        )
        result_queue.put(("result", result))
    except Exception as exc:  # pragma: no cover - exercised through the UI boundary
        result_queue.put(("error", str(exc), traceback.format_exc()))


def _result_worker(kind, result, options, result_queue, cancel_event):
    try:
        if kind == "error":
            result_queue.put(("progress", "Calculating uncertainty for both scans"))
            output = recalculate_error_analysis(result, **options)
        elif kind == "simulation":
            output = run_back_simulation(result, **options, cancel_event=cancel_event,
                progress_callback=lambda message: result_queue.put(("progress", message)))
        else:
            import matplotlib
            matplotlib.use("Agg")
            output = export_analysis_result(result, **options, cancel_event=cancel_event,
                progress_callback=lambda message: result_queue.put(("progress", message)))
        result_queue.put(("result", output))
    except (ExportCancelled, SimulationCancelled) as exc:
        result_queue.put(("cancelled", str(exc)))
    except Exception as exc:
        result_queue.put(("error", str(exc), traceback.format_exc()))


class ConvolutionAnalysisApp:
    """Controller and persistent shell for all four interface stages."""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Convolution Analysis")
        self.root.geometry("1380x900")
        self.root.minsize(1040, 680)
        self.root.protocol("WM_DELETE_WINDOW", self.exit_application)

        self.state = SessionState()
        self._loading_values = False
        self._worker = None
        self._worker_queue = None
        self._worker_kind = "main"
        self._cancel_event = None
        self._poll_id = None
        self._progress_window = None
        self._progress_label = None
        self._progress_bar = None

        self._configure_logging()
        self._configure_styles()
        self._build_menu()
        self._build_shell()

        main_defaults, _ = empty_parameter_values()
        error_defaults = default_error_values()
        self._loading_values = True
        self.stages[Stage.CONFIGURE].set_values(main_defaults)
        self.stages[Stage.RESULTS].set_error_values(error_defaults)
        self._loading_values = False
        self.state.main_values = dict(main_defaults)
        self.state.error_values = dict(error_defaults)
        self.show_stage(Stage.IMPORT)
        self._update_shell_state("Ready")

    def _configure_logging(self) -> None:
        log_directory = Path.home() / ".convolution_analysis"
        try:
            log_directory.mkdir(exist_ok=True)
            self.log_path = log_directory / "application.log"
            if not LOGGER.handlers:
                handler = logging.FileHandler(self.log_path, encoding="utf-8")
                handler.setFormatter(
                    logging.Formatter("%(asctime)s %(levelname)s %(message)s")
                )
                LOGGER.addHandler(handler)
                LOGGER.setLevel(logging.INFO)
        except OSError:
            self.log_path = Path.cwd() / "application.log"
        LOGGER.info("Application started")

    def _configure_styles(self) -> None:
        configure_theme(self.root)

    def _build_menu(self) -> None:
        menu = tk.Menu(self.root)
        self.root.configure(menu=menu)

        file_menu = tk.Menu(menu, tearoff=False)
        file_menu.add_command(label="New Analysis", command=self.new_analysis)
        file_menu.add_command(label="Open CV File...", command=self.choose_cv_file)
        file_menu.add_command(label="Open Saved Analysis...", state="disabled")
        file_menu.add_separator()
        file_menu.add_command(label="Save Latest Results...", command=self.save_latest_result)
        file_menu.add_command(label="Export Current Figure...", command=self.export_current_figure)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.exit_application)
        menu.add_cascade(label="File", menu=file_menu)
        self.file_menu = file_menu

        analysis_menu = tk.Menu(menu, tearoff=False)
        analysis_menu.add_command(label="Review Preprocessing", command=self.review_from_menu)
        analysis_menu.add_command(label="Run Convolution Analysis", command=self.run_main_analysis)
        analysis_menu.add_command(label="Run Error Analysis", command=self.run_error_from_menu)
        analysis_menu.add_separator()
        analysis_menu.add_command(label="Cancel Current Calculation", command=self.cancel_calculation)
        menu.add_cascade(label="Analysis", menu=analysis_menu)
        self.analysis_menu = analysis_menu

        settings_menu = tk.Menu(menu, tearoff=False)
        settings_menu.add_command(label="Clear Parameter Fields", command=self.restore_defaults)
        settings_menu.add_command(label="Load Parameter Preset...", command=self.load_parameter_preset)
        settings_menu.add_command(label="Save Parameters as Preset...", command=self.save_parameter_preset)
        settings_menu.add_separator()
        settings_menu.add_command(label="Application Preferences...", state="disabled")
        menu.add_cascade(label="Settings", menu=settings_menu)

        view_menu = tk.Menu(menu, tearoff=False)
        for stage in Stage:
            view_menu.add_command(
                label=f"Go to {stage.name.title()}",
                command=lambda value=stage: self.show_stage(value),
            )
        view_menu.add_separator()
        view_menu.add_command(label="Reset Current Figure View", command=self.reset_figure_view)
        view_menu.add_command(label="Increase UI Scale", command=lambda: self.change_scale(0.1))
        view_menu.add_command(label="Decrease UI Scale", command=lambda: self.change_scale(-0.1))
        menu.add_cascade(label="View", menu=view_menu)

        help_menu = tk.Menu(menu, tearoff=False)
        help_menu.add_command(label="CSV Format", command=self.show_csv_help)
        help_menu.add_command(label="Parameter Definitions and Units", command=self.show_parameter_help)
        help_menu.add_command(label="Analysis Method", command=self.show_method_help)
        help_menu.add_command(label="Model Assumptions", command=self.show_limitations)
        help_menu.add_separator()
        help_menu.add_command(label="Open Application Log", command=self.show_log_location)
        help_menu.add_command(label="About", command=self.show_about)
        menu.add_cascade(label="Help", menu=help_menu)

    def _build_shell(self) -> None:
        shell = ttk.Frame(self.root)
        shell.pack(fill="both", expand=True)
        shell.rowconfigure(0, weight=1)
        shell.columnconfigure(1, weight=1)

        sidebar = ttk.Frame(shell, padding=(8, 20), style="Rail.TFrame")
        sidebar.grid(row=0, column=0, sticky="ns")
        ttk.Label(sidebar, text="Convolution\nAnalysis", style="Brand.TLabel",
                  justify="left").pack(anchor="w", padx=10, pady=(0, 28))
        self.stage_buttons = {}
        labels = {
            Stage.IMPORT: "1  Import",
            Stage.CONFIGURE: "2  Configure",
            Stage.REVIEW: "3  Review",
            Stage.RESULTS: "4  Results",
        }
        for stage in Stage:
            button = ttk.Button(
                sidebar,
                text=labels[stage],
                style="Stage.TButton",
                command=lambda value=stage: self.show_stage(value),
                width=14,
            )
            button.pack(fill="x", pady=2)
            self.stage_buttons[stage] = button
        ttk.Label(sidebar, text="Local workspace", style="Rail.TLabel",
                  wraplength=145, justify="left").pack(side="bottom", anchor="w", padx=10, pady=8)

        self.content = ttk.Frame(shell)
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.rowconfigure(0, weight=1)
        self.content.columnconfigure(0, weight=1)
        self.stages = {
            Stage.IMPORT: ImportStage(self.content, self),
            Stage.CONFIGURE: ConfigureStage(self.content, self),
            Stage.REVIEW: ReviewStage(self.content, self),
            Stage.RESULTS: ResultsStage(self.content, self),
        }
        for frame in self.stages.values():
            frame.grid(row=0, column=0, sticky="nsew")
            frame.grid_remove()

        status = ttk.Frame(shell, padding=(10, 5))
        status.grid(row=1, column=0, columnspan=2, sticky="ew")
        status.columnconfigure(0, weight=1)
        self.operation_variable = tk.StringVar(value="Ready")
        self.file_variable = tk.StringVar(value="File: none")
        self.result_variable = tk.StringVar(value="No result")
        ttk.Label(status, textvariable=self.operation_variable, style="Caption.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(status, textvariable=self.file_variable, style="Caption.TLabel").grid(row=0, column=1, padx=16)
        ttk.Label(status, textvariable=self.result_variable, style="Caption.TLabel").grid(row=0, column=2, sticky="e")

    def show_stage(self, stage) -> None:
        stage = Stage(int(stage))
        if stage >= Stage.CONFIGURE and self.state.inspection is None:
            if stage != Stage.IMPORT:
                messagebox.showinfo("Import required", "Choose and validate a CV file first.")
            stage = Stage.IMPORT
        if stage == Stage.REVIEW and self.state.preview is None:
            messagebox.showinfo("Preview required", "Validate parameters and generate a preprocessing preview first.")
            stage = Stage.CONFIGURE
        if stage == Stage.RESULTS and self.state.main_result is None:
            messagebox.showinfo("Analysis required", "Run convolution analysis before opening Results.")
            stage = Stage.REVIEW if self.state.preview is not None else Stage.CONFIGURE
        self.state.stage = stage
        for frame in self.stages.values():
            frame.grid_remove()
        self.stages[stage].grid()
        self.stages[stage].tkraise()
        self._update_shell_state()

    def _update_shell_state(self, operation=None) -> None:
        if operation is not None:
            self.operation_variable.set(operation)
        inspection = self.state.inspection
        self.file_variable.set(f"File: {inspection.input_path.name}" if inspection else "File: none")
        if self.state.calculating:
            result_text = "Calculating"
        elif self.state.main_result is None:
            result_text = "No result"
        elif self.state.result_outdated or self.state.error_outdated or self.state.simulation_outdated:
            result_text = "Displayed result is outdated"
        elif self.state.saved_path:
            result_text = "Current result - saved"
        else:
            result_text = "Current result - not saved"
        warning_count = len(self.state.current_result.warnings) if self.state.current_result else 0
        if warning_count:
            result_text += f" | {warning_count} warning(s)"
        self.result_variable.set(result_text)

        for stage, button in self.stage_buttons.items():
            enabled = (
                stage == Stage.IMPORT
                or (stage == Stage.CONFIGURE and inspection is not None)
                or (stage == Stage.REVIEW and self.state.preview is not None)
                or (stage == Stage.RESULTS and self.state.main_result is not None)
            )
            style = "Current.Stage.TButton" if stage == self.state.stage else "Stage.TButton"
            if stage == Stage.CONFIGURE and self.state.configure_complete and stage != self.state.stage:
                style = "Complete.Stage.TButton"
            if stage == Stage.REVIEW and self.state.preview is not None and stage != self.state.stage:
                style = "Outdated.Stage.TButton" if self.state.preview_outdated else "Complete.Stage.TButton"
            if stage == Stage.RESULTS and self.state.main_result is not None and stage != self.state.stage:
                style = "Outdated.Stage.TButton" if self.state.result_outdated else "Complete.Stage.TButton"
            if stage == Stage.IMPORT and inspection is not None and stage != self.state.stage:
                style = "Complete.Stage.TButton"
            button.configure(state="normal" if enabled else "disabled", style=style)

        has_result = self.state.main_result is not None
        self.file_menu.entryconfigure("Save Latest Results...", state="normal" if has_result else "disabled")
        self.file_menu.entryconfigure("Export Current Figure...", state="normal" if has_result else "disabled")
        self.analysis_menu.entryconfigure("Cancel Current Calculation", state="normal" if self.state.calculating else "disabled")
        self.analysis_menu.entryconfigure("Run Error Analysis", state="normal" if has_result else "disabled")
        if has_result:
            results_stage = self.stages[Stage.RESULTS]
            results_stage.simulation_tab.sync_status()
            results_stage.analysis_variable.set(
                "Outdated" if self.state.result_outdated or self.state.error_outdated else "Completed"
            )
            results_stage.save_state_variable.set(
                "Saved" if self.state.saved_path is not None else "Not saved"
            )

    def choose_cv_file(self) -> None:
        if self.state.calculating:
            return
        path = filedialog.askopenfilename(
            title="Choose cyclic-voltammetry CSV file",
            filetypes=[("CSV files", "*.csv"), ("All files", "*")],
        )
        if path:
            self.import_cv(path)

    def choose_background_cv_file(self) -> None:
        if self.state.inspection is None:
            messagebox.showinfo("Experiment required", "Import the experiment CV first.")
            return
        path = filedialog.askopenfilename(
            title="Choose background CV file",
            filetypes=[("CSV files", "*.csv"), ("All files", "*")],
        )
        if not path:
            return
        panel = self.stages[Stage.CONFIGURE].background_panel
        try:
            inspect_background_cv(self.state.inspection, path)
            panel.set_background_cv(path, valid=True)
            self._update_shell_state("Background CV validated")
            LOGGER.info("Validated background CV %s", path)
        except Exception as exc:
            panel.set_background_cv("", valid=False)
            panel.message.set(str(exc))
            LOGGER.warning("Background CV validation failed: %s", exc)
            messagebox.showerror("Background CV does not match", str(exc))
            self._update_shell_state("Background CV validation failed")

    def import_cv(self, path: str) -> None:
        if self.state.calculating:
            return
        current_path = self.state.inspection.input_path if self.state.inspection else None
        try:
            try:
                inspection = inspect_cv(path)
            except ValueError as exc:
                if "selected potential/current columns were not found" not in str(exc):
                    raise
                mapping = self._ask_column_mapping(path)
                if mapping is None:
                    return
                inspection = inspect_cv(path, mapping[0], mapping[1])
            if (self.state.inspection is None or inspection.source != self.state.inspection.source) and not self._confirm_discard_unsaved():
                return
            self.state.set_import(inspection)
            if self.state.main_result is None:
                self.stages[Stage.RESULTS].clear()
            self.stages[Stage.IMPORT].show_inspection(inspection)
            self.show_stage(Stage.IMPORT)
            self._update_shell_state("CV file validated")
            LOGGER.info("Imported %s using columns %s / %s", path, inspection.potential_column, inspection.current_column)
        except Exception as exc:
            LOGGER.exception("CV import failed")
            messagebox.showerror("Cannot import CV file", str(exc))
            self._update_shell_state("Import failed")

    def _ask_column_mapping(self, path):
        columns = [
            str(value)
            for value in pd.read_csv(path, nrows=0, skipinitialspace=True).columns
        ]
        if len(columns) < 2:
            raise ValueError("The CSV must contain at least two columns.")
        dialog = tk.Toplevel(self.root)
        dialog.title("Map CSV columns")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)
        body = ttk.Frame(dialog, padding=18)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Expected column names were not found.", style="SectionTitle.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 12))
        potential = tk.StringVar(value=columns[0])
        current = tk.StringVar(value=columns[1])
        ttk.Label(body, text="Potential column").grid(row=1, column=0, sticky="w", pady=5)
        ttk.Combobox(body, textvariable=potential, values=columns, state="readonly", width=30).grid(row=1, column=1, pady=5)
        ttk.Label(body, text="V").grid(row=1, column=2, padx=(8, 0))
        ttk.Label(body, text="Current column").grid(row=2, column=0, sticky="w", pady=5)
        ttk.Combobox(body, textvariable=current, values=columns, state="readonly", width=30).grid(row=2, column=1, pady=5)
        ttk.Label(body, text="A").grid(row=2, column=2, padx=(8, 0))
        answer = []

        def apply_mapping():
            if potential.get() == current.get():
                messagebox.showerror("Invalid mapping", "Potential and current must use different columns.", parent=dialog)
                return
            answer.append((potential.get(), current.get()))
            dialog.destroy()

        buttons = ttk.Frame(body)
        buttons.grid(row=3, column=0, columnspan=3, sticky="e", pady=(14, 0))
        ttk.Button(buttons, text="Cancel Import", command=dialog.destroy).pack(side="left", padx=5)
        ttk.Button(buttons, text="Apply Mapping", command=apply_mapping, style="Primary.TButton").pack(side="left")
        dialog.wait_window()
        return answer[0] if answer else None

    def clear_import(self) -> None:
        if self.state.calculating:
            return
        if not self._confirm_discard_unsaved():
            return
        self.state.clear_import()
        self.stages[Stage.IMPORT].clear()
        self.stages[Stage.RESULTS].clear()
        self.show_stage(Stage.IMPORT)
        self._update_shell_state("Import cleared")

    def go_to_configure(self) -> None:
        self.show_stage(Stage.CONFIGURE)

    def mark_main_parameters_edited(self) -> None:
        if self._loading_values:
            return
        raw = self.stages[Stage.CONFIGURE].raw_values()
        self.state.set_main_values(raw)
        self._update_shell_state("Parameters edited")

    def mark_error_parameters_edited(self) -> None:
        if self._loading_values:
            return
        raw = self.stages[Stage.RESULTS].error_form.raw_values()
        self.state.set_error_values(raw)
        self._update_shell_state("Error parameters edited")

    def _validated_error_values(self):
        return self.stages[Stage.RESULTS].error_form.validate()

    def review_preprocessing(self, main_values, auto=False) -> None:
        if self.state.calculating:
            return
        if self.state.inspection is None:
            self.show_stage(Stage.IMPORT)
            return
        try:
            config = build_analysis_config(main_values)
            inspection = self.state.inspection
            preview = preview_preprocessing(
                str(inspection.input_path), config,
                inspection.potential_column, inspection.current_column,
            )
            fresh = inspect_cv(str(inspection.input_path), inspection.potential_column, inspection.current_column)
            if fresh.source != preview.source:
                raise ValueError("The input changed during preview. Refresh the preview again.")
            if fresh.source != inspection.source:
                self.state.set_import(fresh)
                self.stages[Stage.IMPORT].show_inspection(fresh)
                self.stages[Stage.RESULTS].clear()
            if main_values["cv_cycles_n"] > len(preview.segments) // 2:
                raise ValueError(
                    f"Cycle {main_values['cv_cycles_n']} was requested, but only "
                    f"{len(preview.segments) // 2} complete cycle(s) were detected."
                )
            self.state.set_main_values(main_values)
            self.state.set_preview(preview)
            self.stages[Stage.REVIEW].show_preview(preview, int(main_values["cv_cycles_n"]))
            self.show_stage(Stage.REVIEW)
            self._update_shell_state("Preprocessing preview ready")
        except Exception as exc:
            LOGGER.exception("Preprocessing preview failed")
            self.stages[Stage.REVIEW].preview_failed(str(exc))
            if not auto:
                messagebox.showerror("Cannot generate preview", str(exc))
            self._update_shell_state("Preview failed")

    def refresh_preview(self, auto=False) -> None:
        values = self.stages[Stage.CONFIGURE].validate()
        if values is not None:
            self.review_preprocessing(values, auto=auto)

    def review_from_menu(self) -> None:
        self.refresh_preview()

    def run_main_analysis(self) -> None:
        if self.state.calculating:
            return
        if self.state.inspection is None or self.state.preview is None:
            self.refresh_preview()
            if self.state.preview is None:
                return
        elif self.state.preview_outdated:
            self.refresh_preview()
            if self.state.preview_outdated:
                return
        main_values = self.stages[Stage.CONFIGURE].validate()
        if main_values is None:
            messagebox.showerror("Invalid parameters", "Correct the highlighted parameter values before calculation.")
            return
        try:
            config = build_analysis_config(main_values)
            inspection = self.state.inspection
            context = mp.get_context("spawn")
            self._worker_queue = context.Queue()
            self._worker_kind = "main"
            preview = self.state.preview
            self._worker = context.Process(
                target=_analysis_worker,
                args=(
                    str(inspection.input_path), config,
                    inspection.potential_column, inspection.current_column,
                    self._worker_queue,
                    preview.source.sha256 if preview.source else None,
                    preview.background_source.sha256 if preview.background_source else None,
                ),
                daemon=True,
            )
            self.state.calculating = True
            self._worker.start()
            self._show_progress("Starting convolution analysis...")
            self._update_shell_state("Starting convolution analysis")
            self._poll_id = self.root.after(100, self._poll_worker)
        except Exception as exc:
            self.state.calculating = False
            LOGGER.exception("Could not start calculation")
            self._cleanup_worker()
            messagebox.showerror("Cannot start analysis", str(exc))
            self._close_progress()
            self._update_shell_state("Analysis could not start")

    def _start_result_job(self, kind, result, options):
        if self.state.calculating:
            return
        context = mp.get_context("spawn")
        self._worker_kind = kind
        self._cancel_event = context.Event()
        self._worker_queue = context.Queue()
        self._worker = context.Process(target=_result_worker,
            args=(kind, result, options, self._worker_queue, self._cancel_event), daemon=True)
        try:
            self._worker.start()
            self.state.calculating = True
            operation = {"export": "Saving results", "simulation": "Running back simulation", "error": "Calculating uncertainty"}[kind]
            self._show_progress(operation + "…")
            self._update_shell_state(operation)
            self._poll_id = self.root.after(100, self._poll_worker)
        except Exception:
            self.state.calculating = False
            self._cleanup_worker()
            self._close_progress()
            raise

    def _show_progress(self, message) -> None:
        window = tk.Toplevel(self.root)
        window.title("Calculating")
        window.transient(self.root)
        window.grab_set()
        window.protocol("WM_DELETE_WINDOW", self.cancel_calculation)
        window.resizable(False, False)
        body = ttk.Frame(window, padding=20)
        body.pack(fill="both", expand=True)
        self._progress_label = tk.StringVar(value=message)
        ttk.Label(body, textvariable=self._progress_label, width=48).pack(anchor="w")
        self._progress_bar = ttk.Progressbar(body, mode="indeterminate", length=430)
        self._progress_bar.pack(fill="x", pady=14)
        self._progress_bar.start(12)
        ttk.Button(body, text="Cancel", command=self.cancel_calculation).pack(anchor="e")
        self._progress_window = window

    def _poll_worker(self) -> None:
        self._poll_id = None
        if not self.state.calculating:
            return
        terminal_message = None
        try:
            while True:
                message = self._worker_queue.get_nowait()
                if message[0] == "progress":
                    self._progress_label.set(message[1])
                    self._update_shell_state(message[1])
                else:
                    terminal_message = message
                    break
        except queue.Empty:
            pass

        if terminal_message is not None:
            self._finish_worker(terminal_message)
            return
        if self._worker is not None and not self._worker.is_alive():
            try:
                while True:
                    terminal_message = self._worker_queue.get(timeout=0.3)
                    if terminal_message[0] != "progress":
                        break
            except queue.Empty:
                terminal_message = ("error", "The analysis worker exited without returning a result.", "")
            self._finish_worker(terminal_message)
            return
        self._poll_id = self.root.after(100, self._poll_worker)

    def _finish_worker(self, message) -> None:
        kind = self._worker_kind
        self._cleanup_worker()
        self.state.calculating = False
        self._close_progress()
        if message[0] == "result":
            result = message[1]
            try:
                if kind == "export":
                    self.state.mark_saved(result)
                    self._update_shell_state("Results saved")
                    self._show_saved_result(Path(result))
                elif kind == "error":
                    self.state.set_error_result(result)
                    self.stages[Stage.RESULTS].show_error_result(result)
                    self.stages[Stage.RESULTS].notebook.select(1)
                    self._update_shell_state("Error analysis completed")
                elif kind == "simulation":
                    self.state.set_simulation_result(result)
                    self.stages[Stage.RESULTS].simulation_tab.show_simulation(result)
                    self.stages[Stage.RESULTS].notebook.select(2)
                    self._update_shell_state("Back simulation completed")
                else:
                    self.state.set_main_result(result)
                    self.stages[Stage.RESULTS].show_result(result)
                    self.show_stage(Stage.RESULTS)
                    self._update_shell_state("Analysis completed")
            except Exception as exc:
                LOGGER.exception("Could not display completed result")
                messagebox.showerror("Display failed", f"The result is retained, but could not be displayed: {exc}")
        elif message[0] == "cancelled":
            self._update_shell_state("Operation cancelled; prior result retained")
            messagebox.showinfo("Operation cancelled", message[1])
        else:
            detail = message[2] if len(message) > 2 else ""
            LOGGER.error("Analysis failed: %s\n%s", message[1], detail)
            messagebox.showerror("Analysis failed", message[1])
            self._update_shell_state("Analysis failed; prior result retained")

    def _cleanup_worker(self):
        if self._poll_id is not None:
            self.root.after_cancel(self._poll_id)
            self._poll_id = None
        if self._worker is not None:
            if self._worker.pid is not None:
                self._worker.join(timeout=0.5)
                if self._worker.is_alive():
                    self._worker.terminate()
                    self._worker.join(timeout=0.5)
            self._worker.close()
        if self._worker_queue is not None:
            self._worker_queue.cancel_join_thread()
            self._worker_queue.close()
        self._worker = self._worker_queue = self._cancel_event = None

    def cancel_calculation(self) -> None:
        if not self.state.calculating:
            return
        if self._worker_kind == "export":
            self._cancel_event.set()
            self._progress_label.set("Finishing the current file and cancelling…")
            return
        if self._worker is not None and self._worker.is_alive():
            self._worker.terminate()
            self._worker.join(timeout=1.0)
        self.state.calculating = False
        self._cleanup_worker()
        self._close_progress()
        self._update_shell_state("Calculation cancelled; prior result retained")
        LOGGER.info("Analysis calculation cancelled")

    def _close_progress(self) -> None:
        if self._progress_bar is not None:
            self._progress_bar.stop()
        if self._progress_window is not None and self._progress_window.winfo_exists():
            self._progress_window.destroy()
        self._progress_window = None
        self._progress_label = None
        self._progress_bar = None

    def run_error_analysis(self, values) -> None:
        if self.state.calculating:
            return
        if self.state.main_result is None:
            messagebox.showinfo("Main result required", "Run convolution analysis first.")
            return
        try:
            base = self.state.main_result
            options = dict(
                sigma_current=values["sigma_current"],
                sigma_cdl=values["sigma_cdl"],
                sigma_diameter=values["sigma_diameter_percent"] * base.config.diameter / 100.0,
                sigma_diffusion_o=values["sigma_diffusion_o_percent"] * base.config.diffusion_o / 100.0,
                sigma_diffusion_r=values["sigma_diffusion_r_percent"] * base.config.diffusion_r / 100.0,
                lgk_error_limit=values["lgk_error_limit"],
            )
            self.state.set_error_values(values)
            self._start_result_job("error", base, options)
        except Exception as exc:
            LOGGER.exception("Error analysis failed")
            messagebox.showerror("Error analysis failed", str(exc))
            self._update_shell_state("Error analysis failed; prior result retained")

    def run_back_simulation(self, alpha=.5, kinetic_model="BV", lambda_eV=None):
        if self.state.calculating:
            return
        if self.state.main_result is None or self.state.result_outdated:
            messagebox.showinfo("Current analysis required", "Run convolution analysis with the current settings first.")
            return
        try:
            self._start_result_job("simulation", self.state.main_result,
                                   {"alpha": alpha, "kinetic_model": kinetic_model, "lambda_eV": lambda_eV})
        except Exception as exc:
            LOGGER.exception("Could not start back simulation")
            messagebox.showerror("Back simulation failed", str(exc))

    def run_error_from_menu(self) -> None:
        values = self._validated_error_values()
        if values is not None:
            self.run_error_analysis(values)

    def apply_error_limit(self, error_limit) -> None:
        if self.state.calculating:
            return
        base = self.state.error_result
        if base is None:
            messagebox.showinfo(
                "Error analysis required",
                "Run error analysis once before changing only its selection limit.",
            )
            return
        try:
            result = select_error_limit(base, error_limit)
            raw_values = self.stages[Stage.RESULTS].error_form.raw_values()
            parsed_values = {}
            other_inputs_outdated = False
            for definition in ERROR_PARAMETERS:
                if definition.key == "lgk_error_limit":
                    continue
                try:
                    parsed_values[definition.key] = definition.parse(
                        raw_values.get(definition.key, "")
                    )
                except ValueError:
                    other_inputs_outdated = True
            expected = {
                "sigma_current": base.config.sigma_current,
                "sigma_cdl": base.config.sigma_cdl,
                "sigma_diameter_percent": 100.0 * base.config.sigma_diameter / base.config.diameter,
                "sigma_diffusion_o_percent": 100.0 * base.config.sigma_diffusion_o / base.config.diffusion_o,
                "sigma_diffusion_r_percent": 100.0 * base.config.sigma_diffusion_r / base.config.diffusion_r,
            }
            other_inputs_outdated = other_inputs_outdated or any(
                not math.isclose(parsed_values.get(key, float("nan")), expected_value, rel_tol=1e-12, abs_tol=1e-15)
                for key, expected_value in expected.items()
            )
            self.state.error_result = result
            self.state.saved_path = None
            self.state.error_outdated = other_inputs_outdated
            self.stages[Stage.RESULTS].show_error_result(result)
            operation = "Error-limit selection updated"
            if other_inputs_outdated:
                operation += "; other error-input edits still require recalculation"
            self._update_shell_state(operation)
        except Exception as exc:
            messagebox.showerror("Cannot apply error limit", str(exc))

    def restore_defaults(self) -> None:
        if self.state.calculating:
            return
        main, error = empty_parameter_values()
        main.update(self.stages[Stage.REVIEW].smoothing_values())
        self._loading_values = True
        self.stages[Stage.CONFIGURE].set_values(main)
        self.stages[Stage.RESULTS].set_error_values(error)
        self._loading_values = False
        self.state.set_main_values(main)
        self.state.set_error_values(error)
        self._update_shell_state("Parameter fields cleared")

    def restore_error_defaults(self) -> None:
        if self.state.calculating:
            return
        _main, error = empty_parameter_values()
        self._loading_values = True
        self.stages[Stage.RESULTS].set_error_values(error)
        self._loading_values = False
        self.state.set_error_values(error)
        self._update_shell_state("Error fields cleared")

    def load_parameter_preset(self) -> None:
        if self.state.calculating:
            return
        path = filedialog.askopenfilename(
            title="Load parameter preset", filetypes=[("JSON files", "*.json"), ("All files", "*")]
        )
        if not path:
            return
        try:
            main, error = load_preset(path)
            self._loading_values = True
            self.stages[Stage.CONFIGURE].set_values(main)
            self.stages[Stage.RESULTS].set_error_values(error)
            self._loading_values = False
            self.state.set_main_values(main)
            self.state.set_error_values(error)
            self._update_shell_state("Parameter preset loaded")
        except Exception as exc:
            messagebox.showerror("Cannot load preset", str(exc))

    def save_parameter_preset(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Save parameter preset", defaultextension=".json",
            filetypes=[("JSON files", "*.json")],
        )
        if not path:
            return
        try:
            payload = preset_payload(
                self.stages[Stage.CONFIGURE].raw_values(),
                self.stages[Stage.RESULTS].error_form.raw_values(),
            )
            Path(path).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            self._update_shell_state("Parameter preset saved")
        except Exception as exc:
            messagebox.showerror("Cannot save preset", str(exc))

    def save_latest_result(self) -> None:
        if self.state.calculating:
            return
        result = self.state.current_result
        if result is None:
            messagebox.showinfo("No result", "Run an analysis before saving results.")
            return
        dialog = tk.Toplevel(self.root)
        dialog.title("Save analysis")
        dialog.transient(self.root)
        dialog.grab_set()
        body = ttk.Frame(dialog, padding=22)
        body.pack(fill="both", expand=True)
        error_included = self.state.error_result is not None
        outdated = self.state.result_outdated or self.state.error_outdated
        results = self.stages[Stage.RESULTS]
        simulation = self.state.simulation_result
        simulation_smoothing = None
        if simulation is not None:
            try:
                simulation_smoothing = results.simulation_tab.smoothing_values()
                comparison_view(simulation, simulation_smoothing)
            except ValueError as exc:
                messagebox.showerror("Invalid comparison smoothing", str(exc), parent=dialog)
                dialog.destroy()
                return
        main_scan = results.KINETICS_SCAN_OPTIONS[results.kinetics_scan_variable.get()]
        error_scan = results.KINETICS_SCAN_OPTIONS[results.error_kinetics_scan_variable.get()]
        text = (f"{result.input_path.name}\n\nOffline overview report • readable CSVs • file guide\n"
                "PNG, SVG and PDF figures • original input copies\nCSV data folders and reproducibility manifest\n\n"
                f"Main kinetics: {main_scan}\nError analysis: {error_scan if error_included else 'not requested'}\n"
                f"Back simulation: {'last completed run' if simulation is not None else 'not run'}\n"
                + ("Simulation settings changed; last completed parameters will be recorded.\n" if self.state.simulation_outdated else "") + "\n"
                + ("Settings have changed. This exports the last successful result and its original settings." if outdated else "Result matches the current calculation settings."))
        ttk.Label(body, text=text, wraplength=460, justify="left").pack(anchor="w")
        def save():
            output_root = filedialog.askdirectory(parent=dialog, title="Choose a folder for this analysis")
            if not output_root:
                return
            dialog.destroy()
            try:
                self._start_result_job("export", result, dict(output_root=output_root,
                    include_error_figures=error_included, kinetics_scan=main_scan,
                    error_kinetics_scan=error_scan, result_outdated=outdated,
                    simulation=simulation, simulation_smoothing=simulation_smoothing,
                    simulation_outdated=self.state.simulation_outdated))
            except Exception as exc:
                messagebox.showerror("Cannot save results", str(exc))
        ttk.Button(body, text="Choose folder & save…", command=save, style="Primary.TButton").pack(anchor="e", pady=(18, 0))

    def _show_saved_result(self, path):
        window = tk.Toplevel(self.root)
        window.title("Results saved")
        body = ttk.Frame(window, padding=22)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=f"Your analysis is ready.\n{path}", wraplength=480).pack(anchor="w")
        ttk.Button(body, text="Open overview report", command=lambda: webbrowser.open((path / "Overview.html").as_uri()), style="Primary.TButton").pack(fill="x", pady=(15, 5))
        def open_folder():
            try:
                if sys.platform == "darwin":
                    subprocess.Popen(["open", str(path)])
                elif sys.platform == "win32":
                    os.startfile(str(path))
                else:
                    subprocess.Popen(["xdg-open", str(path)])
            except OSError as exc:
                messagebox.showerror("Cannot open folder", str(exc))
        ttk.Button(body, text="Open folder", command=open_folder).pack(fill="x")

    def export_current_figure(self) -> None:
        if self.state.main_result is None:
            return
        results = self.stages[Stage.RESULTS]
        selected = results.notebook.index(results.notebook.select())
        if selected == 2:
            results.simulation_tab.refresh_plot()
            results.simulation_tab.figure.export()
        else:
            (results.error_figures if selected == 1 else results.main_figures).export()

    def reset_figure_view(self) -> None:
        if self.state.main_result is None:
            return
        results = self.stages[Stage.RESULTS]
        if results.notebook.index(results.notebook.select()) == 2:
            results.simulation_tab.refresh_plot()
            return
        self.stages[Stage.RESULTS].show_result(
            self.state.main_result,
            saved=self.state.saved_path is not None,
            outdated=self.state.result_outdated,
        )
        if self.state.error_result is not None:
            self.stages[Stage.RESULTS].show_error_result(self.state.error_result)

    def change_scale(self, delta) -> None:
        current = float(self.root.tk.call("tk", "scaling"))
        self.root.tk.call("tk", "scaling", min(2.5, max(0.8, current + delta)))

    def new_analysis(self) -> None:
        if self.state.calculating:
            return
        if not self._confirm_discard_unsaved():
            return
        self.state.reset()
        self.stages[Stage.IMPORT].clear()
        self.stages[Stage.RESULTS].clear()
        self.stages[Stage.REVIEW].info_variable.set("Generate a preview from Configure.")
        self.stages[Stage.REVIEW].warning_variable.set("")
        self.show_stage(Stage.IMPORT)
        self._update_shell_state("New analysis ready")

    def _confirm_discard_unsaved(self) -> bool:
        if not self.state.has_unsaved_result:
            return True
        return messagebox.askyesno(
            "Unsaved result",
            "The newest successful result has not been saved. Continue and discard it?",
        )

    def exit_application(self) -> None:
        if self.state.calculating:
            if not messagebox.askyesno("Calculation running", "Cancel the calculation and exit?"):
                return
            self.cancel_calculation()
            if self.state.calculating:
                return
        if not self._confirm_discard_unsaved():
            return
        LOGGER.info("Application closed")
        self.root.destroy()

    def show_csv_help(self) -> None:
        messagebox.showinfo(
            "CSV format",
            "Choose a CSV with numeric potential and current columns. The preferred names are "
            "Potential/V and Current/A. Other names can be mapped during import. Use volts and amperes, "
            "with positive current for oxidation. Import requires at least 3 valid rows. Analysis "
            "requires a complete selected cycle and enough samples for the chosen smoothing window. "
            "Include the current history from the start of the first sweep.",
        )

    def show_parameter_help(self) -> None:
        messagebox.showinfo(
            "Parameters and units",
            "The Configure stage lists experiment, transport, and background-correction inputs with "
            "their units. Scientific notation is accepted. Error inputs use absolute A/F values and "
            "percentage uncertainties for diameter and diffusion coefficients.",
        )

    def show_method_help(self) -> None:
        messagebox.showinfo(
            "Analysis method",
            "E0 is calculated from the reverse scan near zero current using the concentration ratio. "
            "kₛ is the geometric mean of kO and kR at the reverse-scan potential nearest E0. Saving "
            "exports the latest successful in-memory result and does not rerun the analysis.",
        )

    def show_limitations(self) -> None:
        messagebox.showinfo(
            "Model assumptions",
            "Convolution analysis uses semi-infinite planar diffusion for a dissolved redox couple. "
            "Migration, convection, adsorption and coupled chemical reactions are assumed negligible. "
            "Surface concentrations are referenced to depletion of O at the negative potential endpoint "
            "and R at the positive endpoint. See docs/DATA_ANALYSIS_METHOD.md for the equations.",
        )

    def show_log_location(self) -> None:
        messagebox.showinfo("Application log", f"The application log is stored at:\n{self.log_path}")

    def show_about(self) -> None:
        messagebox.showinfo(
            "About Convolution Analysis",
            "Convolution Analysis\nFour-stage research workflow\nImport -> Configure -> Review -> Results",
        )


def launch() -> None:
    """Start the desktop application."""

    mp.freeze_support()
    root = tk.Tk()
    ConvolutionAnalysisApp(root)
    root.mainloop()
