"""Start the Streamlit app for the DAP documentation assistant."""

from urllib.parse import urlsplit

import streamlit as st

from documentation_assistant.frontend.reports import (
    new_report,
    open_report,
    review_report,
)
from documentation_assistant.frontend.sidebar import show_sidebar

ABOUT = """## DAP Documentation Assistant

AI-powered documentation assistant for school social workers, developed as a UMGC CMSC 495 capstone project.
"""

menu_items = {"About": ABOUT}
if app_url := st.context.url:
    menu_items["Report a bug"] = (
        urlsplit(app_url)._replace(query="view=contacts", fragment="").geturl()
    )

st.set_page_config(
    page_title="DAP Documentation Assistant", layout="wide", menu_items=menu_items
)

if st.query_params.get("view") == "contacts":
    st.title("Contacts")
    st.markdown(
        """
- **Oliver Sung** — Lead Architect
- **Robert Williams** — Interface Designer
- **Mikia Robinson** — Integration Lead
"""
    )
    if st.button("Back to reports", icon=":material/arrow_back:"):
        del st.query_params["view"]
        st.rerun()
    st.stop()

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
