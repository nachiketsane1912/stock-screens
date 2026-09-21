import pandas as pd
import streamlit as st

from data_loader import (
    load_raw,
    load_universe_cache,
    portfolio_fundamentals,
    portfolio_industry_exposure,
    portfolio_view,
    portfolio_weighted_pe,
)

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

st.markdown("**Allocation**")
allocation = holdings.sort_values("Current Value", ascending=False).set_index("Symbol")["Current Value"]
st.bar_chart(allocation)

st.markdown("**Industry exposure**")
exposure = portfolio_industry_exposure(holdings)
top = exposure.iloc[0]
e1, e2 = st.columns(2)
e1.metric("Industries", f"{len(exposure)}")
e2.metric("Largest industry", f"{top['Industry']} ({top['Weight (%)']:.1f}%)" if pd.notna(top["Weight (%)"]) else "—")
st.bar_chart(exposure.set_index("Industry")["Weight (%)"])
st.dataframe(
    exposure.style.format({"Current Value": "{:,.2f}", "Weight (%)": "{:.2f}", "Gain (%)": "{:.2f}"}, na_rep="—"),
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

event = st.dataframe(
    filtered,
    use_container_width=True,
    hide_index=True,
    on_select="rerun",
    selection_mode="single-row",
    key="portfolio_table",
)
if event.selection.rows:
    st.session_state["jump_to_symbol"] = filtered.iloc[event.selection.rows[0]]["Symbol"]
    st.switch_page("pages/data_explorer.py")
