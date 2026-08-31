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
- **`pages/data_explorer.py`** — per-company exploration (search, symbol picker, quarterly/IS/BS/CAGR tables, a **Filters** section showing every screen's verdict for the selected company). Reads `st.session_state["jump_to_symbol"]` (set by the Screens page) to pre-select a symbol for drill-through, via a `key="data_explorer_symbol"` selectbox.
- **`pages/screens.py`** — runs screens across the whole universe of companies (SSGR, Moats, Nalanda's F, CCP, Vijay Malik, Net-Net, Vantage tabs) and lists who passes each.

### Pages / navigation

Uses Streamlit's native multipage API (`st.navigation`/`st.Page`, confirmed available in the installed 1.62.0). `app.py` is the only place `st.set_page_config` may be called. Page scripts under `pages/` import from `data_loader.py` exactly like the old single-script `app.py` did — Streamlit adds the entrypoint's directory (the project root) to `sys.path`, not each page's own directory.

### Workbook shape

`Raw data.xlsx` has five required sheets plus one optional one, loaded via `load_raw()` into a `dict[str, pd.DataFrame]` keyed by sheet name (`pd.read_excel(path, sheet_name=None)`, so any extra sheet — like `Market` — is picked up automatically with no loader changes):

- `Industry` — one row per company (`Symbol`, `Industry`), used to drive the company search/select list.
- `Quarter`, `IS`, `BS` — "wide" sheets: one row per `Symbol`, with all other columns following a `Metric-Period` naming convention (e.g. `Rev-Q127` = Revenue for Q1 FY27, `Rev-26` = Revenue for FY26), parsed by `COL_RE` in `data_loader.py`. Period order in the column headers is most-recent-first. Metric prefixes: `Quarter`/`IS` use `Rev` (revenue), `Exp` (expenses), `OI` (other income), `Int` (interest), `Dep` (depreciation), `Net` (net profit, in ₹ crores); `IS` also has `Div` (dividend). `BS` uses `Eq`, `Res`, `Borr`, `OL`, `NB`, `WIP`, `Invest`, `OA`, `Rec`, `Inv`, `Cash`, `NOS` (number of shares, absolute count — **not** crores), `CFO`, `CFI`, `CFF`.
- `Macro` — one row per macro parameter (`Parameter` column) with dates as columns; transposed by `macro_table()` so dates become rows.
- `Market` (optional) — one row per company: `Symbol`, `CMP` (current price), `PE`, `Market cap (INR Cr)`, `Beta` (only `CMP`/`PE`/`Market cap (INR Cr)` are currently read) — typically a data-vendor export, re-pasted as often as needed. See "Market data" below.

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
- `CapitalEmployedExCash` = `CapitalEmployed - Cash - Invest` — excludes both cash and investments as non-operating surplus; this is the "Nalanda's F" basis
- `ROCEExCash` = `PBIT / CapitalEmployedExCash * 100` — always `>= ROCE` (subtracting cash from the denominator can only raise the ratio)

### Revenue growth (IS only)

`add_rev_growth()` appends a `RevGrowth` row (year-over-year revenue growth, %) to the `IS` table: `(Rev - prior year's Rev) / prior year's Rev * 100`, via `.shift(-1)` on `IS`'s most-recent-first columns (same technique as `Capex`'s year-over-year diff). `NaN` for the oldest available year. Built for the CCP screen — no other screen uses it.

### Screens page: universe-wide caching

Looping `get_company_view` across all ~2080 companies (`build_universe_cache()`) takes **~53 seconds** — too slow to recompute on every page load, and far too slow to redo on every widget interaction (a threshold slider, say). Since the underlying data (`Raw data.xlsx`) only changes ~once a year, `pages/screens.py` does **not** use `st.cache_data` for this; instead it persists results to `universe_cache.csv` (`UNIVERSE_CACHE_FILE` in `data_loader.py`) via `save_universe_cache()`/`load_universe_cache()`. The page loads instantly from that file on every visit and only recomputes (with a progress bar, via `build_universe_cache(sheets, progress_callback=...)`) on the very first run ever (no cache file yet) or when the user clicks **Refresh**. `load_universe_cache()` returns `None` if the file doesn't exist. **The cache has no schema-version check** — if a code change adds/renames universe-cache columns (as every screen addition so far has), a stale `universe_cache.csv` from before that change will raise a `KeyError` on load; click **Refresh** (or delete the file) after any such change, not just after a real data update.

**One cache, many screens**: `build_universe_cache()` computes everything every current or future screen needs in that single ~53s pass, so adding a screen doesn't mean adding another full pass — it means adding columns to this one row-per-company table. It currently produces `Symbol`, `Industry`, `SSGR (%)`, `Rev 10Y CAGR (%)`, `SSGR Passes` (for the SSGR screen), plus for every **unique** `row` in `{config["row"] for config in MOAT_METRIC_CONFIG.values()} | CCP_EXTRA_CACHE_ROWS` (several screens can share one row — see below; `CCP_EXTRA_CACHE_ROWS = {"RevGrowth"}` covers rows the CCP screen needs that no `MOAT_METRIC_CONFIG` entry references), `"{row} Y1 (%)"` … `"{row} Y10 (%)"` — that row's 10 most recent completed-FY values per company, `NaN`-padded if fewer than 10 years exist. Any screen whose pass/fail depends on a **user-adjustable** parameter (like a threshold) must store the raw building-block numbers (here, 10 years per row) rather than a precomputed verdict, so the verdict can be recomputed instantly from the small cached table on every rerun instead of re-running the 53s loop.

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

`consistency="all_years"`: a company passes if **all** of `"{row} Y1 (%)"`…`"{row} Y{years} (%)"` clear the threshold — above it for `direction="higher"`, below it for `"lower"`. `consistency="median"`: the **median** of those same years must clear it instead — a "typical year" bar rather than "every year" (added specifically for ROCE/Nalanda's F, since a single bad year swinging the whole verdict is less meaningful for a returns metric). Either way `NaN` (fewer than `years` years of history) gives a `pd.NA` verdict (`metric_moat_passes()`), mirroring the SSGR screen's `None`-for-insufficient-data convention — a median still needs the full window to mean that. `years` defaults to 10 (every screen in the table above uses the full window the universe cache stores); the CCP screen (below) is the first to let the user shrink it via a slider.

Thresholds are **per-company**, not one global number, *for the Moats tab*: `industry_metric_thresholds()` computes each company's threshold as its own industry's percentile of peers' value — `0.75` (top quartile) for higher-is-better metrics, `0.25` (bottom quartile — the industry's best-in-class *low* value) for lower-is-better ones — falling back to `config["default"]` for industries with fewer than `min_companies=5` peers with usable data. The percentile **basis** matches `consistency`: each peer's `"{row} Y1 (%)"` for `"all_years"`, or each peer's own 10-year median for `"median"` — so the industry bar reflects the same lens being screened. **Nalanda's F does not use this** — see below.

### Screens tab UI: two layouts, chosen by whether a combined score means anything

`pages/screens.py` has three tabs: **SSGR** (unchanged, standalone — a growth-sustainability check, never called a "moat" or included in any ranking), **Moats** (the 7 `group="moats"` screens, `render_screen_group_tab()` — a combined score), and **Nalanda's F** (the 4 `group="nalanda"` ROCE/Nalanda's-F screens, `render_filter_tab()` — no score). Both take the same `(universe, title, description, group_configs)` shape and both reuse `render_threshold_controls()` for the per-screen widget row, but they diverge on whether summing pass/fail across the group's screens is meaningful:

- **`render_screen_group_tab()`** (Moats): the 7 screens measure genuinely distinct traits (margin, debt, capex, leverage, returns), so "how many did it clear" is a meaningful signal. Progressive disclosure — a ranking table by default, with two rarely-needed pieces in collapsed `st.expander`s:
  - **"Configure thresholds"** (collapsed): one compact `st.columns` row per screen via `render_threshold_controls()`, returning that screen's `(thresholds, passes)`. Called once per screen in the group — `st.tabs`' `with tab:` bodies (and, same principle, everything inside an always-rendered `st.expander`) execute every rerun regardless of expanded/collapsed state, so `all_thresholds`/`all_passes` are fully populated before the ranking table below is built — no `session_state` indirection needed.
  - **Ranking table** (always visible): `Symbol`, `Industry`, `Score` (`moat_score(all_passes)`, 0–N), then one pass/fail column per screen; sorted by `Score` descending. A "Minimum score" slider (0–N) replaces a per-screen "show only passing" checkbox.
  - **"Metric detail (10-year history)"** (collapsed): a screen-label `st.selectbox` plus `render_metric_detail_table()` — Symbol/Industry/Threshold/`Y1`…`Y10`/Passes for one screen, reusing the already-computed `thresholds`/`passes`. Column labels read from `config["row"]`, so e.g. picking "ROCE (Median)" and "ROCE (10Y)" both show the same underlying `ROCE Y1`…`Y10` values — only `Threshold Used`/`Passes` differ.
- **`render_filter_tab()`** (Nalanda's F): all 4 screens measure the same underlying idea (ROCE, with/without cash, median vs. every-year) — summing them wouldn't add information a single glance at all four doesn't already give, so there's no score and no ranking table. Instead each screen gets its own always-visible section, stacked vertically: the `render_threshold_controls()` widget row, a pass-count caption (`f"{len(passing)} of {len(universe)} companies pass"`), and a table of **only the passing companies** (Symbol/Industry/Threshold/`Y1`…`Y10`) — a `st.divider()` between sections. One shared search box at the top of the tab filters all four sections' tables at once (not per-section, unlike Moats' single detail view). Unlike Moats, `render_filter_tab()` calls `render_threshold_controls(..., allow_industry=False)` — Nalanda's F has no industry-percentile toggle, only the manual slider; `use_industry` is hardcoded `False` (still shadow-copied to the `_saved` key so `evaluate_screens_for_company` sees it).

### CCP tab: two metrics AND-ed together, two lists

The 4th tab, **CCP** (Coffee Can Portfolio — Saurabh Mukherjea's screen: ROCE ≥15% and revenue growth ≥10%, every year for 10 years), doesn't fit either of the above layouts — it's not one independent screen per section (`render_filter_tab`) and not several distinct traits worth summing into a score (`render_screen_group_tab`). It's **two metrics combined with AND**, shown as **two lists** (regular `ROCE` vs. `ROCEExCash`, both AND-ed with the same `RevGrowth` check). `render_ccp_tab()` is bespoke:

- Unlike every other screen, CCP's thresholds are **fixed absolute benchmarks by design** (that's the whole point of the Coffee Can criteria), not industry-relative — so there's no "use industry percentile" toggle, just three plain sliders: min ROCE %, min revenue growth %, and (new) a **years** slider (1–10) controlling the consistency window itself, passed straight through to `metric_moat_passes(..., years=years)`.
- `and_tri_state(a, b) -> pd.Series` (new, generic three-valued AND) combines the two `metric_moat_passes(..., consistency="all_years", years=years)` results: `False` dominates (an AND with a definite `False` can never become `True`, even if the other side is `NA`); `NA` only wins when neither side is a definite `False`; `True` only if both sides are `True`.
- Each of the two lists (`and_tri_state(ROCE_passes, RevGrowth_passes)` and `and_tri_state(ROCEExCash_passes, RevGrowth_passes)`) is filtered to `passes == True` and shown as its own table (Symbol/Industry/`{ROCE or ROCEExCash} Y1`…`Y{years}`/`RevGrowth Y1`…`Y{years}`) with a pass-count caption, sharing one search box at the top of the tab — same "several small independent-looking sections" shape as `render_filter_tab`, but here the two sections are each a 2-metric combination rather than a single metric.
- At the default 15%/10%/10-years settings this is a very selective screen (as intended — matching the real-world rarity of true "Coffee Can" compounders); loosening `years` (e.g. to 5) sharply increases the pass count, confirming the window is being respected.

Both expanders' tables, and the ranking table, support the same search-box + `st.dataframe(..., on_select="rerun")` drill-through pattern as the SSGR tab (`drill_through()` helper).

### Market data (Price, Market Cap, P/E) — a second, faster cadence

Every screen above is built from `Raw data.xlsx`'s annual/quarterly financial sheets, which change ~once a year — the whole `universe_cache.csv` / **Refresh**-button design exists because that 53s computation is only worth redoing that rarely. Price-derived figures (Market Cap, P/E, and future screens built on them) don't fit that cadence — Price can change daily. Rather than force these into the once-a-year cache (making Price look stale for up to a year, or forcing a full 53s recompute just to update one number), the app uses **two cadences that only meet at a merge-by-Symbol join**:

- **Slow (fundamentals)** — unchanged: the once-a-year `universe_cache.csv` / **Refresh**-button pipeline, now also used by the Vijay Malik and Net-Net screens' latest-year snapshot columns (see below) — none of this touches Price.
- **Fast (Price/P·E/Market Cap)** — an optional `Market` sheet in the workbook (`Symbol`, `CMP`, `PE`, `Market cap (INR Cr)`, `Beta`), re-pasted from a data vendor as often as the user likes. **These three figures are read directly from the sheet, not derived** — deliberately: the vendor already knows real current shares outstanding and reported EPS, which this app can't reproduce as accurately from the annual workbook alone. `merge_market_data(universe, sheets)` (`data_loader.py`) left-merges `Market`'s `CMP`/`PE`/`Market cap (INR Cr)` onto the universe DataFrame by `Symbol`, renaming to `Price`/`PE`/`Market Cap (Cr)`. This function is **deliberately uncached** — a plain merge over ~2000 rows is fast enough to redo on every rerun, so `pages/screens.py` calls it right after resolving `universe` (cached or freshly built) and every tab downstream sees Price as of the workbook's last save, with no Refresh click needed for it. If `sheets` has no `"Market"` key, `merge_market_data` returns `Price`/`Market Cap (Cr)`/`PE` all `NaN` rather than raising, so the app works unchanged for a workbook that hasn't added the sheet yet. A `Market Cap (Cr)` of exactly `0` is masked to `NaN` too — a listed operating company can never have zero market cap, so this is treated as a vendor data-export artifact (seen in practice for a handful of symbols) rather than a real value; `Price`/`PE` are left as the vendor reports them.
- **Per-company (Data Explorer)** — `get_company_view()`'s new `_company_market_data()` helper does the same lookup for one symbol directly against `sheets["Market"]` (no need to route through the universe cache), returned as `view["market"] = {"price", "pe", "market_cap_cr"}` — same shape/spirit as the existing `view["ssgr_screen"]`. Shown as a small "Market" metrics row on the Data Explorer page, right after the Filters section.

**Note for whoever builds the next PE/Market-Cap screen**: unlike every `MOAT_METRIC_CONFIG` row, these are point-in-time values, not a 10-year `Y1`…`Y10` history — a screen built on them won't fit `render_screen_group_tab`/`render_filter_tab`'s shape and will need a bespoke renderer, the same way `render_ccp_tab()` did.

### Vijay Malik tab: a 5-check AND, on latest-year snapshots and 10Y CAGRs

The 5th tab, **Vijay Malik**, is a 5-parameter checklist (Sales CAGR >15%, Net Profit CAGR >30%, Debt/Equity <1, CFO positive, Market Cap >₹500 Cr) — all 5 must pass. Unlike every screen before it, none of its checks are a `Y1..Y10` consistency bar:

- `VIJAY_MALIK_CHECKS` (`data_loader.py`) is the single source of truth — a list of dicts (`key`, `label`, `column`, `direction`, `unit`, `default`), each naming one **already-scalar** column: `Rev 10Y CAGR (%)` and `Net 10Y CAGR (%)` (10-year CAGRs, computed once as a single value — same shape as `SSGR (%)`/`Rev 10Y CAGR (%)`, not a per-year series), `DebtEquity Latest (%)` and `CFO Latest (Cr)` (the latest completed fiscal year's value only — a snapshot, not a trend), and `Market Cap (Cr)` (from `merge_market_data`, point-in-time).
- **`scalar_metric_passes(values, threshold, direction)`** (new, generic) — the scalar equivalent of `metric_moat_passes`: tri-state pass/fail for a single-column-vs-fixed-threshold check, `pd.NA` where the value is missing.
- **`vijay_malik_passes(universe, thresholds)`** — applies `scalar_metric_passes` to each of the 5 `VIJAY_MALIK_CHECKS` and folds the results with `and_tri_state` (via `functools.reduce`) into one combined verdict. Returns `(per_check_dict, combined_series)` so both `render_vijay_malik_tab()` (the list) and `evaluate_screens_for_company()` (which sub-check named the failure) can reuse the same computation.
- All 5 thresholds are **fixed absolute benchmarks** (same rationale as CCP) — sliders (0–200%/0–300%) for the 3 percentage checks, `st.number_input` for CFO/Market Cap since those aren't 0–100%-bounded. Shadow-copied to `f"vm_{key}_saved"` session-state keys, same cross-page-sync fix as every other screen.
- `add_capex_and_ratios()` gained a `DebtEquity = Borr / NetWorth * 100` row (borrowings only, unlike `LiabEquity`'s `Borr + OL`) so Debt/Equity is also visible in the per-company Income Statement table. `get_company_view()`'s CAGR table now includes `Net` alongside `Rev/Exp/OP/PBIT/PBT`.

### Net-Net tab: Market Cap vs. Benjamin Graham's NCAV, two asset bases

The 6th tab, **Net-Net**, is structured like CCP: **two lists sharing one secondary filter**. A stock clears a list when `Market Cap (Cr) < (that list's NCAV column)` *and* `Market Cap (Cr)` is above a shared, UI-configurable floor.

- `NCAV` (Net Current Asset Value) = Current Assets − Total Liabilities excluding equity. The workbook has no granular Current Assets figure, so (matching `WC`'s existing OA-as-Current-Assets proxy) `NCAV = OA − (Borr + OL) = (OA − OL) − Borr = WC − Borr`. A second, more conservative basis, `NCAVCashInvRec = (Cash + Inv + Rec) − (Borr + OL)`, only counts cash, inventory and receivables as "current assets" — not all of `OA`'s other odds and ends. Both are computed in `add_roce()` (same function as `WC`/`ROCE`/`ROCEExCash` — `Inv`/`Rec` are pulled in alongside the rows it already reads) and cached as the latest-year scalars `NCAV Latest (Cr)` / `NCAVCashInvRec Latest (Cr)`, same pattern as `DebtEquity Latest (%)`/`CFO Latest (Cr)`.
- **`net_net_passes(universe, ncav_column)`** — tri-state, but *not* `scalar_metric_passes`: the "threshold" here is another column, not a constant, so it's a small dedicated comparison, parameterized by which NCAV column to use (`ncav_column`) so the same function serves both lists — the same "one comparison, two bases" shape `metric_moat_passes(..., "ROCE"/"ROCEExCash")` gives CCP. `pd.NA` if either `Market Cap (Cr)` or the chosen NCAV column is missing; a negative NCAV just fails naturally (Market Cap, always positive, can never be below a negative number) — no separate "NCAV > 0" gate needed. Requires `universe` to already have `Market Cap (Cr)` (i.e., called after `merge_market_data()`).
- A shared **Market Cap floor** (`st.number_input`, default `0.0` — off) filters out companies too small/illiquid to matter, *not* a ceiling — confirmed with the user, since true net-nets are almost always small caps and an unfiltered screen can otherwise surface untradeable micro-caps. Applied via `scalar_metric_passes(mcap, min_mcap, "higher")`, AND-ed with each list's `net_net_passes()` result via `and_tri_state` — exactly how CCP ANDs its two ROCE variants with one shared revenue-growth check. Shadow-copied to `"net_net_min_mcap_saved"`, same cross-page-sync fix as every other screen.
- `render_net_net_tab()` loops over the two `(label, ncav_column)` pairs (mirroring `render_ccp_tab`'s loop over its two `(label, roce_row)` pairs), showing only the passing companies per list, sorted by `Discount to NCAV (%)` (`(NCAV − Mcap) / NCAV * 100`, computed for display only, not cached) descending — biggest bargains first.

### Vantage tab: Sanjay Bakshi's banker's-valuation analysis

The 7th tab, **Vantage**, values a company the way a banker sizing up collateral would, then compares that valuation to the market price:

```
WA_CFO / WA_Interest = decay-weighted average of CFO / Int over the last 10 fiscal years (Y1 = latest,
                        weighs most; weight for the i-th year back = decay**(i-1))
Cashflow             = WA_CFO - WA_Interest
InterestServiceable  = Cashflow / 3                      (fixed divisor — not user-configurable, not asked)
Loan                 = InterestServiceable / lending_rate (rate as a decimal, e.g. 0.10 for 10%)
TotalValue           = Loan + Cash (latest year)
Multiple             = Market Cap (Cr) / TotalValue
Passes               = min_threshold < Multiple < max_threshold  (default 0.0 < Multiple < 1.0)
```

- **`weighted_average_by_year(universe, row_prefix, unit, decay, years=10)`** — generic decay-weighted average of `"{row_prefix} Y1 ({unit})"`..`"{row_prefix} Y{years} ({unit})"`; `NaN` if any of the `years` years is missing (same "needs the full window" convention as `metric_moat_passes`). `decay` is the single UI-configurable "recency weighting" control — deliberately one slider rather than 10 separate per-year weights, keeping this screen's UI in line with every other screen's couple-of-sliders footprint.
- **`build_universe_cache()`** now also caches `"Int Y1 (Cr)"`..`"Int Y10 (Cr)"` (from `income_statement`), `"CFO Y1 (Cr)"`..`"CFO Y10 (Cr)"` (from `balance_sheet` — not previously cached as a 10-year series, only `CFO Latest (Cr)` existed for Vijay Malik), and `"Cash Latest (Cr)"`. These are raw building blocks, not a precomputed average, because `decay` is user-adjustable — the pass/fail must recompute instantly on every rerun, not require a 53s Refresh every time the slider moves.
- **`vantage_metrics(universe, decay, rate, years=10)`** runs the whole pipeline above universe-wide in one shot (used by both `render_vantage_tab()` and `evaluate_screens_for_company()`, avoiding the duplicated-computation pattern CCP/Vijay Malik accept). `Multiple` is `_safe_divide(Market Cap (Cr), Total Value (Cr))` — deliberately **not masking a negative `TotalValue`**: a negative `Multiple` is exactly the "Loan swamps Cash" signal the pass condition's lower bound (`Multiple > 0`) is designed to catch, so it must survive to the comparison rather than becoming `NaN`.
- **The pass condition is a range, not a ceiling** — `min_threshold < Multiple < max_threshold`, both configurable (`st.number_input`, defaults `0.0`/`1.0`), computed as `and_tri_state(scalar_metric_passes(multiple, min_threshold, "higher"), scalar_metric_passes(multiple, max_threshold, "lower"))`. The lower bound exists specifically to rule out a negative `TotalValue` (a company whose debt-servicing capacity is so poor that `Loan` swamps `Cash`) ever numerically satisfying "Multiple < 1" and masquerading as cheap.
- **`company_vantage_metrics(income_statement, balance_sheet, price, decay, rate, years=10)`** is the per-company equivalent for Data Explorer — builds a one-row, universe-cache-shaped frame from that company's own tables and feeds it through `vantage_metrics()` itself (no duplicated math), then adds a `NOS`-based `value_per_share` and `price`-based `multiple` for display. This per-share `Multiple` and the universe-wide `Market Cap / TotalValue` `Multiple` are algebraically identical only if both sides use the same share count — the universe screen skips share counts entirely (simpler, no lag), while the per-company view uses the company's own `NOS` for a transparent, inspectable per-share breakdown; small divergences between the two are expected, same as the existing `NOS`-vs-vendor-implied-shares lag already accepted elsewhere in this app.
- **Assumption**: "Cash" is the `Cash` BS row alone, not `Cash + Invest` — same literal reading used everywhere else in this app.
- Shown on Data Explorer as a small **"Vantage"** metrics block (WA CFO, WA Interest, Loan, Total Value, Cashflow, Interest Serviceable, Value/Share, Multiple) — the one screen whose building blocks aren't otherwise visible anywhere else on the page, unlike e.g. Vijay Malik's checks which reuse existing IS/BS rows.

### Data Explorer's Filters section: one company vs. every screen

`pages/data_explorer.py` shows a **Filters** table (right after the company header, before the detailed financial tables) with a row for every screen across the whole app — SSGR + the 7 Moats + the 4 Nalanda's F filters + the 2 CCP lists + Vijay Malik + the 2 Net-Net lists + Vantage (18 rows) — giving that one company's verdict on each, and *why* it failed when it did.

- **`data_loader.py`'s `evaluate_screens_for_company(universe, symbol, overrides)`** does the actual work (kept there, not in the page, so it's covered by the test suite): looks up the one row for `symbol` in the universe cache and re-runs the exact same `industry_metric_thresholds()`/`metric_moat_passes()`/`and_tri_state()` calls `pages/screens.py` uses for the whole universe, just for that one row. `overrides` (a plain dict the page resolves from `st.session_state`, keeping this function itself UI-free) carries each screen's current threshold settings.
- **`failure_detail(values, threshold, direction, consistency)`** — new, pure/testable — turns a definite `False` verdict into a specific explanation: for `"all_years"`, the exact failing years and their values (e.g. `"fails in 2/10 year(s): Y3 (12.40%), Y7 (9.80%)"`); for `"median"`, the median vs. the threshold. For a CCP row (an AND of two sub-checks), `evaluate_screens_for_company` calls this once per failing sub-check and prefixes each with which one it is (`"ROCE: ..."` / `"Revenue growth: ..."`), so a CCP failure never just says "fails" without saying which side caused it.
- Reads `load_universe_cache()` directly (no recomputation) — if it's `None` (Screens page never run), shows a prompt instead of computing anything.

**Cross-page threshold sync, and a real Streamlit gotcha it works around**: the Filters section is meant to reflect whatever thresholds are *currently* set on the Screens page, not always the defaults. The obvious approach — reading the Screens page's own widget keys (`f"{key}_use_industry"`, `f"{key}_manual"`, `"ccp_roce_threshold"`, etc.) directly via `st.session_state.get(...)` — **does not work reliably**: widget-bound `session_state` entries can reset back to their `value=` default once that widget stops being instantiated on the currently-running page (e.g., after navigating to Data Explorer, then back to Screens), unlike a plain dict-style entry (like `jump_to_symbol`) which persists indefinitely. The fix: `render_threshold_controls()` and `render_ccp_tab()` shadow-copy each resolved value into a **plain, non-widget-bound key** on every run — `f"{config_key}_use_industry_saved"`, `f"{config_key}_manual_saved"`, `"ccp_roce_threshold_saved"`, `"ccp_growth_threshold_saved"`, `"ccp_years_saved"` — and `pages/data_explorer.py` reads *those* `_saved` keys, never the raw widget keys. Falls back to each screen's own default if the Screens page hasn't been visited this session yet (no `_saved` key exists).
