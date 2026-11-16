"""Publication-style chart presentation shared by previews, results and exports.

Only artists and axis formatting belong here; this module never transforms data.
Sizes are points, independent of the desktop's logical DPI or export resolution.
"""

from matplotlib.ticker import AutoMinorLocator, MaxNLocator, ScalarFormatter

FONT = "DejaVu Sans"
TYPE = {"title": 16, "label": 18, "tick": 14, "legend": 12, "note": 12}
CURVE_WIDTH = 2.6
COLORS = {
    "blue": "#354c82",
    "orange": "#846b4b",
    "green": "#489780",
    "red": "#b54c50",
    "purple": "#6746a3",
    "gray": "#939aa3",
}


def style_axis(axis, title, xlabel="Potential (V)", ylabel=""):
    """White paper, boxed axes, inward ticks and prominent scientific labels."""
    font = dict(fontfamily=FONT, math_fontfamily="dejavusans", color="#17191d")
    axis.set_facecolor("white")
    axis.figure.set_facecolor("white")
    axis.set_title(title, fontsize=TYPE["title"], fontweight="normal", loc="left", pad=16, **font)
    axis.set_xlabel(xlabel, fontsize=TYPE["label"], labelpad=10, **font)
    axis.set_ylabel(ylabel, fontsize=TYPE["label"], labelpad=12, **font)
    axis.grid(False, which="both")
    axis.xaxis.set_major_locator(MaxNLocator(nbins=5, min_n_ticks=3))
    axis.yaxis.set_major_locator(MaxNLocator(nbins=5, min_n_ticks=3))
    axis.xaxis.set_minor_locator(AutoMinorLocator(2))
    axis.yaxis.set_minor_locator(AutoMinorLocator(2))
    for coordinate in (axis.xaxis, axis.yaxis):
        coordinate.set_major_formatter(ScalarFormatter(useMathText=True, useOffset=False))
        coordinate.get_offset_text().set_fontsize(TYPE["tick"])
        coordinate.get_offset_text().set_fontfamily(FONT)
    axis.tick_params(which="major", direction="in", top=True, right=True,
                     labelsize=TYPE["tick"], colors="#24272c", length=6, width=1.3, pad=8)
    axis.tick_params(which="minor", direction="in", top=True, right=True,
                     colors="#24272c", length=3, width=1)
    for label in axis.get_xticklabels() + axis.get_yticklabels():
        label.set_fontfamily(FONT)
        label.set_math_fontfamily("dejavusans")
    for spine in axis.spines.values():
        spine.set_visible(True)
        spine.set_color("#24272c")
        spine.set_linewidth(1.3)
    axis.set_axisbelow(True)
    for line in axis.lines:
        line.set_solid_capstyle("round")
        line.set_solid_joinstyle("round")
    axis.margins(x=0.045, y=0.09)


def legend_columns(axis, count):
    # Size according to physical width, not raster pixels, so exports and desktop
    # display agree. Narrow plots wrap the legend rather than shrinking its text.
    width = axis.figure.get_figwidth() * axis.get_position().width
    return min(count, 3 if width >= 6.2 else 2 if width >= 3.5 else 1)


def position_title(axis, rows):
    axis.set_title(axis.get_title(loc="left"), loc="left",
                   fontsize=TYPE["title"], fontfamily=FONT, fontweight="normal",
                   pad=18 + rows * (TYPE["legend"] * 1.5 + 3))
