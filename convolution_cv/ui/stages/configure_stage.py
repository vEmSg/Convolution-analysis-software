import tkinter as tk
from tkinter import ttk

from ...engine import inspect_background_cv
from ...models import BACKGROUND_CAPACITANCE, BACKGROUND_CV
from ..parameter_schema import MAIN_PARAMETERS
from ..state import Stage
from ..widgets import ParameterForm, ScrollFrame, wrap_to_width


DOUBLE_LAYER_DEFINITION = next(
    item for item in MAIN_PARAMETERS if item.key == "double_layer_capacity"
)


class BackgroundCorrectionPanel(ttk.LabelFrame):
    def __init__(self, master, app):
        super().__init__(master, text="Background correction", padding=(12, 10))
        self.app = app
        self.mode = tk.StringVar(value=BACKGROUND_CAPACITANCE)
        self.capacity = tk.StringVar()
        self.background_path = tk.StringVar()
        self.path_display = tk.StringVar(value="No background CV selected")
        self.message = tk.StringVar()

        ttk.Radiobutton(
            self,
            text="Use double-layer capacitance",
            variable=self.mode,
            value=BACKGROUND_CAPACITANCE,
            command=self._mode_changed,
        ).grid(row=0, column=0, sticky="w", pady=4)
        self.capacity_entry = ttk.Entry(self, textvariable=self.capacity, width=10)
        self.capacity_entry.grid(row=0, column=1, sticky="w", padx=(12, 0))
        ttk.Label(self, text="F", width=9).grid(row=0, column=2, sticky="w", padx=(8, 0))

        ttk.Radiobutton(
            self,
            text="Subtract a background CV point by point",
            variable=self.mode,
            value=BACKGROUND_CV,
            command=self._mode_changed,
        ).grid(row=1, column=0, sticky="w", pady=4)
        self.choose_button = ttk.Button(
            self, text="Choose Background CV...", command=app.choose_background_cv_file
        )
        self.choose_button.grid(row=1, column=1, sticky="w", padx=(12, 0))
        self.clear_button = ttk.Button(
            self, text="Clear", command=self.clear_background_cv
        )
        self.clear_button.grid(row=1, column=2, sticky="w", padx=(8, 0))

        path_label = ttk.Label(self, textvariable=self.path_display, style="Hint.TLabel", width=30)
        path_label.grid(row=2, column=0, columnspan=4, sticky="ew", padx=(26, 0), pady=(4, 0))
        wrap_to_width(path_label, self, 50)
        self.message_label = ttk.Label(
            self, textvariable=self.message, style="Error.TLabel", wraplength=850
        )
        self.message_label.grid(
            row=3, column=0, columnspan=4, sticky="w", padx=(26, 0), pady=(2, 0)
        )
        wrap_to_width(self.message_label, self, 50)
        self.columnconfigure(3, weight=1)

        self.capacity.trace_add("write", lambda *_args: app.mark_main_parameters_edited())
        self.background_path.trace_add(
            "write", lambda *_args: app.mark_main_parameters_edited()
        )
        self._sync_mode()

    def _mode_changed(self) -> None:
        self._sync_mode()
        self.message.set("")
        self.app.mark_main_parameters_edited()

    def _sync_mode(self) -> None:
        use_background = self.mode.get() == BACKGROUND_CV
        self.capacity_entry.configure(state="disabled" if use_background else "normal")
        state = "normal" if use_background else "disabled"
        self.choose_button.configure(state=state)
        self.clear_button.configure(state=state)

    def clear_background_cv(self) -> None:
        self.background_path.set("")
        self.path_display.set("No background CV selected")
        self.message.set("")

    def set_background_cv(self, path: str, valid: bool = True) -> None:
        self.background_path.set(path)
        self.path_display.set(path or "No background CV selected")
        self.message_label.configure(style="Valid.TLabel" if valid else "Error.TLabel")
        self.message.set(
            "Potential/V matches the experiment exactly." if valid and path else ""
        )

    def raw_values(self):
        return {
            "double_layer_capacity": self.capacity.get(),
            "background_mode": self.mode.get(),
            "background_cv_path": self.background_path.get(),
        }

    def set_values(self, values) -> None:
        self.capacity.set(str(values.get("double_layer_capacity", "")))
        self.mode.set(str(values.get("background_mode", BACKGROUND_CAPACITANCE)))
        path = str(values.get("background_cv_path", ""))
        self.background_path.set(path)
        self.path_display.set(path or "No background CV selected")
        self.message.set("")
        self._sync_mode()

    def validate(self, experiment):
        self.message_label.configure(style="Error.TLabel")
        if self.mode.get() == BACKGROUND_CV:
            path = self.background_path.get().strip()
            if not path:
                self.message.set("Choose a background CV file.")
                return None
            try:
                inspect_background_cv(experiment, path)
            except Exception as exc:
                self.message.set(str(exc))
                return None
            self.message_label.configure(style="Valid.TLabel")
            self.message.set("Potential/V matches the experiment exactly.")
            capacity = 0.0
        else:
            try:
                capacity = DOUBLE_LAYER_DEFINITION.parse(self.capacity.get())
            except ValueError as exc:
                self.message.set(str(exc))
                return None
            self.message.set("")
        return {
            "double_layer_capacity": capacity,
            "background_mode": self.mode.get(),
            "background_cv_path": self.background_path.get().strip(),
        }


class ConfigureStage(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=18)
        self.app = app
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        ttk.Label(self, text="Configure convolution analysis", style="StageTitle.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            self,
            text="Set the main experiment and transport parameters. Error inputs are configured after a main result exists.",
            style="Subtitle.TLabel",
            wraplength=900,
        ).grid(row=1, column=0, sticky="w", pady=(2, 12))

        scroll_container = ScrollFrame(self)
        scroll_container.grid(row=2, column=0, sticky="nsew")
        scroll_container.columnconfigure(0, weight=1)
        scroll_container.rowconfigure(0, weight=1)

        inner = scroll_container.inner

        non_background_parameters = tuple(
            item for item in MAIN_PARAMETERS if item.group != "Background correction"
        )
        self.form = ParameterForm(
            inner,
            non_background_parameters,
            on_change=app.mark_main_parameters_edited,
            columns_per_group={"Experiment": 2, "Mass transport": 2},
            entry_width=10,
            compact=True,
        )
        self.form.pack(fill="x", expand=True, padx=(0, 6))
        self.background_panel = BackgroundCorrectionPanel(inner, app)
        self.background_panel.pack(fill="x", expand=True, padx=(0, 6), pady=(0, 10))

        buttons = ttk.Frame(self)
        buttons.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        buttons.columnconfigure(0, weight=1)
        # Keep the four secondary actions together; give the primary Review action
        # its own row so longer labels still fit at the minimum window width.
        actions = ttk.Frame(buttons)
        actions.grid(row=0, column=0, sticky="w")
        back_button = ttk.Button(actions, text="<- Back", width=0, command=lambda: app.show_stage(1))
        clear_button = ttk.Button(actions, text="Clear fields", width=0, command=app.restore_defaults)
        self.load_preset_button = ttk.Button(
            actions, text="Load preset parameters", width=0, command=app.load_parameter_preset
        )
        self.save_preset_button = ttk.Button(
            actions, text="Save parameters", width=0, command=app.save_parameter_preset
        )
        secondary_buttons = (back_button, clear_button, self.load_preset_button, self.save_preset_button)
        for column, button in enumerate(secondary_buttons):
            button.grid(row=0, column=column, padx=(0, 12) if column < 3 else 0)
        review_button = ttk.Button(
            buttons, text="Review Preprocessing ->", command=self.review,
            style="Primary.TButton",
        )
        review_button.grid(row=1, column=0, sticky="e", pady=(12, 0))
        self.action_buttons = (*secondary_buttons, review_button)

    def review(self) -> None:
        values = self.validate()
        if values is not None:
            self.app.review_preprocessing(values)

    def set_values(self, values) -> None:
        self.form.set_values(values)
        self.background_panel.set_values(values)
        self.app.stages[Stage.REVIEW].set_smoothing(values)

    def raw_values(self):
        values = self.form.raw_values()
        values.update(self.background_panel.raw_values())
        values.update(self.app.stages[Stage.REVIEW].smoothing_values())
        return values

    def validate(self):
        values = self.form.validate()
        background_values = self.background_panel.validate(self.app.state.inspection)
        smoothing_values = self.app.stages[Stage.REVIEW].validate_smoothing()
        if values is None or background_values is None or smoothing_values is None:
            return None
        values.update(background_values)
        values.update(smoothing_values)
        return values
