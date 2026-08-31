import pandas as pd
import streamlit as st

from data_loader import (
    MOAT_METRIC_CONFIG,
    VIJAY_MALIK_CHECKS,
    evaluate_screens_for_company,
    get_company_view,
    load_raw,
    load_universe_cache,
    macro_table,
    merge_market_data,
)

st.title("Stock Fundamentals Explorer")

try:
    sheets = load_raw()
except RuntimeError as exc:
    st.error(str(exc))
    st.stop()

companies = sheets["Industry"]

st.header("Companies")
search = st.text_input("Search by symbol or industry")
if search:
    mask = companies["Symbol"].str.contains(search, case=False, na=False) | companies[
        "Industry"
    ].str.contains(search, case=False, na=False)
    filtered = companies[mask]
else:
    filtered = companies

st.caption(f"{len(filtered)} of {len(companies)} companies")
st.dataframe(filtered, use_container_width=True, height=300)

st.header("Company detail")

if "jump_to_symbol" in st.session_state:
    st.session_state["data_explorer_symbol"] = st.session_state.pop("jump_to_symbol")

symbol = st.selectbox(
    "Symbol",
    options=sorted(companies["Symbol"].dropna().unique()),
    key="data_explorer_symbol",
)

if symbol:
    view = get_company_view(symbol, sheets)
    st.subheader(f"{symbol} — {view['industry']}")

    st.markdown("**Filters**")
    universe = load_universe_cache()
    if universe is None:
        st.info("Run the Screens page (click Refresh if it's never been run) to see filter results here.")
    else:
        universe = merge_market_data(universe, sheets)
        # Reads the plain "_saved" shadow keys pages/screens.py's widgets copy
        # themselves into on every run, not the raw widget-bound keys — those
        # aren't reliably preserved once navigated away from (see the comment
        # in render_threshold_controls).
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
        overrides["net_net"] = {
            "min_mcap": st.session_state.get("net_net_min_mcap_saved", 0.0),
        }
        st.dataframe(
            evaluate_screens_for_company(universe, symbol, overrides), use_container_width=True, hide_index=True
        )

    st.markdown("**Market**")
    market = view["market"]
    mcol1, mcol2, mcol3 = st.columns(3)
    mcol1.metric("Price (₹)", f"{market['price']:.2f}" if pd.notna(market["price"]) else "—")
    mcol2.metric("Market Cap (₹ Cr)", f"{market['market_cap_cr']:.2f}" if pd.notna(market["market_cap_cr"]) else "—")
    mcol3.metric("P/E", f"{market['pe']:.2f}" if pd.notna(market["pe"]) else "—")
    if pd.isna(market["price"]):
        st.caption("Add a `Market` sheet (Symbol, CMP, PE, Market cap (INR Cr)) to Raw data.xlsx to see this.")

    st.markdown("**Quarterly financials**")
    st.dataframe(view["quarterly"], use_container_width=True)

    st.markdown("**Annual income statement**")
    st.dataframe(view["income_statement"], use_container_width=True)

    st.markdown("**Annual balance sheet**")
    st.dataframe(view["balance_sheet"], use_container_width=True)

    st.markdown("**CAGR (annual metrics)**")
    st.dataframe(view["cagr"], use_container_width=True)

    st.markdown("**Quarterly Revenue CAGR**")
    st.dataframe(view["quarterly_cagr"], use_container_width=True)

st.header("Macro indicators")
st.dataframe(macro_table(sheets), use_container_width=True)
