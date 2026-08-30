# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
pip install -r requirements.txt   # streamlit, pandas, openpyxl, pytest
streamlit run app.py              # launch the app (default: http://localhost:8501)
pytest tests/ -v                  # run the test suite
pytest tests/test_data_loader.py::test_add_ssgr_matches_hand_computed_value  # run a single test
```

There is no linter or build step in this repo. Tests live in `tests/test_data_loader.py` and use small, hand-built synthetic sheets (not the real workbook), so every expected value is exactly computable.

## Architecture

This is a small Streamlit app for exploring fundamentals of multiple stocks pulled from a single Excel workbook, `Raw data.xlsx`. The workbook is the only data source — there is no database or API.

- **`data_loader.py`** — all data access and reshaping. No Streamlit UI logic except the `@st.cache_data` decorator on `load_raw`.
- **`app.py`** — the multipage entrypoint only: calls `st.set_page_config` then `st.navigation([...]).run()`. Holds no UI of its own.
- **`pages/data_explorer.py`** — per-company exploration (search, symbol picker, quarterly/IS/BS/CAGR tables, SSGR screen card for one company). Reads `st.session_state["jump_to_symbol"]` (set by the Screens page) to pre-select a symbol for drill-through, via a `key="data_explorer_symbol"` selectbox.
- **`pages/screens.py`** — runs screens across the whole universe of companies (SSGR, 7 moat screens, and an Overall Ranking, all as tabs on one page) and lists who passes each.

### Pages / navigation

Uses Streamlit's native multipage API (`st.navigation`/`st.Page`, confirmed available in the installed 1.62.0). `app.py` is the only place `st.set_page_config` may be called. Page scripts under `pages/` import from `data_loader.py` exactly like the old single-script `app.py` did — Streamlit adds the entrypoint's directory (the project root) to `sys.path`, not each page's own directory.

### Workbook shape

`Raw data.xlsx` has five sheets, loaded via `load_raw()` into a `dict[str, pd.DataFrame]` keyed by sheet name:

- `Industry` — one row per company (`Symbol`, `Industry`), used to drive the company search/select list.
- `Quarter`, `IS`, `BS` — "wide" sheets: one row per `Symbol`, with all other columns following a `Metric-Period` naming convention (e.g. `Rev-Q127` = Revenue for Q1 FY27, `Rev-26` = Revenue for FY26), parsed by `COL_RE` in `data_loader.py`. Period order in the column headers is most-recent-first. Metric prefixes: `Quarter`/`IS` use `Rev` (revenue), `Exp` (expenses), `OI` (other income), `Int` (interest), `Dep` (depreciation), `Net` (net profit, in ₹ crores); `IS` also has `Div` (dividend). `BS` uses `Eq`, `Res`, `Borr`, `OL`, `NB`, `WIP`, `Invest`, `OA`, `Rec`, `Inv`, `Cash`, `NOS` (number of shares, absolute count — **not** crores), `CFO`, `CFI`, `CFF`.
- `Macro` — one row per macro parameter (`Parameter` column) with dates as columns; transposed by `macro_table()` so dates become rows.

### Reshaping pipeline

For the three wide sheets, `parse_metric_periods()` groups columns by metric prefix, then `company_metric_table()` pivots a single company's row into a metric-by-period table (rows = metric, columns = period, newest period first). `get_company_view(symbol, sheets)` assembles the full per-company view (industry + quarterly/IS/BS tables) consumed directly by `app.py`.

`load_raw()` also normalizes the literal string `"NA"` to `pd.NA` across every sheet, and converts `PermissionError` (file open in Excel) and `FileNotFoundError` into a `RuntimeError` with a user-facing message that `app.py` displays via `st.error` instead of crashing.

Because `Raw data.xlsx` is the sole data source, any change to its sheet names, the `Symbol`/`Industry`/`Parameter` column names, or the `Metric-Period` header convention requires corresponding changes in `data_loader.py`.

### Derived metrics (Quarter and IS only)

`add_derived_metrics()` appends these computed rows to the `Quarter` and `IS` pivot tables inside `get_company_view()`:

- `OP` (Operating Profit) = `Rev - Exp`
- `OPM` (Operating Profit Margin, %) = `OP / Rev * 100`
- `PBIT` (Profit Before Interest & Tax) = `OP + OI - Dep`
- `PBT` (Profit Before Tax) = `PBIT - Int`
- `NPM` (Net Profit Margin, %) = `Net / Rev * 100`
- `EPS` = `Net * 1e7 / NOS` — `Net` is in ₹ crores while `NOS` (from `BS`) is an absolute share count, so `Net` is converted to rupees (`CRORE = 1e7`) before dividing.

`BS` only reports `NOS` per fiscal year, but `Quarter` periods (e.g. `Q127`) need a share count too. `_shares_for_period()` looks up the period's fiscal year in `BS`; if that year isn't there yet (e.g. the latest quarter is ahead of the latest annual filing), it falls back to the nearest earlier year with data, or the earliest available year if none is earlier.

### TTM column (IS only)

`add_ttm_column()` inserts a `TTM` (trailing twelve months) column as the first column of the `IS` table, built from the 4 most-recent columns of the (already-derived) `Quarter` table — the `Quarter` sheet's most-recent-first column order makes `.iloc[:, :4]` the trailing 4 quarters. `Rev, Exp, OI, Int, Dep, Net, OP, PBIT, PBT` are summed across those 4 quarters (`NaN` if any quarter is missing, via `sum(min_count=4)`); `OPM`/`NPM` are recomputed from the summed `OP`/`Net` over summed `Rev` (not averaged); `EPS` is the sum of the 4 quarterly `EPS` values. `Div` has no quarterly source in the workbook, so its `TTM` is always blank.

### BS totals

`add_bs_totals()` appends three rows to the `BS` pivot table:

- `TL` (Total Liabilities) = `Eq + Res + Borr + OL`
- `TA` (Total Assets) = `NB + WIP + Invest + OA` — `Rec`, `Inv`, `Cash` are informational sub-breakdowns already folded into `OA`, not separately additive (confirmed empirically: summing them again roughly doubles the mismatch between `TL` and `TA`, which otherwise balance).
- `NCF` (Net Cash Flow) = `CFO + CFI + CFF`

### SSGR (Self-Sustainable Growth Rate) — IS only

`add_ssgr()` appends `NFAT`, `DPR`, `DepNFA` and `SSGR` rows to the `IS` table (annual only — `Div`, needed for `DPR`, has no quarterly source, so there's no quarterly SSGR). `NFA` (Net Fixed Assets) = `NB` from `BS`, aligned to `IS` by fiscal-year column label (`TTM` naturally gets `NaN` since `BS` has no `TTM` column):

- `NFAT` = `Rev / NFA` (a turnover ratio, not a %)
- `DPR` (Dividend Payout Ratio) = `Div / Net * 100`
- `DepNFA` = `Dep / NFA * 100`
- `SSGR` = `(NFAT * (Net/Rev) * (1 - DPR/100) - DepNFA/100) * 100`

All divisions go through `_safe_divide()` (`NaN` for a zero/missing denominator; negative denominators pass through, since a negative ratio is still meaningful here — unlike a CAGR root).

### CAGR tables

`build_cagr_table(table, metrics, windows, periods_per_year, unit_suffix)` is generic: for each metric it takes `series.iloc[0]` as "latest" and `series.iloc[w]` as the value `w` columns back, so it works unchanged for `IS` (which has `TTM` at position 0 — making CAGR **TTM-anchored**: "1Y" compares `TTM` to the latest completed FY, "10Y" to the FY 10 columns back), `BS` (no `TTM`, so "latest" is just the latest FY-end balance — appropriate since `NB`/`Borr` are point-in-time, not flow, metrics), and `Quarter` (`periods_per_year=4`, so a window is counted in quarters, e.g. `"3Q"`). `_cagr_pct()` returns `NaN` whenever either endpoint is missing or `<= 0` (a root of a non-positive number is undefined).

`get_company_view()` builds two such tables per company:
- `view["cagr"]`: rows `Rev, Exp, OP, PBIT, PBT` (from `IS`, TTM-anchored) and `NB, Borr` (from `BS`), columns `1Y/3Y/5Y/10Y`.
- `view["quarterly_cagr"]`: row `Rev` (from `Quarter`), columns `1Q/3Q/5Q/10Q`.

### SSGR screen

`view["ssgr_screen"]` compares the latest completed fiscal year's `SSGR` against `view["cagr"].loc["Rev", "10Y"]`: `passes = True` if `SSGR > Rev 10Y CAGR` (the company grew organically, without needing external debt/equity to fund that growth), `False` if not, `None` if either value is `NaN`.

### Capex and equity-based ratios (IS only)

`add_capex_and_ratios()` appends `NetWorth`, `Capex`, `LowCapex`, `LowDebt`, `CapexNI`, `LiabEquity` and `ROE` rows to the `IS` table (annual only, same pattern as `add_ssgr` — pulls `BS` data in via `.reindex(is_table.columns)`):

- `NetWorth` = `Eq + Res` — the standard meaning of "Equity" in Debt/Equity and ROE ratios (not the `Eq` column alone, which is just paid-up share capital).
- `Capex` = `Δ(NB + WIP) + Dep`, year-over-year via `.shift(-1)` on `BS`'s most-recent-first columns — the indirect approximation used when a workbook has no explicit capex line (capex sits in `WIP` before being capitalized into `NB`). `NaN` for the oldest available year (no earlier year to diff against).
- `LowCapex` = `Capex / Rev * 100`; `CapexNI` = `Capex / Net * 100`
- `LowDebt` = `Int / OP * 100` — needs no `BS` data at all, since `Int` and `OP` are already on `IS`.
- `LiabEquity` = `(Borr + OL) / NetWorth * 100`
- `ROE` = `Net / NetWorth * 100`

### ROCE (IS only)

`add_roce()` appends `WC`, `CapitalEmployed`, `ROCE`, `CapitalEmployedExCash` and `ROCEExCash` rows to the `IS` table (annual only, same pattern as `add_ssgr`/`add_capex_and_ratios`). The workbook has no granular Current Assets/Current Liabilities split, only the `OA`/`OL` aggregates already used for `TA`/`TL`/`LiabEquity`:

- `WC` (Working Capital) = `OA - OL`
- `CapitalEmployed` = `NB + WIP + Invest + WC` — provably ≈ `NetWorth + Borr` given this schema (since `TA ≈ TL`, the same empirical-rounding equivalence already noted for `TL`/`TA`); computed via the WC-based formula so `WC` is visible as an intermediate row
- `ROCE` = `PBIT / CapitalEmployed * 100` (`PBIT` is EBIT under a different name, already on `IS` from `add_derived_metrics`)
- `CapitalEmployedExCash` = `CapitalEmployed - Cash` — excludes cash (only cash, not `Invest`) as non-operating surplus; this is the "Nalanda's F" basis
- `ROCEExCash` = `PBIT / CapitalEmployedExCash * 100` — always `>= ROCE` (subtracting cash from the denominator can only raise the ratio)

### Screens page: universe-wide caching

Looping `get_company_view` across all ~2080 companies (`build_universe_cache()`) takes **~53 seconds** — too slow to recompute on every page load, and far too slow to redo on every widget interaction (a threshold slider, say). Since the underlying data (`Raw data.xlsx`) only changes ~once a year, `pages/screens.py` does **not** use `st.cache_data` for this; instead it persists results to `universe_cache.csv` (`UNIVERSE_CACHE_FILE` in `data_loader.py`) via `save_universe_cache()`/`load_universe_cache()`. The page loads instantly from that file on every visit and only recomputes (with a progress bar, via `build_universe_cache(sheets, progress_callback=...)`) on the very first run ever (no cache file yet) or when the user clicks **Refresh**. `load_universe_cache()` returns `None` if the file doesn't exist. **The cache has no schema-version check** — if a code change adds/renames universe-cache columns (as every screen addition so far has), a stale `universe_cache.csv` from before that change will raise a `KeyError` on load; click **Refresh** (or delete the file) after any such change, not just after a real data update.

**One cache, many screens**: `build_universe_cache()` computes everything every current or future screen needs in that single ~53s pass, so adding a screen doesn't mean adding another full pass — it means adding columns to this one row-per-company table. It currently produces `Symbol`, `Industry`, `SSGR (%)`, `Rev 10Y CAGR (%)`, `SSGR Passes` (for the SSGR screen), plus for every **unique** `row` referenced across `MOAT_METRIC_CONFIG` (several screens can share one row — see below), `"{row} Y1 (%)"` … `"{row} Y10 (%)"` — that row's 10 most recent completed-FY values per company, `NaN`-padded if fewer than 10 years exist. Any screen whose pass/fail depends on a **user-adjustable** parameter (like a threshold) must store the raw building-block numbers (here, 10 years per row) rather than a precomputed verdict, so the verdict can be recomputed instantly from the small cached table on every rerun instead of re-running the 53s loop.

### Screens (generalized): `MOAT_METRIC_CONFIG`

`MOAT_METRIC_CONFIG` (in `data_loader.py`) is the single source of truth for every screen on the Moats and Nalanda's F tabs — config key → `{row, label, default, direction, percentile, consistency, group}`. The dict **key** is what widget `key=`s and the ranking table are built from (must be unique per screen); **`row`** is the underlying `IS` row the screen actually reads (several config keys can share one `row` — e.g. `ROCEMedian` and `ROCEAllYears` both read the `ROCE` row, just with different `consistency`). **`group`** (`"moats"` or `"nalanda"`) selects which tab a screen appears on.

| key | row | label | default | direction | consistency | group |
|---|---|---|---|---|---|---|
| `OPM` | `OPM` | Operating Margin | 40% | higher | all_years | moats |
| `NPM` | `NPM` | Net Margin | 20% | higher | all_years | moats |
| `LowDebt` | `LowDebt` | Interest / Operating Profit | 15% | lower | all_years | moats |
| `LowCapex` | `LowCapex` | Capex / Revenue | 10% | lower | all_years | moats |
| `CapexNI` | `CapexNI` | Capex / Net Income | 25% | lower | all_years | moats |
| `LiabEquity` | `LiabEquity` | Liabilities / Equity | 80% | lower | all_years | moats |
| `ROE` | `ROE` | Net Income / Equity (ROE) | 15% | higher | all_years | moats |
| `ROCEMedian` | `ROCE` | ROCE (Median) | 20% | higher | median | nalanda |
| `ROCEAllYears` | `ROCE` | ROCE (10Y) | 20% | higher | all_years | nalanda |
| `NalandaFMedian` | `ROCEExCash` | Nalanda's F (Median) | 20% | higher | median | nalanda |
| `NalandaFAllYears` | `ROCEExCash` | Nalanda's F (10Y) | 20% | higher | all_years | nalanda |

`consistency="all_years"`: a company passes if **all 10** of `"{row} Y1 (%)"`…`"{row} Y10 (%)"` clear the threshold — above it for `direction="higher"`, below it for `"lower"`. `consistency="median"`: the **median** of those same 10 values must clear it instead — a "typical year" bar rather than "every year" (added specifically for ROCE/Nalanda's F, since a single bad year swinging the whole verdict is less meaningful for a returns metric). Either way `NaN` (fewer than 10 years of history) gives a `pd.NA` verdict (`metric_moat_passes()`), mirroring the SSGR screen's `None`-for-insufficient-data convention — a median still needs the full 10-year window to mean that.

Thresholds are **per-company**, not one global number: `industry_metric_thresholds()` computes each company's threshold as its own industry's percentile of peers' value — `0.75` (top quartile) for higher-is-better metrics, `0.25` (bottom quartile — the industry's best-in-class *low* value) for lower-is-better ones — falling back to `config["default"]` for industries with fewer than `min_companies=5` peers with usable data. The percentile **basis** matches `consistency`: each peer's `"{row} Y1 (%)"` for `"all_years"`, or each peer's own 10-year median for `"median"` — so the industry bar reflects the same lens being screened.

### Screens tab UI: two layouts, chosen by whether a combined score means anything

`pages/screens.py` has three tabs: **SSGR** (unchanged, standalone — a growth-sustainability check, never called a "moat" or included in any ranking), **Moats** (the 7 `group="moats"` screens, `render_screen_group_tab()` — a combined score), and **Nalanda's F** (the 4 `group="nalanda"` ROCE/Nalanda's-F screens, `render_filter_tab()` — no score). Both take the same `(universe, title, description, group_configs)` shape and both reuse `render_threshold_controls()` for the per-screen widget row, but they diverge on whether summing pass/fail across the group's screens is meaningful:

- **`render_screen_group_tab()`** (Moats): the 7 screens measure genuinely distinct traits (margin, debt, capex, leverage, returns), so "how many did it clear" is a meaningful signal. Progressive disclosure — a ranking table by default, with two rarely-needed pieces in collapsed `st.expander`s:
  - **"Configure thresholds"** (collapsed): one compact `st.columns` row per screen via `render_threshold_controls()`, returning that screen's `(thresholds, passes)`. Called once per screen in the group — `st.tabs`' `with tab:` bodies (and, same principle, everything inside an always-rendered `st.expander`) execute every rerun regardless of expanded/collapsed state, so `all_thresholds`/`all_passes` are fully populated before the ranking table below is built — no `session_state` indirection needed.
  - **Ranking table** (always visible): `Symbol`, `Industry`, `Score` (`moat_score(all_passes)`, 0–N), then one pass/fail column per screen; sorted by `Score` descending. A "Minimum score" slider (0–N) replaces a per-screen "show only passing" checkbox.
  - **"Metric detail (10-year history)"** (collapsed): a screen-label `st.selectbox` plus `render_metric_detail_table()` — Symbol/Industry/Threshold/`Y1`…`Y10`/Passes for one screen, reusing the already-computed `thresholds`/`passes`. Column labels read from `config["row"]`, so e.g. picking "ROCE (Median)" and "ROCE (10Y)" both show the same underlying `ROCE Y1`…`Y10` values — only `Threshold Used`/`Passes` differ.
- **`render_filter_tab()`** (Nalanda's F): all 4 screens measure the same underlying idea (ROCE, with/without cash, median vs. every-year) — summing them wouldn't add information a single glance at all four doesn't already give, so there's no score and no ranking table. Instead each screen gets its own always-visible section, stacked vertically: the `render_threshold_controls()` widget row, a pass-count caption (`f"{len(passing)} of {len(universe)} companies pass"`), and a table of **only the passing companies** (Symbol/Industry/Threshold/`Y1`…`Y10`) — a `st.divider()` between sections. One shared search box at the top of the tab filters all four sections' tables at once (not per-section, unlike Moats' single detail view).

Both expanders' tables, and the ranking table, support the same search-box + `st.dataframe(..., on_select="rerun")` drill-through pattern as the SSGR tab (`drill_through()` helper).
