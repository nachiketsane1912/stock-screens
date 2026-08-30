import streamlit as st

from data_loader import get_company_view, load_raw, macro_table

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

    st.markdown("**SSGR Screen**")
    screen = view["ssgr_screen"]
    if screen["passes"] is None:
        st.info("Not enough data to run the SSGR screen.")
    else:
        col1, col2 = st.columns(2)
        col1.metric(f"SSGR (FY{screen['latest_year']})", f"{screen['ssgr_pct']:.2f}%")
        col2.metric("Revenue 10Y CAGR", f"{screen['rev_cagr_10y_pct']:.2f}%")
        if screen["passes"]:
            st.success("Passes: SSGR is above the 10-year revenue CAGR.")
        else:
            st.error("Fails: SSGR is below the 10-year revenue CAGR.")

st.header("Macro indicators")
st.dataframe(macro_table(sheets), use_container_width=True)
