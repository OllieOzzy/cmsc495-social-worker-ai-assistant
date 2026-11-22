"""Render self-service password change for any signed-in account."""

import streamlit as st

from .api_client import request_api
from .auth_state import clear_session


def show_password_navigation() -> bool:
    """Open account settings without mixing them into report or admin forms."""
    if not st.session_state.get("auth_user"):
        return False
    selected = st.session_state.get("app_view") == "password"
    with st.sidebar:
        if st.button(
            "Back to reports" if selected else "Change password",
            key="password_settings",
            icon=":material/lock:",
        ):
            st.session_state["app_view"] = "reports" if selected else "password"
            st.rerun()
    return selected


def show_password_change() -> None:
    """Confirm the current password and a matching replacement before sending."""
    st.header("Change password")
    with st.form("change_own_password", clear_on_submit=True):
        current = st.text_input(
            "Current password",
            type="password",
            max_chars=1024,
            key="account_current_password",
        )
        replacement = st.text_input(
            "New password", type="password", max_chars=1024, key="account_new_password"
        )
        confirmation = st.text_input(
            "Confirm new password",
            type="password",
            max_chars=1024,
            key="account_password_confirmation",
        )
        st.caption(
            "Use 15–1,024 characters for the new password. Changing it signs you out of all sessions; sign in again with the new password."
        )
        submitted = st.form_submit_button(
            "Change password", icon=":material/lock_reset:"
        )
    if not submitted:
        return
    for key in (
        "account_current_password",
        "account_new_password",
        "account_password_confirmation",
    ):
        st.session_state.pop(key, None)
    if not current:
        st.error("Enter your current password.")
        return
    if replacement != confirmation:
        st.error("Passwords do not match.")
        return
    if not 15 <= len(replacement) <= 1024:
        st.error("New account passwords must contain 15 to 1024 characters.")
        return
    changed = request_api(
        "POST",
        "/auth/change-password",
        payload={"current_password": current, "new_password": replacement},
    )
    if changed is True:
        clear_session("Password changed. Please sign in with your new password.")
        st.rerun(scope="app")
