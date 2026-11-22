"""Route Streamlit between reports, admin account management, and team contacts."""

from urllib.parse import urlsplit

import streamlit as st

from documentation_assistant.frontend.account import (
    show_password_change,
    show_password_navigation,
)
from documentation_assistant.frontend.auth import require_login
from documentation_assistant.frontend.reports import (
    new_report,
    open_report,
    review_report,
)
from documentation_assistant.frontend.sidebar import show_sidebar
from documentation_assistant.frontend.users import (
    show_admin_navigation,
    show_user_management,
)

ABOUT = """## DAP Documentation Assistant

AI-powered documentation assistant for school social workers, developed as a UMGC CMSC 495 capstone project.
"""

menu_items = {"About": ABOUT}
# Use Streamlit's built-in Report a bug menu item to open team contacts.
if app_url := st.context.url:
    menu_items["Report a bug"] = (
        urlsplit(app_url)._replace(query="view=contacts", fragment="").geturl()
    )

st.set_page_config(
    page_title="DAP Documentation Assistant",
    layout="wide",
    initial_sidebar_state=420,
    menu_items=menu_items,
)

# Serve the contacts page before rendering report navigation.
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

if not require_login():
    st.stop()

with st.sidebar, st.container(horizontal=True, gap="small"):
    password_view = show_password_navigation()
    users_view = show_admin_navigation()

if password_view:
    show_password_change()
    st.stop()

if users_view:
    show_user_management()
    st.stop()

show_sidebar()

# Consume the notice so it appears only on the next rerun.
report_notice = st.session_state.pop("report_notice", None)
if report_notice:
    st.success(report_notice)

if "report" in st.session_state:
    review_report(st.session_state["report"])
elif pending_report_id := st.session_state.get("pending_report_id"):
    # Reuse the saved report ID after the initial fetch fails.
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
