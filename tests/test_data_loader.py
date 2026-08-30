import pandas as pd
import pytest

from data_loader import (
    MOAT_METRIC_CONFIG,
    _cagr_pct,
    _safe_divide,
    add_bs_totals,
    add_capex_and_ratios,
    add_derived_metrics,
    add_roce,
    add_ssgr,
    add_ttm_column,
    build_cagr_table,
    build_universe_cache,
    company_metric_table,
    get_company_view,
    industry_metric_thresholds,
    load_universe_cache,
    metric_moat_passes,
    moat_score,
    save_universe_cache,
)


def make_table(rows: dict[str, list], columns: list[str]) -> pd.DataFrame:
    """Build a metric-by-period table directly (index=metric, columns=period)."""
    return pd.DataFrame(rows, index=columns).T


def make_wide_sheet(symbol: str, metrics: dict[str, list[float]], periods: list[str]) -> pd.DataFrame:
    """Build a raw wide sheet row (Symbol + Metric-Period columns), like a row of IS/Quarter/BS."""
    data = {"Symbol": [symbol]}
    for metric, values in metrics.items():
        for period, value in zip(periods, values):
            data[f"{metric}-{period}"] = [value]
    return pd.DataFrame(data)


# --- company_metric_table -----------------------------------------------------

def test_company_metric_table_pivots_by_metric_and_period():
    df = pd.DataFrame({
        "Symbol": ["AAA", "BBB"],
        "Rev-26": [100, 200],
        "Rev-25": [90, 180],
        "Exp-26": [60, 120],
    })
    table = company_metric_table(df, "AAA")
    assert list(table.columns) == ["26", "25"]
    assert table.loc["Rev", "26"] == 100
    assert table.loc["Rev", "25"] == 90
    assert table.loc["Exp", "26"] == 60
    assert pd.isna(table.loc["Exp", "25"])


def test_company_metric_table_missing_symbol_returns_empty():
    df = pd.DataFrame({"Symbol": ["AAA"], "Rev-26": [100]})
    assert company_metric_table(df, "ZZZ").empty


# --- add_derived_metrics --------------------------------------------------------

def test_add_derived_metrics_computes_op_pbit_pbt_margins_and_eps():
    table = make_table(
        {"Rev": [1000.0], "Exp": [700.0], "OI": [20.0], "Int": [30.0], "Dep": [50.0], "Net": [150.0]},
        columns=["26"],
    )
    shares_by_year = {"26": 10_000_000.0}  # 1 crore shares

    result = add_derived_metrics(table, shares_by_year)

    assert result.loc["OP", "26"] == 300.0
    assert result.loc["OPM", "26"] == 30.0
    assert result.loc["PBIT", "26"] == 270.0
    assert result.loc["PBT", "26"] == 240.0
    assert result.loc["NPM", "26"] == 15.0
    assert result.loc["EPS", "26"] == 150.0  # 150 crore -> 1.5e9 rupees / 1e7 shares


def test_add_derived_metrics_zero_revenue_gives_nan_margins_not_inf():
    table = make_table({"Rev": [0.0], "Exp": [10.0], "Net": [-10.0]}, columns=["26"])
    result = add_derived_metrics(table, {})
    assert pd.isna(result.loc["OPM", "26"])
    assert pd.isna(result.loc["NPM", "26"])


# --- add_ttm_column --------------------------------------------------------------

def test_add_ttm_column_sums_last_four_quarters():
    quarterly = make_table(
        {
            "Rev": [100, 90, 80, 70, 60],
            "OP": [40, 35, 30, 25, 20],
            "Net": [20, 18, 16, 14, 12],
            "EPS": [2.0, 1.8, 1.6, 1.4, 1.2],
        },
        columns=["Q127", "Q426", "Q326", "Q226", "Q126"],
    )
    # In production, add_derived_metrics always populates OP/OPM/EPS on is_table
    # before add_ttm_column runs, so those rows must pre-exist here too — TTM
    # values are only written for rows already present in is_table.
    is_table = make_table(
        {"Rev": [300.0], "OP": [250.0], "OPM": [83.33], "EPS": [5.0], "Div": [10.0]},
        columns=["26"],
    )

    result = add_ttm_column(is_table, quarterly)

    assert list(result.columns)[0] == "TTM"
    assert result.loc["Rev", "TTM"] == 340.0  # 100+90+80+70
    assert result.loc["OP", "TTM"] == 130.0  # 40+35+30+25
    assert result.loc["EPS", "TTM"] == 6.8  # 2.0+1.8+1.6+1.4
    assert result.loc["OPM", "TTM"] == round(130 / 340 * 100, 2)
    assert pd.isna(result.loc["Div", "TTM"])  # no quarterly Div source


def test_add_ttm_column_skips_when_fewer_than_four_quarters():
    quarterly = make_table({"Rev": [100, 90, 80]}, columns=["Q127", "Q426", "Q326"])
    is_table = make_table({"Rev": [300.0]}, columns=["26"])
    result = add_ttm_column(is_table, quarterly)
    assert "TTM" not in result.columns


# --- add_bs_totals -----------------------------------------------------------------

def test_add_bs_totals_computes_tl_ta_ncf():
    table = make_table(
        {
            "Eq": [10.0], "Res": [40.0], "Borr": [20.0], "OL": [5.0],
            "NB": [30.0], "WIP": [5.0], "Invest": [10.0], "OA": [30.0],
            "CFO": [15.0], "CFI": [-5.0], "CFF": [-2.0],
        },
        columns=["26"],
    )
    result = add_bs_totals(table)
    assert result.loc["TL", "26"] == 75.0
    assert result.loc["TA", "26"] == 75.0
    assert result.loc["NCF", "26"] == 8.0


def test_add_bs_totals_missing_metric_gives_nan():
    table = make_table({"Eq": [10.0], "Res": [40.0], "Borr": [20.0]}, columns=["26"])  # no OL at all
    result = add_bs_totals(table)
    assert pd.isna(result.loc["TL", "26"])


# --- add_ssgr ----------------------------------------------------------------------

def test_add_ssgr_matches_hand_computed_value():
    is_table = make_table({"Rev": [1000.0], "Net": [150.0], "Div": [30.0], "Dep": [40.0]}, columns=["26"])
    bs_table = make_table({"NB": [500.0]}, columns=["26"])

    result = add_ssgr(is_table, bs_table)

    nfat, npm, dpr, dep_nfa = 1000 / 500, 150 / 1000, 30 / 150, 40 / 500
    expected_ssgr = round((nfat * npm * (1 - dpr) - dep_nfa) * 100, 2)

    assert result.loc["NFAT", "26"] == 2.0
    assert result.loc["DPR", "26"] == 20.0
    assert result.loc["DepNFA", "26"] == 8.0
    assert result.loc["SSGR", "26"] == expected_ssgr


def test_add_ssgr_nan_when_net_or_nfa_non_positive():
    is_table = make_table({"Rev": [1000.0], "Net": [0.0], "Div": [0.0], "Dep": [40.0]}, columns=["26"])
    bs_table = make_table({"NB": [0.0]}, columns=["26"])
    result = add_ssgr(is_table, bs_table)
    assert pd.isna(result.loc["DPR", "26"])  # Div/Net, Net==0
    assert pd.isna(result.loc["NFAT", "26"])  # Rev/NFA, NFA==0
    assert pd.isna(result.loc["SSGR", "26"])


# --- add_capex_and_ratios -----------------------------------------------------------

def test_add_capex_and_ratios_matches_hand_computed_values():
    # Columns most-recent-first: "26" then "25". Capex needs an earlier year to
    # diff against, so it (and anything derived from it) is NaN for the oldest "25".
    is_table = make_table(
        {"Rev": [1000.0, 900.0], "Net": [150.0, 120.0], "Dep": [30.0, 25.0],
         "OP": [300.0, 270.0], "Int": [45.0, 40.0]},
        columns=["26", "25"],
    )
    bs_table = make_table(
        {"NB": [200.0, 150.0], "WIP": [50.0, 40.0], "Eq": [100.0, 100.0],
         "Res": [400.0, 350.0], "Borr": [150.0, 140.0], "OL": [50.0, 45.0]},
        columns=["26", "25"],
    )

    result = add_capex_and_ratios(is_table, bs_table)

    assert result.loc["NetWorth", "26"] == 500.0
    assert result.loc["Capex", "26"] == 90.0  # (250-190) + 30
    assert result.loc["LowCapex", "26"] == 9.0  # 90/1000*100
    assert result.loc["LowDebt", "26"] == 15.0  # 45/300*100
    assert result.loc["CapexNI", "26"] == 60.0  # 90/150*100
    assert result.loc["LiabEquity", "26"] == 40.0  # (150+50)/500*100
    assert result.loc["ROE", "26"] == 30.0  # 150/500*100

    # Oldest year: Capex undefined (no earlier year), but LowDebt/LiabEquity/ROE
    # don't depend on Capex, so they're still computed.
    assert pd.isna(result.loc["Capex", "25"])
    assert pd.isna(result.loc["LowCapex", "25"])
    assert pd.isna(result.loc["CapexNI", "25"])
    assert result.loc["LowDebt", "25"] == pytest.approx(round(40 / 270 * 100, 2))
    assert result.loc["LiabEquity", "25"] == pytest.approx(round(185 / 450 * 100, 2))
    assert result.loc["ROE", "25"] == pytest.approx(round(120 / 450 * 100, 2))


# --- add_roce ------------------------------------------------------------------------

def test_add_roce_matches_hand_computed_values():
    is_table = make_table({"PBIT": [200.0, 150.0]}, columns=["26", "25"])
    bs_table = make_table(
        {"NB": [100.0, 90.0], "WIP": [20.0, 15.0], "Invest": [30.0, 25.0],
         "OA": [150.0, 120.0], "OL": [50.0, 40.0], "Cash": [40.0, 30.0]},
        columns=["26", "25"],
    )

    result = add_roce(is_table, bs_table)

    assert result.loc["WC", "26"] == 100.0  # 150-50
    assert result.loc["CapitalEmployed", "26"] == 250.0  # 100+20+30+100
    assert result.loc["ROCE", "26"] == 80.0  # 200/250*100
    assert result.loc["CapitalEmployedExCash", "26"] == 210.0  # 250-40
    assert result.loc["ROCEExCash", "26"] == pytest.approx(round(200 / 210 * 100, 2))

    assert result.loc["WC", "25"] == 80.0  # 120-40
    assert result.loc["CapitalEmployed", "25"] == 210.0  # 90+15+25+80
    assert result.loc["ROCE", "25"] == pytest.approx(round(150 / 210 * 100, 2))
    assert result.loc["CapitalEmployedExCash", "25"] == 180.0  # 210-30
    assert result.loc["ROCEExCash", "25"] == pytest.approx(round(150 / 180 * 100, 2))

    # Excluding cash can only raise (or leave unchanged) ROCE.
    assert result.loc["ROCEExCash", "26"] >= result.loc["ROCE", "26"]
    assert result.loc["ROCEExCash", "25"] >= result.loc["ROCE", "25"]


# --- _safe_divide --------------------------------------------------------------------

def test_safe_divide_zero_and_nan_denominator_is_nan_but_negative_passes_through():
    num = pd.Series([10.0, 10.0, 10.0])
    denom = pd.Series([0.0, float("nan"), -5.0])
    result = _safe_divide(num, denom)
    assert pd.isna(result.iloc[0])
    assert pd.isna(result.iloc[1])
    assert result.iloc[2] == -2.0


# --- _cagr_pct / build_cagr_table ------------------------------------------------------

@pytest.mark.parametrize(
    "latest, base, years, expected",
    [
        (200.0, 100.0, 1, 100.0),
        (800.0, 100.0, 3, 100.0),  # doubles every year for 3 years -> 100% CAGR
        (100.0, -50.0, 1, None),  # negative base -> NaN
        (float("nan"), 100.0, 1, None),
        (100.0, 0.0, 1, None),
    ],
)
def test_cagr_pct(latest, base, years, expected):
    result = _cagr_pct(latest, base, years)
    if expected is None:
        assert pd.isna(result)
    else:
        assert result == pytest.approx(expected)


def test_build_cagr_table_uses_column_position_as_window():
    table = make_table({"Rev": [800.0, 400.0, 200.0, 100.0]}, columns=["26", "25", "24", "23"])
    result = build_cagr_table(table, ["Rev"], (1, 3), periods_per_year=1, unit_suffix="Y")
    assert result.loc["Rev", "1Y"] == 100.0  # 800 vs 400, 1 year
    assert result.loc["Rev", "3Y"] == 100.0  # 800 vs 100, 3 years, doubles/yr


def test_build_cagr_table_insufficient_history_is_nan():
    table = make_table({"Rev": [800.0, 400.0]}, columns=["26", "25"])
    result = build_cagr_table(table, ["Rev"], (1, 5), periods_per_year=1, unit_suffix="Y")
    assert result.loc["Rev", "1Y"] == 100.0
    assert pd.isna(result.loc["Rev", "5Y"])


# --- get_company_view (integration) ---------------------------------------------------

def test_get_company_view_end_to_end():
    # 11 fiscal years, most-recent-first: '26'..'16'. Rev doubles each year going
    # forward (halves going back), Exp/Dep/Net are constant fractions of Rev, so
    # Exp/OP/PBIT/PBT end up proportional to Rev too (OI=Int=0) -> same CAGR as Rev.
    years = [str(y) for y in range(26, 15, -1)]
    rev_annual = [1024 / 2**k for k in range(11)]
    exp_annual = [0.6 * r for r in rev_annual]
    dep_annual = [0.05 * r for r in rev_annual]
    net_annual = [0.1 * r for r in rev_annual]
    zeros = [0.0] * 11

    is_sheet = make_wide_sheet("AAA", {
        "Rev": rev_annual, "Exp": exp_annual, "OI": zeros, "Int": zeros,
        "Dep": dep_annual, "Net": net_annual, "Div": zeros,
    }, years)
    bs_sheet = make_wide_sheet("AAA", {"NB": [500.0] * 11, "Borr": [100.0] * 11}, years)

    # 11 quarters, most-recent-first, revenue doubling every quarter.
    quarters = ["Q127", "Q426", "Q326", "Q226", "Q126", "Q425", "Q325", "Q225", "Q125", "Q424", "Q324"]
    rev_q = [1024 / 2**k for k in range(11)]
    quarter_sheet = make_wide_sheet("AAA", {
        "Rev": rev_q, "Exp": [0.6 * r for r in rev_q], "OI": [0.0] * 11, "Int": [0.0] * 11,
        "Dep": [0.05 * r for r in rev_q], "Net": [0.1 * r for r in rev_q],
    }, quarters)

    industry_sheet = pd.DataFrame({"Symbol": ["AAA"], "Industry": ["Test Industry"]})
    sheets = {"Industry": industry_sheet, "Quarter": quarter_sheet, "IS": is_sheet, "BS": bs_sheet}

    view = get_company_view("AAA", sheets)

    assert view["income_statement"].loc["Rev", "TTM"] == 1920.0  # 1024+512+256+128

    cagr = view["cagr"]
    for metric in ["Exp", "OP", "PBIT", "PBT"]:
        for col in cagr.columns:
            assert cagr.loc[metric, col] == pytest.approx(cagr.loc["Rev", col])

    for metric in ["NB", "Borr"]:  # flat every year -> 0% at every window, incl. 10Y
        assert (cagr.loc[metric] == 0.0).all()

    # Quarterly Rev doubles every quarter -> the same ~1500% annualized CAGR at
    # every window, since (2**w)**(4/w) == 16 for any w.
    for col in view["quarterly_cagr"].columns:
        assert view["quarterly_cagr"].loc["Rev", col] == pytest.approx(1500.0, abs=0.01)

    expected_ssgr = round((1024 / 500 * 0.1 * 1 - (0.05 * 1024) / 500) * 100, 2)
    assert view["income_statement"].loc["SSGR", "26"] == pytest.approx(expected_ssgr)

    expected_10y_cagr = round(((1920 / 2) ** (1 / 10) - 1) * 100, 2)
    screen = view["ssgr_screen"]
    assert screen["latest_year"] == "26"
    assert screen["ssgr_pct"] == pytest.approx(expected_ssgr)
    assert screen["rev_cagr_10y_pct"] == pytest.approx(expected_10y_cagr)
    assert screen["passes"] is False  # SSGR (~10%) well below Rev 10Y CAGR (~99%)


# --- build_universe_cache / cache ------------------------------------------------

def test_build_universe_cache_returns_one_row_per_symbol_and_reports_progress():
    # AAA: same 11-year/11-quarter fixture as the get_company_view test -> Passes=False.
    years_full = [str(y) for y in range(26, 15, -1)]
    rev_full = [1024 / 2**k for k in range(11)]
    # Int = 0.1*Rev (nonzero, so LowDebt = Int/OP is meaningful: 0.1/0.4*100 = 25%).
    is_aaa = make_wide_sheet("AAA", {
        "Rev": rev_full, "Exp": [0.6 * r for r in rev_full], "OI": [0.0] * 11, "Int": [0.1 * r for r in rev_full],
        "Dep": [0.05 * r for r in rev_full], "Net": [0.1 * r for r in rev_full], "Div": [0.0] * 11,
    }, years_full)
    bs_aaa = make_wide_sheet("AAA", {"NB": [500.0] * 11, "Borr": [100.0] * 11}, years_full)
    quarters = ["Q127", "Q426", "Q326", "Q226", "Q126", "Q425", "Q325", "Q225", "Q125", "Q424", "Q324"]
    rev_q = [1024 / 2**k for k in range(11)]
    quarter_aaa = make_wide_sheet("AAA", {
        "Rev": rev_q, "Exp": [0.6 * r for r in rev_q], "OI": [0.0] * 11, "Int": [0.0] * 11,
        "Dep": [0.05 * r for r in rev_q], "Net": [0.1 * r for r in rev_q],
    }, quarters)

    # BBB: only 2 years / 4 quarters of history -> not enough for a 10Y CAGR -> Passes=None.
    years_short = ["26", "25"]
    is_bbb = make_wide_sheet("BBB", {
        "Rev": [200.0, 180.0], "Exp": [120.0, 108.0], "OI": [0.0, 0.0], "Int": [0.1 * 200, 0.1 * 180],
        "Dep": [10.0, 9.0], "Net": [20.0, 18.0], "Div": [0.0, 0.0],
    }, years_short)
    bs_bbb = make_wide_sheet("BBB", {"NB": [100.0, 100.0], "Borr": [50.0, 50.0]}, years_short)
    quarter_bbb = make_wide_sheet("BBB", {
        "Rev": [50.0, 48.0, 46.0, 44.0], "Exp": [30.0, 29.0, 28.0, 27.0],
        "OI": [0.0] * 4, "Int": [0.0] * 4, "Dep": [2.0] * 4, "Net": [5.0, 4.8, 4.6, 4.4],
    }, ["Q127", "Q426", "Q326", "Q226"])

    sheets = {
        "Industry": pd.DataFrame({"Symbol": ["AAA", "BBB"], "Industry": ["Ind A", "Ind B"]}),
        "Quarter": pd.concat([quarter_aaa, quarter_bbb], ignore_index=True),
        "IS": pd.concat([is_aaa, is_bbb], ignore_index=True),
        "BS": pd.concat([bs_aaa, bs_bbb], ignore_index=True),
    }

    progress_calls = []
    result = build_universe_cache(
        sheets, progress_callback=lambda done, total: progress_calls.append((done, total))
    )

    expected_cols = {"Symbol", "Industry", "SSGR (%)", "Rev 10Y CAGR (%)", "SSGR Passes"}
    rows_needed = {config["row"] for config in MOAT_METRIC_CONFIG.values()}
    expected_cols |= {f"{row} Y{y} (%)" for row in rows_needed for y in range(1, 11)}
    assert list(result["Symbol"]) == ["AAA", "BBB"]
    assert set(result.columns) == expected_cols

    aaa_row = result[result["Symbol"] == "AAA"].iloc[0]
    assert aaa_row["SSGR Passes"] is False
    # AAA: Exp = 0.6 * Rev every year -> OPM = 40% for all 11 available years.
    for y in range(1, 11):
        assert aaa_row[f"OPM Y{y} (%)"] == pytest.approx(40.0)
    # Int = 0.1*Rev, OP = 0.4*Rev -> LowDebt = 0.1/0.4*100 = 25% every year.
    for y in range(1, 11):
        assert aaa_row[f"LowDebt Y{y} (%)"] == pytest.approx(25.0)

    bbb_row = result[result["Symbol"] == "BBB"].iloc[0]
    assert pd.isna(bbb_row["Rev 10Y CAGR (%)"])
    assert bbb_row["SSGR Passes"] is None
    # BBB only has 2 years of IS history -> OPM/LowDebt Y1/Y2 present, Y3-10 NaN.
    assert bbb_row["OPM Y1 (%)"] == pytest.approx(40.0)
    assert bbb_row["OPM Y2 (%)"] == pytest.approx(40.0)
    assert bbb_row["LowDebt Y1 (%)"] == pytest.approx(25.0)
    assert bbb_row["LowDebt Y2 (%)"] == pytest.approx(25.0)
    for y in range(3, 11):
        assert pd.isna(bbb_row[f"OPM Y{y} (%)"])
        assert pd.isna(bbb_row[f"LowDebt Y{y} (%)"])

    assert progress_calls[-1] == (2, 2)


def test_save_and_load_universe_cache_roundtrip(tmp_path):
    path = str(tmp_path / "cache.csv")
    df = pd.DataFrame({
        "Symbol": ["AAA", "BBB", "CCC"],
        "Industry": ["Ind A", "Ind B", "Ind C"],
        "SSGR (%)": [10.24, -32.96, float("nan")],
        "Rev 10Y CAGR (%)": [9.41, 8.45, float("nan")],
        "SSGR Passes": [True, False, None],
    })

    save_universe_cache(df, path=path)
    loaded = load_universe_cache(path=path)

    assert list(loaded["Symbol"]) == ["AAA", "BBB", "CCC"]
    assert (loaded["SSGR Passes"] == True).tolist() == [True, False, False]  # noqa: E712


def test_load_universe_cache_missing_file_returns_none(tmp_path):
    assert load_universe_cache(path=str(tmp_path / "missing.csv")) is None


# --- industry_metric_thresholds / metric_moat_passes -----------------------------------

def test_industry_metric_thresholds_percentile_and_small_industry_fallback():
    universe = pd.DataFrame({
        "Symbol": ["A1", "A2", "A3", "A4", "A5", "B1", "B2"],
        "Industry": ["Big"] * 5 + ["Small"] * 2,
        "OPM Y1 (%)": [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0],
    })

    result = industry_metric_thresholds(universe, "OPM", percentile=0.75, min_companies=5, fallback=40.0)

    big_threshold = result[universe["Industry"] == "Big"]
    expected_big = universe[universe["Industry"] == "Big"]["OPM Y1 (%)"].quantile(0.75)
    assert big_threshold.nunique() == 1  # same threshold applied to every company in the industry
    assert big_threshold.iloc[0] == pytest.approx(expected_big)

    small_threshold = result[universe["Industry"] == "Small"]
    assert (small_threshold == 40.0).all()  # only 2 companies -> falls back


def test_metric_moat_passes_higher_direction_full_history_below_and_missing_year():
    universe = pd.DataFrame({
        "Symbol": ["ALL_ABOVE", "ONE_BELOW", "MISSING_YEAR"],
        **{f"OPM Y{y} (%)": [50.0, 50.0, 50.0] for y in range(1, 11)},
    })
    # ONE_BELOW: year 5 dips under the bar.
    universe.loc[universe["Symbol"] == "ONE_BELOW", "OPM Y5 (%)"] = 10.0
    # MISSING_YEAR: year 10 is missing entirely.
    universe.loc[universe["Symbol"] == "MISSING_YEAR", "OPM Y10 (%)"] = float("nan")

    thresholds = pd.Series(40.0, index=universe.index)
    result = metric_moat_passes(universe, "OPM", thresholds, direction="higher")

    assert result[universe["Symbol"] == "ALL_ABOVE"].iloc[0] is True
    assert result[universe["Symbol"] == "ONE_BELOW"].iloc[0] is False
    assert pd.isna(result[universe["Symbol"] == "MISSING_YEAR"].iloc[0])


def test_metric_moat_passes_lower_direction():
    universe = pd.DataFrame({
        "Symbol": ["ALL_BELOW", "ONE_ABOVE"],
        **{f"LowDebt Y{y} (%)": [10.0, 10.0] for y in range(1, 11)},
    })
    universe.loc[universe["Symbol"] == "ONE_ABOVE", "LowDebt Y3 (%)"] = 25.0

    thresholds = pd.Series(15.0, index=universe.index)
    result = metric_moat_passes(universe, "LowDebt", thresholds, direction="lower")

    assert result[universe["Symbol"] == "ALL_BELOW"].iloc[0] is True
    assert result[universe["Symbol"] == "ONE_ABOVE"].iloc[0] is False


def test_metric_moat_passes_median_consistency():
    universe = pd.DataFrame({
        "Symbol": ["GOOD_MEDIAN", "BAD_MEDIAN", "MISSING_YEAR"],
        **{f"ROCE Y{y} (%)": [25.0, 15.0, 25.0] for y in range(1, 11)},
    })
    universe.loc[universe["Symbol"] == "GOOD_MEDIAN", "ROCE Y5 (%)"] = 5.0  # one bad year, median still 25
    universe.loc[universe["Symbol"] == "MISSING_YEAR", "ROCE Y10 (%)"] = float("nan")

    thresholds = pd.Series(20.0, index=universe.index)
    result = metric_moat_passes(universe, "ROCE", thresholds, direction="higher", consistency="median")

    assert result[universe["Symbol"] == "GOOD_MEDIAN"].iloc[0] is True
    assert result[universe["Symbol"] == "BAD_MEDIAN"].iloc[0] is False
    assert pd.isna(result[universe["Symbol"] == "MISSING_YEAR"].iloc[0])


def test_industry_metric_thresholds_median_consistency_uses_10_year_median_not_y1():
    # Each company's Y1 is a wild outlier (999); Y2-Y10 all equal that company's
    # "true" target value, so the 10-year median is the target, not Y1.
    targets = [10.0, 20.0, 30.0, 40.0, 50.0]
    data = {"Symbol": [f"A{i}" for i in range(5)], "Industry": ["Big"] * 5}
    for y in range(1, 11):
        data[f"ROCE Y{y} (%)"] = [999.0 if y == 1 else t for t in targets]
    universe = pd.DataFrame(data)

    result = industry_metric_thresholds(
        universe, "ROCE", percentile=0.75, min_companies=5, fallback=20.0, consistency="median"
    )

    expected = pd.Series(targets).quantile(0.75)
    assert result.nunique() == 1
    assert result.iloc[0] == pytest.approx(expected)


# --- moat_score -------------------------------------------------------------------

def test_moat_score_counts_true_only_and_treats_na_as_zero():
    index = pd.RangeIndex(3)  # PERFECT, PARTIAL, NONE
    passes_by_metric = {
        "OPM": pd.Series([True, True, False], index=index, dtype=object),
        "NPM": pd.Series([True, False, pd.NA], index=index, dtype=object),
        "ROE": pd.Series([True, pd.NA, False], index=index, dtype=object),
    }

    score = moat_score(passes_by_metric)

    assert score.tolist() == [3, 1, 0]
