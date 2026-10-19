import pandas as pd
import streamlit as st

STATUS_GOOD = "#0ca30c"
STATUS_CRITICAL = "#d03b3b"
STATUS_MUTED = "#898781"

PERCENT_FORMAT = "%.2f%%"
CURRENCY_FORMAT = "₹ %,.2f"


def style_tri_state(df, columns):
    """Color + label True/False/pd.NA columns as a fixed status badge (green
    "Pass" / red "Fail" / gray "—") instead of raw True/False/<NA> text —
    status always carries an icon + label, never color alone.

    Takes the DataFrame itself (not a Styler) and replaces each column's
    values with the label strings directly, then colors by those strings —
    rather than leaving the original True/False/pd.NA values in place and
    relying on Styler.format() to transform the display text, since
    Streamlit's dataframe renderer doesn't reliably apply format()'s na_rep
    for every pd.NA cell. Returns a Styler, ready for st.dataframe(...).
    """
    def _label(v):
        if v is True:
            return "✓ Pass"
        if v is False:
            return "✗ Fail"
        return "—"

    def _color(v):
        if v == "✓ Pass":
            return f"color: {STATUS_GOOD}; font-weight: 600"
        if v == "✗ Fail":
            return f"color: {STATUS_CRITICAL}; font-weight: 600"
        return f"color: {STATUS_MUTED}"

    labeled = df.copy()
    for c in columns:
        labeled[c] = labeled[c].map(_label)
    return labeled.style.map(_color, subset=columns)


def tri_state_column_config(columns):
    """column_config override for tri-state columns: st.dataframe otherwise
    auto-detects a True/False/pd.NA column as boolean and renders its own
    checkbox widget, which ignores style_tri_state's text/color entirely —
    forcing a plain TextColumn is what lets the "✓ Pass"/"✗ Fail"/"—" labels
    and their color actually show up. Merge this into the caller's own
    column_config dict (e.g. alongside a Score ProgressColumn).
    """
    return {c: st.column_config.TextColumn() for c in columns}


def style_diverging(styler, columns):
    """Color a numeric gain/loss-style column green/red/gray by sign."""
    def _color(v):
        if pd.isna(v):
            return f"color: {STATUS_MUTED}"
        if v > 0:
            return f"color: {STATUS_GOOD}"
        if v < 0:
            return f"color: {STATUS_CRITICAL}"
        return f"color: {STATUS_MUTED}"

    return styler.map(_color, subset=columns)
