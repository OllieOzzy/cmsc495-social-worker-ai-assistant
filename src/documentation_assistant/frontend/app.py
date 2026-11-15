"""Start the Streamlit app for the DAP documentation assistant."""

import streamlit as st

from documentation_assistant.frontend.reports import (
    new_report,
    open_report,
    review_report,
)
from documentation_assistant.frontend.sidebar import show_sidebar

st.set_page_config(page_title="DAP Documentation Assistant", layout="wide")

st.title("DAP Documentation Assistant")

show_sidebar()

report_notice = st.session_state.pop("report_notice", None)
if report_notice:
    st.success(report_notice)

if "report" in st.session_state:
    review_report(st.session_state["report"])
elif pending_report_id := st.session_state.get("pending_report_id"):
    st.warning("Your draft was saved, but it could not be opened.")
    st.html("""
        <style>
        .st-key-retry_opening_draft button {
            background-color: #f7dc82;
            border-color: #b08a19;
            color: #2c2100;
        }
        .st-key-retry_opening_draft button:hover {
            background-color: #f2ce62;
            border-color: #8a6911;
            color: #2c2100;
        }
        </style>
    """)
    if st.button("Retry opening draft", key="retry_opening_draft"):
        open_report(pending_report_id)
else:
    new_report()
