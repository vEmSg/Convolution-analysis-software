"""Shared desktop design tokens; no third-party theme dependency."""

from tkinter import font as tkfont, ttk


SURFACE = "#ffffff"
CANVAS = "#f3f5f9"
INK = "#18283e"
MUTED = "#617187"
ACCENT = "#2563eb"
RAIL = "#13243b"
# Points: one restrained type scale, shared by forms, commands and summaries.
TYPE = {"caption": 13, "body": 15, "section": 15, "value": 22, "page": 26}


def configure_theme(root):
    families = set(tkfont.families(root))
    family = next((name for name in ("SF Pro Text", "Helvetica Neue", "Segoe UI", "DejaVu Sans")
                   if name in families), "Helvetica")
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
        tkfont.nametofont(name).configure(family=family, size=TYPE["body"])
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", font=(family, TYPE["body"]), background=CANVAS, foreground=INK,
                    borderwidth=0, relief="flat", focuscolor=ACCENT)
    style.configure("TFrame", background=CANVAS)
    style.configure("TLabel", background=CANVAS)
    style.configure("Surface.TFrame", background=SURFACE)
    style.configure("Surface.TLabel", background=SURFACE)
    style.configure("TLabelframe", background=CANVAS, borderwidth=0, relief="flat")
    style.configure("TLabelframe.Label", background=CANVAS, foreground=MUTED, font=(family, TYPE["section"], "bold"))
    style.configure("TButton", background=SURFACE, padding=(10, 6), borderwidth=0, relief="flat")
    style.map("TButton", background=[("disabled", CANVAS), ("pressed", "#dbeafe"), ("active", "#e8eef8")],
              foreground=[("disabled", "#9aa6b5")], relief=[("pressed", "flat"), ("active", "flat")])
    style.configure("Primary.TButton", background=ACCENT, foreground="white", font=(family, TYPE["body"], "bold"))
    style.map("Primary.TButton", background=[("disabled", "#dce4ef"), ("pressed", "#1e40af"), ("active", "#1d4ed8")],
              foreground=[("disabled", MUTED), ("!disabled", "white")])
    style.configure("Quiet.TButton", background=CANVAS, padding=(10, 6))
    style.configure("TEntry", padding=(8, 6), fieldbackground=SURFACE, borderwidth=1,
                    bordercolor="#d5deea", lightcolor=SURFACE, darkcolor=SURFACE, relief="flat")
    style.map("TEntry", bordercolor=[("focus", ACCENT)])
    style.configure("Invalid.TEntry", fieldbackground="#fff1f2", bordercolor="#e11d48")
    style.configure("TCombobox", padding=(8, 6), fieldbackground=SURFACE, background=SURFACE,
                    arrowcolor=MUTED, bordercolor="#d5deea", lightcolor=SURFACE, darkcolor=SURFACE)
    style.map("TCombobox", fieldbackground=[("readonly", SURFACE)],
              selectbackground=[("readonly", SURFACE)], selectforeground=[("readonly", INK)],
              bordercolor=[("focus", ACCENT)])
    style.configure("TNotebook", background=CANVAS, borderwidth=0, tabmargins=(0, 0, 0, 8))
    style.configure("TNotebook", bordercolor=CANVAS, lightcolor=CANVAS, darkcolor=CANVAS)
    style.layout("TNotebook.Tab", [("Notebook.padding", {"sticky": "nswe", "children": [
        ("Notebook.focus", {"sticky": "nswe", "children": [("Notebook.label", {"sticky": "nswe"})]})]})])
    style.configure("TNotebook.Tab", background=CANVAS, padding=(16, 8), borderwidth=0)
    style.map("TNotebook.Tab", background=[("selected", SURFACE), ("active", "#e8eef8")],
              foreground=[("selected", ACCENT)], lightcolor=[("selected", SURFACE)],
              expand=[("selected", (0, 0, 0, 0)), ("!selected", (0, 0, 0, 0))])
    style.configure("StageTitle.TLabel", font=(family, TYPE["page"], "bold"))
    style.configure("Subtitle.TLabel", foreground=MUTED)
    style.configure("SectionTitle.TLabel", font=(family, TYPE["section"], "bold"))
    style.configure("ResultValue.TLabel", background=SURFACE, font=(family, TYPE["value"], "bold"))
    style.configure("MetricTitle.TLabel", background=SURFACE, foreground=MUTED, font=(family, TYPE["caption"]))
    style.configure("Caption.TLabel", foreground=MUTED, font=(family, TYPE["caption"]))
    style.configure("Status.TLabel", background=SURFACE, foreground=MUTED, font=(family, TYPE["body"]))
    for name, color in (("ResultState", MUTED), ("Hint", MUTED), ("Warning", "#996015"),
                         ("Error", "#b42318"), ("Valid", "#147d64"), ("Help", ACCENT)):
        style.configure(f"{name}.TLabel", foreground=color)
    style.configure("Rail.TFrame", background=RAIL)
    style.configure("Rail.TLabel", background=RAIL, foreground="#93a9c3", font=(family, TYPE["caption"]))
    style.configure("Brand.TLabel", background=RAIL, foreground="white", font=(family, 17, "bold"))
    for prefix, color, background in (("", "#c6d3e3", RAIL), ("Current.", "white", "#244164"),
                                       ("Complete.", "#8ed5c1", RAIL), ("Outdated.", "#f5c477", RAIL)):
        name = f"{prefix}Stage.TButton"
        style.configure(name, background=background, foreground=color, anchor="w", padding=(12, 10))
        style.map(name, background=[("active", "#294766"), ("!active", background)],
                  foreground=[("disabled", "#617992"), ("!disabled", color)])
    # Label-only radiobuttons behave as accessible segmented plot/tool controls.
    style.layout("PlotTab.TRadiobutton", [("Radiobutton.padding", {"children": [
        ("Radiobutton.focus", {"children": [("Radiobutton.label", {"sticky": "nswe"})], "sticky": "nswe"})], "sticky": "nswe"})])
    style.configure("PlotTab.TRadiobutton", padding=(12, 8), background=SURFACE, foreground=MUTED)
    style.map("PlotTab.TRadiobutton", background=[("selected", "#e8f0ff"), ("active", "#f0f4fa")],
              foreground=[("selected", ACCENT)])
    style.configure("Page.PlotTab.TRadiobutton", background=CANVAS, padding=(0, 8), font=(family, TYPE["body"], "bold"))
    style.map("Page.PlotTab.TRadiobutton", background=[("selected", CANVAS), ("active", CANVAS)],
              foreground=[("selected", INK), ("!selected", MUTED)])
    style.configure("Tool.TButton", padding=(8, 4), background=SURFACE, font=(family, TYPE["body"]))
    style.configure("Tool.PlotTab.TRadiobutton", padding=(8, 4), font=(family, TYPE["body"]))
    style.configure("Vertical.TScrollbar", troughcolor=CANVAS, background="#cbd5e1",
                    borderwidth=0, arrowsize=12, arrowcolor=MUTED, gripcount=0)
    style.configure("Treeview", background=SURFACE, fieldbackground=SURFACE, rowheight=34, borderwidth=0)
    style.configure("Treeview.Heading", background="#eaf0f7", foreground=MUTED, font=(family, TYPE["body"], "bold"), padding=8)
    style.map("Treeview", background=[("selected", "#e2edff")], foreground=[("selected", INK)])
    root.configure(background=CANVAS)
