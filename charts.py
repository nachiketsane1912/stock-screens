import altair as alt
import pandas as pd
import streamlit as st

CHART_HEIGHT = 280
SERIES_COLOR_SCHEME = "set2"
SEQUENTIAL_COLOR_SCHEME = "blues"
HIGHLIGHT_COLOR = "#f5a623"
BASE_COLOR = "#4c78a8"


def render_trend_chart(frame: pd.DataFrame, x_field: str = "Date", x_type: str = "T") -> None:
    """One trend line chart, y-axis auto-scaled to the data's own range instead
    of anchored at 0 — a plain st.line_chart always starts at 0, which flattens
    series like PMI (~50-75) or FX reserves (~600-800) into a hard-to-read band
    near the top of the chart. Smoothed (monotone) lines with point markers and
    hover tooltips, on a distinct color palette from Streamlit's native chart
    default, make each series easier to read and compare at a glance.

    `x_field`/`x_type` default to a temporal "Date" axis; pass a categorical
    field instead (e.g. fiscal-year labels, not real dates) with `x_type="N"`,
    sorted to `frame`'s own (already-chronological) row order rather than
    alphabetically.
    """
    if frame.dropna(how="all").empty:
        st.caption("Not enough history")
        return

    long = frame.copy()
    long.index.name = x_field
    long = long.reset_index().melt(id_vars=x_field, var_name="Series", value_name="Value").dropna(subset=["Value"])

    x_kwargs = {"title": None}
    if x_type != "T":
        x_kwargs["sort"] = list(frame.index)
    chart = (
        alt.Chart(long)
        .mark_line(point=alt.OverlayMarkDef(size=55, filled=True), strokeWidth=2.5, interpolate="monotone")
        .encode(
            x=alt.X(f"{x_field}:{x_type}", **x_kwargs),
            y=alt.Y("Value:Q", title=None, scale=alt.Scale(zero=False)),
            color=alt.Color("Series:N", title=None, scale=alt.Scale(scheme=SERIES_COLOR_SCHEME)),
            tooltip=[x_field, "Series", "Value"],
        )
        .properties(height=CHART_HEIGHT)
    )
    st.altair_chart(chart, use_container_width=True)


def render_grouped_bar_chart(frame: pd.DataFrame) -> None:
    """Grouped bar chart: one FY on the x-axis, each of `frame`'s columns
    as its own bar offset side-by-side within that FY (Altair's xOffset —
    the native grouped-bar idiom; st.bar_chart only stacks, it can't group).
    Rounded bar tops and hover tooltips, on the same palette as the trend
    charts, for visual consistency across the app.
    """
    if frame.dropna(how="all").empty:
        st.caption("Not enough history")
        return

    long = frame.copy()
    long.index.name = "FY"
    long = long.reset_index().melt(id_vars="FY", var_name="Series", value_name="Value").dropna(subset=["Value"])

    chart = (
        alt.Chart(long)
        .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
        .encode(
            x=alt.X("FY:N", title=None, sort=list(frame.index)),
            xOffset=alt.XOffset("Series:N"),
            y=alt.Y("Value:Q", title=None),
            color=alt.Color("Series:N", title=None, scale=alt.Scale(scheme=SERIES_COLOR_SCHEME)),
            tooltip=["FY", "Series", "Value"],
        )
        .properties(height=CHART_HEIGHT)
    )
    st.altair_chart(chart, use_container_width=True)


def render_bar_chart(series: pd.Series, highlight_top: int = 3) -> None:
    """Single-series bar chart, sorted descending by value, with the top
    `highlight_top` bars picked out in an accent color (a "podium" look) and
    every bar carrying a hover tooltip — replaces st.bar_chart, which can't
    sort, highlight, or show a tooltip, and only draws flat, single-color bars.
    """
    if series.dropna().empty:
        st.caption("Not enough data")
        return

    x_field = series.index.name or "Category"
    frame = (
        series.rename("Value")
        .rename_axis(x_field)
        .reset_index()
        .sort_values("Value", ascending=False)
        .reset_index(drop=True)
    )
    frame["Highlight"] = frame.index < highlight_top

    chart = (
        alt.Chart(frame)
        .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
        .encode(
            x=alt.X(f"{x_field}:N", title=None, sort="-y"),
            y=alt.Y("Value:Q", title=None),
            color=alt.Color(
                "Highlight:N",
                scale=alt.Scale(domain=[True, False], range=[HIGHLIGHT_COLOR, BASE_COLOR]),
                legend=None,
            ),
            tooltip=[x_field, "Value"],
        )
        .properties(height=CHART_HEIGHT)
    )
    st.altair_chart(chart, use_container_width=True)


def render_scatter_chart(
    frame: pd.DataFrame,
    x_field: str,
    y_field: str,
    size_field: str | None = None,
    color_field: str | None = None,
    color_domain: list | None = None,
    color_range: list | None = None,
    tooltip_fields: list[str] | None = None,
) -> None:
    """Scatter/bubble chart for comparing two continuous metrics across many
    companies at once (e.g. quality vs valuation) — a shape none of the
    trend/bar charts above fit. Semi-transparent circles handle overplotting
    at universe scale (~1000s of points).

    `color_field` is meant for a small, fixed status split (e.g. pass/fail on
    a screen) — never a high-cardinality field like Industry, which would
    blow past the categorical color limit; scope those with a filter before
    calling this, not a color legend. `size_field` draws no legend of its own
    (a precise size reading isn't the point, just a visual cue).
    """
    if frame.dropna(subset=[x_field, y_field]).empty:
        st.caption("Not enough data")
        return

    encoding = {
        "x": alt.X(f"{x_field}:Q", scale=alt.Scale(zero=False)),
        "y": alt.Y(f"{y_field}:Q", scale=alt.Scale(zero=False)),
        "tooltip": tooltip_fields or [x_field, y_field],
    }
    if size_field:
        encoding["size"] = alt.Size(f"{size_field}:Q", legend=None)
    if color_field:
        scale_kwargs = {}
        if color_domain is not None:
            scale_kwargs["domain"] = color_domain
        if color_range is not None:
            scale_kwargs["range"] = color_range
        encoding["color"] = alt.Color(f"{color_field}:N", title=None, scale=alt.Scale(**scale_kwargs))

    chart = alt.Chart(frame).mark_circle(opacity=0.55).encode(**encoding).properties(height=CHART_HEIGHT)
    st.altair_chart(chart, use_container_width=True)


def render_heatmap_chart(
    frame: pd.DataFrame,
    x_field: str,
    y_field: str,
    color_field: str,
    y_order: list[str] | None = None,
    tooltip_fields: list[str] | None = None,
) -> None:
    """Category x metric heatmap — a single sequential hue (light->dark) over
    an already 0-1-normalized `color_field`, so differently-scaled and
    differently-directioned metrics can share one color scale meaningfully
    (see industry_metric_heatmap_frame, which does that normalization).
    Never pass a raw mixed-unit value as `color_field` directly — the
    tooltip is where the real value belongs.
    """
    if frame.dropna(subset=[color_field]).empty:
        st.caption("Not enough data")
        return

    y_kwargs = {"title": None}
    if y_order is not None:
        y_kwargs["sort"] = y_order
    height = min(900, max(CHART_HEIGHT, 20 * frame[y_field].nunique()))

    chart = (
        alt.Chart(frame)
        .mark_rect()
        .encode(
            x=alt.X(f"{x_field}:N", title=None),
            y=alt.Y(f"{y_field}:N", **y_kwargs),
            color=alt.Color(f"{color_field}:Q", title=None, scale=alt.Scale(scheme=SEQUENTIAL_COLOR_SCHEME)),
            tooltip=tooltip_fields or [y_field, x_field, color_field],
        )
        .properties(height=height)
    )
    st.altair_chart(chart, use_container_width=True)


def render_boxplot_chart(
    frame: pd.DataFrame, category_field: str, value_field: str, category_order: list[str] | None = None
) -> None:
    """Box plot (median, IQR box, 1.5xIQR whiskers, outlier points) of
    `value_field` grouped by `category_field` — shows a distribution's
    *spread* (how convergent/divergent it is), not just its center, which
    neither a heatmap's single aggregated cell nor a bar chart's single bar
    can. Takes the raw per-row values (one row per company); Vega-Lite's
    composite boxplot mark computes the quartiles itself.
    """
    if frame.dropna(subset=[value_field]).empty:
        st.caption("Not enough data")
        return

    y_kwargs = {"title": None}
    if category_order is not None:
        y_kwargs["sort"] = category_order
    height = min(900, max(CHART_HEIGHT, 20 * frame[category_field].nunique()))

    chart = (
        alt.Chart(frame)
        .mark_boxplot(size=10, color=BASE_COLOR)
        .encode(
            x=alt.X(f"{value_field}:Q", scale=alt.Scale(zero=False)),
            y=alt.Y(f"{category_field}:N", **y_kwargs),
        )
        .properties(height=height)
    )
    st.altair_chart(chart, use_container_width=True)


def render_histogram_chart(series: pd.Series, bins: int = 20, markers: dict[str, float] | None = None) -> None:
    """Binned histogram of a single score/metric, with optional labeled
    vertical rule markers (e.g. a handful of portfolio holdings' own values)
    overlaid on the universe distribution — shows how selective a threshold
    is, and where specific companies sit in that spread.
    """
    values = series.dropna()
    if values.empty:
        st.caption("Not enough data")
        return

    frame = values.rename("Value").to_frame()
    chart = (
        alt.Chart(frame)
        .mark_bar(color=BASE_COLOR)
        .encode(
            x=alt.X("Value:Q", bin=alt.Bin(maxbins=bins), title=None),
            y=alt.Y("count()", title=None),
            tooltip=["count()"],
        )
        .properties(height=CHART_HEIGHT)
    )

    if markers:
        marker_frame = pd.DataFrame({"Label": list(markers.keys()), "Value": list(markers.values())}).dropna()
        if not marker_frame.empty:
            rules = (
                alt.Chart(marker_frame)
                .mark_rule(color=HIGHLIGHT_COLOR, strokeWidth=2)
                .encode(x="Value:Q", tooltip=["Label", "Value"])
            )
            chart = chart + rules

    st.altair_chart(chart, use_container_width=True)
