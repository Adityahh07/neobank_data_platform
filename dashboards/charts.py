"""Chart style and builders (Altair) shared by all dashboard views.

Colours come from a fixed, colour-blind-validated categorical palette with separate
steps for light and dark mode. Each transaction type always keeps the same colour
(colour follows the entity), lines are 2px, bars have rounded ends, and every chart
has a hover tooltip. One y-axis per chart - never dual axes.
"""

import altair as alt
import pandas as pd

# Categorical slots 1-5 of the reference palette (light / dark steps)
SLOTS = {
    "light": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"],
    "dark": ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181"],
}
CHROME = {
    "light": {"text": "#52514e", "muted": "#898781", "grid": "#e1e0d9", "axis": "#c3c2b7"},
    "dark": {"text": "#c3c2b7", "muted": "#898781", "grid": "#2c2c2a", "axis": "#383835"},
}

# Fixed order = fixed colour per transaction type, on every chart and filter state
TXN_TYPES = ["PAYMENT", "TRANSFER", "CASH_OUT", "CASH_IN", "DEBIT"]


def _style(chart: alt.Chart, mode: str, height: int = 280) -> alt.Chart:
    c = CHROME[mode]
    return (
        chart.properties(height=height, background="transparent")
        .configure_view(strokeWidth=0)
        .configure_axis(gridColor=c["grid"], domainColor=c["axis"], tickColor=c["axis"],
                        labelColor=c["muted"], titleColor=c["text"], labelFontSize=11,
                        titleFontSize=12, titleFontWeight="normal")
        .configure_legend(labelColor=c["text"], titleColor=c["text"], orient="top",
                          title=None, labelFontSize=12, symbolStrokeWidth=2)
    )


def line(df: pd.DataFrame, x: str, y: str, y_title: str, mode: str, *,
         series: str | None = None, domain: list[str] | None = None,
         y_format: str = ",.0f", x_is_date: bool = True, height: int = 280) -> alt.Chart:
    """Line chart with a crosshair + tooltip. One series, or several via `series`."""
    slots = SLOTS[mode]
    x_enc = (alt.X(f"{x}:T", title=None, axis=alt.Axis(format="%d %b", labelAngle=0))
             if x_is_date else alt.X(f"{x}:O", title=None))
    base = alt.Chart(df).encode(x=x_enc)
    y_enc = alt.Y(f"{y}:Q", title=y_title, axis=alt.Axis(format=y_format, tickCount=5))

    if series:
        domain = domain or sorted(df[series].unique())
        color = alt.Color(f"{series}:N", scale=alt.Scale(domain=domain, range=slots[:len(domain)]))
        lines = base.mark_line(strokeWidth=2).encode(y=y_enc, color=color)
        tooltip_fields = [alt.Tooltip(f"{x}:T", title="Date", format="%a %d %b %Y")] + [
            alt.Tooltip(f"{s}:Q", format=y_format) for s in domain]
        hover_source = base.transform_pivot(series, value=y, groupby=[x])
    else:
        lines = base.mark_line(strokeWidth=2, color=slots[0]).encode(y=y_enc)
        tooltip_fields = [alt.Tooltip(f"{x}:T" if x_is_date else f"{x}:O", title="Date",
                                      **({"format": "%a %d %b %Y"} if x_is_date else {})),
                          alt.Tooltip(f"{y}:Q", title=y_title, format=y_format)]
        hover_source = base

    hover = alt.selection_point(fields=[x], nearest=True, on="pointerover", empty=False, clear="pointerout")
    points = lines.mark_point(filled=True, size=80).encode(
        opacity=alt.condition(hover, alt.value(1), alt.value(0)))
    rule = hover_source.mark_rule(color=CHROME[mode]["muted"], strokeWidth=1).encode(
        opacity=alt.condition(hover, alt.value(0.8), alt.value(0)),
        tooltip=tooltip_fields,
    ).add_params(hover)
    return _style(alt.layer(lines, points, rule), mode, height)


def grouped_bar(df: pd.DataFrame, category: str, measure: str, value: str, value_title: str,
                mode: str, *, measures: list[str], value_format: str = ".2f",
                label_suffix: str = "", height: int = 280) -> alt.Chart:
    """Vertical grouped bars (2px gap, rounded ends) with direct value labels and tooltips."""
    slots = SLOTS[mode]
    base = alt.Chart(df).encode(
        x=alt.X(f"{category}:N", title=None, axis=alt.Axis(labelAngle=0)),
        xOffset=alt.XOffset(f"{measure}:N", sort=measures),
    )
    bars = base.mark_bar(cornerRadiusEnd=4, width={"band": 0.95}, stroke="transparent").encode(
        y=alt.Y(f"{value}:Q", title=value_title, axis=alt.Axis(format=value_format, tickCount=5)),
        color=alt.Color(f"{measure}:N", scale=alt.Scale(domain=measures, range=slots[:len(measures)]),
                        sort=measures),
        tooltip=[alt.Tooltip(f"{category}:N", title="Type"), alt.Tooltip(f"{measure}:N", title="Measure"),
                 alt.Tooltip(f"{value}:Q", title=value_title, format=value_format)],
    )
    labels = base.mark_text(dy=-8, fontSize=11, color=CHROME[mode]["text"]).encode(
        y=alt.Y(f"{value}:Q"),
        text=alt.Text(f"{value}:Q", format=value_format),
    )
    if label_suffix:
        labels = labels.transform_calculate(
            label=f"format(datum['{value}'], '{value_format}') + '{label_suffix}'"
        ).encode(text="label:N")
    return _style(alt.layer(bars, labels), mode, height)
