import pandas as pd
import streamlit as st

from charts import render_bar_chart, render_boxplot_chart, render_heatmap_chart, render_scatter_chart, render_trend_chart
from data_loader import (
    QUALITY_METRIC_OPTIONS,
    industry_metric_heatmap_frame,
    industry_metric_median_trend,
    industry_metric_spread_frame,
    industry_overview,
    industry_revenue_concentration_trend,
    load_raw,
    load_universe_cache,
    merge_market_data,
)

st.title("Industries")

try:
    sheets = load_raw()
except RuntimeError as exc:
    st.error(str(exc))
    st.stop()

universe = load_universe_cache()
if universe is None:
    st.info("Open the Screens page once to build the fundamentals cache.")
    st.stop()
universe = merge_market_data(universe, sheets)

st.caption(
    "Every screen on the Screens page ranks companies. This page ranks the industries they belong to: how big "
    "each one is, whether its growth is speeding up or slowing down, how competitive it looks internally, and "
    "how its companies compare metric-by-metric. Pick a classification level below — every section on this "
    "page re-renders at that granularity."
)

level = st.selectbox(
    "Classification level",
    ["Basic Industry", "Industry", "Sector", "Macro-economic Sector"],
    index=1,
    key="industries_level",
)

overview = industry_overview(universe, group_col=level).sort_values("Market Cap (Cr)", ascending=False)

st.markdown("#### Industry scorecard")
st.caption(
    "One row per industry. Click a column header to sort. \"Growth Δ\" and \"HHI\" are explained in "
    "the sections below; industries with fewer than 5 companies in a given window show — for that cell."
)
st.dataframe(
    overview,
    use_container_width=True,
    hide_index=True,
    column_config={
        "Market Cap (Cr)": st.column_config.NumberColumn(format="%,.0f"),
        "Market Cap Share (%)": st.column_config.NumberColumn(format="%.2f%%"),
        "HHI": st.column_config.NumberColumn(format="%.0f"),
        "Median OPM (%)": st.column_config.NumberColumn(format="%.2f%%"),
        "Median Rev Growth (%)": st.column_config.NumberColumn(format="%.2f%%"),
        "Growth Δ (pp)": st.column_config.NumberColumn(format="%.2f"),
        "Median PE": st.column_config.NumberColumn(format="%.2f"),
    },
)

st.divider()

st.markdown("#### Relative size")
st.caption("Share of total universe Market Cap held by each industry.")
render_bar_chart(overview.set_index("Industry")["Market Cap Share (%)"])

st.divider()

st.markdown("#### Growth trajectory")
st.caption(
    "Momentum, not level: the median YoY revenue growth across the industry's companies over the last "
    "3 years minus the same median from the 3 years before that. Positive means the industry is "
    "accelerating, negative means it's slowing down."
)
growth_delta = overview.set_index("Industry")["Growth Δ (pp)"].dropna().sort_values(ascending=False)
if growth_delta.empty:
    st.caption("Not enough year-over-year history yet to compute momentum for any industry.")
else:
    render_bar_chart(growth_delta)
    st.caption(
        f"Most accelerating: **{growth_delta.index[0]}** ({growth_delta.iloc[0]:+.2f}pp). "
        f"Most decelerating: **{growth_delta.index[-1]}** ({growth_delta.iloc[-1]:+.2f}pp)."
    )

st.divider()

st.markdown("#### Competitive intensity")
st.caption(
    "HHI (Herfindahl-Hirschman Index) measures how concentrated each industry's Market Cap is among its "
    "listed companies — near 0 means many similarly-sized competitors (fragmented, often price-"
    "competitive), near 10,000 means one company dominates. Plotted against median Operating Margin, with "
    "bubble size for total industry Market Cap: the bottom-left corner (low HHI, low margin) is where "
    "competition is most intense; the top-right (high HHI, high margin) is where it's most comfortable."
)
intensity_frame = overview.dropna(subset=["HHI", "Median OPM (%)"])
if intensity_frame.empty:
    st.caption("Not enough data")
else:
    render_scatter_chart(
        intensity_frame,
        x_field="HHI",
        y_field="Median OPM (%)",
        size_field="Market Cap (Cr)",
        tooltip_fields=["Industry", "HHI", "Median OPM (%)", "Market Cap (Cr)"],
    )
    fragmented = intensity_frame.sort_values(["HHI", "Median OPM (%)"]).iloc[0]
    st.caption(
        f"Most fragmented and thinnest-margin: **{fragmented['Industry']}** "
        f"(HHI {fragmented['HHI']:.0f}, Median OPM {fragmented['Median OPM (%)']:.2f}%)."
    )

st.divider()

st.markdown("#### Industry heatmap")
st.caption(
    "Median of each metric by industry (industries with fewer than 5 companies are omitted), normalized "
    "within each column so one color scale works across differently-scaled metrics — darker is stronger, "
    "regardless of the metric's own units or direction."
)

heatmap_metrics = [
    ("OPM", "Operating Margin", "higher"),
    ("NPM", "Net Margin", "higher"),
    ("ROE", "ROE", "higher"),
    ("ROCEExCash", "Nalanda's F", "higher"),
    ("LiabEquity", "Liabilities / Equity", "lower"),
    ("LowDebt", "Interest / Op. Profit", "lower"),
    ("SSGR (%)", "SSGR", "higher"),
]
heatmap_frame = industry_metric_heatmap_frame(universe, heatmap_metrics, group_col=level)
if heatmap_frame.empty:
    st.caption("Not enough data")
else:
    industry_order = (
        heatmap_frame.groupby("Industry")["Normalized"].mean().sort_values(ascending=False).index.tolist()
    )
    render_heatmap_chart(
        heatmap_frame,
        x_field="Metric",
        y_field="Industry",
        color_field="Normalized",
        y_order=industry_order,
        tooltip_fields=["Industry", "Metric", "Value"],
    )

st.divider()

st.markdown("#### Industry spread")
st.caption(
    "How convergent or divergent a metric is within an industry — a median (shown in the heatmap above) "
    "can't tell a tightly-clustered industry apart from one where a few outliers drag the average around. "
    "Industries with fewer than 5 companies are omitted; sorted most-divergent-first."
)

spread_label = st.selectbox("Metric", list(QUALITY_METRIC_OPTIONS.keys()), key="industries_spread_metric")
spread_frame = industry_metric_spread_frame(universe, QUALITY_METRIC_OPTIONS[spread_label], group_col=level)

if spread_frame.empty:
    st.caption("Not enough data")
else:
    iqr = spread_frame.groupby("Industry")["Value"].quantile(0.75) - spread_frame.groupby("Industry")["Value"].quantile(
        0.25
    )
    iqr = iqr.sort_values(ascending=False)
    render_boxplot_chart(spread_frame, "Industry", "Value", category_order=iqr.index.tolist())
    st.caption(
        f"Most divergent: **{iqr.index[0]}** (IQR {iqr.iloc[0]:.1f}pp). "
        f"Most convergent: **{iqr.index[-1]}** (IQR {iqr.iloc[-1]:.1f}pp)."
    )

st.divider()

st.markdown("#### Deep dive")
st.caption(
    "Pick one industry (at the classification level chosen above) to see how it's changed over the last "
    "10 fiscal years, not just where it stands today."
)

drill_options = overview["Industry"].tolist()
selected = st.selectbox("Drill into", drill_options, index=0, key="industries_drill_into")
selected_row = overview.loc[overview["Industry"] == selected].iloc[0]

m1, m2, m3, m4 = st.columns(4)
m1.metric("Companies", f"{selected_row['Companies']:.0f}")
m2.metric(
    "Market Cap",
    f"₹{selected_row['Market Cap (Cr)']:,.0f} Cr" if pd.notna(selected_row["Market Cap (Cr)"]) else "—",
)
m3.metric(
    "Market Cap Share",
    f"{selected_row['Market Cap Share (%)']:.2f}%" if pd.notna(selected_row["Market Cap Share (%)"]) else "—",
)
m4.metric("HHI (today, Market Cap)", f"{selected_row['HHI']:.0f}" if pd.notna(selected_row["HHI"]) else "—")

st.markdown("##### Competitive intensity over time")
st.caption(
    "Revenue-share HHI, not the Market-Cap HHI above — we only have today's Market Cap, not 10 years of "
    "it, so each company's share of the industry's own revenue each year is the closest available proxy for "
    "concentration. Rising means the industry is consolidating; falling means it's fragmenting."
)
concentration_trend = industry_revenue_concentration_trend(universe, level, selected).iloc[::-1]
render_trend_chart(pd.DataFrame({"Revenue-share HHI": concentration_trend}), x_field="Year", x_type="N")

st.markdown("##### Margin trend")
st.caption("Median Operating Margin and Net Margin across the industry's companies, by fiscal year.")
margin_frame = pd.DataFrame(
    {
        "Operating Margin (%)": industry_metric_median_trend(universe, level, selected, "OPM").iloc[::-1],
        "Net Margin (%)": industry_metric_median_trend(universe, level, selected, "NPM").iloc[::-1],
    }
)
render_trend_chart(margin_frame, x_field="Year", x_type="N")

st.markdown("##### Revenue growth trajectory")
st.caption("Median YoY revenue growth across the industry's companies, by fiscal year.")
growth_trend = industry_metric_median_trend(universe, level, selected, "RevGrowth").iloc[::-1]
render_trend_chart(pd.DataFrame({"Revenue Growth (%)": growth_trend}), x_field="Year", x_type="N")

st.markdown("##### Company roster")
roster = universe.loc[
    universe[level] == selected, ["Symbol", "ROCE Y1 (%)", "OPM Y1 (%)", "Rev Y1 (Cr)", "Market Cap (Cr)", "PE"]
].sort_values("Market Cap (Cr)", ascending=False)
st.dataframe(
    roster,
    use_container_width=True,
    hide_index=True,
    column_config={
        "ROCE Y1 (%)": st.column_config.NumberColumn(format="%.2f%%"),
        "OPM Y1 (%)": st.column_config.NumberColumn(format="%.2f%%"),
        "Rev Y1 (Cr)": st.column_config.NumberColumn(format="₹ %,.2f"),
        "Market Cap (Cr)": st.column_config.NumberColumn(format="₹ %,.2f"),
        "PE": st.column_config.NumberColumn(format="%.2f"),
    },
)
