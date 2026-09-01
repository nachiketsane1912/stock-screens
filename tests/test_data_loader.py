import pandas as pd
import pytest

from data_loader import (
    CCP_EXTRA_CACHE_ROWS,
    CPI_BASKET_CATEGORIES,
    MOAT_METRIC_CONFIG,
    _cagr_pct,
    _safe_divide,
    add_bs_totals,
    add_capex_and_ratios,
    add_derived_metrics,
    add_rev_growth,
    add_roce,
    add_ssgr,
    add_ttm_column,
    and_tri_state,
    build_cagr_table,
    build_trend_frame,
    build_universe_cache,
    company_metric_table,
    company_vantage_metrics,
    cpi_basket_ranking,
    evaluate_screens_for_company,
    failure_detail,
    get_company_view,
    industry_metric_thresholds,
    load_universe_cache,
    macro_latest_snapshot,
    macro_trend_frame,
    magic_formula_ranking,
    merge_market_data,
    metric_moat_passes,
    moat_score,
    net_net_passes,
    pmi_status,
    portfolio_view,
    portfolio_weighted_pe,
    save_universe_cache,
    scalar_metric_passes,
    vantage_metrics,
    vijay_malik_passes,
    vijay_malik_pro_passes,
    weighted_average_by_year,
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
         "OP": [300.0, 270.0], "Int": [45.0, 40.0], "PBIT": [280.0, 200.0], "PBT": [235.0, 160.0]},
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
    assert result.loc["DebtEquity", "26"] == 30.0  # 150/500*100 (Borr alone, no OL)
    assert result.loc["TotalLiabExEquity", "26"] == 200.0  # 150+50
    assert result.loc["TaxPayoutRatio", "26"] == pytest.approx(round(85 / 235 * 100, 2))  # (235-150)/235*100
    assert result.loc["InterestCoverage", "26"] == pytest.approx(round(280 / 45, 2))  # PBIT/Int

    # Oldest year: Capex undefined (no earlier year), but LowDebt/LiabEquity/ROE
    # don't depend on Capex, so they're still computed.
    assert pd.isna(result.loc["Capex", "25"])
    assert pd.isna(result.loc["LowCapex", "25"])
    assert pd.isna(result.loc["CapexNI", "25"])
    assert result.loc["LowDebt", "25"] == pytest.approx(round(40 / 270 * 100, 2))
    assert result.loc["LiabEquity", "25"] == pytest.approx(round(185 / 450 * 100, 2))
    assert result.loc["ROE", "25"] == pytest.approx(round(120 / 450 * 100, 2))
    assert result.loc["DebtEquity", "25"] == pytest.approx(round(140 / 450 * 100, 2))
    assert result.loc["TotalLiabExEquity", "25"] == 185.0  # 140+45
    assert result.loc["TaxPayoutRatio", "25"] == 25.0  # (160-120)/160*100
    assert result.loc["InterestCoverage", "25"] == 5.0  # 200/40


# --- add_roce ------------------------------------------------------------------------

def test_add_roce_matches_hand_computed_values():
    is_table = make_table({"PBIT": [200.0, 150.0]}, columns=["26", "25"])
    bs_table = make_table(
        {"NB": [100.0, 90.0], "WIP": [20.0, 15.0], "Invest": [30.0, 25.0],
         "OA": [150.0, 120.0], "OL": [50.0, 40.0], "Cash": [40.0, 30.0], "Borr": [60.0, 55.0],
         "Inv": [80.0, 70.0], "Rec": [90.0, 80.0]},
        columns=["26", "25"],
    )

    result = add_roce(is_table, bs_table)

    assert result.loc["WC", "26"] == 100.0  # 150-50
    assert result.loc["CapitalEmployed", "26"] == 250.0  # 100+20+30+100
    assert result.loc["ROCE", "26"] == 80.0  # 200/250*100
    assert result.loc["CapitalEmployedExCash", "26"] == 180.0  # 250-40-30
    assert result.loc["ROCEExCash", "26"] == pytest.approx(round(200 / 180 * 100, 2))
    assert result.loc["NCAV", "26"] == 40.0  # 100-60
    assert result.loc["NCAVCashInvRec", "26"] == 100.0  # (40+80+90)-(60+50)
    assert result.loc["MagicROC", "26"] == 100.0  # 200/(100+100)*100
    assert result.loc["MagicROCExCash", "26"] == 125.0  # 200/(100+100-40)*100
    assert result.loc["CurrentRatio", "26"] == 3.0  # 150/50

    assert result.loc["WC", "25"] == 80.0  # 120-40
    assert result.loc["CapitalEmployed", "25"] == 210.0  # 90+15+25+80
    assert result.loc["ROCE", "25"] == pytest.approx(round(150 / 210 * 100, 2))
    assert result.loc["CapitalEmployedExCash", "25"] == 155.0  # 210-30-25
    assert result.loc["ROCEExCash", "25"] == pytest.approx(round(150 / 155 * 100, 2))
    assert result.loc["NCAV", "25"] == 25.0  # 80-55
    assert result.loc["NCAVCashInvRec", "25"] == 85.0  # (30+70+80)-(55+40)
    assert result.loc["MagicROC", "25"] == pytest.approx(round(150 / (90 + 80) * 100, 2))
    assert result.loc["MagicROCExCash", "25"] == pytest.approx(round(150 / (90 + 80 - 30) * 100, 2))
    assert result.loc["CurrentRatio", "25"] == 3.0  # 120/40

    # Excluding cash can only raise (or leave unchanged) ROCE.
    assert result.loc["ROCEExCash", "26"] >= result.loc["ROCE", "26"]
    assert result.loc["ROCEExCash", "25"] >= result.loc["ROCE", "25"]


# --- add_rev_growth -------------------------------------------------------------------

def test_add_rev_growth_matches_hand_computed_values():
    is_table = make_table({"Rev": [120.0, 100.0, 80.0]}, columns=["26", "25", "24"])

    result = add_rev_growth(is_table)

    assert result.loc["RevGrowth", "26"] == 20.0  # (120-100)/100*100
    assert result.loc["RevGrowth", "25"] == 25.0  # (100-80)/80*100
    assert pd.isna(result.loc["RevGrowth", "24"])  # oldest year, no earlier year to diff against


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


# --- build_trend_frame ---------------------------------------------------------

def test_build_trend_frame_orders_chronologically_and_drops_ttm():
    table = make_table({"Rev": [999.0, 800.0, 400.0, 200.0]}, columns=["TTM", "26", "25", "24"])
    result = build_trend_frame(table, ["Rev"])
    assert list(result.index) == ["24", "25", "26"]
    assert "TTM" not in result.index
    assert result.loc["24", "Rev"] == 200.0
    assert result.loc["25", "Rev"] == 400.0
    assert result.loc["26", "Rev"] == 800.0


def test_build_trend_frame_missing_row_is_all_nan():
    table = make_table({"Rev": [800.0, 400.0]}, columns=["26", "25"])
    result = build_trend_frame(table, ["Rev", "ROE"])
    assert list(result.columns) == ["Rev", "ROE"]
    assert result["ROE"].isna().all()


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
    for metric in ["Exp", "OP", "PBIT", "PBT", "Net"]:
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


# --- get_company_view market data (Price/Market Cap/P·E) -------------------------------

def _market_fixture_sheets(market_row: dict | None) -> dict[str, pd.DataFrame]:
    """Minimal Industry/Quarter/IS/BS sheets for symbol "AAA" (get_company_view
    needs all four to run, but market data itself doesn't depend on their
    content), plus an optional Market sheet row.
    """
    years = ["26"]
    is_sheet = make_wide_sheet("AAA", {
        "Rev": [100.0], "Exp": [60.0], "OI": [0.0], "Int": [0.0], "Dep": [5.0], "Net": [10.0], "Div": [0.0],
    }, years)
    bs_sheet = make_wide_sheet("AAA", {"NB": [50.0], "Borr": [10.0]}, years)
    quarter_sheet = make_wide_sheet("AAA", {
        "Rev": [25.0] * 4, "Exp": [15.0] * 4, "OI": [0.0] * 4, "Int": [0.0] * 4, "Dep": [1.0] * 4, "Net": [2.5] * 4,
    }, ["Q127", "Q426", "Q326", "Q226"])

    industry_sheet = pd.DataFrame({"Symbol": ["AAA"], "Industry": ["Test Industry"]})
    sheets = {"Industry": industry_sheet, "Quarter": quarter_sheet, "IS": is_sheet, "BS": bs_sheet}
    if market_row is not None:
        sheets["Market"] = pd.DataFrame([market_row])
    return sheets


def test_get_company_view_reads_market_data_directly_from_sheet():
    sheets = _market_fixture_sheets({"Symbol": "AAA", "CMP": 960.0, "PE": 5.0, "Market cap (INR Cr)": 1200.0})

    market = get_company_view("AAA", sheets)["market"]

    assert market["price"] == 960.0
    assert market["pe"] == 5.0
    assert market["market_cap_cr"] == 1200.0


def test_get_company_view_market_data_missing_sheet_is_nan_not_error():
    sheets = _market_fixture_sheets(market_row=None)
    assert "Market" not in sheets

    market = get_company_view("AAA", sheets)["market"]

    assert pd.isna(market["price"])
    assert pd.isna(market["pe"])
    assert pd.isna(market["market_cap_cr"])


def test_get_company_view_market_data_symbol_not_in_market_sheet():
    sheets = _market_fixture_sheets({"Symbol": "ZZZ", "CMP": 100.0, "PE": 10.0, "Market cap (INR Cr)": 500.0})

    market = get_company_view("AAA", sheets)["market"]
    assert pd.isna(market["price"])


# --- merge_market_data -----------------------------------------------------------------

def test_merge_market_data_reads_price_pe_and_market_cap():
    universe = pd.DataFrame({"Symbol": ["AAA", "BBB"]})
    sheets = {"Market": pd.DataFrame({
        "Symbol": ["AAA", "BBB"], "CMP": [200.0, 50.0], "PE": [10.0, 5.0],
        "Market cap (INR Cr)": [1500.0, 250.0], "Beta": [1.1, 0.9],
    })}

    result = merge_market_data(universe, sheets)

    aaa = result.loc[result["Symbol"] == "AAA"].iloc[0]
    assert aaa["Price"] == 200.0
    assert aaa["PE"] == 10.0
    assert aaa["Market Cap (Cr)"] == 1500.0
    bbb = result.loc[result["Symbol"] == "BBB"].iloc[0]
    assert bbb["Price"] == 50.0
    assert bbb["PE"] == 5.0
    assert bbb["Market Cap (Cr)"] == 250.0


def test_merge_market_data_symbol_missing_from_market_sheet_is_nan():
    universe = pd.DataFrame({"Symbol": ["AAA"]})
    sheets = {"Market": pd.DataFrame({
        "Symbol": ["ZZZ"], "CMP": [100.0], "PE": [10.0], "Market cap (INR Cr)": [500.0],
    })}

    result = merge_market_data(universe, sheets)

    assert pd.isna(result["Price"].iloc[0])
    assert pd.isna(result["PE"].iloc[0])
    assert pd.isna(result["Market Cap (Cr)"].iloc[0])


def test_merge_market_data_no_market_sheet_gives_nan_columns_no_crash():
    universe = pd.DataFrame({"Symbol": ["AAA"]})

    result = merge_market_data(universe, {})

    assert pd.isna(result["Price"].iloc[0])
    assert pd.isna(result["Market Cap (Cr)"].iloc[0])
    assert pd.isna(result["PE"].iloc[0])


def test_merge_market_data_zero_market_cap_is_treated_as_missing():
    # A listed company can never have zero market cap -- this is a vendor
    # data-export artifact, not a real value (observed in practice).
    universe = pd.DataFrame({"Symbol": ["AAA"]})
    sheets = {"Market": pd.DataFrame({
        "Symbol": ["AAA"], "CMP": [641.05], "PE": [26.99], "Market cap (INR Cr)": [0.0],
    })}

    result = merge_market_data(universe, sheets)

    assert pd.isna(result["Market Cap (Cr)"].iloc[0])
    assert result["Price"].iloc[0] == 641.05  # Price/PE are untouched by this guard


# --- portfolio_view ---------------------------------------------------------------

def _portfolio_sheets(portfolio_rows: list[dict], industry_rows: list[dict] | None = None) -> dict:
    industry_rows = industry_rows if industry_rows is not None else [
        {"Symbol": "AAA", "Industry": "Chemicals"}, {"Symbol": "BBB", "Industry": "Pharmaceuticals"},
    ]
    return {
        "Portfolio": pd.DataFrame(portfolio_rows),
        "Industry": pd.DataFrame(industry_rows),
    }


def test_portfolio_view_matches_hand_computed_values():
    sheets = _portfolio_sheets([
        {"Symbol": "AAA", "Quantity": 10, "Invested": 1000.0, "CMP": 120.0},  # Value 1200, Gain 200 (20%)
        {"Symbol": "BBB", "Quantity": 5, "Invested": 1000.0, "CMP": 160.0},  # Value 800, Gain -200 (-20%)
    ])

    result = portfolio_view(sheets)

    aaa = result.loc[result["Symbol"] == "AAA"].iloc[0]
    assert aaa["Current Value"] == 1200.0
    assert aaa["Gain/Loss"] == 200.0
    assert aaa["Gain (%)"] == 20.0
    assert aaa["Industry"] == "Chemicals"
    assert aaa["Weight (%)"] == 60.0  # 1200 / (1200+800) * 100

    bbb = result.loc[result["Symbol"] == "BBB"].iloc[0]
    assert bbb["Current Value"] == 800.0
    assert bbb["Gain/Loss"] == -200.0
    assert bbb["Gain (%)"] == -20.0
    assert bbb["Industry"] == "Pharmaceuticals"
    assert bbb["Weight (%)"] == 40.0

    assert result["Weight (%)"].sum() == pytest.approx(100.0)


def test_portfolio_view_no_portfolio_sheet_is_empty_with_expected_columns():
    result = portfolio_view({"Industry": pd.DataFrame({"Symbol": ["AAA"], "Industry": ["Chemicals"]})})

    assert result.empty
    assert list(result.columns) == [
        "Symbol", "Industry", "Quantity", "Invested", "CMP", "PE", "Current Value",
        "Gain/Loss", "Gain (%)", "Weight (%)",
    ]


def test_portfolio_view_unknown_symbol_gets_unknown_industry():
    sheets = _portfolio_sheets(
        [{"Symbol": "ZZZ", "Quantity": 10, "Invested": 1000.0, "CMP": 120.0}],
        industry_rows=[{"Symbol": "AAA", "Industry": "Chemicals"}],
    )

    result = portfolio_view(sheets)

    assert result.iloc[0]["Industry"] == "Unknown"


def test_portfolio_view_zero_invested_gain_pct_is_nan():
    sheets = _portfolio_sheets([{"Symbol": "AAA", "Quantity": 10, "Invested": 0.0, "CMP": 120.0}])

    result = portfolio_view(sheets)

    assert result.iloc[0]["Current Value"] == 1200.0
    assert result.iloc[0]["Gain/Loss"] == 1200.0
    assert pd.isna(result.iloc[0]["Gain (%)"])


def test_portfolio_view_all_zero_current_value_weight_is_nan_not_crash():
    sheets = _portfolio_sheets([
        {"Symbol": "AAA", "Quantity": 0, "Invested": 1000.0, "CMP": 120.0},
        {"Symbol": "BBB", "Quantity": 0, "Invested": 500.0, "CMP": 160.0},
    ])

    result = portfolio_view(sheets)

    assert result["Weight (%)"].isna().all()


def test_portfolio_view_merges_pe_from_market_sheet():
    sheets = _portfolio_sheets([
        {"Symbol": "AAA", "Quantity": 10, "Invested": 1000.0, "CMP": 120.0},
        {"Symbol": "BBB", "Quantity": 5, "Invested": 1000.0, "CMP": 160.0},
    ])
    sheets["Market"] = pd.DataFrame({"Symbol": ["AAA", "BBB"], "PE": [20.0, 35.5]})

    result = portfolio_view(sheets)

    assert result.loc[result["Symbol"] == "AAA"].iloc[0]["PE"] == 20.0
    assert result.loc[result["Symbol"] == "BBB"].iloc[0]["PE"] == 35.5


def test_portfolio_view_pe_nan_when_symbol_missing_from_market_sheet():
    sheets = _portfolio_sheets([{"Symbol": "AAA", "Quantity": 10, "Invested": 1000.0, "CMP": 120.0}])
    sheets["Market"] = pd.DataFrame({"Symbol": ["ZZZ"], "PE": [20.0]})

    result = portfolio_view(sheets)

    assert pd.isna(result.iloc[0]["PE"])


def test_portfolio_view_pe_nan_when_no_market_sheet():
    sheets = _portfolio_sheets([{"Symbol": "AAA", "Quantity": 10, "Invested": 1000.0, "CMP": 120.0}])

    result = portfolio_view(sheets)

    assert pd.isna(result.iloc[0]["PE"])


# --- portfolio_weighted_pe ---------------------------------------------------------

def test_portfolio_weighted_pe_matches_hand_computed_value():
    holdings = pd.DataFrame({
        "Current Value": [1200.0, 800.0],  # weights 60% / 40%
        "PE": [20.0, 40.0],
    })

    result = portfolio_weighted_pe(holdings)

    assert result == pytest.approx(0.6 * 20.0 + 0.4 * 40.0)  # 28.0


def test_portfolio_weighted_pe_excludes_missing_pe_and_renormalizes():
    holdings = pd.DataFrame({
        "Current Value": [1200.0, 800.0],
        "PE": [20.0, float("nan")],
    })

    result = portfolio_weighted_pe(holdings)

    assert result == pytest.approx(20.0)  # BBB excluded entirely, not treated as 0


def test_portfolio_weighted_pe_excludes_non_positive_pe():
    holdings = pd.DataFrame({
        "Current Value": [1200.0, 800.0],
        "PE": [20.0, -5.0],
    })

    result = portfolio_weighted_pe(holdings)

    assert result == pytest.approx(20.0)


def test_portfolio_weighted_pe_nan_when_no_usable_pe():
    holdings = pd.DataFrame({
        "Current Value": [1200.0, 800.0],
        "PE": [float("nan"), float("nan")],
    })

    assert pd.isna(portfolio_weighted_pe(holdings))


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

    expected_cols = {
        "Symbol", "Industry", "SSGR (%)", "Rev 10Y CAGR (%)", "SSGR Passes",
        "Net 10Y CAGR (%)", "DebtEquity Latest (%)", "CFO Latest (Cr)", "NCAV Latest (Cr)",
        "NCAVCashInvRec Latest (Cr)", "Cash Latest (Cr)",
        "PBIT Latest (Cr)", "TotalLiabExEquity Latest (Cr)", "MagicROC Latest (%)", "MagicROCExCash Latest (%)",
        "TaxPayoutRatio Latest (%)", "InterestCoverage Latest (x)", "CurrentRatio Latest (x)",
    }
    expected_cols |= {f"Int Y{y} (Cr)" for y in range(1, 11)} | {f"CFO Y{y} (Cr)" for y in range(1, 11)}
    rows_needed = {config["row"] for config in MOAT_METRIC_CONFIG.values()} | CCP_EXTRA_CACHE_ROWS
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
    # Rev doubles every year (backward) -> RevGrowth = 100% every year.
    for y in range(1, 11):
        assert aaa_row[f"RevGrowth Y{y} (%)"] == pytest.approx(100.0)

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


def test_metric_moat_passes_custom_years_window():
    # Fails only in Y7-Y10 -> should still pass when only the first 5 years are checked.
    universe = pd.DataFrame({
        "Symbol": ["LATE_DIP"],
        **{f"ROCE Y{y} (%)": [25.0] for y in range(1, 7)},
        **{f"ROCE Y{y} (%)": [5.0] for y in range(7, 11)},
    })
    thresholds = pd.Series(20.0, index=universe.index)

    result_5y = metric_moat_passes(universe, "ROCE", thresholds, direction="higher", years=5)
    result_10y = metric_moat_passes(universe, "ROCE", thresholds, direction="higher", years=10)

    assert result_5y.iloc[0] is True
    assert result_10y.iloc[0] is False


def test_metric_moat_passes_custom_unit_reads_non_percent_columns():
    # CFO is cached as "CFO Y1 (Cr)".."CFO Y10 (Cr)", not "(%)" — unit="Cr" must
    # read those columns, and the default unit="%" must be unaffected.
    universe = pd.DataFrame({
        "Symbol": ["ALWAYS_POSITIVE", "ONE_NEGATIVE"],
        **{f"CFO Y{y} (Cr)": [100.0, 100.0] for y in range(1, 11)},
    })
    universe.loc[universe["Symbol"] == "ONE_NEGATIVE", "CFO Y4 (Cr)"] = -5.0

    thresholds = pd.Series(0.0, index=universe.index)
    result = metric_moat_passes(universe, "CFO", thresholds, direction="higher", unit="Cr")

    assert result[universe["Symbol"] == "ALWAYS_POSITIVE"].iloc[0] is True
    assert result[universe["Symbol"] == "ONE_NEGATIVE"].iloc[0] is False


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


# --- scalar_metric_passes ---------------------------------------------------------

def test_scalar_metric_passes_higher_direction():
    values = pd.Series([20.0, 10.0, float("nan")])

    result = scalar_metric_passes(values, threshold=15.0, direction="higher")

    assert result.iloc[0] is True
    assert result.iloc[1] is False
    assert pd.isna(result.iloc[2])


def test_scalar_metric_passes_lower_direction():
    values = pd.Series([0.5, 1.5])

    result = scalar_metric_passes(values, threshold=1.0, direction="lower")

    assert result.iloc[0] is True
    assert result.iloc[1] is False


# --- vijay_malik_passes -------------------------------------------------------------

def _vm_universe(**overrides) -> pd.DataFrame:
    row = {
        "Symbol": ["AAA"],
        "Rev 10Y CAGR (%)": [20.0],
        "Net 10Y CAGR (%)": [40.0],
        "DebtEquity Latest (%)": [40.0],
        "CFO Latest (Cr)": [50.0],
        "Market Cap (Cr)": [1000.0],
    }
    row.update({k: [v] for k, v in overrides.items()})
    return pd.DataFrame(row)


def test_vijay_malik_passes_all_clear_default_thresholds():
    universe = _vm_universe()

    per_check, combined = vijay_malik_passes(universe, {})

    assert combined.iloc[0] is True
    assert all(series.iloc[0] is True for series in per_check.values())


def test_vijay_malik_passes_one_failure_dominates():
    universe = _vm_universe(**{"DebtEquity Latest (%)": 150.0})

    per_check, combined = vijay_malik_passes(universe, {})

    assert per_check["debt_equity"].iloc[0] is False
    assert combined.iloc[0] is False


def test_vijay_malik_passes_missing_value_is_na_unless_another_check_fails():
    universe = _vm_universe(**{"CFO Latest (Cr)": float("nan")})

    per_check, combined = vijay_malik_passes(universe, {})

    assert pd.isna(per_check["cfo"].iloc[0])
    assert pd.isna(combined.iloc[0])


# --- vijay_malik_pro_passes -----------------------------------------------------------

def _vmp_universe(**overrides) -> pd.DataFrame:
    row = {
        "Symbol": ["AAA"],
        "Rev 10Y CAGR (%)": [20.0],
        "Net 10Y CAGR (%)": [40.0],
        "DebtEquity Latest (%)": [40.0],
        "Market Cap (Cr)": [1000.0],
        "TaxPayoutRatio Latest (%)": [27.0],
        "InterestCoverage Latest (x)": [5.0],
        "CurrentRatio Latest (x)": [1.5],
    }
    npm_values = overrides.pop("NPM", [30.0] * 10)
    cfo_values = overrides.pop("CFO", [100.0] * 10)
    for y in range(1, 11):
        row[f"NPM Y{y} (%)"] = [npm_values[y - 1]]
        row[f"CFO Y{y} (Cr)"] = [cfo_values[y - 1]]
    row.update({k: [v] for k, v in overrides.items()})
    return pd.DataFrame(row)


def test_vijay_malik_pro_passes_all_clear_scores_nine():
    universe = _vmp_universe()

    per_check = vijay_malik_pro_passes(universe, {})

    assert all(series.iloc[0] is True for series in per_check.values())
    assert moat_score(per_check).iloc[0] == 9


def test_vijay_malik_pro_passes_scalar_failure():
    universe = _vmp_universe(**{"Market Cap (Cr)": 10.0})

    per_check = vijay_malik_pro_passes(universe, {})

    assert per_check["market_cap"].iloc[0] is False
    assert moat_score(per_check).iloc[0] == 8


def test_vijay_malik_pro_passes_consistency_failure_one_bad_year():
    universe = _vmp_universe(NPM=[30.0, 30.0, 30.0, 2.0, 30.0, 30.0, 30.0, 30.0, 30.0, 30.0])

    per_check = vijay_malik_pro_passes(universe, {})

    assert per_check["npm"].iloc[0] is False
    assert moat_score(per_check).iloc[0] == 8


def test_vijay_malik_pro_passes_tax_payout_range_fails_below_and_above():
    per_check_low = vijay_malik_pro_passes(_vmp_universe(**{"TaxPayoutRatio Latest (%)": 5.0}), {})
    assert per_check_low["tax_payout"].iloc[0] is False

    per_check_high = vijay_malik_pro_passes(_vmp_universe(**{"TaxPayoutRatio Latest (%)": 60.0}), {})
    assert per_check_high["tax_payout"].iloc[0] is False


def test_vijay_malik_pro_passes_custom_thresholds():
    universe = _vmp_universe()

    per_check = vijay_malik_pro_passes(universe, {"market_cap": 5000.0, "tax_payout_min": 30.0})

    assert per_check["market_cap"].iloc[0] is False  # 1000 < 5000
    assert per_check["tax_payout"].iloc[0] is False  # 27 < 30


# --- net_net_passes -----------------------------------------------------------------

def test_net_net_passes_mcap_below_ncav():
    universe = pd.DataFrame({"Market Cap (Cr)": [100.0], "NCAV Latest (Cr)": [200.0]})
    assert net_net_passes(universe, "NCAV Latest (Cr)").iloc[0] is True


def test_net_net_passes_mcap_above_ncav():
    universe = pd.DataFrame({"Market Cap (Cr)": [300.0], "NCAV Latest (Cr)": [200.0]})
    assert net_net_passes(universe, "NCAV Latest (Cr)").iloc[0] is False


def test_net_net_passes_negative_ncav_always_fails():
    # Market Cap is always positive for a listed company, so it can never be
    # below a negative NCAV — no separate "NCAV > 0" gate is needed.
    universe = pd.DataFrame({"Market Cap (Cr)": [50.0], "NCAV Latest (Cr)": [-20.0]})
    assert net_net_passes(universe, "NCAV Latest (Cr)").iloc[0] is False


def test_net_net_passes_missing_value_is_na():
    universe = pd.DataFrame({"Market Cap (Cr)": [float("nan")], "NCAV Latest (Cr)": [200.0]})
    assert pd.isna(net_net_passes(universe, "NCAV Latest (Cr)").iloc[0])


def test_net_net_passes_uses_the_given_ncav_column():
    # Same Market Cap, different results depending on which NCAV basis is used.
    universe = pd.DataFrame({
        "Market Cap (Cr)": [150.0],
        "NCAV Latest (Cr)": [200.0],
        "NCAVCashInvRec Latest (Cr)": [100.0],
    })
    assert net_net_passes(universe, "NCAV Latest (Cr)").iloc[0] is True
    assert net_net_passes(universe, "NCAVCashInvRec Latest (Cr)").iloc[0] is False


# --- weighted_average_by_year -------------------------------------------------------

def test_weighted_average_by_year_decay_weighting():
    universe = pd.DataFrame({"CFO Y1 (Cr)": [30.0], "CFO Y2 (Cr)": [20.0], "CFO Y3 (Cr)": [10.0]})

    result = weighted_average_by_year(universe, "CFO", "Cr", decay=0.5, years=3)

    # weights 1, 0.5, 0.25 (sum 1.75) -> (30*1 + 20*0.5 + 10*0.25) / 1.75
    assert result.iloc[0] == pytest.approx((30 + 10 + 2.5) / 1.75)


def test_weighted_average_by_year_missing_year_is_nan():
    universe = pd.DataFrame({"CFO Y1 (Cr)": [30.0], "CFO Y2 (Cr)": [float("nan")], "CFO Y3 (Cr)": [10.0]})
    result = weighted_average_by_year(universe, "CFO", "Cr", decay=0.5, years=3)
    assert pd.isna(result.iloc[0])


# --- vantage_metrics ----------------------------------------------------------------

def _vantage_universe(cfo: float, interest: float, cash: float, market_cap: float) -> pd.DataFrame:
    row = {"Cash Latest (Cr)": [cash], "Market Cap (Cr)": [market_cap]}
    for y in range(1, 11):
        row[f"CFO Y{y} (Cr)"] = [cfo]
        row[f"Int Y{y} (Cr)"] = [interest]
    return pd.DataFrame(row)


def test_vantage_metrics_matches_hand_computed_values():
    universe = _vantage_universe(cfo=500.0, interest=50.0, cash=200.0, market_cap=1000.0)

    result = vantage_metrics(universe, decay=0.85, rate=0.10)

    assert result.loc[0, "WA CFO (Cr)"] == 500.0
    assert result.loc[0, "WA Interest (Cr)"] == 50.0
    assert result.loc[0, "Cashflow (Cr)"] == 450.0
    assert result.loc[0, "Interest Serviceable (Cr)"] == 150.0
    assert result.loc[0, "Loan (Cr)"] == 1500.0
    assert result.loc[0, "Total Value (Cr)"] == 1700.0
    assert result.loc[0, "Multiple"] == pytest.approx(round(1000 / 1700, 2))


def test_vantage_metrics_negative_total_value_gives_negative_multiple():
    # Interest exceeds CFO -> Cashflow/InterestServiceable/Loan all negative;
    # Loan swamps Cash -> Total Value negative -> Multiple negative (not masked).
    universe = _vantage_universe(cfo=10.0, interest=100.0, cash=50.0, market_cap=1000.0)

    result = vantage_metrics(universe, decay=0.85, rate=0.10)

    assert result.loc[0, "Cashflow (Cr)"] == -90.0
    assert result.loc[0, "Total Value (Cr)"] == pytest.approx(-250.0)
    assert result.loc[0, "Multiple"] == pytest.approx(-4.0)
    assert scalar_metric_passes(result["Multiple"], 0.0, "higher").iloc[0] is False


# --- company_vantage_metrics ---------------------------------------------------------

def test_company_vantage_metrics_matches_hand_computed_values():
    years = [str(y) for y in range(26, 16, -1)]
    is_table = make_table({"Int": [50.0] * 10}, columns=years)
    bs_table = make_table({"CFO": [500.0] * 10, "Cash": [200.0] * 10, "NOS": [10_000_000.0] * 10}, columns=years)

    result = company_vantage_metrics(is_table, bs_table, price=850.0, decay=0.85, rate=0.10)

    assert result["wa_cfo"] == 500.0
    assert result["wa_interest"] == 50.0
    assert result["cashflow"] == 450.0
    assert result["interest_serviceable"] == 150.0
    assert result["loan"] == 1500.0
    assert result["cash"] == 200.0
    assert result["total_value"] == 1700.0
    assert result["value_per_share"] == pytest.approx(1700.0)  # 1 crore shares -> Cr value == per-share value
    assert result["multiple"] == pytest.approx(0.5)  # 850/1700


# --- magic_formula_ranking -----------------------------------------------------------

def _magic_formula_universe(companies: dict) -> pd.DataFrame:
    """companies: {Symbol: {"market_cap":, "total_liab_ex_equity":, "pbit":, "roc":}}."""
    rows = []
    for symbol, c in companies.items():
        rows.append({
            "Symbol": symbol,
            "Industry": "Ind X",
            "Market Cap (Cr)": c["market_cap"],
            "TotalLiabExEquity Latest (Cr)": c["total_liab_ex_equity"],
            "PBIT Latest (Cr)": c["pbit"],
            "MagicROC Latest (%)": c["roc"],
        })
    return pd.DataFrame(rows)


def test_magic_formula_ranking_matches_hand_computed_ranks():
    # EV all = 1000 for A/C (TotalLiabExEquity 0/500), 2000 for B.
    universe = _magic_formula_universe({
        "A": {"market_cap": 1000.0, "total_liab_ex_equity": 0.0, "pbit": 200.0, "roc": 50.0},   # EY=20%, ROC=50%
        "B": {"market_cap": 2000.0, "total_liab_ex_equity": 0.0, "pbit": 200.0, "roc": 40.0},   # EY=10%, ROC=40%
        "C": {"market_cap": 500.0, "total_liab_ex_equity": 500.0, "pbit": 150.0, "roc": 30.0},  # EY=15%, ROC=30%
    })

    result = magic_formula_ranking(universe, "MagicROC Latest (%)", min_market_cap=0.0)
    by_symbol = result.set_index("Symbol")

    assert by_symbol.loc["A", "Earnings Yield (%)"] == 20.0
    assert by_symbol.loc["B", "Earnings Yield (%)"] == 10.0
    assert by_symbol.loc["C", "Earnings Yield (%)"] == 15.0

    # EY ranks (desc): A=1, C=2, B=3. ROC ranks (desc): A=1, B=2, C=3.
    assert by_symbol.loc["A", "Total Rank"] == 2.0  # 1+1
    assert by_symbol.loc["B", "Total Rank"] == 5.0  # 3+2
    assert by_symbol.loc["C", "Total Rank"] == 5.0  # 2+3

    assert by_symbol.loc["A", "Magic Rank"] == 1.0
    assert by_symbol.loc["B", "Magic Rank"] == 2.0  # tied with C, method="min"
    assert by_symbol.loc["C", "Magic Rank"] == 2.0


def test_magic_formula_ranking_market_cap_floor_excludes_company():
    universe = _magic_formula_universe({
        "BIG": {"market_cap": 1000.0, "total_liab_ex_equity": 0.0, "pbit": 100.0, "roc": 20.0},
        "TINY": {"market_cap": 50.0, "total_liab_ex_equity": 0.0, "pbit": 10.0, "roc": 20.0},
    })

    result = magic_formula_ranking(universe, "MagicROC Latest (%)", min_market_cap=100.0)

    assert list(result["Symbol"]) == ["BIG"]
    assert result.set_index("Symbol").loc["BIG", "Magic Rank"] == 1.0


def test_magic_formula_ranking_missing_roc_excludes_company_only():
    universe = _magic_formula_universe({
        "OK": {"market_cap": 1000.0, "total_liab_ex_equity": 0.0, "pbit": 100.0, "roc": 20.0},
        "NODATA": {"market_cap": 1000.0, "total_liab_ex_equity": 0.0, "pbit": 100.0, "roc": float("nan")},
    })

    result = magic_formula_ranking(universe, "MagicROC Latest (%)", min_market_cap=0.0)

    assert list(result["Symbol"]) == ["OK"]
    assert result.set_index("Symbol").loc["OK", "Magic Rank"] == 1.0


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


# --- and_tri_state ---------------------------------------------------------------

def test_and_tri_state_all_combinations():
    a = pd.Series([True, True, pd.NA, pd.NA, False], dtype=object)
    b = pd.Series([True, False, True, pd.NA, pd.NA], dtype=object)

    result = and_tri_state(a, b)

    assert result.iloc[0] is True          # True AND True -> True
    assert result.iloc[1] is False         # True AND False -> False
    assert pd.isna(result.iloc[2])         # NA AND True -> NA
    assert pd.isna(result.iloc[3])         # NA AND NA -> NA
    assert result.iloc[4] is False         # False AND NA -> False (False dominates)


# --- failure_detail --------------------------------------------------------------

def test_failure_detail_all_years_lists_failing_years():
    values = pd.Series([25.0, 25.0, 10.0, 25.0, 25.0, 25.0, 8.0, 25.0, 25.0, 25.0])

    result = failure_detail(values, threshold=20.0, direction="higher", consistency="all_years")

    assert result == "fails in 2/10 year(s): Y3 (10.00%), Y7 (8.00%)"


def test_failure_detail_median():
    values = pd.Series([10.0, 20.0, 30.0])

    result = failure_detail(values, threshold=25.0, direction="higher", consistency="median")

    assert result == "median 20.00% vs threshold 25.00%"


# --- evaluate_screens_for_company --------------------------------------------------

# Constant-per-year values comfortably on the "passing" side of every screen's default
# threshold, so a company built from these alone passes everything; tests override just
# the row(s) they care about.
_COMFORTABLE_PASS_VALUES = {
    "OPM": 50.0, "NPM": 30.0, "LowDebt": 5.0, "LowCapex": 3.0, "CapexNI": 10.0,
    "LiabEquity": 40.0, "ROE": 25.0, "ROCE": 30.0, "ROCEExCash": 35.0, "RevGrowth": 20.0,
}


def make_universe_df(companies: list[dict]) -> pd.DataFrame:
    """Build a synthetic universe-cache-shaped DataFrame. Each company dict needs
    "Symbol"/"Industry", optionally "ssgr_pct"/"rev_cagr"/"ssgr_passes"/
    "net_cagr"/"debt_equity"/"cfo"/"market_cap"/"ncav"/"ncav_cash_inv_rec"/
    "cash_latest"/"vantage_cfo"/"vantage_int" (the last two as 10-value lists)/
    "pbit"/"total_liab_ex_equity"/"magic_roc"/"magic_roc_ex_cash"/
    "tax_payout_ratio"/"interest_coverage"/"current_ratio", and optionally
    a list of 10 values for any key in _COMFORTABLE_PASS_VALUES to override that
    row (everything else defaults to a flat comfortable-pass value).
    """
    records = []
    for company in companies:
        record = {
            "Symbol": company["Symbol"],
            "Industry": company["Industry"],
            "SSGR (%)": company.get("ssgr_pct", 50.0),
            "Rev 10Y CAGR (%)": company.get("rev_cagr", 20.0),  # >15 (Vijay Malik) and <50 (SSGR default)
            "SSGR Passes": company.get("ssgr_passes", True),
            "Net 10Y CAGR (%)": company.get("net_cagr", 40.0),
            "DebtEquity Latest (%)": company.get("debt_equity", 40.0),
            "CFO Latest (Cr)": company.get("cfo", 50.0),
            "Market Cap (Cr)": company.get("market_cap", 1000.0),
            "NCAV Latest (Cr)": company.get("ncav", 2000.0),  # > Market Cap default (1000.0), so Net-Net passes
            "NCAVCashInvRec Latest (Cr)": company.get("ncav_cash_inv_rec", 2000.0),
            # Flat CFO=500/Int=50/Cash=200 -> Cashflow=450, InterestServiceable=150,
            # Loan=1500 (at the default 10% rate), TotalValue=1700 -> Multiple ~0.59
            # (comfortably inside the default 0..1 Vantage pass range vs. Market Cap 1000.0).
            "Cash Latest (Cr)": company.get("cash_latest", 200.0),
            # Magic Formula: PBIT=200, TotalLiabExEquity=300 -> EV=1300, EY~15.38%;
            # MagicROC/ExCash are just non-NaN placeholders — with only one company
            # in these fixtures it's always rank #1 as long as it's not excluded.
            "PBIT Latest (Cr)": company.get("pbit", 200.0),
            "TotalLiabExEquity Latest (Cr)": company.get("total_liab_ex_equity", 300.0),
            "MagicROC Latest (%)": company.get("magic_roc", 25.0),
            "MagicROCExCash Latest (%)": company.get("magic_roc_ex_cash", 30.0),
            # Vijay Malik Pro's 3 new scalar checks: comfortably inside their default bars
            # (Tax Payout 20-35%, Interest Coverage >3x, Current Ratio >1.25x).
            "TaxPayoutRatio Latest (%)": company.get("tax_payout_ratio", 27.0),
            "InterestCoverage Latest (x)": company.get("interest_coverage", 5.0),
            "CurrentRatio Latest (x)": company.get("current_ratio", 1.5),
        }
        vantage_cfo = company.get("vantage_cfo", [500.0] * 10)
        vantage_int = company.get("vantage_int", [50.0] * 10)
        for y in range(1, 11):
            record[f"CFO Y{y} (Cr)"] = vantage_cfo[y - 1]
            record[f"Int Y{y} (Cr)"] = vantage_int[y - 1]
        for row, default_val in _COMFORTABLE_PASS_VALUES.items():
            values = company.get(row, [default_val] * 10)
            for y in range(1, 11):
                record[f"{row} Y{y} (%)"] = values[y - 1]
        records.append(record)
    return pd.DataFrame(records)


def _default_overrides() -> dict:
    overrides = {key: {"use_industry": True, "manual": cfg["default"]} for key, cfg in MOAT_METRIC_CONFIG.items()}
    overrides["ccp"] = {"roce": 15, "growth": 10, "years": 10}
    overrides["vijay_malik"] = {"sales_cagr": 15, "net_cagr": 30, "debt_equity": 100, "cfo": 0, "market_cap": 500}
    overrides["vijay_malik_pro"] = {
        "sales_cagr": 15, "npm": 8, "net_cagr": 30, "debt_equity": 50, "cfo": 0, "market_cap": 25,
        "tax_payout_min": 20, "tax_payout_max": 35, "interest_coverage": 3, "current_ratio": 1.25,
    }
    overrides["net_net"] = {"min_mcap": 0.0}
    overrides["vantage"] = {"decay": 0.85, "rate": 0.10, "min_threshold": 0.0, "max_threshold": 1.0}
    overrides["magic_formula"] = {"min_market_cap": 0.0}
    return overrides


def test_evaluate_screens_for_company_all_pass():
    # Alone in its "industry" (well below min_companies=5), so every industry
    # threshold falls back to each screen's flat default -> deterministic.
    universe = make_universe_df([{"Symbol": "PASSER", "Industry": "Ind X"}])

    result = evaluate_screens_for_company(universe, "PASSER", _default_overrides())

    assert len(result) == 29  # SSGR + 7 moats + 4 nalanda + 2 ccp + vijay malik + 9 vm pro + 2 net-net + vantage + 2 magic formula
    assert (result["Passes"] == True).all()  # noqa: E712
    assert (result["Detail"] == "—").all()


def test_evaluate_screens_for_company_reports_failing_years():
    universe = make_universe_df([
        {"Symbol": "PASSER", "Industry": "Ind X"},
        {"Symbol": "FAILER", "Industry": "Ind X",
         "OPM": [50.0, 50.0, 10.0, 50.0, 50.0, 50.0, 8.0, 50.0, 50.0, 50.0]},
    ])

    result = evaluate_screens_for_company(universe, "FAILER", _default_overrides())

    opm_row = result[result["Filter"] == "Operating Margin"].iloc[0]
    assert opm_row["Passes"] == False  # noqa: E712 (a homogeneous True/False column may be bool dtype, not object)
    assert opm_row["Detail"] == "fails in 2/10 year(s): Y3 (10.00%), Y7 (8.00%)"


def test_evaluate_screens_for_company_missing_year_is_not_enough_history():
    universe = make_universe_df([
        {"Symbol": "MISSING", "Industry": "Ind X",
         "OPM": [50.0, 50.0, 50.0, 50.0, 50.0, 50.0, 50.0, 50.0, 50.0, float("nan")]},
    ])

    result = evaluate_screens_for_company(universe, "MISSING", _default_overrides())

    opm_row = result[result["Filter"] == "Operating Margin"].iloc[0]
    assert pd.isna(opm_row["Passes"])
    assert opm_row["Detail"] == "not enough history"


def test_evaluate_screens_for_company_ccp_names_the_failing_sub_check():
    universe = make_universe_df([
        {"Symbol": "GROWTHFAIL", "Industry": "Ind X",
         "RevGrowth": [20.0, 20.0, 5.0, 20.0, 20.0, 20.0, 3.0, 20.0, 20.0, 20.0]},
    ])

    result = evaluate_screens_for_company(universe, "GROWTHFAIL", _default_overrides())

    ccp_row = result[result["Filter"] == "CCP – Regular ROCE"].iloc[0]
    assert ccp_row["Passes"] == False  # noqa: E712 (a homogeneous True/False column may be bool dtype, not object)
    assert "Revenue growth" in ccp_row["Detail"]
    assert "ROCE" not in ccp_row["Detail"]


def test_evaluate_screens_for_company_vijay_malik_names_the_failing_check():
    universe = make_universe_df([
        {"Symbol": "LEVERED", "Industry": "Ind X", "debt_equity": 150.0},
    ])

    result = evaluate_screens_for_company(universe, "LEVERED", _default_overrides())

    vm_row = result[result["Filter"] == "Vijay Malik"].iloc[0]
    assert vm_row["Passes"] == False  # noqa: E712 (a homogeneous True/False column may be bool dtype, not object)
    assert "Debt/Equity" in vm_row["Detail"]
    assert "Sales CAGR" not in vm_row["Detail"]


def test_evaluate_screens_for_company_vijay_malik_missing_data_is_not_enough():
    universe = make_universe_df([
        {"Symbol": "NODATA", "Industry": "Ind X", "cfo": float("nan")},
    ])

    result = evaluate_screens_for_company(universe, "NODATA", _default_overrides())

    vm_row = result[result["Filter"] == "Vijay Malik"].iloc[0]
    assert pd.isna(vm_row["Passes"])
    assert vm_row["Detail"] == "not enough data"


def test_evaluate_screens_for_company_vijay_malik_pro_has_9_independent_rows():
    universe = make_universe_df([
        {"Symbol": "MOSTLY_GOOD", "Industry": "Ind X", "market_cap": 5.0},
    ])

    result = evaluate_screens_for_company(universe, "MOSTLY_GOOD", _default_overrides())
    vmp_rows = result[result["Group"] == "Vijay Malik Pro"]

    assert len(vmp_rows) == 9
    mcap_row = vmp_rows[vmp_rows["Filter"] == "Market Cap"].iloc[0]
    assert mcap_row["Passes"] == False  # noqa: E712 (a homogeneous True/False column may be bool dtype, not object)
    assert "Market Cap" in mcap_row["Detail"]
    # Every other check should still pass — a scalar failure doesn't cascade
    # into the other 8 checks, unlike the AND-based Vijay Malik screen.
    other_rows = vmp_rows[vmp_rows["Filter"] != "Market Cap"]
    assert (other_rows["Passes"] == True).all()  # noqa: E712


def test_evaluate_screens_for_company_vijay_malik_pro_range_check_names_the_bound():
    universe = make_universe_df([
        {"Symbol": "LOWTAX", "Industry": "Ind X", "tax_payout_ratio": 5.0},
    ])

    result = evaluate_screens_for_company(universe, "LOWTAX", _default_overrides())

    tax_row = result[result["Filter"] == "Tax Payout Ratio"].iloc[0]
    assert tax_row["Passes"] == False  # noqa: E712 (a homogeneous True/False column may be bool dtype, not object)
    assert "not above" in tax_row["Detail"]


def test_evaluate_screens_for_company_vijay_malik_pro_consistency_check_reports_failing_years():
    universe = make_universe_df([
        {"Symbol": "BADYEAR", "Industry": "Ind X",
         "NPM": [30.0, 30.0, 30.0, 2.0, 30.0, 30.0, 30.0, 30.0, 30.0, 30.0]},
    ])

    result = evaluate_screens_for_company(universe, "BADYEAR", _default_overrides())

    npm_row = result[result["Filter"] == "NPM (every year)"].iloc[0]
    assert npm_row["Passes"] == False  # noqa: E712 (a homogeneous True/False column may be bool dtype, not object)
    assert "fails in 1/10 year(s)" in npm_row["Detail"]


def test_evaluate_screens_for_company_net_net_fails_when_mcap_above_ncav():
    universe = make_universe_df([
        {"Symbol": "PRICEY", "Industry": "Ind X", "market_cap": 3000.0, "ncav": 2000.0, "ncav_cash_inv_rec": 2500.0},
    ])

    result = evaluate_screens_for_company(universe, "PRICEY", _default_overrides())

    full_row = result[result["Filter"] == "Net-Net – Full Current Assets"].iloc[0]
    assert full_row["Passes"] == False  # noqa: E712 (a homogeneous True/False column may be bool dtype, not object)
    assert "3000.00" in full_row["Detail"]
    assert "2000.00" in full_row["Detail"]

    quick_row = result[result["Filter"] == "Net-Net – Cash+Inv+Rec"].iloc[0]
    assert quick_row["Passes"] == False  # noqa: E712
    assert "2500.00" in quick_row["Detail"]


def test_evaluate_screens_for_company_net_net_market_cap_floor():
    # Clears Mcap < NCAV comfortably, but Market Cap is below the configured floor.
    universe = make_universe_df([{"Symbol": "TOOSMALL", "Industry": "Ind X"}])
    overrides = _default_overrides()
    overrides["net_net"] = {"min_mcap": 5000.0}  # default Market Cap (1000.0) is below this

    result = evaluate_screens_for_company(universe, "TOOSMALL", overrides)

    full_row = result[result["Filter"] == "Net-Net – Full Current Assets"].iloc[0]
    assert full_row["Passes"] == False  # noqa: E712
    assert "floor" in full_row["Detail"]
    assert "5000.00" in full_row["Detail"]


def test_evaluate_screens_for_company_vantage_fails_when_multiple_too_high():
    # Comfortable-pass Vantage inputs (CFO=500/Int=50/Cash=200 -> Total Value 1700)
    # but a Market Cap well above Total Value -> Multiple > 1.
    universe = make_universe_df([{"Symbol": "PRICEY", "Industry": "Ind X", "market_cap": 3000.0}])

    result = evaluate_screens_for_company(universe, "PRICEY", _default_overrides())

    vantage_row = result[result["Filter"] == "Vantage"].iloc[0]
    assert vantage_row["Passes"] == False  # noqa: E712
    assert "not below 1.00" in vantage_row["Detail"]


def test_evaluate_screens_for_company_vantage_fails_when_loan_swamps_cash():
    # Interest far exceeds CFO -> Cashflow/Loan negative -> Total Value negative
    # -> Multiple negative -> fails the "> 0" lower bound specifically.
    universe = make_universe_df([
        {"Symbol": "DISTRESSED", "Industry": "Ind X", "vantage_int": [1000.0] * 10},
    ])

    result = evaluate_screens_for_company(universe, "DISTRESSED", _default_overrides())

    vantage_row = result[result["Filter"] == "Vantage"].iloc[0]
    assert vantage_row["Passes"] == False  # noqa: E712
    assert "Loan swamps Cash" in vantage_row["Detail"]


def test_evaluate_screens_for_company_vantage_missing_year_is_not_enough_data():
    universe = make_universe_df([
        {"Symbol": "MISSING", "Industry": "Ind X", "vantage_cfo": [500.0] * 9 + [float("nan")]},
    ])

    result = evaluate_screens_for_company(universe, "MISSING", _default_overrides())

    vantage_row = result[result["Filter"] == "Vantage"].iloc[0]
    assert pd.isna(vantage_row["Passes"])
    assert vantage_row["Detail"] == "not enough data"


def test_evaluate_screens_for_company_magic_formula_outside_top_10():
    # 10 companies with a strong, identical PBIT (so they all out-rank the 11th
    # on Earnings Yield) plus one much weaker company that should rank last.
    companies = [{"Symbol": f"C{i}", "Industry": "Ind X", "pbit": 1000.0} for i in range(1, 11)]
    companies.append({"Symbol": "WORST", "Industry": "Ind X", "pbit": 1.0})
    universe = make_universe_df(companies)

    result = evaluate_screens_for_company(universe, "WORST", _default_overrides())

    row = result[result["Filter"] == "Magic Formula – Plain WC"].iloc[0]
    assert row["Passes"] == False  # noqa: E712 (a homogeneous True/False column may be bool dtype, not object)
    assert "outside the top 10" in row["Detail"]
    assert "#11" in row["Detail"]


def test_evaluate_screens_for_company_magic_formula_market_cap_floor():
    universe = make_universe_df([{"Symbol": "TOOSMALL", "Industry": "Ind X", "market_cap": 50.0}])
    overrides = _default_overrides()
    overrides["magic_formula"] = {"min_market_cap": 100.0}

    result = evaluate_screens_for_company(universe, "TOOSMALL", overrides)

    row = result[result["Filter"] == "Magic Formula – Plain WC"].iloc[0]
    assert pd.isna(row["Passes"])
    assert "floor" in row["Detail"]
    assert "100.00" in row["Detail"]


def test_evaluate_screens_for_company_symbol_not_in_universe():
    universe = make_universe_df([{"Symbol": "PASSER", "Industry": "Ind X"}])

    result = evaluate_screens_for_company(universe, "NOT_THERE", _default_overrides())

    assert len(result) == 29
    assert result["Passes"].isna().all()
    assert (result["Detail"] == "not in Screens cache — click Refresh on the Screens page").all()


# --- macro_trend_frame ---------------------------------------------------------

def test_macro_trend_frame_orders_chronologically():
    table = pd.DataFrame({"IIP": [130.0, 125.0, 120.0]}, index=["26-03", "26-02", "26-01"])

    result = macro_trend_frame(table, ["IIP"])

    assert list(result.index) == ["26-01", "26-02", "26-03"]
    assert result.loc["26-01", "IIP"] == 120.0
    assert result.loc["26-02", "IIP"] == 125.0
    assert result.loc["26-03", "IIP"] == 130.0


def test_macro_trend_frame_missing_column_is_all_nan():
    table = pd.DataFrame({"IIP": [130.0, 125.0]}, index=["26-02", "26-01"])

    result = macro_trend_frame(table, ["IIP", "GDP"])

    assert list(result.columns) == ["IIP", "GDP"]
    assert result["GDP"].isna().all()


# --- macro_latest_snapshot -------------------------------------------------------

def test_macro_latest_snapshot_matches_hand_computed_values():
    table = pd.DataFrame({"FX reserves - USD Bn": [640.0, 620.0, 600.0]}, index=["26-03", "26-02", "26-01"])

    result = macro_latest_snapshot(table)
    row = result[result["Parameter"] == "FX reserves - USD Bn"].iloc[0]

    assert row["Latest Date"] == "26-03"
    assert row["Latest Value"] == 640.0
    assert row["Prior Date"] == "26-02"
    assert row["Prior Value"] == 620.0
    assert row["Change"] == 20.0
    assert row["Change (%)"] == pytest.approx(20 / 620 * 100, abs=0.01)


def test_macro_latest_snapshot_falls_back_past_nan_latest_column():
    # GDP-style: most-recent column is NaN (quarterly data lagging a monthly sheet).
    table = pd.DataFrame({"GDP": [float("nan"), 0.078, 0.075]}, index=["26-03", "26-02", "26-01"])

    result = macro_latest_snapshot(table)
    row = result[result["Parameter"] == "GDP"].iloc[0]

    assert row["Latest Date"] == "26-02"
    assert row["Latest Value"] == 0.078
    assert row["Prior Date"] == "26-01"
    assert row["Prior Value"] == 0.075


def test_macro_latest_snapshot_fewer_than_two_readings_is_nan():
    table = pd.DataFrame({"Manufacturing PMI": [55.0, float("nan"), float("nan")]}, index=["26-03", "26-02", "26-01"])

    result = macro_latest_snapshot(table)
    row = result[result["Parameter"] == "Manufacturing PMI"].iloc[0]

    assert row["Latest Value"] == 55.0
    assert pd.isna(row["Prior Value"])
    assert pd.isna(row["Change"])
    assert pd.isna(row["Change (%)"])


def test_macro_latest_snapshot_all_nan_parameter():
    table = pd.DataFrame({"Services PMI": [float("nan"), float("nan")]}, index=["26-02", "26-01"])

    result = macro_latest_snapshot(table)
    row = result[result["Parameter"] == "Services PMI"].iloc[0]

    assert pd.isna(row["Latest Value"])
    assert pd.isna(row["Latest Date"])
    assert pd.isna(row["Prior Value"])


def test_macro_latest_snapshot_zero_prior_value_change_pct_is_nan():
    table = pd.DataFrame({"CPI": [10.0, 0.0]}, index=["26-02", "26-01"])

    result = macro_latest_snapshot(table)
    row = result[result["Parameter"] == "CPI"].iloc[0]

    assert row["Change"] == 10.0
    assert pd.isna(row["Change (%)"])


# --- cpi_basket_ranking ----------------------------------------------------------

def test_cpi_basket_ranking_orders_by_cumulative_pct_change_descending():
    table = pd.DataFrame({
        "Food and beverages": [112.0, 108.0, 100.0],  # +12% earliest(100)->latest(112)
        "Health": [103.0, 101.0, 100.0],               # +3%
        "Transport": [95.0, 98.0, 100.0],              # -5%
    }, index=["26-03", "26-02", "26-01"])

    result = cpi_basket_ranking(table)
    ranked = result[result["Change (%)"].notna()]

    assert list(ranked["Category"]) == ["Food and beverages", "Health", "Transport"]
    assert ranked.iloc[0]["Change (%)"] == pytest.approx(12.0)
    assert ranked.iloc[1]["Change (%)"] == pytest.approx(3.0)
    assert ranked.iloc[2]["Change (%)"] == pytest.approx(-5.0)
    assert ranked.iloc[0]["Earliest Date"] == "26-01"
    assert ranked.iloc[0]["Latest Date"] == "26-03"


def test_cpi_basket_ranking_missing_category_is_nan_and_sorted_last():
    table = pd.DataFrame({"Food and beverages": [112.0, 100.0]}, index=["26-02", "26-01"])
    # every other CPI_BASKET_CATEGORIES entry is absent from `table`

    result = cpi_basket_ranking(table)

    assert result.iloc[0]["Category"] == "Food and beverages"
    assert result.iloc[0]["Change (%)"] == pytest.approx(12.0)
    assert result["Change (%)"].iloc[1:].isna().all()
    assert set(result["Category"]) == set(CPI_BASKET_CATEGORIES)
    assert len(result) == len(CPI_BASKET_CATEGORIES)


def test_cpi_basket_ranking_single_reading_is_nan():
    table = pd.DataFrame({"Health": [100.0]}, index=["26-01"])

    result = cpi_basket_ranking(table)
    row = result[result["Category"] == "Health"].iloc[0]

    assert pd.isna(row["Change (%)"])
    assert row["Latest Value"] == 100.0
    assert pd.isna(row["Earliest Value"])


# --- pmi_status --------------------------------------------------------------------

def test_pmi_status_expansion():
    assert pmi_status(54.3) == "Expansion"


def test_pmi_status_contraction():
    assert pmi_status(47.8) == "Contraction"


def test_pmi_status_no_change():
    assert pmi_status(50.0) == "No Change"


def test_pmi_status_nan():
    assert pmi_status(float("nan")) == "—"
