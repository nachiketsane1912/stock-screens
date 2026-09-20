import altair as alt
import pandas as pd
import streamlit as st

from data_loader import (
    annual_period_labels,
    bottom_up_aggregate_table,
    bottom_up_borr_vs_nb,
    cpi_basket_ranking,
    load_raw,
    load_universe_cache,
    macro_latest_snapshot,
    macro_table,
    macro_trend_frame,
    macro_yoy_frame,
    pmi_status,
)

BOTTOM_UP_TREND_CHARTS = [
    ("Revenue, Expenses & Operating Profit (₹ Cr, aggregate)", ["Rev", "Exp", "OP"]),
    ("Interest & Depreciation (₹ Cr, aggregate)", ["Int", "Dep"]),
    ("PBT & Net Profit (₹ Cr, aggregate)", ["PBT", "Net"]),
    ("Margins (%, aggregate OPM/NPM)", ["OPM", "NPM"]),
    ("Capex vs Depreciation (₹ Cr, aggregate)", ["Capex", "Dep"]),
    ("Capex Intensity (%, aggregate Capex/Revenue)", ["CapexIntensity"]),
]


def render_trend_chart(frame: pd.DataFrame, x_field: str = "Date", x_type: str = "T") -> None:
    """One macro trend line chart, y-axis auto-scaled to the data's own
    range instead of anchored at 0 — a plain st.line_chart always starts at
    0, which flattens series like PMI (~50-75) or FX reserves (~600-800)
    into a hard-to-read band near the top of the chart.

    `x_field`/`x_type` default to a temporal "Date" axis (the top-down macro
    charts' shape); the bottom-up rollup passes a categorical field instead
    (relative "FY-10".."FY-1" labels, not real dates), sorted to `frame`'s
    own (already-chronological) row order rather than alphabetically.
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


st.title("Macro")

try:
    sheets = load_raw()
except RuntimeError as exc:
    st.error(str(exc))
    st.stop()

if "Macro" not in sheets:
    st.info("Add a `Macro` sheet to `Raw data.xlsx` (a `Parameter` column plus one column per date) to see this page.")
    st.stop()

table = macro_table(sheets)
if table.empty:
    st.info("The `Macro` sheet has no data yet.")
    st.stop()

st.markdown("**Trends**")

st.caption("Growth & Activity")
growth_cols = st.columns(2)
with growth_cols[0]:
    st.caption("GDP")
    render_trend_chart(macro_trend_frame(table, ["GDP"]))
with growth_cols[1]:
    st.caption("IIP (YoY %)")
    render_trend_chart(macro_yoy_frame(table, ["IIP"]))

other_trend_charts = [
    ("Prices (YoY %)", macro_yoy_frame(table, ["CPI", "CPI - Rural", "CPI - Urban"])),
    ("PMI", macro_trend_frame(table, ["Manufacturing PMI", "Services PMI"])),
    ("External", macro_trend_frame(table, ["FX reserves - USD Bn"])),
]
other_cols = st.columns(2)
for i, (title, frame) in enumerate(other_trend_charts):
    with other_cols[i % 2]:
        st.caption(title)
        render_trend_chart(frame)

snapshot = macro_latest_snapshot(table)
st.markdown("**Latest snapshot**")
st.dataframe(snapshot, use_container_width=True, hide_index=True)

st.markdown("**CPI basket breakdown**")
st.dataframe(cpi_basket_ranking(table), use_container_width=True, hide_index=True)

st.markdown("**PMI status**")
pmi_cols = st.columns(2)
for i, label in enumerate(["Manufacturing PMI", "Services PMI"]):
    match = snapshot.loc[snapshot["Parameter"] == label, "Latest Value"]
    value = match.iloc[0] if not match.empty else float("nan")
    with pmi_cols[i]:
        st.metric(label, f"{value:.1f}" if pd.notna(value) else "—", pmi_status(value))

st.divider()
st.header("Bottom-Up: Company Universe Rollup")
st.caption(
    "Sum of Rev/Exp/OP/Int/Dep/PBT/Net/Capex across every company that reports "
    "each metric that year (a company need not have a full 10-year history "
    "to contribute), for the last 10 completed fiscal years. OPM/NPM/Capex "
    "Intensity are derived from these aggregate totals (sum(OP)/sum(Rev), "
    "sum(Net)/sum(Rev), sum(Capex)/sum(Rev)), not averaged from each "
    "company's own ratio."
)

universe = load_universe_cache()
if universe is None:
    st.info("Run the Screens page (click Refresh if it's never been run) to see the bottom-up rollup here.")
else:
    period_labels = annual_period_labels(sheets, years=10)
    bottom_up = bottom_up_aggregate_table(universe, period_labels)

    st.markdown("**Aggregate trends**")
    bu_cols = st.columns(2)
    for i, (title, cols) in enumerate(BOTTOM_UP_TREND_CHARTS):
        with bu_cols[i % 2]:
            st.caption(title)
            render_trend_chart(bottom_up[cols], x_field="FY", x_type="N")

    st.markdown("**Borrowings vs Net Block (₹ Cr, aggregate)**")
    render_grouped_bar_chart(bottom_up_borr_vs_nb(universe, period_labels))
