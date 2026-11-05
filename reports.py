"""HTML export for a single company's "report card" — the Market metrics,
Filters table (every screen's pass/fail) and Vantage/CAGR tables assembled
into one self-contained, downloadable snapshot for sharing outside the app.

No charts in this first cut: Altair's chart.to_html() emits a full
standalone document per chart (its own <html> wrapper + vega-embed script),
so concatenating the Trend charts would need one shared vega-embed script
with uniquely-id'd divs — extra complexity not worth bundling into v1.

Kept out of data_loader.py (no Streamlit UI logic there) and out of tables.py
(that module styles Streamlit-rendered DataFrames, not raw HTML strings) —
its own module, same rationale as charts.py/tables.py.
"""

import html as _html

import pandas as pd

from tables import STATUS_CRITICAL, STATUS_GOOD, STATUS_MUTED

_CSS = f"""
<style>
  body {{ font-family: -apple-system, Segoe UI, Arial, sans-serif; margin: 2rem; color: #1a1a1a; }}
  h1 {{ margin-bottom: 0; }}
  .subtitle {{ color: {STATUS_MUTED}; margin-top: 0.25rem; }}
  h2 {{ margin-top: 2rem; border-bottom: 1px solid #ddd; padding-bottom: 0.25rem; }}
  h3 {{ margin-top: 1.5rem; }}
  table {{ border-collapse: collapse; width: 100%; margin-top: 0.5rem; }}
  th, td {{ text-align: left; padding: 0.4rem 0.6rem; border-bottom: 1px solid #eee; font-size: 0.9rem; }}
  th {{ background: #fafafa; }}
  .metrics {{ display: flex; flex-wrap: wrap; gap: 1.5rem; margin: 0.5rem 0 1rem; }}
  .metric {{ min-width: 140px; }}
  .metric .label {{ color: {STATUS_MUTED}; font-size: 0.8rem; }}
  .metric .value {{ font-size: 1.25rem; font-weight: 600; }}
  .pass {{ color: {STATUS_GOOD}; font-weight: 600; }}
  .fail {{ color: {STATUS_CRITICAL}; font-weight: 600; }}
  .muted {{ color: {STATUS_MUTED}; }}
</style>
"""


def _fmt(value, suffix: str = "", decimals: int = 2) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    return f"{value:,.{decimals}f}{suffix}"


def _metrics_html(items: list[tuple[str, str]]) -> str:
    cells = "".join(
        f'<div class="metric"><div class="label">{_html.escape(label)}</div>'
        f'<div class="value">{_html.escape(value)}</div></div>'
        for label, value in items
    )
    return f'<div class="metrics">{cells}</div>'


def _filters_table_html(filters_table: pd.DataFrame) -> str:
    def _row_class(passes):
        if passes is True:
            return "pass"
        if passes is False:
            return "fail"
        return "muted"

    def _label(passes):
        if passes is True:
            return "✓ Pass"
        if passes is False:
            return "✗ Fail"
        return "—"

    if filters_table.empty:
        return '<p class="muted">Run the Screens page (click Refresh if it\'s never been run) to see this.</p>'

    rows = "".join(
        "<tr><td>{filt}</td><td>{group}</td><td class=\"{cls}\">{label}</td><td>{detail}</td></tr>".format(
            filt=_html.escape(str(r["Filter"])),
            group=_html.escape(str(r["Group"])),
            cls=_row_class(r["Passes"]),
            label=_label(r["Passes"]),
            detail=_html.escape(str(r["Detail"])),
        )
        for _, r in filters_table.iterrows()
    )
    return (
        "<table><thead><tr><th>Filter</th><th>Group</th><th>Passes</th><th>Detail</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )


def _cagr_table_html(title: str, table: pd.DataFrame) -> str:
    header = "".join(f"<th>{_html.escape(str(c))}</th>" for c in table.columns)
    rows = "".join(
        f"<tr><td>{_html.escape(str(row_name))}</td>"
        + "".join(f"<td>{_fmt(v, '%')}</td>" for v in table.loc[row_name])
        + "</tr>"
        for row_name in table.index
    )
    return f"<h3>{_html.escape(title)}</h3><table><thead><tr><th></th>{header}</tr></thead><tbody>{rows}</tbody></table>"


def build_company_report_html(
    symbol: str,
    industry: str,
    filters_table: pd.DataFrame,
    market: dict,
    vantage: dict,
    cagr: pd.DataFrame,
    quarterly_cagr: pd.DataFrame,
) -> str:
    """Self-contained HTML "report card" for one company: Market metrics,
    the Filters table (every screen's pass/fail), Vantage metrics, and both
    CAGR tables — everything Data Explorer already assembles for this
    company, minus the Trend charts (see module docstring). Status colors
    reuse tables.py's palette so Pass/Fail reads the same as in the app.
    """
    market_html = _metrics_html([
        ("Price (₹)", _fmt(market.get("price"))),
        ("Market Cap (₹ Cr)", _fmt(market.get("market_cap_cr"))),
        ("P/E", _fmt(market.get("pe"))),
    ])
    vantage_html = _metrics_html([
        ("WA CFO (₹ Cr)", _fmt(vantage.get("wa_cfo"))),
        ("WA Interest (₹ Cr)", _fmt(vantage.get("wa_interest"))),
        ("Loan (₹ Cr)", _fmt(vantage.get("loan"))),
        ("Total Value (₹ Cr)", _fmt(vantage.get("total_value"))),
        ("Value/Share (₹)", _fmt(vantage.get("value_per_share"))),
        ("Multiple", _fmt(vantage.get("multiple"))),
    ])

    symbol_safe = _html.escape(symbol)
    industry_safe = _html.escape(industry)

    return f"""<!doctype html>
<html>
<head><meta charset="utf-8"><title>{symbol_safe} — Report</title>{_CSS}</head>
<body>
  <h1>{symbol_safe}</h1>
  <p class="subtitle">{industry_safe}</p>

  <h2>Market</h2>
  {market_html}

  <h2>Filters</h2>
  {_filters_table_html(filters_table)}

  <h2>Vantage</h2>
  {vantage_html}

  <h2>CAGR</h2>
  {_cagr_table_html("Annual metrics", cagr)}
  {_cagr_table_html("Quarterly Revenue", quarterly_cagr)}
</body>
</html>
"""
