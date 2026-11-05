import os
from datetime import datetime

import pandas as pd
import streamlit as st

from charts import (
    render_bar_chart,
    render_boxplot_chart,
    render_heatmap_chart,
    render_histogram_chart,
    render_scatter_chart,
)
from data_loader import (
    MOAT_METRIC_CONFIG,
    UNIVERSE_CACHE_FILE,
    VIJAY_MALIK_CHECKS,
    VIJAY_MALIK_PRO_CHECKS,
    and_tri_state,
    build_universe_cache,
    compute_universe_screens,
    industry_metric_heatmap_frame,
    industry_metric_spread_frame,
    industry_metric_thresholds,
    industry_overview,
    industry_scalar_thresholds,
    load_raw,
    load_universe_cache,
    magic_formula_ranking,
    merge_market_data,
    metric_moat_passes,
    moat_score,
    net_net_passes,
    portfolio_view,
    relative_valuation_passes,
    relative_valuation_scatter_frame,
    save_universe_cache,
    scalar_metric_passes,
    vantage_metrics,
    vijay_malik_passes,
    vijay_malik_pro_passes,
)
from tables import STATUS_GOOD, STATUS_MUTED, style_diverging, style_tri_state, tri_state_column_config

st.title("Screens")

try:
    sheets = load_raw()
except RuntimeError as exc:
    st.error(str(exc))
    st.stop()

refresh = st.button("Refresh")
universe = load_universe_cache()

if universe is None or refresh:
    progress = st.progress(0.0)

    def report(done: int, total: int) -> None:
        progress.progress(done / total, text=f"Computing screens data… {done}/{total}")

    with st.spinner("Computing screens data across ~2000 companies (about a minute)…"):
        universe = build_universe_cache(sheets, progress_callback=report)
        save_universe_cache(universe)
    progress.empty()

if os.path.exists(UNIVERSE_CACHE_FILE):
    last_refreshed = datetime.fromtimestamp(os.path.getmtime(UNIVERSE_CACHE_FILE))
    st.caption(f"Last refreshed: {last_refreshed:%Y-%m-%d %H:%M}")

# Price (and Market Cap/P·E derived from it) changes far more often than the
# fundamentals above, so this is a fresh, uncached merge on every run rather
# than part of the Refresh-button cache — see merge_market_data()'s docstring.
universe = merge_market_data(universe, sheets)


def search_and_filter(df: pd.DataFrame, passes_col: str, key: str) -> pd.DataFrame:
    search = st.text_input("Search by symbol or industry", key=f"{key}_search")
    only_passing = st.checkbox("Show only passing companies", key=f"{key}_only_passing")

    filtered = df
    if search:
        mask = filtered["Symbol"].str.contains(search, case=False, na=False) | filtered[
            "Industry"
        ].str.contains(search, case=False, na=False)
        filtered = filtered[mask]
    if only_passing:
        filtered = filtered[filtered[passes_col] == True]  # noqa: E712 (NaN/False must not match)

    st.caption(f"{len(filtered)} of {len(df)} companies")
    return filtered


def drill_through(event, df: pd.DataFrame) -> None:
    if event.selection.rows:
        st.session_state["jump_to_symbol"] = df.iloc[event.selection.rows[0]]["Symbol"]
        st.switch_page("pages/data_explorer.py")


def render_threshold_controls(
    universe: pd.DataFrame, config_key: str, config: dict, allow_industry: bool = True
) -> tuple[pd.Series, pd.Series]:
    """One compact widget row for a screen's threshold, inside a "Configure
    thresholds" expander. Returns (thresholds, passes) for use by the ranking
    table and the metric-detail view. `allow_industry=False` drops the
    industry-percentile toggle entirely (Nalanda's F: a manual bar only).
    """
    row = config["row"]
    pctl = int(config["percentile"] * 100)
    if allow_industry:
        label_col, toggle_col, slider_col = st.columns([2, 2, 3])
        label_col.markdown(f"**{config['label']}**")
        use_industry = toggle_col.checkbox(
            f"Industry {pctl}th pctl.",
            value=True,
            key=f"{config_key}_use_industry",
            help=(
                f"Each company is compared to its own industry's {pctl}th-percentile {config['label']}, "
                "falling back to the manual value for industries with fewer than 5 companies."
            ),
        )
        manual_threshold = slider_col.slider(
            "Manual threshold (%)",
            min_value=0,
            max_value=100,
            value=int(config["default"]),
            key=f"{config_key}_manual",
            label_visibility="collapsed",
        )
    else:
        label_col, slider_col = st.columns([2, 5])
        label_col.markdown(f"**{config['label']}**")
        use_industry = False
        manual_threshold = slider_col.slider(
            "Manual threshold (%)",
            min_value=0,
            max_value=100,
            value=int(config["default"]),
            key=f"{config_key}_manual",
            label_visibility="collapsed",
        )

    # Widget-bound session_state (the keys above) isn't reliably preserved once
    # this widget stops being rendered — e.g. after navigating to another page —
    # Streamlit can reset it back to `value=` on next render. Shadow-copy into a
    # plain, non-widget-bound key (like `jump_to_symbol`) so the Data Explorer
    # page's Filters section can read the *current* setting reliably.
    st.session_state[f"{config_key}_use_industry_saved"] = use_industry
    st.session_state[f"{config_key}_manual_saved"] = manual_threshold

    if use_industry:
        thresholds = industry_metric_thresholds(
            universe, row, config["percentile"], fallback=manual_threshold, consistency=config["consistency"]
        )
    else:
        thresholds = pd.Series(manual_threshold, index=universe.index)

    passes = metric_moat_passes(universe, row, thresholds, config["direction"], config["consistency"])
    return thresholds, passes


def render_metric_detail_table(
    universe: pd.DataFrame, config_key: str, config: dict, thresholds: pd.Series, passes: pd.Series
) -> None:
    """Symbol/Industry/Threshold/10-year-history/Passes table for one screen,
    shown inside a "Metric detail" expander.
    """
    row = config["row"]
    direction_word = "above" if config["direction"] == "higher" else "below"
    if config["consistency"] == "median":
        st.caption(
            f"Companies whose median annual {config['label']} over the last 10 fiscal years is {direction_word} a bar."
        )
    else:
        st.caption(
            f"Companies whose annual {config['label']} has stayed {direction_word} a bar "
            "for each of the last 10 fiscal years."
        )

    detail = universe.copy()
    detail["Threshold Used (%)"] = thresholds.round(2)
    detail["Passes"] = passes

    filtered = search_and_filter(detail, "Passes", key=f"{config_key}_detail")

    display_cols = ["Symbol", "Industry", "Threshold Used (%)"] + [
        f"{row} Y{y} (%)" for y in range(1, 11)
    ] + ["Passes"]
    percent_cols = ["Threshold Used (%)"] + [f"{row} Y{y} (%)" for y in range(1, 11)]
    event = st.dataframe(
        filtered[display_cols],
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key=f"{config_key}_detail_table",
        column_config={c: st.column_config.NumberColumn(format="%.2f%%") for c in percent_cols},
    )
    drill_through(event, filtered)


def render_screen_group_tab(universe: pd.DataFrame, title: str, description: str, group_configs: dict) -> None:
    """A full tab: "Configure thresholds" expander (one row per screen in
    `group_configs`), a ranking table scored across just those screens, and a
    "Metric detail" expander. Used for both the Moats and Nalanda's F tabs.
    """
    st.subheader(title)
    st.caption(description)

    with st.expander("Configure thresholds"):
        all_thresholds: dict[str, pd.Series] = {}
        all_passes: dict[str, pd.Series] = {}
        for config_key, config in group_configs.items():
            all_thresholds[config_key], all_passes[config_key] = render_threshold_controls(universe, config_key, config)

    ranking = universe[["Symbol", "Industry"]].copy()
    ranking["Score"] = moat_score(all_passes)
    for config_key, passes in all_passes.items():
        ranking[group_configs[config_key]["label"]] = passes
    ranking = ranking.sort_values(["Score", "Symbol"], ascending=[False, True])

    key_prefix = title.lower().replace(" ", "_").replace("'", "")
    search_rank = st.text_input("Search by symbol or industry", key=f"{key_prefix}_search")
    min_score = st.slider(
        "Minimum score", min_value=0, max_value=len(group_configs), value=0, key=f"{key_prefix}_min_score"
    )

    filtered_rank = ranking[ranking["Score"] >= min_score]
    if search_rank:
        mask = filtered_rank["Symbol"].str.contains(search_rank, case=False, na=False) | filtered_rank[
            "Industry"
        ].str.contains(search_rank, case=False, na=False)
        filtered_rank = filtered_rank[mask]

    st.caption(f"{len(filtered_rank)} of {len(ranking)} companies")

    event_rank = st.dataframe(
        filtered_rank,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key=f"{key_prefix}_table",
        column_config={
            "Score": st.column_config.ProgressColumn(min_value=0, max_value=len(group_configs), format="%d")
        },
    )
    drill_through(event_rank, filtered_rank)

    with st.expander("Metric detail (10-year history)"):
        label_to_key = {cfg["label"]: key for key, cfg in group_configs.items()}
        chosen_label = st.selectbox("Metric", options=list(label_to_key.keys()), key=f"{key_prefix}_detail_metric")
        chosen = label_to_key[chosen_label]
        render_metric_detail_table(universe, chosen, group_configs[chosen], all_thresholds[chosen], all_passes[chosen])


def render_filter_tab(universe: pd.DataFrame, title: str, description: str, group_configs: dict) -> None:
    """A tab of independent filters, one section per screen in `group_configs`
    — threshold controls, a pass-count, and the table of companies that pass.
    No combined score: used when the screens in the group are variations on
    the same underlying idea (so summing them wouldn't add information), unlike
    the Moats tab's genuinely distinct traits.
    """
    st.subheader(title)
    st.caption(description)

    search = st.text_input("Search by symbol or industry", key=f"{title}_filter_search")

    for config_key, config in group_configs.items():
        thresholds, passes = render_threshold_controls(universe, config_key, config, allow_industry=False)

        passing = universe[passes == True].copy()  # noqa: E712 (NA/False must not match)
        passing["Threshold Used (%)"] = thresholds[passes == True].round(2)
        if search:
            mask = passing["Symbol"].str.contains(search, case=False, na=False) | passing[
                "Industry"
            ].str.contains(search, case=False, na=False)
            passing = passing[mask]

        st.caption(f"**{len(passing)}** of {len(universe)} companies pass")

        row = config["row"]
        display_cols = ["Symbol", "Industry", "Threshold Used (%)"] + [f"{row} Y{y} (%)" for y in range(1, 11)]
        percent_cols = ["Threshold Used (%)"] + [f"{row} Y{y} (%)" for y in range(1, 11)]
        event = st.dataframe(
            passing[display_cols],
            use_container_width=True,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            key=f"{config_key}_filter_table",
            column_config={c: st.column_config.NumberColumn(format="%.2f%%") for c in percent_cols},
        )
        drill_through(event, passing)
        st.divider()


def render_ccp_tab(universe: pd.DataFrame) -> None:
    """CCP (Coffee Can Portfolio) tab: two lists, each requiring ROCE and
    revenue growth to both clear a bar every year for N years. Unlike the
    Moats/Nalanda's F tabs, thresholds here are fixed absolute benchmarks
    (15%/10% by default) rather than industry-relative — that's the point of
    this screen — so there's no industry-percentile toggle, just the two
    threshold sliders and a years slider the user asked for.
    """
    st.subheader("CCP")
    st.caption(
        "Coffee Can Portfolio filter: ROCE and revenue growth both above a bar, every year for N years. "
        "Two lists, sharing the same thresholds — one using regular ROCE, one using ROCE excluding "
        "excess cash (\"Nalanda's F\")."
    )

    col1, col2, col3 = st.columns(3)
    roce_threshold = col1.slider("Min ROCE (%), every year", min_value=0, max_value=100, value=15, key="ccp_roce_threshold")
    growth_threshold = col2.slider(
        "Min revenue growth (%), every year", min_value=0, max_value=100, value=10, key="ccp_growth_threshold"
    )
    years = col3.slider("Number of years", min_value=1, max_value=10, value=10, key="ccp_years")

    # See the comment in render_threshold_controls: shadow-copy into plain keys
    # so the Data Explorer page's Filters section reads the current setting
    # reliably, since widget-bound session_state can reset once these sliders
    # stop being rendered (e.g. after navigating away).
    st.session_state["ccp_roce_threshold_saved"] = roce_threshold
    st.session_state["ccp_growth_threshold_saved"] = growth_threshold
    st.session_state["ccp_years_saved"] = years

    roce_thresh = pd.Series(roce_threshold, index=universe.index)
    growth_thresh = pd.Series(growth_threshold, index=universe.index)

    growth_passes = metric_moat_passes(universe, "RevGrowth", growth_thresh, "higher", "all_years", years)
    roce_passes = metric_moat_passes(universe, "ROCE", roce_thresh, "higher", "all_years", years)
    ex_cash_passes = metric_moat_passes(universe, "ROCEExCash", roce_thresh, "higher", "all_years", years)

    search = st.text_input("Search by symbol or industry", key="ccp_search")

    lists = [
        ("Regular ROCE", and_tri_state(roce_passes, growth_passes), "ROCE"),
        ("Nalanda's F", and_tri_state(ex_cash_passes, growth_passes), "ROCEExCash"),
    ]
    for label, passes, roce_row in lists:
        st.markdown(f"#### {label}")
        passing = universe[passes == True].copy()  # noqa: E712 (NA/False must not match)
        if search:
            mask = passing["Symbol"].str.contains(search, case=False, na=False) | passing[
                "Industry"
            ].str.contains(search, case=False, na=False)
            passing = passing[mask]

        st.caption(f"**{len(passing)}** of {len(universe)} companies pass")

        percent_cols = [f"{roce_row} Y{y} (%)" for y in range(1, years + 1)] + [
            f"RevGrowth Y{y} (%)" for y in range(1, years + 1)
        ]
        display_cols = ["Symbol", "Industry"] + percent_cols
        event = st.dataframe(
            passing[display_cols],
            use_container_width=True,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            key=f"ccp_{label}_table",
            column_config={c: st.column_config.NumberColumn(format="%.2f%%") for c in percent_cols},
        )
        drill_through(event, passing)
        st.divider()


def render_vijay_malik_tab(universe: pd.DataFrame) -> None:
    """Vijay Malik checklist: 5 fixed-threshold checks (Sales CAGR, Net Profit
    CAGR, Debt/Equity, CFO, Market Cap) AND-ed into one pass/fail, shown as a
    single list. Like CCP, thresholds are fixed absolute benchmarks (that's
    the point of this checklist) rather than industry-relative, and each
    check reads one already-computed scalar column (VIJAY_MALIK_CHECKS),
    never a 10-year history.
    """
    st.subheader("Vijay Malik")
    st.caption(
        "Vijay Malik's 5-parameter checklist: Sales and Net Profit CAGR (10Y) above a bar, Debt/Equity below "
        "a bar and CFO positive in the latest fiscal year, and Market Cap above a bar. All 5 must pass."
    )

    slider_specs = {
        "sales_cagr": ("Min Sales CAGR (10Y, %)", 0, 200),
        "net_cagr": ("Min Net Profit CAGR (10Y, %)", 0, 200),
        "debt_equity": ("Max Debt/Equity (%, 100 = 1.0x)", 0, 300),
    }
    number_specs = {
        "cfo": ("Min CFO, latest year (₹ Cr)", 10.0, 10.0),
        "market_cap": ("Min Market Cap (₹ Cr)", 500.0, None),
    }

    thresholds = {}
    slider_cols = st.columns(3)
    for col, key in zip(slider_cols, slider_specs):
        label, min_value, max_value = slider_specs[key]
        default = next(c["default"] for c in VIJAY_MALIK_CHECKS if c["key"] == key)
        thresholds[key] = col.slider(label, min_value=min_value, max_value=max_value, value=int(default), key=f"vm_{key}")

    number_cols = st.columns(2)
    for col, key in zip(number_cols, number_specs):
        label, default, min_value = number_specs[key]
        thresholds[key] = col.number_input(label, value=default, min_value=min_value, step=10.0, key=f"vm_{key}")

    # Shadow-copy into plain keys, same fix as render_threshold_controls/render_ccp_tab,
    # so the Data Explorer Filters section reads the current setting reliably.
    for key, value in thresholds.items():
        st.session_state[f"vm_{key}_saved"] = value

    _per_check, combined = vijay_malik_passes(universe, thresholds)

    search = st.text_input("Search by symbol or industry", key="vijay_malik_search")
    passing = universe[combined == True].copy()  # noqa: E712 (NA/False must not match)
    if search:
        mask = passing["Symbol"].str.contains(search, case=False, na=False) | passing[
            "Industry"
        ].str.contains(search, case=False, na=False)
        passing = passing[mask]

    st.caption(f"**{len(passing)}** of {len(universe)} companies pass")

    display_cols = ["Symbol", "Industry"] + [c["column"] for c in VIJAY_MALIK_CHECKS]
    vm_column_config = {
        c["column"]: st.column_config.NumberColumn(format="%.2f%%" if c["unit"].strip() == "%" else "₹ %,.2f")
        for c in VIJAY_MALIK_CHECKS
    }
    event = st.dataframe(
        passing[display_cols],
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key="vijay_malik_table",
        column_config=vm_column_config,
    )
    drill_through(event, passing)

    st.markdown("**Industry-relative growth cutoffs**")
    st.caption(
        "A separate calculation: Sales CAGR and Net Profit CAGR use each company's own industry's "
        "75th-percentile CAGR instead of the fixed sliders above, falling back to those same sliders' "
        "values for industries with fewer than 5 peers with usable data. Debt/Equity, CFO, and Market "
        "Cap are unchanged from above."
    )

    industry_thresholds = dict(thresholds)
    industry_thresholds["sales_cagr"] = industry_scalar_thresholds(
        universe, "Rev 10Y CAGR (%)", 0.75, fallback=thresholds["sales_cagr"]
    )
    industry_thresholds["net_cagr"] = industry_scalar_thresholds(
        universe, "Net 10Y CAGR (%)", 0.75, fallback=thresholds["net_cagr"]
    )
    _industry_per_check, industry_combined = vijay_malik_passes(universe, industry_thresholds)

    industry_search = st.text_input("Search by symbol or industry", key="vijay_malik_industry_search")
    industry_passing = universe[industry_combined == True].copy()  # noqa: E712 (NA/False must not match)
    if industry_search:
        mask = industry_passing["Symbol"].str.contains(industry_search, case=False, na=False) | industry_passing[
            "Industry"
        ].str.contains(industry_search, case=False, na=False)
        industry_passing = industry_passing[mask]

    st.caption(f"**{len(industry_passing)}** of {len(universe)} companies pass")

    industry_display = industry_passing[display_cols].copy()
    industry_display["Sales CAGR Threshold Used (%)"] = industry_thresholds["sales_cagr"].loc[industry_passing.index].round(2)
    industry_display["Net Profit CAGR Threshold Used (%)"] = industry_thresholds["net_cagr"].loc[industry_passing.index].round(2)

    event2 = st.dataframe(
        industry_display,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key="vijay_malik_industry_table",
        column_config={
            **vm_column_config,
            "Sales CAGR Threshold Used (%)": st.column_config.NumberColumn(format="%.2f%%"),
            "Net Profit CAGR Threshold Used (%)": st.column_config.NumberColumn(format="%.2f%%"),
        },
    )
    drill_through(event2, industry_passing)


def render_vijay_malik_pro_tab(universe: pd.DataFrame) -> None:
    """Vijay Malik Pro: a more detailed, 9-check version of the checklist,
    scored 0-9 (moat_score, one point per check cleared) and ranked — same
    shape as the Moats tab's 7 distinct traits — rather than AND-ed into one
    pass/fail like the original Vijay Malik tab. Bespoke rather than reusing
    render_screen_group_tab, since that helper assumes every check is an
    industry-relative Y1..Y10 (%) row; these checks mix latest-year scalars,
    a 10-year consistency bar, and one two-sided range, with non-% units.
    """
    st.subheader("Vijay Malik Pro")
    st.caption(
        "A more detailed, 9-parameter version of the Vijay Malik checklist: each company is scored 0-9 "
        "(one point per check cleared) and ranked, instead of requiring every check to pass."
    )

    thresholds: dict = {}
    with st.expander("Configure thresholds"):
        for check in VIJAY_MALIK_PRO_CHECKS:
            key = check["key"]
            label_col, control_col = st.columns([2, 5])
            label_col.markdown(f"**{check['label']}**")
            if check["type"] == "range":
                low, high = control_col.slider(
                    "Range (%)",
                    min_value=0,
                    max_value=100,
                    value=(int(check["default_min"]), int(check["default_max"])),
                    key=f"vmpro_{key}",
                    label_visibility="collapsed",
                )
                thresholds[f"{key}_min"], thresholds[f"{key}_max"] = float(low), float(high)
                st.session_state[f"vmpro_{key}_min_saved"] = thresholds[f"{key}_min"]
                st.session_state[f"vmpro_{key}_max_saved"] = thresholds[f"{key}_max"]
            elif check["unit"] == "%":
                value = control_col.slider(
                    "Threshold (%)",
                    min_value=0,
                    max_value=200,
                    value=int(check["default"]),
                    key=f"vmpro_{key}",
                    label_visibility="collapsed",
                )
                thresholds[key] = float(value)
                st.session_state[f"vmpro_{key}_saved"] = thresholds[key]
            else:
                unit = check["unit"].strip()
                step = 10.0 if unit == "Cr" else 0.25
                min_value = 10.0 if key == "cfo" else None
                value = control_col.number_input(
                    f"Threshold ({unit})",
                    value=float(check["default"]),
                    min_value=min_value,
                    step=step,
                    key=f"vmpro_{key}",
                    label_visibility="collapsed",
                )
                thresholds[key] = float(value)
                st.session_state[f"vmpro_{key}_saved"] = thresholds[key]

    per_check = vijay_malik_pro_passes(universe, thresholds)

    ranking = universe[["Symbol", "Industry"]].copy()
    ranking["Score"] = moat_score(per_check)
    for check in VIJAY_MALIK_PRO_CHECKS:
        ranking[check["label"]] = per_check[check["key"]]
    ranking = ranking.sort_values(["Score", "Symbol"], ascending=[False, True])

    search = st.text_input("Search by symbol or industry", key="vmpro_search")
    min_score = st.slider(
        "Minimum score", min_value=0, max_value=len(VIJAY_MALIK_PRO_CHECKS), value=8, key="vmpro_min_score"
    )

    filtered = ranking[ranking["Score"] >= min_score]
    if search:
        mask = filtered["Symbol"].str.contains(search, case=False, na=False) | filtered["Industry"].str.contains(
            search, case=False, na=False
        )
        filtered = filtered[mask]

    st.caption(f"{len(filtered)} of {len(ranking)} companies")

    check_labels = [check["label"] for check in VIJAY_MALIK_PRO_CHECKS]
    event = st.dataframe(
        style_tri_state(filtered, check_labels),
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key="vmpro_table",
        column_config={
            "Score": st.column_config.ProgressColumn(min_value=0, max_value=len(VIJAY_MALIK_PRO_CHECKS), format="%d"),
            **tri_state_column_config(check_labels),
        },
    )
    drill_through(event, filtered)

    st.markdown("**Industry-relative growth cutoffs**")
    st.caption(
        "A separate calculation: Sales CAGR and Net Profit CAGR use each company's own industry's "
        "75th-percentile CAGR instead of the fixed thresholds above, falling back to those same values "
        "for industries with fewer than 5 peers with usable data. The other 7 checks are unchanged."
    )

    industry_thresholds = dict(thresholds)
    industry_thresholds["sales_cagr"] = industry_scalar_thresholds(
        universe, "Rev 10Y CAGR (%)", 0.75, fallback=thresholds["sales_cagr"]
    )
    industry_thresholds["net_cagr"] = industry_scalar_thresholds(
        universe, "Net 10Y CAGR (%)", 0.75, fallback=thresholds["net_cagr"]
    )
    industry_per_check = vijay_malik_pro_passes(universe, industry_thresholds)

    industry_ranking = universe[["Symbol", "Industry"]].copy()
    industry_ranking["Score"] = moat_score(industry_per_check)
    for check in VIJAY_MALIK_PRO_CHECKS:
        industry_ranking[check["label"]] = industry_per_check[check["key"]]
    industry_ranking = industry_ranking.sort_values(["Score", "Symbol"], ascending=[False, True])

    industry_search = st.text_input("Search by symbol or industry", key="vmpro_industry_search")
    industry_min_score = st.slider(
        "Minimum score", min_value=0, max_value=len(VIJAY_MALIK_PRO_CHECKS), value=8, key="vmpro_industry_min_score"
    )

    industry_filtered = industry_ranking[industry_ranking["Score"] >= industry_min_score]
    if industry_search:
        mask = industry_filtered["Symbol"].str.contains(industry_search, case=False, na=False) | industry_filtered[
            "Industry"
        ].str.contains(industry_search, case=False, na=False)
        industry_filtered = industry_filtered[mask]

    st.caption(f"{len(industry_filtered)} of {len(industry_ranking)} companies")

    event2 = st.dataframe(
        style_tri_state(industry_filtered, check_labels),
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key="vmpro_industry_table",
        column_config={
            "Score": st.column_config.ProgressColumn(min_value=0, max_value=len(VIJAY_MALIK_PRO_CHECKS), format="%d"),
            **tri_state_column_config(check_labels),
        },
    )
    drill_through(event2, industry_filtered)


def render_net_net_tab(universe: pd.DataFrame) -> None:
    """Net-Net (Benjamin Graham NCAV) tab: two lists, each Market Cap below a
    Net Current Asset Value basis, sharing one Market Cap floor — same "two
    lists, one shared secondary filter" shape as render_ccp_tab, just with a
    floor instead of a bar-every-year check.
    """
    st.subheader("Net-Net")
    st.caption(
        "Benjamin Graham's Net-Net screen: Market Cap below Net Current Asset Value "
        "(current assets minus Total Liabilities excluding equity). Two lists, sharing the same "
        "Market Cap floor — one using all of OA as current assets, one using only Cash + Inventory + "
        "Receivables (a more conservative basis)."
    )

    mcap_cols = st.columns(2)
    min_mcap = mcap_cols[0].number_input("Min Market Cap (₹ Cr)", value=0.0, step=10.0, key="net_net_min_mcap")
    max_mcap = mcap_cols[1].number_input(
        "Max Market Cap (₹ Cr, 0 = no max)", value=0.0, step=10.0, key="net_net_max_mcap"
    )

    # Shadow-copy into a plain key, same fix as render_threshold_controls/render_ccp_tab,
    # so the Data Explorer page's Filters section reads the current setting reliably.
    # Max Market Cap has no such copy — it's a page-display filter only, not part of
    # the actual screen, so nothing else needs to read it.
    st.session_state["net_net_min_mcap_saved"] = min_mcap

    mcap_series = pd.to_numeric(universe["Market Cap (Cr)"], errors="coerce")
    mcap_floor_passes = scalar_metric_passes(mcap_series, min_mcap, "higher")

    search = st.text_input("Search by symbol or industry", key="net_net_search")

    lists = [
        ("Full Current Assets", "NCAV Latest (Cr)"),
        ("Cash + Inventory + Receivables", "NCAVCashInvRec Latest (Cr)"),
    ]
    for label, ncav_col in lists:
        st.markdown(f"#### {label}")
        combined = and_tri_state(net_net_passes(universe, ncav_col), mcap_floor_passes)
        passing = universe[combined == True].copy()  # noqa: E712 (NA/False must not match)
        passing["Discount to NCAV (%)"] = (
            (passing[ncav_col] - passing["Market Cap (Cr)"]) / passing[ncav_col] * 100
        ).round(2)
        passing = passing.sort_values("Discount to NCAV (%)", ascending=False)

        if max_mcap > 0:
            passing = passing[pd.to_numeric(passing["Market Cap (Cr)"], errors="coerce") <= max_mcap]

        if search:
            mask = passing["Symbol"].str.contains(search, case=False, na=False) | passing[
                "Industry"
            ].str.contains(search, case=False, na=False)
            passing = passing[mask]

        st.caption(f"**{len(passing)}** of {len(universe)} companies pass")

        display_cols = ["Symbol", "Industry", ncav_col, "Market Cap (Cr)", "Discount to NCAV (%)"]
        net_net_table = passing[display_cols]
        event = st.dataframe(
            style_diverging(net_net_table.style, ["Discount to NCAV (%)"]),
            use_container_width=True,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            key=f"net_net_{label}_table",
            column_config={
                ncav_col: st.column_config.NumberColumn(format="₹ %,.2f"),
                "Market Cap (Cr)": st.column_config.NumberColumn(format="₹ %,.2f"),
                "Discount to NCAV (%)": st.column_config.NumberColumn(format="%.2f%%"),
            },
        )
        drill_through(event, passing)
        st.divider()


def render_vantage_tab(universe: pd.DataFrame) -> None:
    """Vantage (Sanjay Bakshi's banker's-valuation) tab: value a company the
    way a banker sizing up collateral would (decay-weighted 10Y CFO/Interest
    -> a loan capacity + cash -> a Total Value), then flag it when Market Cap
    sits inside a configurable multiple-of-that-value range. No industry
    percentile — fixed, user-adjustable thresholds, same as CCP/Vijay Malik.
    """
    st.subheader("Vantage")
    st.caption(
        "Sanjay Bakshi's Vantage analysis: decay-weighted 10-year CFO and Interest give a Cashflow, "
        "1/3 of which is Interest Serviceable; dividing by the lending rate gives the Loan a banker would be "
        "happy to extend; adding Cash gives Total Value. Passes when Market Cap / Total Value (the \"Multiple\") "
        "falls strictly between the two bounds below — the lower bound rules out a negative Total Value "
        "(Loan swamps Cash) ever masquerading as \"cheap\"."
    )

    col1, col2 = st.columns(2)
    decay = col1.slider("Recency decay (per year back)", min_value=0.0, max_value=1.0, value=0.85, step=0.05, key="vantage_decay")
    rate_pct = col2.number_input("Corporate lending rate (%)", value=10.0, step=0.5, key="vantage_rate")

    col3, col4 = st.columns(2)
    min_threshold = col3.number_input("Min Price Multiple", value=0.0, step=0.1, key="vantage_min_threshold")
    max_threshold = col4.number_input("Max Price Multiple", value=1.0, step=0.1, key="vantage_max_threshold")

    # Shadow-copy into plain keys, same fix as every other screen's controls,
    # so the Data Explorer page's Filters section and Vantage block read the
    # current setting reliably.
    st.session_state["vantage_decay_saved"] = decay
    st.session_state["vantage_rate_saved"] = rate_pct / 100
    st.session_state["vantage_min_threshold_saved"] = min_threshold
    st.session_state["vantage_max_threshold_saved"] = max_threshold

    vm = vantage_metrics(universe, decay, rate_pct / 100)
    above_min = scalar_metric_passes(vm["Multiple"], min_threshold, "higher")
    below_max = scalar_metric_passes(vm["Multiple"], max_threshold, "lower")
    passes = and_tri_state(above_min, below_max)

    combined = universe[["Symbol", "Industry", "Market Cap (Cr)"]].join(vm)
    passing = combined[passes == True].copy()  # noqa: E712 (NA/False must not match)
    passing = passing.sort_values("Multiple", ascending=True)

    search = st.text_input("Search by symbol or industry", key="vantage_search")
    if search:
        mask = passing["Symbol"].str.contains(search, case=False, na=False) | passing[
            "Industry"
        ].str.contains(search, case=False, na=False)
        passing = passing[mask]

    st.caption(f"**{len(passing)}** of {len(universe)} companies pass")

    display_cols = ["Symbol", "Industry", "WA CFO (Cr)", "WA Interest (Cr)", "Total Value (Cr)", "Market Cap (Cr)", "Multiple"]
    event = st.dataframe(
        passing[display_cols],
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key="vantage_table",
        column_config={
            "WA CFO (Cr)": st.column_config.NumberColumn(format="₹ %,.2f"),
            "WA Interest (Cr)": st.column_config.NumberColumn(format="₹ %,.2f"),
            "Total Value (Cr)": st.column_config.NumberColumn(format="₹ %,.2f"),
            "Market Cap (Cr)": st.column_config.NumberColumn(format="₹ %,.2f"),
            "Multiple": st.column_config.NumberColumn(format="%.2f"),
        },
    )
    drill_through(event, passing)


def render_magic_formula_tab(universe: pd.DataFrame) -> None:
    """Magic Formula (Joel Greenblatt) tab: rank companies by Earnings Yield
    and by Return on Capital, sum the ranks, rank that sum, show the top 10.
    Two rankings sharing one Market Cap floor — "plain WC" ROC vs. "ex cash"
    ROC — same "two lists, one shared pre-filter" shape as Net-Net.
    """
    st.subheader("Magic Formula")
    st.caption(
        "Joel Greenblatt's Magic Formula: rank companies by Earnings Yield (PBIT / Enterprise Value) and by "
        "Return on Capital (PBIT / (Net Block + Working Capital)), add the two ranks into a Total Rank, then "
        "rank that sum — lower is better. Two lists sharing the same Market Cap floor, differing only in "
        "whether Working Capital excludes cash."
    )

    mcap_cols = st.columns(2)
    min_market_cap = mcap_cols[0].number_input(
        "Min Market Cap (₹ Cr)", value=5000.0, step=10.0, key="magic_formula_min_market_cap"
    )
    max_market_cap = mcap_cols[1].number_input(
        "Max Market Cap (₹ Cr, 0 = no max)", value=0.0, step=10.0, key="magic_formula_max_market_cap"
    )

    # Shadow-copy into a plain key, same fix as every other screen's controls,
    # so the Data Explorer page's Filters section reads the current setting reliably.
    # Max Market Cap has no such copy — it's a page-display filter only, not part of
    # the actual screen (every company's Magic Rank is computed from Min alone).
    st.session_state["magic_formula_min_market_cap_saved"] = min_market_cap

    lists = [
        ("Plain WC", "MagicROC Latest (%)"),
        ("Ex Cash", "MagicROCExCash Latest (%)"),
    ]
    for label, roc_column in lists:
        st.markdown(f"#### {label}")
        ranked = magic_formula_ranking(universe, roc_column, min_market_cap)
        st.caption(f"Top 10 of **{len(ranked)}** eligible companies")

        display_ranked = ranked
        if max_market_cap > 0:
            display_ranked = display_ranked[
                pd.to_numeric(display_ranked["Market Cap (Cr)"], errors="coerce") <= max_market_cap
            ]
            st.caption(f"Showing top {min(10, len(display_ranked))} of {len(display_ranked)} after the Max Market Cap display filter")
        top10 = display_ranked.head(10)

        display_cols = ["Symbol", "Industry", "Earnings Yield (%)", "ROC (%)", "EY Rank", "ROC Rank", "Total Rank", "Magic Rank"]
        event = st.dataframe(
            top10[display_cols],
            use_container_width=True,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            key=f"magic_formula_{label}_table",
            column_config={
                "Earnings Yield (%)": st.column_config.NumberColumn(format="%.2f%%"),
                "ROC (%)": st.column_config.NumberColumn(format="%.2f%%"),
            },
        )
        drill_through(event, top10)
        st.divider()


def render_relative_valuation_tab(universe: pd.DataFrame) -> None:
    """Relative Valuation tab: flag companies whose P/E sits below a chosen
    percentile of their own industry's peers (default: bottom quartile) —
    the first screen to read the Market sheet's PE at all. A thin industry
    (too few peers with a usable P/E) falls back to a flat default bar, same
    as every MOAT_METRIC_CONFIG screen's own fallback — see
    relative_valuation_passes(). A Market Cap floor filters out illiquid
    micro-caps, same rationale Net-Net already established.
    """
    st.subheader("Relative Valuation")
    st.caption(
        "Flags companies whose P/E is cheaper than a chosen percentile of their own industry's peers "
        "(default: bottom quartile). Loss-making companies (negative/zero P/E) are excluded — a P/E "
        "isn't meaningful there. A Market Cap floor filters out illiquid micro-caps, same as Net-Net."
    )

    col1, col2 = st.columns(2)
    percentile_pct = col1.slider(
        "Industry percentile (cheaper than)", min_value=5, max_value=50, value=25, step=5, key="relval_percentile"
    )
    min_market_cap = col2.number_input(
        "Min Market Cap (₹ Cr)", value=0.0, step=10.0, key="relval_min_market_cap"
    )
    percentile = percentile_pct / 100

    # Shadow-copy into plain keys, same fix as every other screen's controls,
    # so the Data Explorer page's Filters section reads the current setting reliably.
    st.session_state["relval_percentile_saved"] = percentile
    st.session_state["relval_min_market_cap_saved"] = min_market_cap

    core_passes, thresholds = relative_valuation_passes(universe, percentile)
    mcap_series = pd.to_numeric(universe["Market Cap (Cr)"], errors="coerce")
    mcap_floor_passes = scalar_metric_passes(mcap_series, min_market_cap, "higher")
    combined = and_tri_state(core_passes, mcap_floor_passes)

    passing_mask = combined == True  # noqa: E712 (NA/False must not match)
    passing = universe[passing_mask].copy()
    passing["Industry PE Threshold"] = thresholds[passing_mask].round(2)
    passing["Discount (%)"] = (
        (passing["Industry PE Threshold"] - passing["PE"]) / passing["Industry PE Threshold"] * 100
    ).round(2)
    passing = passing.sort_values("Discount (%)", ascending=False)

    search = st.text_input("Search by symbol or industry", key="relval_search")
    if search:
        mask = passing["Symbol"].str.contains(search, case=False, na=False) | passing[
            "Industry"
        ].str.contains(search, case=False, na=False)
        passing = passing[mask]

    st.caption(f"**{len(passing)}** of {len(universe)} companies pass")

    display_cols = ["Symbol", "Industry", "PE", "Industry PE Threshold", "Market Cap (Cr)", "Discount (%)"]
    event = st.dataframe(
        style_diverging(passing[display_cols].style, ["Discount (%)"]),
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key="relative_valuation_table",
        column_config={
            "PE": st.column_config.NumberColumn(format="%.2f"),
            "Industry PE Threshold": st.column_config.NumberColumn(format="%.2f"),
            "Market Cap (Cr)": st.column_config.NumberColumn(format="₹ %,.2f"),
            "Discount (%)": st.column_config.NumberColumn(format="%.2f%%"),
        },
    )
    drill_through(event, passing)


# Shared by the Insights tab's Quality vs Valuation scatter and Industry
# spread sections — both let the user pick which already-cached quality
# metric to look at, from the same curated set.
INSIGHTS_METRIC_OPTIONS = {
    "ROCE": "ROCE",
    "Nalanda's F (ROCE ex-cash)": "ROCEExCash",
    "ROE": "ROE",
    "Operating Margin": "OPM",
    "Net Margin": "NPM",
}


def render_insights_tab(universe: pd.DataFrame, sheets: dict) -> None:
    """Insights tab: three visualizations answering questions no single
    pass/fail screen can — where a company sits relative to peers on two
    continuous axes at once (quality vs valuation), which industries look
    strongest across several traits simultaneously, and how selective the
    current thresholds are / where your own holdings sit in that spread.
    """
    st.subheader("Insights")
    st.caption("Chart-first views across the whole universe, built on top of the screens above and your current threshold settings.")

    # Reads the same plain "_saved" shadow keys every other screen's widgets
    # copy themselves into on every run — same cross-page-sync pattern
    # pages/data_explorer.py and pages/portfolio.py already use; read here
    # from within screens.py itself since this tab's body still executes
    # after every other tab's widgets have already run this script pass.
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

    st.markdown("#### Quality vs Valuation")
    st.caption(
        "Every company's P/E against a quality metric of your choice, colored by whether it currently clears "
        "the Relative Valuation screen. Scoped to one industry at a time — coloring by Industry instead would "
        "need far more hues than a legend can hold."
    )

    qcol1, qcol2, qcol3 = st.columns(3)
    quality_label = qcol1.selectbox(
        "Quality metric", list(INSIGHTS_METRIC_OPTIONS.keys()), key="insights_quality_metric"
    )
    industry_options = ["All industries"] + sorted(universe["Industry"].dropna().unique())
    industry_choice = qcol2.selectbox("Industry", industry_options, key="insights_scatter_industry")
    max_pe = qcol3.number_input("Max P/E to show (0 = no max)", value=0.0, step=5.0, key="insights_scatter_max_pe")

    quality_row = INSIGHTS_METRIC_OPTIONS[quality_label]
    scoped_universe = universe if industry_choice == "All industries" else universe[universe["Industry"] == industry_choice]
    scatter_frame = relative_valuation_scatter_frame(scoped_universe, quality_row, max_pe or None)

    if scatter_frame.empty:
        st.caption("Not enough data")
    else:
        relval_passes, _ = relative_valuation_passes(universe, overrides["relative_valuation"]["percentile"])
        scatter_frame = scatter_frame.join(relval_passes.rename("_relval_passes"))
        scatter_frame["Cheap vs Industry"] = scatter_frame["_relval_passes"].apply(
            lambda v: "Below industry percentile" if v is True else "Not below"
        )
        quality_col = f"{quality_row} Y1 (%)"
        render_scatter_chart(
            scatter_frame,
            x_field="PE",
            y_field=quality_col,
            size_field="Market Cap (Cr)",
            color_field="Cheap vs Industry",
            color_domain=["Below industry percentile", "Not below"],
            color_range=[STATUS_GOOD, STATUS_MUTED],
            tooltip_fields=["Symbol", "Industry", "PE", quality_col, "Market Cap (Cr)"],
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
    heatmap_frame = industry_metric_heatmap_frame(universe, heatmap_metrics)
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

    spread_label = st.selectbox("Metric", list(INSIGHTS_METRIC_OPTIONS.keys()), key="insights_spread_metric")
    spread_frame = industry_metric_spread_frame(universe, INSIGHTS_METRIC_OPTIONS[spread_label])

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

    st.markdown("#### Score distribution")
    st.caption(
        "How selective the current thresholds are, and — if you have a Portfolio sheet — where your own "
        "holdings sit in that spread."
    )

    score_choice = st.selectbox(
        "Score", ["Moats Score (0-7)", "Vijay Malik Pro Score (0-9)"], key="insights_score_choice"
    )
    shared = compute_universe_screens(universe, overrides)

    if score_choice.startswith("Moats"):
        insights_moats_configs = {k: v for k, v in MOAT_METRIC_CONFIG.items() if v["group"] == "moats"}
        score_series = moat_score({key: shared["moat"][key][1] for key in insights_moats_configs})
    else:
        score_series = moat_score(shared["vijay_malik_pro"]["per_check"])

    score_by_symbol = score_series.copy()
    score_by_symbol.index = universe.loc[score_by_symbol.index, "Symbol"]

    holdings = portfolio_view(sheets)
    markers = None
    if not holdings.empty:
        markers = {
            symbol: score_by_symbol[symbol] for symbol in holdings["Symbol"] if symbol in score_by_symbol.index
        }

    render_histogram_chart(score_series, markers=markers)


def render_industries_tab(universe: pd.DataFrame) -> None:
    """Chart-and-table views that treat the industry itself (not any one
    company) as the unit of analysis — relative size, growth momentum, and
    competitive intensity. Complements the Insights tab, which compares
    industries one metric at a time; this tab's `industry_overview()` table
    is the single source every section below reads from.
    """
    st.caption(
        "Every screen elsewhere on this page ranks companies. This tab ranks the industries they belong to: "
        "how big each one is, whether its growth is speeding up or slowing down, and how competitive it looks "
        "internally."
    )

    overview = industry_overview(universe).sort_values("Market Cap (Cr)", ascending=False)

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


moats_configs = {k: v for k, v in MOAT_METRIC_CONFIG.items() if v["group"] == "moats"}
nalanda_configs = {k: v for k, v in MOAT_METRIC_CONFIG.items() if v["group"] == "nalanda"}

(
    tab_ssgr,
    tab_moats,
    tab_nalanda,
    tab_ccp,
    tab_vijay_malik,
    tab_vijay_malik_pro,
    tab_net_net,
    tab_vantage,
    tab_magic_formula,
    tab_relative_valuation,
    tab_insights,
    tab_industries,
) = st.tabs(
    [
        "SSGR", "Moats", "Nalanda's F", "CCP", "Vijay Malik", "Vijay Malik Pro", "Net-Net", "Vantage",
        "Magic Formula", "Relative Valuation", "Insights", "Industries",
    ]
)

with tab_ssgr:
    st.subheader("SSGR Screen")
    st.caption("Self-Sustainable Growth Rate vs. 10-year revenue CAGR, across all companies.")

    filtered = search_and_filter(universe, "SSGR Passes", key="ssgr")

    ssgr_cols = ["Symbol", "Industry", "SSGR (%)", "Rev 10Y CAGR (%)", "SSGR Passes"]
    event = st.dataframe(
        filtered[ssgr_cols],
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key="ssgr_table",
        column_config={
            "SSGR (%)": st.column_config.NumberColumn(format="%.2f%%"),
            "Rev 10Y CAGR (%)": st.column_config.NumberColumn(format="%.2f%%"),
        },
    )
    drill_through(event, filtered)

with tab_moats:
    render_screen_group_tab(
        universe, "Moats", f"Companies ranked by how many of the {len(moats_configs)} moat screens they clear.", moats_configs
    )

with tab_nalanda:
    render_filter_tab(
        universe,
        "Nalanda's F",
        "ROCE and ROCE excluding excess cash (\"Nalanda's F\"), each checked both as a median-of-10-years "
        "and an every-year-of-10 bar, against a manual threshold (no industry-relative percentile here). "
        "Four independent filters, not a combined score — all four measure the same underlying idea.",
        nalanda_configs,
    )

with tab_ccp:
    render_ccp_tab(universe)

with tab_vijay_malik:
    render_vijay_malik_tab(universe)

with tab_vijay_malik_pro:
    render_vijay_malik_pro_tab(universe)

with tab_net_net:
    render_net_net_tab(universe)

with tab_vantage:
    render_vantage_tab(universe)

with tab_magic_formula:
    render_magic_formula_tab(universe)

with tab_relative_valuation:
    render_relative_valuation_tab(universe)

with tab_insights:
    render_insights_tab(universe, sheets)

with tab_industries:
    render_industries_tab(universe)
