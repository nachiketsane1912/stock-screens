import streamlit as st

st.set_page_config(page_title="Stock Fundamentals Explorer", layout="wide")

pg = st.navigation([
    st.Page("pages/data_explorer.py", title="Data Explorer", icon="🔍"),
    st.Page("pages/screens.py", title="Screens", icon="🧮"),
    st.Page("pages/portfolio.py", title="Portfolio", icon="💼"),
    st.Page("pages/macro.py", title="Macro", icon="🌐"),
])
pg.run()
