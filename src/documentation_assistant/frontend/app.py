"""Start the Streamlit app for the DAP documentation assistant."""

import streamlit as st

from documentation_assistant.frontend.reports import new_report, open_report, review_report
from documentation_assistant.frontend.sidebar import show_sidebar

st.set_page_config(page_title="DAP Documentation Assistant", layout="wide")

st.title("DAP Documentation Assistant")

show_sidebar()

report_notice = st.session_state.pop("report_notice", None)
if report_notice:
    st.success(report_notice)

if "report" in st.session_state:
    review_report(st.session_state["report"])
else:
    new_report()
