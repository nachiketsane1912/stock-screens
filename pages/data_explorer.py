import pandas as pd
import streamlit as st

from data_loader import (
    MOAT_METRIC_CONFIG,
    VIJAY_MALIK_CHECKS,
    VIJAY_MALIK_PRO_CHECKS,
    build_trend_frame,
    company_vantage_metrics,
    evaluate_screens_for_company,
    get_company_view,
    load_raw,
    load_universe_cache,
    merge_market_data,
)

TREND_CHARTS = [
    ("Revenue & Operating Profit (₹ Cr)", ["Rev", "OP"]),
    ("Margins (%)", ["OPM", "NPM"]),
    ("Returns (%)", ["ROE", "ROCE", "ROCEExCash"]),
    ("EPS (₹)", ["EPS"]),
    ("Leverage (%)", ["LiabEquity", "DebtEquity"]),
]

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

    vantage_decay = st.session_state.get("vantage_decay_saved", 0.85)
    vantage_rate = st.session_state.get("vantage_rate_saved", 0.10)
    vantage_min_threshold = st.session_state.get("vantage_min_threshold_saved", 0.0)
    vantage_max_threshold = st.session_state.get("vantage_max_threshold_saved", 1.0)

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
        overrides["vijay_malik_pro"] = {}
        for check in VIJAY_MALIK_PRO_CHECKS:
            key = check["key"]
            if check["type"] == "range":
                overrides["vijay_malik_pro"][f"{key}_min"] = st.session_state.get(
                    f"vmpro_{key}_min_saved", check["default_min"]
                )
                overrides["vijay_malik_pro"][f"{key}_max"] = st.session_state.get(
                    f"vmpro_{key}_max_saved", check["default_max"]
                )
            else:
                overrides["vijay_malik_pro"][key] = st.session_state.get(f"vmpro_{key}_saved", check["default"])
        overrides["net_net"] = {
            "min_mcap": st.session_state.get("net_net_min_mcap_saved", 0.0),
        }
        overrides["vantage"] = {
            "decay": vantage_decay,
            "rate": vantage_rate,
            "min_threshold": vantage_min_threshold,
            "max_threshold": vantage_max_threshold,
        }
        overrides["magic_formula"] = {
            "min_market_cap": st.session_state.get("magic_formula_min_market_cap_saved", 5000.0),
        }
        st.dataframe(
            evaluate_screens_for_company(universe, symbol, overrides), use_container_width=True, hide_index=True
        )

    st.markdown("**Trends**")
    trend_cols = st.columns(2)
    for i, (title, rows) in enumerate(TREND_CHARTS):
        with trend_cols[i % 2]:
            st.caption(title)
            frame = build_trend_frame(view["income_statement"], rows)
            if frame.dropna(how="all").empty:
                st.caption("Not enough history")
            else:
                st.line_chart(frame)

    st.markdown("**Market**")
    market = view["market"]
    mcol1, mcol2, mcol3 = st.columns(3)
    mcol1.metric("Price (₹)", f"{market['price']:.2f}" if pd.notna(market["price"]) else "—")
    mcol2.metric("Market Cap (₹ Cr)", f"{market['market_cap_cr']:.2f}" if pd.notna(market["market_cap_cr"]) else "—")
    mcol3.metric("P/E", f"{market['pe']:.2f}" if pd.notna(market["pe"]) else "—")
    if pd.isna(market["price"]):
        st.caption("Add a `Market` sheet (Symbol, CMP, PE, Market cap (INR Cr)) to Raw data.xlsx to see this.")

    st.markdown("**Vantage**")
    vantage = company_vantage_metrics(
        view["income_statement"], view["balance_sheet"], market["price"], vantage_decay, vantage_rate
    )
    vcol1, vcol2, vcol3, vcol4 = st.columns(4)
    vcol1.metric("WA CFO (₹ Cr)", f"{vantage['wa_cfo']:.2f}" if pd.notna(vantage["wa_cfo"]) else "—")
    vcol2.metric("WA Interest (₹ Cr)", f"{vantage['wa_interest']:.2f}" if pd.notna(vantage["wa_interest"]) else "—")
    vcol3.metric("Loan (₹ Cr)", f"{vantage['loan']:.2f}" if pd.notna(vantage["loan"]) else "—")
    vcol4.metric("Total Value (₹ Cr)", f"{vantage['total_value']:.2f}" if pd.notna(vantage["total_value"]) else "—")
    vcol5, vcol6, vcol7, vcol8 = st.columns(4)
    vcol5.metric("Cashflow (₹ Cr)", f"{vantage['cashflow']:.2f}" if pd.notna(vantage["cashflow"]) else "—")
    vcol6.metric("Interest Serviceable (₹ Cr)", f"{vantage['interest_serviceable']:.2f}" if pd.notna(vantage["interest_serviceable"]) else "—")
    vcol7.metric("Value/Share (₹)", f"{vantage['value_per_share']:.2f}" if pd.notna(vantage["value_per_share"]) else "—")
    vcol8.metric("Multiple", f"{vantage['multiple']:.2f}" if pd.notna(vantage["multiple"]) else "—")

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
