import pandas as pd
import streamlit as st

from data_loader import (
    cpi_basket_ranking,
    load_raw,
    macro_latest_snapshot,
    macro_table,
    macro_trend_frame,
    pmi_status,
)

MACRO_TREND_CHARTS = [
    ("Growth & Activity", ["GDP", "IIP"]),
    ("Prices", ["CPI", "CPI - Rural", "CPI - Urban"]),
    ("PMI", ["Manufacturing PMI", "Services PMI"]),
    ("External", ["FX reserves - USD Bn"]),
]

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
trend_cols = st.columns(2)
for i, (title, columns) in enumerate(MACRO_TREND_CHARTS):
    with trend_cols[i % 2]:
        st.caption(title)
        frame = macro_trend_frame(table, columns)
        if frame.dropna(how="all").empty:
            st.caption("Not enough history")
        else:
            st.line_chart(frame)

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
