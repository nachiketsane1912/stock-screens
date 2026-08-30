import os
from datetime import datetime

import pandas as pd
import streamlit as st

from data_loader import (
    MOAT_METRIC_CONFIG,
    UNIVERSE_CACHE_FILE,
    build_universe_cache,
    industry_metric_thresholds,
    load_raw,
    load_universe_cache,
    metric_moat_passes,
    moat_score,
    save_universe_cache,
)

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


def render_threshold_controls(universe: pd.DataFrame, config_key: str, config: dict) -> tuple[pd.Series, pd.Series]:
    """One compact widget row for a screen's threshold, inside a "Configure
    thresholds" expander. Returns (thresholds, passes) for use by the ranking
    table and the metric-detail view.
    """
    row = config["row"]
    pctl = int(config["percentile"] * 100)
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
    event = st.dataframe(
        filtered[display_cols],
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key=f"{config_key}_detail_table",
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
        thresholds, passes = render_threshold_controls(universe, config_key, config)

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
        event = st.dataframe(
            passing[display_cols],
            use_container_width=True,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            key=f"{config_key}_filter_table",
        )
        drill_through(event, passing)
        st.divider()


moats_configs = {k: v for k, v in MOAT_METRIC_CONFIG.items() if v["group"] == "moats"}
nalanda_configs = {k: v for k, v in MOAT_METRIC_CONFIG.items() if v["group"] == "nalanda"}

tab_ssgr, tab_moats, tab_nalanda = st.tabs(["SSGR", "Moats", "Nalanda's F"])

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
        "and an every-year-of-10 bar. Four independent filters, not a combined score — all four measure "
        "the same underlying idea.",
        nalanda_configs,
    )
