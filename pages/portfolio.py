import pandas as pd
import streamlit as st

from data_loader import load_raw, portfolio_view, portfolio_weighted_pe

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

st.markdown("**Allocation**")
allocation = holdings.sort_values("Current Value", ascending=False).set_index("Symbol")["Current Value"]
st.bar_chart(allocation)

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
