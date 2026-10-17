import altair as alt
import pandas as pd
import streamlit as st


def render_trend_chart(frame: pd.DataFrame, x_field: str = "Date", x_type: str = "T") -> None:
    """One trend line chart, y-axis auto-scaled to the data's own range instead
    of anchored at 0 — a plain st.line_chart always starts at 0, which flattens
    series like PMI (~50-75) or FX reserves (~600-800) into a hard-to-read band
    near the top of the chart.

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
    chart = alt.Chart(long).mark_line().encode(
        x=alt.X(f"{x_field}:{x_type}", **x_kwargs),
        y=alt.Y("Value:Q", title=None, scale=alt.Scale(zero=False)),
        color=alt.Color("Series:N", title=None),
    )
    st.altair_chart(chart, use_container_width=True)


def render_grouped_bar_chart(frame: pd.DataFrame) -> None:
    """Grouped bar chart: one FY on the x-axis, each of `frame`'s columns
    as its own bar offset side-by-side within that FY (Altair's xOffset —
    the native grouped-bar idiom; st.bar_chart only stacks, it can't group).
    """
    if frame.dropna(how="all").empty:
        st.caption("Not enough history")
        return

    long = frame.copy()
    long.index.name = "FY"
    long = long.reset_index().melt(id_vars="FY", var_name="Series", value_name="Value").dropna(subset=["Value"])

    chart = alt.Chart(long).mark_bar().encode(
        x=alt.X("FY:N", title=None, sort=list(frame.index)),
        xOffset=alt.XOffset("Series:N"),
        y=alt.Y("Value:Q", title=None),
        color=alt.Color("Series:N", title=None),
    )
    st.altair_chart(chart, use_container_width=True)


def render_bar_chart(series: pd.Series) -> None:
    """Single-series bar chart, sorted descending by value and colored on a
    sequential scale by value — replaces st.bar_chart, which can't sort and
    only draws flat, single-color bars.
    """
    if series.dropna().empty:
        st.caption("Not enough data")
        return

    x_field = series.index.name or "Category"
    frame = series.rename("Value").rename_axis(x_field).reset_index()
    chart = alt.Chart(frame).mark_bar().encode(
        x=alt.X(f"{x_field}:N", title=None, sort="-y"),
        y=alt.Y("Value:Q", title=None),
        color=alt.Color("Value:Q", title=None, scale=alt.Scale(scheme="blues"), legend=None),
        tooltip=[x_field, "Value"],
    )
    st.altair_chart(chart, use_container_width=True)
