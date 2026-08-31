# Stock Fundamentals Explorer

A Streamlit app for exploring the fundamentals of a universe of stocks (quarterly and annual financials, balance sheets, derived ratios) and screening them against a set of quality/moat criteria — all driven from a single Excel workbook.

## Features

- **Data Explorer** — search companies by symbol or industry, then drill into one company's quarterly financials, annual income statement, and balance sheet, plus derived metrics: OP, OPM, PBIT, PBT, NPM, EPS, TTM figures, CAGR (1/3/5/10 years and 1/3/5/10 quarters), SSGR, capex/debt/equity ratios, and ROCE.
- **Screens** — run the same metrics across the entire universe of companies:
  - **SSGR** — Self-Sustainable Growth Rate vs. 10-year revenue CAGR (did the company grow organically, without needing external capital?).
  - **Moats** — 7 quality screens (Operating Margin, Net Margin, Interest/Operating Profit, Capex/Revenue, Capex/Net Income, Liabilities/Equity, ROE), each checked for consistency over the last 10 fiscal years, with a combined 0–7 score and ranking.
  - **Nalanda's F** — 4 ROCE-based filters (ROCE and ROCE excluding excess cash and investments, each checked as a 10-year median and as an every-year-of-10 bar), against a manual threshold.
  - **CCP (Coffee Can Portfolio)** — ROCE (regular and excluding excess cash) AND revenue growth, both above a bar every year for a configurable number of years. Two lists, fixed absolute thresholds.
  - **Vijay Malik** — a 5-parameter checklist: Sales CAGR, Net Profit CAGR (both 10-year), Debt/Equity and CFO (latest year), and Market Cap — all 5 must pass.
  - **Net-Net** — Benjamin Graham's screen: Market Cap below Net Current Asset Value (current assets minus total liabilities excluding equity). Two lists (one using all current assets, one using only Cash + Inventory + Receivables) sharing a configurable minimum Market Cap floor — sorted by biggest discount to NCAV first.
  - Moats thresholds default to your own industry peers' percentile, with a manual override slider; every other screen uses fixed/manual thresholds only (no industry-relative option). Click any row in a results table to jump straight to that company in the Data Explorer.
  - **Data Explorer** also shows a **Filters** section: every screen's pass/fail verdict for the one company you're viewing, with the specific reason for any failure.
  - An optional **Market** sheet (see below) supplies live Price/P·E/Market Cap, used by the Vijay Malik and Net-Net screens and shown on the Data Explorer page.

## Getting started

### Prerequisites

- Python 3.10+
- Your own `Raw data.xlsx` workbook in the project root (see [Data file format](#data-file-format) below) — this file is **not included in the repo**.

### Install

```bash
pip install -r requirements.txt
```

### Run

```bash
streamlit run app.py
```

This opens the app at `http://localhost:8501`. The first time you open the **Screens** page, it computes results across the whole universe of companies (~1 minute for ~2000 companies) and caches them to `universe_cache.csv`; every later visit loads instantly from that cache until you click **Refresh**.

### Run the tests

```bash
pytest tests/ -v
```

## Data file format

The app reads everything from one Excel workbook, **`Raw data.xlsx`**, placed in the project root. It must contain five sheets: `Industry`, `Quarter`, `IS`, `BS`, `Macro`, plus an optional sixth, `Market`. The literal string `"NA"` anywhere in the workbook is treated as a missing value.

### `Industry` sheet

One row per company:

| Symbol | Industry |
|---|---|
| AAVAS | Banking Services |
| AARTIDRUGS | Pharmaceuticals |

### `Quarter`, `IS`, `BS` sheets ("wide" format)

One row per company (`Symbol` is the first column), with every other column named `Metric-Period`:

- In `Quarter`, `Period` looks like `Q127` (Q1 of FY27), `Q426` (Q4 of FY26), etc.
- In `IS` and `BS`, `Period` is just the two-digit fiscal year, e.g. `26` for FY26.
- **Columns must be ordered most-recent period first** — the app relies on column position (not the period label) to find "1 year ago," "the last 4 quarters," etc.

Example `IS` row:

| Symbol | Rev-26 | Rev-25 | Exp-26 | Exp-25 | Net-26 | Net-25 | ... |
|---|---|---|---|---|---|---|---|
| AAVAS | 2683.46 | 2354.51 | 706.45 | 581.91 | 654.88 | 574.11 | ... |

**Metric prefixes** (`Quarter` and `IS` share the first six; `BS` is separate):

| Prefix | Meaning | Sheet(s) | Units |
|---|---|---|---|
| `Rev` | Revenue | Quarter, IS | ₹ crore |
| `Exp` | Total expenses | Quarter, IS | ₹ crore |
| `OI` | Other income | Quarter, IS | ₹ crore |
| `Int` | Interest expense | Quarter, IS | ₹ crore |
| `Dep` | Depreciation | Quarter, IS | ₹ crore |
| `Net` | Net profit | Quarter, IS | ₹ crore |
| `Div` | Dividend | IS only | ₹ crore |
| `Eq` | Equity share capital | BS | ₹ crore |
| `Res` | Reserves | BS | ₹ crore |
| `Borr` | Borrowings | BS | ₹ crore |
| `OL` | Other liabilities | BS | ₹ crore |
| `NB` | Net block (fixed assets) | BS | ₹ crore |
| `WIP` | Capital work-in-progress | BS | ₹ crore |
| `Invest` | Investments | BS | ₹ crore |
| `OA` | Other assets | BS | ₹ crore |
| `Rec` | Receivables | BS | ₹ crore |
| `Inv` | Inventory | BS | ₹ crore |
| `Cash` | Cash & equivalents | BS | ₹ crore |
| `NOS` | Number of shares outstanding | BS | **absolute count, not crore** |
| `CFO` / `CFI` / `CFF` | Cash flow from operating / investing / financing activities | BS | ₹ crore |

> **Important:** `Rec`, `Inv` and `Cash` are informational sub-breakdowns already folded into `OA` — don't expect `OA` to equal `Rec + Inv + Cash + other assets` on top of itself; `OA` **is** the total, and `NB + WIP + Invest + OA` should balance against `Eq + Res + Borr + OL` (Total Assets = Total Liabilities).

### `Market` sheet (optional)

One row per company — typically pasted straight from a data vendor export, as often as you like (daily, if you want current P/E and Market Cap):

| Symbol | CMP | PE | Market cap (INR Cr) | Beta |
|---|---|---|---|---|
| AAVAS | 1450.5 | 22.3 | 11800.0 | 0.9 |

- `CMP`, `PE`, and `Market cap (INR Cr)` are read directly, as-is — the app doesn't recompute them from the annual financials (your vendor's numbers already reflect actual current shares outstanding and reported EPS, which this app can't reproduce as accurately). `Beta` isn't currently used by any screen.
- There's no date column — the app always uses whatever was last saved, so staleness is on you to manage, unlike the annual/quarterly sheets.
- If this sheet is missing entirely, or a symbol isn't in it, Price/Market Cap/P·E just show as unavailable — nothing else in the app depends on it.

### `Macro` sheet

One row per macro parameter, with one column per date:

| Parameter | 2026-07-01 | 2026-06-01 | ... |
|---|---|---|---|
| Repo Rate | 6.5 | 6.5 | ... |

## Project structure

```
app.py                    # multipage entrypoint (navigation only)
data_loader.py             # all data loading, reshaping, and derived-metric/screen logic
pages/
  data_explorer.py          # per-company exploration page
  screens.py                 # universe-wide screens page (SSGR, Moats, Nalanda's F, CCP, Vijay Malik, Net-Net)
tests/
  test_data_loader.py        # unit + integration tests, using hand-built synthetic sheets
requirements.txt
CLAUDE.md                   # detailed architecture notes (formulas, caching, etc.)
```

For a deeper dive into how each metric and screen is computed, see `CLAUDE.md`.

## Notes

- `Raw data.xlsx` and the generated `universe_cache.csv` / `ssgr_screen_cache.csv` are gitignored — they're either personal data or regenerable, not source code.
- If the workbook's data changes (new year, new companies) or the app's screen logic changes, click **Refresh** on the Screens page to recompute the cache — otherwise a schema mismatch will raise an error.
