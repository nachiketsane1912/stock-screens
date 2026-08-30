"""Loading and reshaping for Raw data.xlsx.

No Streamlit UI logic here (aside from the @st.cache_data decorator on load_raw) —
this module is about getting the raw workbook into clean, usable pandas structures.
"""

import os
import re

import pandas as pd
import streamlit as st

RAW_FILE = "Raw data.xlsx"
UNIVERSE_CACHE_FILE = "universe_cache.csv"

WIDE_SHEETS = ("Quarter", "IS", "BS")
COL_RE = re.compile(r"^([A-Za-z]+)-(.+)$")
YEAR_RE = re.compile(r"(\d{2})$")

# Net Profit ("Net") is reported in crores; NOS (BS) is an absolute share
# count. 1 crore = 1e7, so this converts crores to rupees for EPS.
CRORE = 10_000_000

# The screens on the Screens page (Moats tab and Nalanda's F tab): each entry is
# one screen. "row" is the underlying IS row the screen reads (several screens
# can share a row, e.g. ROCE's Median and 10Y variants); "direction" controls
# both the industry-percentile pick (75th for higher-is-better, 25th for
# lower-is-better) and the pass/fail comparison (> vs <); "consistency" is
# "all_years" (every one of the last 10 years must clear the bar) or "median"
# (the median of the last 10 years must clear it); "group" is which tab it's on.
MOAT_METRIC_CONFIG = {
    "OPM": {"row": "OPM", "label": "Operating Margin", "default": 40.0, "direction": "higher", "percentile": 0.75, "consistency": "all_years", "group": "moats"},
    "NPM": {"row": "NPM", "label": "Net Margin", "default": 20.0, "direction": "higher", "percentile": 0.75, "consistency": "all_years", "group": "moats"},
    "LowDebt": {"row": "LowDebt", "label": "Interest / Operating Profit", "default": 15.0, "direction": "lower", "percentile": 0.25, "consistency": "all_years", "group": "moats"},
    "LowCapex": {"row": "LowCapex", "label": "Capex / Revenue", "default": 10.0, "direction": "lower", "percentile": 0.25, "consistency": "all_years", "group": "moats"},
    "CapexNI": {"row": "CapexNI", "label": "Capex / Net Income", "default": 25.0, "direction": "lower", "percentile": 0.25, "consistency": "all_years", "group": "moats"},
    "LiabEquity": {"row": "LiabEquity", "label": "Liabilities / Equity", "default": 80.0, "direction": "lower", "percentile": 0.25, "consistency": "all_years", "group": "moats"},
    "ROE": {"row": "ROE", "label": "Net Income / Equity (ROE)", "default": 15.0, "direction": "higher", "percentile": 0.75, "consistency": "all_years", "group": "moats"},
    "ROCEMedian": {"row": "ROCE", "label": "ROCE (Median)", "default": 20.0, "direction": "higher", "percentile": 0.75, "consistency": "median", "group": "nalanda"},
    "ROCEAllYears": {"row": "ROCE", "label": "ROCE (10Y)", "default": 20.0, "direction": "higher", "percentile": 0.75, "consistency": "all_years", "group": "nalanda"},
    "NalandaFMedian": {"row": "ROCEExCash", "label": "Nalanda's F (Median)", "default": 20.0, "direction": "higher", "percentile": 0.75, "consistency": "median", "group": "nalanda"},
    "NalandaFAllYears": {"row": "ROCEExCash", "label": "Nalanda's F (10Y)", "default": 20.0, "direction": "higher", "percentile": 0.75, "consistency": "all_years", "group": "nalanda"},
}


@st.cache_data
def load_raw(path: str = RAW_FILE) -> dict[str, pd.DataFrame]:
    """Read every sheet from the workbook into a dict of DataFrames.

    Raises a RuntimeError with a friendly message if the file is missing or
    locked (e.g. still open in Excel), instead of letting the raw
    PermissionError/FileNotFoundError surface.
    """
    try:
        sheets = pd.read_excel(path, sheet_name=None)
    except PermissionError as exc:
        raise RuntimeError(
            f"Can't read '{path}' — it looks like it's open in Excel. "
            "Close it there and reload this page."
        ) from exc
    except FileNotFoundError as exc:
        raise RuntimeError(f"Can't find '{path}'. Check the file is in this folder.") from exc

    for name, df in sheets.items():
        sheets[name] = df.replace("NA", pd.NA)

    return sheets


def parse_metric_periods(columns) -> dict[str, list[tuple[str, str]]]:
    """Group data column names (all but the leading Symbol column) by metric.

    Returns {metric: [(period, original_column_name), ...]} preserving the
    order periods appear in the sheet (which is most-recent-first).
    """
    blocks: dict[str, list[tuple[str, str]]] = {}
    for col in columns:
        m = COL_RE.match(str(col))
        if not m:
            continue
        metric, period = m.group(1), m.group(2)
        blocks.setdefault(metric, []).append((period, col))
    return blocks


def company_metric_table(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Pivot one wide sheet (Quarter/IS/BS) for a single symbol into a
    metric-by-period table (rows = metric, columns = period, most-recent
    period first).
    """
    row = df.loc[df["Symbol"] == symbol]
    if row.empty:
        return pd.DataFrame()
    row = row.iloc[0]

    blocks = parse_metric_periods(df.columns[1:])

    # Union of periods across metrics, in first-seen (chronological, newest-first) order.
    period_order: list[str] = []
    for periods in blocks.values():
        for period, _ in periods:
            if period not in period_order:
                period_order.append(period)

    table = pd.DataFrame(index=list(blocks.keys()), columns=period_order, dtype=object)
    for metric, periods in blocks.items():
        for period, col in periods:
            table.loc[metric, period] = row[col]

    return table


def _year_of(period: str) -> str:
    """Fiscal year suffix of a period label ('26' for IS/BS, 'Q127' for Quarter)."""
    m = YEAR_RE.search(period)
    return m.group(1) if m else period


def _shares_by_year(bs_df: pd.DataFrame, symbol: str) -> dict[str, float]:
    """Map fiscal year -> NOS (number of shares) for one symbol, from the BS sheet."""
    row = bs_df.loc[bs_df["Symbol"] == symbol]
    if row.empty:
        return {}
    row = row.iloc[0]
    return {
        col.split("-", 1)[1]: row[col]
        for col in bs_df.columns
        if col.startswith("NOS-") and pd.notna(row[col])
    }


def _shares_for_period(shares_by_year: dict[str, float], period: str) -> float:
    """NOS for a period's fiscal year, falling back to the nearest year with data
    (BS's most recent NOS lags the latest quarter/year in Quarter/IS).
    """
    year = _year_of(period)
    if year in shares_by_year:
        return shares_by_year[year]
    if not shares_by_year:
        return float("nan")
    earlier = [y for y in shares_by_year if y <= year]
    closest = max(earlier) if earlier else min(shares_by_year)
    return shares_by_year[closest]


def _numeric_row(table: pd.DataFrame, name: str) -> pd.Series:
    """Numeric version of one row of a metric table, or all-NA if the metric is absent."""
    if name not in table.index:
        return pd.Series(float("nan"), index=table.columns, dtype="float64")
    return pd.to_numeric(table.loc[name], errors="coerce")


def add_derived_metrics(table: pd.DataFrame, shares_by_year: dict[str, float]) -> pd.DataFrame:
    """Add OP, OPM, PBIT, PBT, NPM and EPS rows to an IS/Quarter metric table.

    OP = Rev - Exp
    PBIT = OP + OI - Dep   (Int is treated as a financing cost, added back for PBIT)
    PBT = PBIT - Int
    EPS = Net (in crores, converted to rupees) / NOS for that period's fiscal year
    """
    if table.empty:
        return table

    rev, exp, oi, interest, dep, net = (
        _numeric_row(table, "Rev"), _numeric_row(table, "Exp"), _numeric_row(table, "OI"),
        _numeric_row(table, "Int"), _numeric_row(table, "Dep"), _numeric_row(table, "Net"),
    )

    op = rev - exp
    pbit = op + oi - dep
    pbt = pbit - interest
    opm = (op / rev * 100).replace([float("inf"), float("-inf")], float("nan")).round(2)
    npm = (net / rev * 100).replace([float("inf"), float("-inf")], float("nan")).round(2)

    shares = pd.Series(
        [_shares_for_period(shares_by_year, period) for period in table.columns],
        index=table.columns,
        dtype="float64",
    )
    eps = (net * CRORE / shares).replace([float("inf"), float("-inf")], float("nan")).round(2)

    table.loc["OP"] = op
    table.loc["OPM"] = opm
    table.loc["PBIT"] = pbit
    table.loc["PBT"] = pbt
    table.loc["NPM"] = npm
    table.loc["EPS"] = eps

    return table


def add_ttm_column(is_table: pd.DataFrame, quarterly_table: pd.DataFrame) -> pd.DataFrame:
    """Insert a TTM (trailing twelve months) column into an IS metric table, built
    from the 4 most-recent quarters of `quarterly_table` (already run through
    add_derived_metrics, most-recent quarter first).

    Flow metrics are summed over the 4 quarters; OPM/NPM are recomputed from the
    summed OP/Net over summed Rev (not averaged); EPS is the sum of the 4
    quarterly EPS values. `Div` has no quarterly source and is left blank.
    """
    if is_table.empty or quarterly_table.shape[1] < 4:
        return is_table

    last4 = quarterly_table.iloc[:, :4]
    flow_metrics = ("Rev", "Exp", "OI", "Int", "Dep", "Net", "OP", "PBIT", "PBT")

    ttm = {
        metric: pd.to_numeric(last4.loc[metric], errors="coerce").sum(min_count=4)
        for metric in flow_metrics
        if metric in last4.index
    }

    def safe_margin(numerator, denominator):
        if pd.isna(numerator) or pd.isna(denominator) or denominator == 0:
            return float("nan")
        return round(numerator / denominator * 100, 2)

    ttm["OPM"] = safe_margin(ttm.get("OP"), ttm.get("Rev"))
    ttm["NPM"] = safe_margin(ttm.get("Net"), ttm.get("Rev"))

    if "EPS" in last4.index:
        eps_ttm = pd.to_numeric(last4.loc["EPS"], errors="coerce").sum(min_count=4)
        ttm["EPS"] = round(eps_ttm, 2) if pd.notna(eps_ttm) else float("nan")

    is_table.insert(0, "TTM", pd.Series(ttm, index=is_table.index, dtype="float64"))
    return is_table


def _safe_divide(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    """Elementwise numerator/denominator, NaN where the denominator is NaN or 0.

    Negative denominators pass through unchanged — unlike CAGR's root operation,
    a plain ratio with a negative denominator is still mathematically meaningful.
    """
    result = numerator / denominator
    return result.mask(denominator.isna() | (denominator == 0))


def add_ssgr(is_table: pd.DataFrame, bs_table: pd.DataFrame) -> pd.DataFrame:
    """Add NFAT, DPR, DepNFA and SSGR rows to an IS metric table (annual only —
    Div, needed for DPR, has no quarterly source).

    NFAT = Rev / NFA                    (NFA = NB, Net Block, from BS)
    DPR = Div / Net * 100
    DepNFA = Dep / NFA * 100
    SSGR = (NFAT * (Net/Rev) * (1 - DPR/100) - DepNFA/100) * 100
    """
    if is_table.empty or bs_table.empty:
        return is_table

    rev = _numeric_row(is_table, "Rev")
    net = _numeric_row(is_table, "Net")
    div = _numeric_row(is_table, "Div")
    dep = _numeric_row(is_table, "Dep")
    nfa = _numeric_row(bs_table, "NB").reindex(is_table.columns)

    nfat = _safe_divide(rev, nfa)
    npm_frac = _safe_divide(net, rev)
    dpr_frac = _safe_divide(div, net)
    dep_nfa_frac = _safe_divide(dep, nfa)

    ssgr = (nfat * npm_frac * (1 - dpr_frac) - dep_nfa_frac) * 100

    is_table.loc["NFAT"] = nfat.round(2)
    is_table.loc["DPR"] = (dpr_frac * 100).round(2)
    is_table.loc["DepNFA"] = (dep_nfa_frac * 100).round(2)
    is_table.loc["SSGR"] = ssgr.round(2)

    return is_table


def add_capex_and_ratios(is_table: pd.DataFrame, bs_table: pd.DataFrame) -> pd.DataFrame:
    """Add NetWorth, Capex, LowCapex, LowDebt, CapexNI, LiabEquity and ROE rows
    to an IS metric table (annual only, like add_ssgr).

    NetWorth = Eq + Res (Equity Capital + Reserves — the standard "Equity" in
               Debt/Equity and ROE ratios)
    Capex = Δ(NB + WIP) + Dep   (indirect approximation: capex sits in WIP before
            being capitalized into Net Block; NaN for the oldest available year,
            which has no earlier year to diff against)
    LowCapex = Capex / Rev * 100
    LowDebt = Int / OP * 100    (needs no BS data — Int and OP are already on IS)
    CapexNI = Capex / Net * 100
    LiabEquity = (Borr + OL) / NetWorth * 100
    ROE = Net / NetWorth * 100
    """
    if is_table.empty or bs_table.empty:
        return is_table

    rev = _numeric_row(is_table, "Rev")
    net = _numeric_row(is_table, "Net")
    interest = _numeric_row(is_table, "Int")
    op = _numeric_row(is_table, "OP")

    nb_wip = _numeric_row(bs_table, "NB") + _numeric_row(bs_table, "WIP")
    prior_nb_wip = nb_wip.shift(-1)  # BS columns are most-recent-first; shift(-1) pulls in the prior year
    dep_bs = _numeric_row(is_table, "Dep").reindex(bs_table.columns)
    capex = ((nb_wip - prior_nb_wip) + dep_bs).reindex(is_table.columns)

    net_worth = (_numeric_row(bs_table, "Eq") + _numeric_row(bs_table, "Res")).reindex(is_table.columns)
    borr_ol = (_numeric_row(bs_table, "Borr") + _numeric_row(bs_table, "OL")).reindex(is_table.columns)

    is_table.loc["NetWorth"] = net_worth.round(2)
    is_table.loc["Capex"] = capex.round(2)
    is_table.loc["LowCapex"] = (_safe_divide(capex, rev) * 100).round(2)
    is_table.loc["LowDebt"] = (_safe_divide(interest, op) * 100).round(2)
    is_table.loc["CapexNI"] = (_safe_divide(capex, net) * 100).round(2)
    is_table.loc["LiabEquity"] = (_safe_divide(borr_ol, net_worth) * 100).round(2)
    is_table.loc["ROE"] = (_safe_divide(net, net_worth) * 100).round(2)

    return is_table


def add_roce(is_table: pd.DataFrame, bs_table: pd.DataFrame) -> pd.DataFrame:
    """Add WC, CapitalEmployed, ROCE, CapitalEmployedExCash and ROCEExCash rows
    to an IS table (annual only).

    WC = OA - OL   (the workbook has no granular Current Assets/Liabilities
         split, so this reuses the same OA/OL aggregates as add_bs_totals/
         add_capex_and_ratios)
    CapitalEmployed = NB + WIP + Invest + WC
    ROCE = PBIT / CapitalEmployed * 100   (PBIT is EBIT under a different name)
    CapitalEmployedExCash = CapitalEmployed - Cash   ("Nalanda's F" basis —
        excludes cash, treated as non-operating surplus, from capital employed)
    ROCEExCash = PBIT / CapitalEmployedExCash * 100
    """
    if is_table.empty or bs_table.empty:
        return is_table

    pbit = _numeric_row(is_table, "PBIT")

    oa = _numeric_row(bs_table, "OA").reindex(is_table.columns)
    ol = _numeric_row(bs_table, "OL").reindex(is_table.columns)
    nb = _numeric_row(bs_table, "NB").reindex(is_table.columns)
    wip = _numeric_row(bs_table, "WIP").reindex(is_table.columns)
    invest = _numeric_row(bs_table, "Invest").reindex(is_table.columns)
    cash = _numeric_row(bs_table, "Cash").reindex(is_table.columns)

    wc = oa - ol
    capital_employed = nb + wip + invest + wc
    capital_employed_ex_cash = capital_employed - cash

    is_table.loc["WC"] = wc.round(2)
    is_table.loc["CapitalEmployed"] = capital_employed.round(2)
    is_table.loc["ROCE"] = (_safe_divide(pbit, capital_employed) * 100).round(2)
    is_table.loc["CapitalEmployedExCash"] = capital_employed_ex_cash.round(2)
    is_table.loc["ROCEExCash"] = (_safe_divide(pbit, capital_employed_ex_cash) * 100).round(2)

    return is_table


def _cagr_pct(latest: float, base: float, years: float) -> float:
    """Annualized % growth from `base` to `latest` over `years`.

    NaN if either endpoint is missing or non-positive (a root of a non-positive
    base/latest is undefined), or if `years` isn't positive.
    """
    if pd.isna(latest) or pd.isna(base) or latest <= 0 or base <= 0 or years <= 0:
        return float("nan")
    return round(((latest / base) ** (1 / years) - 1) * 100, 2)


def build_cagr_table(
    table: pd.DataFrame, metrics: list[str], windows: tuple[int, ...], periods_per_year: int, unit_suffix: str
) -> pd.DataFrame:
    """CAGR% of each metric in `metrics` over each window in `windows` (counted in
    columns of `table`, most-recent first). `periods_per_year` annualizes the
    window (1 for annual tables, 4 for quarterly). Column labels are e.g. "3Y"/"3Q".
    """
    columns = [f"{w}{unit_suffix}" for w in windows]
    result = pd.DataFrame(index=metrics, columns=columns, dtype="float64")
    if table.empty:
        return result

    for metric in metrics:
        series = _numeric_row(table, metric)
        latest = series.iloc[0] if len(series) else float("nan")
        for w, col in zip(windows, columns):
            base = series.iloc[w] if len(series) > w else float("nan")
            result.loc[metric, col] = _cagr_pct(latest, base, w / periods_per_year)

    return result


def add_bs_totals(table: pd.DataFrame) -> pd.DataFrame:
    """Add TL (Total Liabilities), TA (Total Assets) and NCF (Net Cash Flow) rows.

    TL = Eq + Res + Borr + OL
    TA = NB + WIP + Invest + OA   (Rec/Inv/Cash are informational sub-breakdowns
                                    already folded into OA, not separately additive)
    NCF = CFO + CFI + CFF
    """
    if table.empty:
        return table

    table.loc["TL"] = (
        _numeric_row(table, "Eq") + _numeric_row(table, "Res")
        + _numeric_row(table, "Borr") + _numeric_row(table, "OL")
    )
    table.loc["TA"] = (
        _numeric_row(table, "NB") + _numeric_row(table, "WIP")
        + _numeric_row(table, "Invest") + _numeric_row(table, "OA")
    )
    table.loc["NCF"] = (
        _numeric_row(table, "CFO") + _numeric_row(table, "CFI") + _numeric_row(table, "CFF")
    )

    return table


def get_company_view(symbol: str, sheets: dict[str, pd.DataFrame]) -> dict:
    """Assemble everything about one company: industry + quarterly/IS/BS tables."""
    industry_row = sheets["Industry"].loc[sheets["Industry"]["Symbol"] == symbol]
    industry = industry_row["Industry"].iloc[0] if not industry_row.empty else "Unknown"

    shares_by_year = _shares_by_year(sheets["BS"], symbol)

    quarterly = add_derived_metrics(company_metric_table(sheets["Quarter"], symbol), shares_by_year)
    income_statement = add_ttm_column(
        add_derived_metrics(company_metric_table(sheets["IS"], symbol), shares_by_year),
        quarterly,
    )
    balance_sheet = add_bs_totals(company_metric_table(sheets["BS"], symbol))
    income_statement = add_ssgr(income_statement, balance_sheet)
    income_statement = add_capex_and_ratios(income_statement, balance_sheet)
    income_statement = add_roce(income_statement, balance_sheet)

    windows = (1, 3, 5, 10)
    annual_cagr = pd.concat([
        build_cagr_table(income_statement, ["Rev", "Exp", "OP", "PBIT", "PBT"], windows, 1, "Y"),
        build_cagr_table(balance_sheet, ["NB", "Borr"], windows, 1, "Y"),
    ])
    quarterly_cagr = build_cagr_table(quarterly, ["Rev"], windows, 4, "Q")

    annual_cols = [c for c in income_statement.columns if c != "TTM"]
    latest_ssgr = income_statement.loc["SSGR", annual_cols[0]] if annual_cols else float("nan")
    rev_cagr_10y = annual_cagr.loc["Rev", "10Y"] if "Rev" in annual_cagr.index else float("nan")
    passes = (
        bool(latest_ssgr > rev_cagr_10y)
        if pd.notna(latest_ssgr) and pd.notna(rev_cagr_10y)
        else None
    )

    return {
        "industry": industry,
        "quarterly": quarterly,
        "income_statement": income_statement,
        "balance_sheet": balance_sheet,
        "cagr": annual_cagr,
        "quarterly_cagr": quarterly_cagr,
        "ssgr_screen": {
            "latest_year": annual_cols[0] if annual_cols else None,
            "ssgr_pct": latest_ssgr,
            "rev_cagr_10y_pct": rev_cagr_10y,
            "passes": passes,
        },
    }


def build_universe_cache(
    sheets: dict[str, pd.DataFrame], progress_callback=None
) -> pd.DataFrame:
    """Run get_company_view for every symbol in Industry and collect the fields
    needed by every Screens-page screen, so they all share one expensive pass.

    `progress_callback(done, total)`, if given, is called periodically (every
    ~25 companies, not every one) so a UI layer can show progress during the
    ~1-minute run this takes across the full universe. Returns one row per
    symbol: Symbol, Industry, SSGR (%), Rev 10Y CAGR (%), SSGR Passes, and for
    every underlying IS row referenced by MOAT_METRIC_CONFIG ("row", not the
    config key — several screens can share one row, e.g. ROCE's Median and 10Y
    variants), "{row} Y1 (%)" .. "{row} Y10 (%)" — that row's value for the 10
    most recent completed fiscal years (Y1 = latest completed FY), NaN where
    fewer than 10 years exist.
    """
    rows_needed = {config["row"] for config in MOAT_METRIC_CONFIG.values()}
    symbols = sheets["Industry"]["Symbol"].dropna().unique()
    total = len(symbols)
    rows = []
    for i, symbol in enumerate(symbols):
        view = get_company_view(symbol, sheets)
        screen = view["ssgr_screen"]
        income_statement = view["income_statement"]
        annual_cols = [c for c in income_statement.columns if c != "TTM"]

        row = {
            "Symbol": symbol,
            "Industry": view["industry"],
            "SSGR (%)": screen["ssgr_pct"],
            "Rev 10Y CAGR (%)": screen["rev_cagr_10y_pct"],
            "SSGR Passes": screen["passes"],
        }
        for is_row in rows_needed:
            row_values = _numeric_row(income_statement, is_row)
            for y in range(10):
                row[f"{is_row} Y{y + 1} (%)"] = row_values[annual_cols[y]] if y < len(annual_cols) else float("nan")
        rows.append(row)

        if progress_callback and (i % 25 == 0 or i == total - 1):
            progress_callback(i + 1, total)
    return pd.DataFrame(rows)


def industry_metric_thresholds(
    universe: pd.DataFrame,
    row: str,
    percentile: float,
    min_companies: int = 5,
    fallback: float = 0.0,
    consistency: str = "all_years",
) -> pd.Series:
    """Per-row (aligned to `universe.index`) threshold: the `percentile`th
    percentile of `row`'s value among companies sharing that row's Industry, or
    `fallback` when that industry has fewer than `min_companies` companies with
    a usable value. The basis is `row`'s latest-year value ("{row} Y1 (%)") for
    `consistency="all_years"`, or each company's median across `Y1`..`Y10` for
    `consistency="median"` — matching whichever window `metric_moat_passes`
    screens on, so the industry bar reflects the same lens.
    """
    if consistency == "median":
        cols = [f"{row} Y{y} (%)" for y in range(1, 11)]
        basis = universe[cols].median(axis=1)
    else:
        basis = universe[f"{row} Y1 (%)"]
    grouped = basis.groupby(universe["Industry"])
    counts = grouped.transform("count")
    thresholds = grouped.transform(lambda s: s.quantile(percentile))
    return thresholds.where(counts >= min_companies, fallback)


def metric_moat_passes(
    universe: pd.DataFrame, row: str, thresholds: pd.Series, direction: str = "higher", consistency: str = "all_years"
) -> pd.Series:
    """Tri-state (True/False/pd.NA) verdict for one screen reading IS row `row`.

    `consistency="all_years"`: every one of the last 10 completed-FY values
    must clear the (per-row) threshold — above it for `direction="higher"`,
    below it for `"lower"`. `consistency="median"`: the *median* of the last 10
    years must clear it instead — a "typical year" rather than "every year"
    bar. Either way, NA if any of the 10 years is missing (not enough history
    for a real verdict), matching the SSGR screen's None-for-insufficient-data
    convention — a median still needs the full 10-year window to mean that.
    """
    cols = [f"{row} Y{y} (%)" for y in range(1, 11)]
    has_full_history = universe[cols].notna().all(axis=1)
    if consistency == "median":
        value = universe[cols].median(axis=1)
        meets_bar = value.gt(thresholds) if direction == "higher" else value.lt(thresholds)
    elif direction == "higher":
        meets_bar = universe[cols].gt(thresholds, axis=0).all(axis=1)
    else:
        meets_bar = universe[cols].lt(thresholds, axis=0).all(axis=1)
    result = pd.Series(pd.NA, index=universe.index, dtype=object)
    result[has_full_history] = meets_bar[has_full_history]
    return result


def moat_score(passes_by_metric: dict[str, pd.Series]) -> pd.Series:
    """Sum of how many of the given per-metric pass Series are exactly True,
    per row. A metric with pd.NA (not enough data) or False contributes 0.
    """
    metrics = list(passes_by_metric.values())
    index = metrics[0].index
    score = pd.Series(0, index=index, dtype="int64")
    for passes in metrics:
        score = score + (passes == True).astype("int64")  # noqa: E712 (NA/False must not match)
    return score


def load_universe_cache(path: str = UNIVERSE_CACHE_FILE) -> pd.DataFrame | None:
    """Persisted universe-wide screen results, or None if never computed yet."""
    if not os.path.exists(path):
        return None
    return pd.read_csv(path)


def save_universe_cache(df: pd.DataFrame, path: str = UNIVERSE_CACHE_FILE) -> None:
    df.to_csv(path, index=False)


def macro_table(sheets: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Macro sheet transposed so parameters are columns and dates are rows."""
    df = sheets["Macro"].set_index("Parameter")
    return df.T
