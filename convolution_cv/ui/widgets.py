import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable, Dict, Iterable, Mapping

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure

from .parameter_schema import ParameterDefinition, validate_parameter_values
from .theme import CANVAS, ACCENT


class Tooltip:
    def __init__(self, widget, text):
        self.widget, self.text, self.window = widget, text, None
        widget.bind("<Enter>", self.show, add="+")
        widget.bind("<Leave>", self.hide, add="+")
        widget.bind("<FocusOut>", self.hide, add="+")
        widget.bind("<Destroy>", self.hide, add="+")

    def show(self, _event=None):
        if self.window is not None:
            return
        self.window = tk.Toplevel(self.widget)
        self.window.wm_overrideredirect(True)
        self.window.wm_geometry(f"+{self.widget.winfo_rootx()}+{self.widget.winfo_rooty()+self.widget.winfo_height()+4}")
        ttk.Label(self.window, text=self.text, padding=10, wraplength=320).pack()

    def hide(self, _event=None):
        if self.window is not None:
            self.window.destroy()
            self.window = None


class ScrollFrame(ttk.Frame):
    """A form scroller whose requested size cannot push surrounding plots offscreen."""
    def __init__(self, master, width=290):
        super().__init__(master)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(self, width=width, height=1, highlightthickness=0, background=CANVAS)
        bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=bar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        bar.grid(row=0, column=1, sticky="ns")
        self.inner = ttk.Frame(self.canvas)
        item = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.window_item = item
        self.inner.bind("<Configure>", lambda event: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda event: self.canvas.itemconfigure(item, width=max(1, event.width)))
        self.canvas.bind("<Map>", lambda event: self.after_idle(self._sync_canvas))
        self._wheel_binding = self.bind_all("<MouseWheel>", self._wheel, add="+")

    def _sync_canvas(self):
        if self.canvas.winfo_exists():
            self.canvas.itemconfigure(self.window_item, width=max(1, self.canvas.winfo_width()))
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _wheel(self, event):
        widget = event.widget
        while widget is not None:
            if widget == self:
                if self.inner.winfo_height() > self.canvas.winfo_height():
                    delta = event.delta
                    step = -int(delta / 120) if abs(delta) >= 120 else (-1 if delta > 0 else 1)
                    self.canvas.yview_scroll(step, "units")
                return
            widget = getattr(widget, "master", None)


def wrap_to_width(label, container, padding=8):
    container.bind("<Configure>", lambda event: label.configure(wraplength=max(100, event.width-padding)), add="+")


class PageTabs(ttk.Frame):
    """Equal-baseline page tabs, avoiding platform-dependent notebook tab offsets."""
    def __init__(self, master):
        super().__init__(master)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self.bar = ttk.Frame(self)
        self.bar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.pages, self.buttons, self.indicators = [], [], []
        self.selected = tk.IntVar(value=0)

    def add(self, page, text):
        index = len(self.pages)
        self.pages.append(page)
        slot = ttk.Frame(self.bar)
        slot.pack(side="left", padx=(0, 16))
        button = ttk.Radiobutton(slot, text=text, variable=self.selected, value=index,
            style="Page.PlotTab.TRadiobutton", command=lambda: self.select(index))
        button.pack(fill="x")
        line = tk.Frame(slot, height=2, background=CANVAS)
        line.pack(fill="x")
        self.buttons.append(button)
        self.indicators.append(line)
        for key, step in (("<Left>", -1), ("<Right>", 1)):
            button.bind(key, lambda event, step=step: self._move(step))
        page.grid(row=1, column=0, sticky="nsew")
        self.select(self.selected.get())

    def _move(self, step):
        index = (self.selected.get() + step) % len(self.pages)
        self.select(index)
        self.buttons[index].focus_set()
        return "break"

    def select(self, tab=None):
        if tab is None:
            return str(self.selected.get())
        index = int(tab)
        if not 0 <= index < len(self.pages):
            raise IndexError(index)
        self.selected.set(index)
        for number, page in enumerate(self.pages):
            page.grid() if number == index else page.grid_remove()
            self.indicators[number].configure(background=ACCENT if number == index else CANVAS)
        self.event_generate("<<NotebookTabChanged>>")

    def index(self, tab):
        return int(tab)


class ParameterForm(ttk.Frame):
    def __init__(
        self,
        master,
        definitions: Iterable[ParameterDefinition],
        on_change: Callable[[], None] = None,
        columns_per_group: Mapping[str, int] = None,
        entry_width: int = 18,
        label_width: int = None,
        compact: bool = False,
        inspector: bool = False,
    ):
        super().__init__(master)
        self.definitions = tuple(definitions)
        self.on_change = on_change
        self.variables: Dict[str, tk.StringVar] = {}
        self.error_labels: Dict[str, ttk.Label] = {}
        self.entries: Dict[str, ttk.Entry] = {}
        columns_per_group = dict(columns_per_group or {})
        groups = []
        for definition in self.definitions:
            if definition.group not in groups:
                groups.append(definition.group)
        for group_index, group in enumerate(groups):
            box = ttk.LabelFrame(self, text=group, padding=(12, 8))
            box.grid(row=group_index, column=0, sticky="ew", pady=(0, 10))
            group_definitions = [
                item for item in self.definitions if item.group == group
            ]
            column_count = max(1, int(columns_per_group.get(group, 1)))
            for column in range(column_count):
                box.columnconfigure(column, weight=1, uniform=f"{group_index}_parameters")
            for item_index, definition in enumerate(group_definitions):
                row = item_index // column_count
                column = item_index % column_count
                parameter = ttk.Frame(box)
                parameter.grid(
                    row=row,
                    column=column,
                    sticky="ew",
                    padx=(0 if column == 0 else 14, 14 if column == 0 and column_count > 1 else 0),
                    pady=5,
                )
                if inspector:
                    parameter.columnconfigure(0, weight=1)
                short_labels = {"sigma_current": "Current", "sigma_cdl": "Capacitance",
                    "sigma_diameter_percent": "Diameter", "sigma_diffusion_o_percent": "Diffusion · O",
                    "sigma_diffusion_r_percent": "Diffusion · R", "lgk_error_limit": "Max. log₁₀ width"}
                label = ttk.Label(
                    parameter,
                    text=short_labels.get(definition.key, definition.label) if inspector else definition.label,
                    width=label_width,
                    anchor="w",
                )
                label.grid(row=0, column=0, columnspan=3 if compact else 1, sticky="w", padx=(0, 10))
                if compact:
                    wrap_to_width(label, parameter, 20)
                variable = tk.StringVar()
                entry = ttk.Entry(parameter, textvariable=variable, width=entry_width, justify="right" if inspector else "left")
                entry.grid(row=1 if compact else 0, column=0 if compact else 1, sticky="w", pady=3)
                ttk.Label(parameter, text=definition.unit, width=3 if inspector else 9, style="Caption.TLabel").grid(
                    row=1 if compact else 0, column=1 if compact else 2, sticky="w", padx=(8, 0)
                )
                if inspector:
                    Tooltip(label, definition.label + (f" ({definition.unit})" if definition.unit else ""))
                if definition.help_text:
                    help_button = ttk.Button(parameter, text="?", width=2,
                                             command=lambda text=definition.help_text: messagebox.showinfo("Parameter help", text))
                    help_button.grid(row=1 if compact else 0, column=2 if compact else 3, padx=(6, 0))
                    Tooltip(help_button, definition.help_text)
                    entry.bind("<Enter>", lambda event, text=definition.help_text: self._show_help(text))
                    entry.bind("<Leave>", lambda event: self._show_help(""))
                error_label = ttk.Label(
                    parameter, text="", style="Error.TLabel", wraplength=260
                )
                error_label.grid(row=2 if compact else 1, column=0 if compact else 1, columnspan=3, sticky="w")
                error_label.grid_remove()
                self.variables[definition.key] = variable
                self.entries[definition.key] = entry
                self.error_labels[definition.key] = error_label
                if on_change is not None:
                    variable.trace_add("write", lambda *_args: on_change())
        self.help_variable = tk.StringVar()
        self.help_label = ttk.Label(self, textvariable=self.help_variable, style="Hint.TLabel", width=1)
        self.help_label.grid(row=len(groups), column=0, sticky="ew", pady=(0, 4))
        wrap_to_width(self.help_label, self)
        self.help_label.grid_remove()
        self.columnconfigure(0, weight=1)

    def _show_help(self, text: str) -> None:
        self.help_variable.set(text)
        self.help_label.grid() if text else self.help_label.grid_remove()

    def set_values(self, values: Dict[str, object]) -> None:
        for key, value in values.items():
            if key in self.variables:
                self.variables[key].set(str(value))
        self.clear_errors()

    def raw_values(self) -> Dict[str, str]:
        return {key: variable.get() for key, variable in self.variables.items()}

    def validate(self):
        values, errors = validate_parameter_values(self.definitions, self.raw_values())
        self.show_errors(errors)
        return None if errors else values

    def clear_errors(self) -> None:
        self.show_errors({})

    def show_errors(self, errors: Dict[str, str]) -> None:
        for key, label in self.error_labels.items():
            label.configure(text=errors.get(key, ""))
            label.grid() if key in errors else label.grid_remove()
            self.entries[key].configure(style="Invalid.TEntry" if key in errors else "TEntry")


class FlowBar(ttk.Frame):
    """Keep controls at their readable size; wrap instead of clipping on narrow panes."""
    def __init__(self, master, right_count=0, **kwargs):
        super().__init__(master, **kwargs)
        self.right_count = right_count
        self.configure(height=40)
        self.bind("<Configure>", self._arrange)
        self.bind("<Map>", lambda event: self.after_idle(self._arrange))

    def _arrange(self, event=None):
        children = self.winfo_children()
        if not children:
            return
        width = self.winfo_width()
        x, y, row_height = 8, 6, 0
        for index, child in enumerate(children):
            child_width, child_height = child.winfo_reqwidth(), child.winfo_reqheight()
            if self.right_count and index == len(children) - self.right_count:
                action_width = sum(item.winfo_reqwidth() + 6 for item in children[index:])
                if x + action_width <= width - 8:
                    x = width - 8 - action_width
            if x > 8 and x + child_width > width - 8:
                x, y, row_height = 8, y + row_height + 6, 0
            child.place(x=x, y=y)
            x += child_width + 6
            row_height = max(row_height, child_height)
        height = y + row_height + 6
        if self.winfo_reqheight() != height:
            self.configure(height=height)


class PlotToolbar(FlowBar):
    """Readable controls backed by Matplotlib's existing navigation/history engine."""
    def __init__(self, canvas, master, export=None, enlarge=None):
        super().__init__(master, style="Surface.TFrame", right_count=int(bool(export)) + int(bool(enlarge)))
        self.backend = NavigationToolbar2Tk(canvas, master, pack_toolbar=False)
        # Keep the native icon strip unmounted; navigation and keyboard logic still work.
        self.mode = tk.StringVar(value="inspect")
        for label, mode in (("Inspect", "inspect"), ("Pan", "pan"), ("Zoom", "zoom")):
            ttk.Radiobutton(self, text=label, value=mode, variable=self.mode,
                            command=self._set_mode, style="Tool.PlotTab.TRadiobutton")
        ttk.Button(self, text="Back", command=self.backend.back, style="Tool.TButton")
        ttk.Button(self, text="Reset", command=self.backend.home, style="Tool.TButton")
        if enlarge:
            ttk.Button(self, text="Enlarge", command=enlarge, style="Tool.TButton")
        if export:
            ttk.Button(self, text="Export…", command=export, style="Tool.TButton")

    def _set_mode(self):
        active = str(self.backend.mode)
        desired = self.mode.get()
        if active == "pan/zoom":
            self.backend.pan()
        elif active == "zoom rect":
            self.backend.zoom()
        if desired == "pan":
            self.backend.pan()
        elif desired == "zoom":
            self.backend.zoom()

    def update(self):
        self.mode.set("inspect")
        self._set_mode()
        self.backend.update()


def display_figure(master, figsize):
    """Match Tk's point size; a hard-coded 100 dpi inflates text on 72 dpi Macs.

    The canvas backend may independently apply a supported backing-store ratio.
    Export resolution remains controlled by savefig(dpi=...), not this value.
    """
    return Figure(figsize=figsize, dpi=float(master.winfo_fpixels("1i")), layout="constrained")


class SingleFigure(ttk.Frame):
    def __init__(self, master, figsize=(7.0, 4.2)):
        super().__init__(master)
        self.figure = display_figure(self, figsize)
        self.axis = self.figure.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.figure, master=self)
        self.canvas.get_tk_widget().configure(width=1, height=1)
        self.toolbar = PlotToolbar(self.canvas, self)
        self.toolbar.pack(side="bottom", fill="x")
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

    def redraw(self, drawer: Callable) -> None:
        drawer(self.axis)
        self.toolbar.update()
        self.canvas.draw_idle()


class FigureGrid(ttk.Frame):
    """A single, full-size plot workspace (name retained for API compatibility)."""
    PLOTS = (("Voltammogram", "Processed CV"), ("Surface concentration O", "Concentration O"),
             ("Surface concentration R", "Concentration R"), ("Kinetics", "Kinetics"))

    def __init__(self, master):
        super().__init__(master, style="Surface.TFrame")
        controls = FlowBar(self, style="Surface.TFrame")
        self.plot_controls = controls
        controls.pack(fill="x")
        self.selection = tk.StringVar(value="Kinetics")
        for label, value in self.PLOTS:
            ttk.Radiobutton(controls, text=label, value=value, variable=self.selection,
                            command=self.refresh, style="PlotTab.TRadiobutton")
        self.figure = display_figure(self, (9.5, 6.4))
        self.axes = [self.figure.add_subplot(111)]
        self.canvas = FigureCanvasTkAgg(self.figure, master=self)
        self.canvas.get_tk_widget().configure(width=1, height=1)
        self.toolbar = PlotToolbar(self.canvas, self, export=self.export, enlarge=self.enlarge)
        self.toolbar.pack(side="top", fill="x", pady=(0, 8))
        self.notice = ttk.Label(self, style="Caption.TLabel", padding=(10, 6), justify="left")
        wrap_to_width(self.notice, self, 24)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        self.canvas.get_tk_widget().bind("<Configure>", self._resize_plot, add="+")
        self._resize_job = None
        self.drawer = None
        self.result = None
        self.options = {}
        self.clear()

    def _resize_plot(self, event=None):
        if self._resize_job is not None:
            self.after_cancel(self._resize_job)
        # Reflow legends at the final canvas dimensions, not the previous size.
        self._resize_job = self.after(120, self._finish_resize)

    def _finish_resize(self):
        self._resize_job = None
        if self.result is not None:
            from ..plotting import _legend
            _legend(self.axes[0], kinetics=self.selection.get() == "Kinetics")
            self.axes[0].set_title("", loc="left")
            self.canvas.draw_idle()

    def set_result(self, result, show_error=False, kinetics_scan="backward"):
        self.result = result
        self.options = dict(show_error=show_error, kinetics_scan=kinetics_scan)
        self.refresh()

    def refresh(self):
        if self.result is None:
            return
        from ..plotting import draw_processed_cv, draw_concentration_o, draw_concentration_r, draw_lgk
        selection = self.selection.get()
        self.figure.clear()
        plotter = {"Processed CV": draw_processed_cv, "Concentration O": draw_concentration_o,
                   "Concentration R": draw_concentration_r, "Kinetics": draw_lgk}[selection]
        self.axes = [self.figure.add_subplot(111)]
        options = dict(self.options)
        if selection == "Processed CV":
            options["highlight_error"] = options.pop("show_error")
        elif selection == "Kinetics":
            options["embedded"] = True
        full_options = dict(options)
        if selection == "Kinetics":
            full_options["embedded"] = False
        self.drawer = lambda axes: plotter(axes[0], self.result, **full_options)
        plotter(self.axes[0], self.result, **options)
        if hasattr(self, "notice"):
            axis = self.axes[0]
            axis.set_title("", loc="left")
            captions = [text for text in axis.texts if text.get_gid() == "plot-caption"]
            self.notice.configure(text=" ".join(text.get_text().replace("\n", " ") for text in captions))
            for text in captions:
                text.remove()
            if captions:
                self.notice.pack(side="bottom", fill="x", before=self.canvas.get_tk_widget())
            else:
                self.notice.pack_forget()
        self.toolbar.update()
        self.canvas.draw_idle()

    def clear(self):
        self.result = self.drawer = None
        self.notice.pack_forget()
        self.figure.clear()
        self.figure.text(0.5, 0.55, "Your plot workspace", ha="center", fontsize=20,
                         fontfamily="DejaVu Sans", color="#18283e")
        self.figure.text(0.5, 0.40, "Run analysis to explore\neach result in detail.", ha="center",
                         fontsize=15, fontfamily="DejaVu Sans", color="#617187")
        self.canvas.draw_idle()

    def redraw(self, drawer: Callable) -> None:
        self.drawer = drawer
        drawer(self.axes)
        self.canvas.draw_idle()

    def export(self) -> None:
        if self.drawer is None:
            return
        path = filedialog.asksaveasfilename(
            title="Export current figure",
            defaultextension=".png",
            filetypes=[("PNG image", "*.png"), ("SVG image", "*.svg"), ("PDF", "*.pdf")],
        )
        if path:
            try:
                # Export a complete publication figure, independent of a narrow
                # desktop viewport and its separate title/notice controls.
                figure = Figure(figsize=(9, 6), layout="constrained")
                self.drawer([figure.add_subplot(111)])
                figure.savefig(path, dpi=300, bbox_inches="tight")
            except OSError as exc:
                messagebox.showerror("Cannot export figure", str(exc))

    def enlarge(self) -> None:
        if self.drawer is None:
            return
        window = tk.Toplevel(self)
        window.title("Analysis figures")
        window.geometry("1200x850")
        figure = display_figure(window, (11.5, 7.5))
        axes = [figure.add_subplot(111)]
        self.drawer(axes)
        canvas = FigureCanvasTkAgg(figure, master=window)
        canvas.get_tk_widget().configure(width=1, height=1)
        toolbar = PlotToolbar(canvas, window)
        toolbar.pack(side="bottom", fill="x")
        canvas.get_tk_widget().pack(fill="both", expand=True)
        canvas.draw_idle()
