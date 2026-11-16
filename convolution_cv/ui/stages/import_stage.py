import tkinter as tk
from tkinter import ttk

from ...plotting import draw_import
from ..widgets import SingleFigure, wrap_to_width, Tooltip


class ImportStage(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=18)
        self.app = app
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        ttk.Label(self, text="Import cyclic-voltammetry data", style="StageTitle.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            self,
            text="Choose one CSV file. The software validates and previews it before analysis.",
            style="Subtitle.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(2, 14))

        choose_box = ttk.LabelFrame(self, text="CV data file", padding=14)
        choose_box.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        choose_box.columnconfigure(0, weight=1)
        self.path_variable = tk.StringVar(value="No file selected")
        self.path_label = ttk.Label(choose_box, textvariable=self.path_variable, width=35)
        self.path_label.grid(row=0, column=0, sticky="ew", padx=(0, 12))
        wrap_to_width(self.path_label, choose_box, 190)
        self.path_tooltip = Tooltip(self.path_label, "Choose a CSV file")
        ttk.Button(choose_box, text="Choose CSV File...", command=app.choose_cv_file).grid(
            row=0, column=1
        )

        content = ttk.Panedwindow(self, orient="horizontal")
        content.grid(row=3, column=0, sticky="nsew")
        left = ttk.Frame(content, padding=(0, 0, 10, 0))
        right = ttk.Frame(content)
        content.add(left, weight=2)
        content.add(right, weight=3)
        left.rowconfigure(3, weight=1)
        left.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)

        self.info_variable = tk.StringVar(value="Select a CSV file to see file information.")
        ttk.Label(left, text="File information", style="SectionTitle.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        info = ttk.Label(left, textvariable=self.info_variable, justify="left", width=28)
        info.grid(row=1, column=0, sticky="ew", pady=(4, 10))
        wrap_to_width(info, left)
        self.warning_variable = tk.StringVar()
        ttk.Label(
            left, textvariable=self.warning_variable, style="Warning.TLabel",
            wraplength=380, justify="left",
        ).grid(row=2, column=0, sticky="ew", pady=(0, 8))

        self.preview_table = ttk.Treeview(
            left, columns=("potential", "current"), show="headings", height=12
        )
        self.preview_table.heading("potential", text="Potential / V")
        self.preview_table.heading("current", text="Current / A")
        self.preview_table.column("potential", width=125, anchor="e")
        self.preview_table.column("current", width=125, anchor="e")
        self.preview_table.grid(row=3, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(left, orient="vertical", command=self.preview_table.yview)
        scrollbar.grid(row=3, column=1, sticky="ns")
        self.preview_table.configure(yscrollcommand=scrollbar.set)

        self.figure = SingleFigure(right)
        self.figure.grid(row=0, column=0, sticky="nsew")
        self._empty_plot()

        buttons = ttk.Frame(self)
        buttons.grid(row=4, column=0, sticky="ew", pady=(12, 0))
        self.clear_button = ttk.Button(buttons, text="Clear File", command=app.clear_import, state="disabled")
        self.clear_button.pack(side="left")
        self.continue_button = ttk.Button(
            buttons, text="Continue to Configure ->", command=app.go_to_configure,
            style="Primary.TButton", state="disabled",
        )
        self.continue_button.pack(side="right")

    def show_inspection(self, inspection) -> None:
        self.path_variable.set(inspection.input_path.name)
        self.path_tooltip.text = str(inspection.input_path)
        self.info_variable.set(
            f"Filename: {inspection.input_path.name}\n"
            f"Valid rows: {inspection.valid_rows:,}\n"
            f"Discarded rows: {inspection.discarded_rows:,}\n"
            f"Potential range: {inspection.potential.min():.6g} to {inspection.potential.max():.6g} V\n"
            f"Current range: {inspection.current.min():.6g} to {inspection.current.max():.6g} A\n"
            f"Detected scans: {len(inspection.segments)}\n"
            f"Complete cycles: {inspection.complete_cycles}"
        )
        self.warning_variable.set("\n".join(inspection.warnings))
        for item in self.preview_table.get_children():
            self.preview_table.delete(item)
        for potential, current in zip(inspection.potential[:50], inspection.current[:50]):
            self.preview_table.insert("", "end", values=(f"{potential:.8g}", f"{current:.8g}"))
        self.figure.redraw(lambda axis: draw_import(axis, inspection.potential, inspection.current))
        self.clear_button.configure(state="normal")
        self.continue_button.configure(state="normal")

    def clear(self) -> None:
        self.path_variable.set("No file selected")
        self.info_variable.set("Select a CSV file to see file information.")
        self.warning_variable.set("")
        for item in self.preview_table.get_children():
            self.preview_table.delete(item)
        self._empty_plot()
        self.clear_button.configure(state="disabled")
        self.continue_button.configure(state="disabled")

    def _empty_plot(self):
        self.figure.axis.clear()
        self.figure.axis.set_axis_off()
        self.figure.axis.text(0.5, 0.5, "Your CV preview will appear here\nChoose a CSV to begin", ha="center", va="center",
                              transform=self.figure.axis.transAxes, color="#526478", fontsize=16)
        self.figure.canvas.draw_idle()
