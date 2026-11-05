import pandas as pd
import streamlit as st

from charts import render_bar_chart, render_trend_chart
from data_loader import (
    MOAT_METRIC_CONFIG,
    VIJAY_MALIK_CHECKS,
    VIJAY_MALIK_PRO_CHECKS,
    load_raw,
    load_universe_cache,
    merge_market_data,
    portfolio_fundamentals,
    portfolio_industry_exposure,
    portfolio_metric_trend,
    portfolio_screen_overlay,
    portfolio_view,
    portfolio_weighted_pe,
)
from tables import style_diverging, style_tri_state, tri_state_column_config

st.title("Portfolio")

try:
    sheets = load_raw()
except RuntimeError as exc:
    st.error(str(exc))
    st.stop()

holdings = portfolio_view(sheets)

if holdings.empty:
    st.info(
        "Add a `Portfolio` sheet to `Raw data.xlsx` (columns: `Symbol`, `Quantity`, `Invested`, `CMP`) "
        "to see your holdings here."
    )
    st.stop()

total_invested = holdings["Invested"].sum()
total_value = holdings["Current Value"].sum()
total_gain = total_value - total_invested
total_gain_pct = (total_gain / total_invested * 100) if total_invested else float("nan")

portfolio_pe = portfolio_weighted_pe(holdings)

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Invested", f"₹{total_invested:,.2f}")
col2.metric("Current Value", f"₹{total_value:,.2f}")
col3.metric("Gain/Loss", f"₹{total_gain:,.2f}")
col4.metric("Gain (%)", f"{total_gain_pct:.2f}%" if pd.notna(total_gain_pct) else "—")
col5.metric("Portfolio PE", f"{portfolio_pe:.2f}" if pd.notna(portfolio_pe) else "—")

st.markdown("**Fundamentals**")
universe = load_universe_cache()
if universe is not None:
    universe = merge_market_data(universe, sheets)
if universe is None:
    st.info("Open the Screens page once to build the fundamentals cache.")
else:
    fundamentals = portfolio_fundamentals(holdings, universe)
    nalanda = fundamentals[fundamentals["Metric"] == "Nalanda's F (ROCE ex-cash)"].iloc[0]
    f1, f2 = st.columns(2)
    f1.metric("Median Nalanda's F", f"{nalanda['Median']:.2f}%" if pd.notna(nalanda["Median"]) else "—")
    f2.metric("Weighted Nalanda's F", f"{nalanda['Weighted Avg']:.2f}%" if pd.notna(nalanda["Weighted Avg"]) else "—")
    st.dataframe(
        fundamentals.style.format({"Median": "{:.2f}", "Weighted Avg": "{:.2f}"}, na_rep="—"),
        use_container_width=True,
        hide_index=True,
    )
    st.caption(
        "Latest completed FY. Weighted by Current Value. Holdings missing a value are excluded per metric."
    )

st.markdown("**Trends**")
if universe is None:
    st.info("Open the Screens page once to build the fundamentals cache.")
else:
    trend_options = {
        "ROCE": "ROCE",
        "Nalanda's F (ROCE ex-cash)": "ROCEExCash",
        "Operating Margin": "OPM",
        "Net Margin": "NPM",
        "ROE": "ROE",
    }
    trend_label = st.selectbox("Metric", list(trend_options.keys()), key="portfolio_trend_metric")
    trend_series = portfolio_metric_trend(holdings, universe, trend_options[trend_label])
    trend_frame = pd.DataFrame({trend_label: trend_series.iloc[::-1]})
    render_trend_chart(trend_frame, x_field="Year", x_type="N")
    st.caption(
        "Current Value-weighted average across holdings, oldest (Y10) to latest completed FY (Y1). "
        "Holdings missing a value for a given year are excluded and weights renormalized — same convention "
        "as the Fundamentals table above, just shown across all 10 years instead of just the latest."
    )

st.markdown("**Allocation**")
allocation = holdings.sort_values("Current Value", ascending=False).set_index("Symbol")["Current Value"]
render_bar_chart(allocation)

st.markdown("**Industry exposure**")
exposure = portfolio_industry_exposure(holdings)
top = exposure.iloc[0]
e1, e2 = st.columns(2)
e1.metric("Industries", f"{len(exposure)}")
e2.metric("Largest industry", f"{top['Industry']} ({top['Weight (%)']:.1f}%)" if pd.notna(top["Weight (%)"]) else "—")
render_bar_chart(exposure.set_index("Industry")["Weight (%)"])
exposure_styler = exposure.style.format(
    {"Current Value": "{:,.2f}", "Weight (%)": "{:.2f}", "Gain (%)": "{:.2f}"}, na_rep="—"
)
st.dataframe(
    style_diverging(exposure_styler, ["Gain (%)"]),
    use_container_width=True,
    hide_index=True,
)

st.markdown("**Holdings**")
search = st.text_input("Search by symbol or industry")
filtered = holdings.sort_values("Current Value", ascending=False)
if search:
    mask = filtered["Symbol"].str.contains(search, case=False, na=False) | filtered["Industry"].str.contains(
        search, case=False, na=False
    )
    filtered = filtered[mask]

st.caption(f"{len(filtered)} of {len(holdings)} holdings")

holdings_styler = style_diverging(filtered.style, ["Gain/Loss", "Gain (%)"])
event = st.dataframe(
    holdings_styler,
    use_container_width=True,
    hide_index=True,
    on_select="rerun",
    selection_mode="single-row",
    key="portfolio_table",
    column_config={
        "Invested": st.column_config.NumberColumn(format="₹ %,.2f"),
        "CMP": st.column_config.NumberColumn(format="₹ %,.2f"),
        "Current Value": st.column_config.NumberColumn(format="₹ %,.2f"),
        "Gain/Loss": st.column_config.NumberColumn(format="₹ %,.2f"),
        "Gain (%)": st.column_config.NumberColumn(format="%.2f%%"),
        "Weight (%)": st.column_config.NumberColumn(format="%.2f%%"),
        "PE": st.column_config.NumberColumn(format="%.2f"),
    },
)
if event.selection.rows:
    st.session_state["jump_to_symbol"] = filtered.iloc[event.selection.rows[0]]["Symbol"]
    st.switch_page("pages/data_explorer.py")

st.markdown("**Screens**")
if universe is None:
    st.info("Open the Screens page once to build the fundamentals cache.")
else:
    # Reads the same plain "_saved" shadow keys pages/screens.py's widgets copy
    # themselves into on every run, not the raw widget-bound keys — same
    # cross-page-sync fix as pages/data_explorer.py's Filters section.
    overrides = {
        key: {
            "use_industry": st.session_state.get(f"{key}_use_industry_saved", True),
            "manual": st.session_state.get(f"{key}_manual_saved", int(config["default"])),
        }
        for key, config in MOAT_METRIC_CONFIG.items()
    }
    overrides["ccp"] = {
        "roce": st.session_state.get("ccp_roce_threshold_saved", 15),
        "growth": st.session_state.get("ccp_growth_threshold_saved", 10),
        "years": st.session_state.get("ccp_years_saved", 10),
    }
    overrides["vijay_malik"] = {
        check["key"]: st.session_state.get(f"vm_{check['key']}_saved", check["default"])
        for check in VIJAY_MALIK_CHECKS
    }
    overrides["vijay_malik_pro"] = {}
    for check in VIJAY_MALIK_PRO_CHECKS:
        vmp_key = check["key"]
        if check["type"] == "range":
            overrides["vijay_malik_pro"][f"{vmp_key}_min"] = st.session_state.get(
                f"vmpro_{vmp_key}_min_saved", check["default_min"]
            )
            overrides["vijay_malik_pro"][f"{vmp_key}_max"] = st.session_state.get(
                f"vmpro_{vmp_key}_max_saved", check["default_max"]
            )
        else:
            overrides["vijay_malik_pro"][vmp_key] = st.session_state.get(f"vmpro_{vmp_key}_saved", check["default"])
    overrides["net_net"] = {"min_mcap": st.session_state.get("net_net_min_mcap_saved", 0.0)}
    overrides["vantage"] = {
        "decay": st.session_state.get("vantage_decay_saved", 0.85),
        "rate": st.session_state.get("vantage_rate_saved", 0.10),
        "min_threshold": st.session_state.get("vantage_min_threshold_saved", 0.0),
        "max_threshold": st.session_state.get("vantage_max_threshold_saved", 1.0),
    }
    overrides["magic_formula"] = {
        "min_market_cap": st.session_state.get("magic_formula_min_market_cap_saved", 5000.0),
    }
    overrides["relative_valuation"] = {
        "percentile": st.session_state.get("relval_percentile_saved", 0.25),
        "min_market_cap": st.session_state.get("relval_min_market_cap_saved", 0.0),
    }

    overlay = portfolio_screen_overlay(universe, holdings, overrides)
    screen_columns = [c for c in overlay.columns if c not in ("Symbol", "Screens Passed")]
    overlay = overlay.sort_values("Screens Passed", ascending=False)

    st.caption(f"How many of the {len(screen_columns)} screens each holding currently passes, using the Screens page's current settings.")
    st.dataframe(
        overlay[["Symbol", "Screens Passed"]],
        use_container_width=True,
        hide_index=True,
        column_config={
            "Screens Passed": st.column_config.ProgressColumn(min_value=0, max_value=len(screen_columns), format="%d"),
        },
    )

    with st.expander("Screen pass/fail by holding"):
        st.dataframe(
            style_tri_state(overlay[["Symbol", *screen_columns]], screen_columns),
            use_container_width=True,
            hide_index=True,
            column_config=tri_state_column_config(screen_columns),
        )
