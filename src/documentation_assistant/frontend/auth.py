"""Render login and logout while gating report screens on a verified session."""

from time import monotonic

import streamlit as st

from .api_client import request_api
from .auth_state import clear_session, session_expired


def _expire_if_needed() -> None:
    """Clear cached report content and return to login at the session deadline."""
    if session_expired():
        clear_session("Your session expired. Please sign in again.")
        st.rerun(scope="app")


@st.fragment(run_every=60)
def check_session_expiry() -> None:
    """Verify local expiry and server-side validity while the page is idle."""
    _verify_idle_session()


def _valid_identity(user) -> bool:
    """Require the public identity fields used by navigation and report permissions."""
    return (
        isinstance(user, dict)
        and bool(user.get("user_id"))
        and bool(user.get("username"))
        and user.get("role") in ("user", "admin")
    )


def _accept_identity(user: dict) -> None:
    """Store verified identity, clearing private state if its access scope changed."""
    previous = st.session_state.get("auth_user", {})
    if any(previous.get(field) != user.get(field) for field in ("user_id", "role")):
        token = st.session_state["auth_token"]
        expires = st.session_state["auth_expires_at"]
        clear_session()
        st.session_state.update(
            auth_token=token,
            auth_expires_at=expires,
            auth_user=user,
            auth_verified_at=monotonic(),
        )
        st.rerun(scope="app")
    st.session_state.update(auth_user=user, auth_verified_at=monotonic())


def _verify_idle_session() -> None:
    """Reuse a recent full-page check; hide the full page if an idle check fails.

    request_api clears state on a 401. On an outage or malformed identity,
    force a full rerun so require_login hides cached screens and offers retry.
    The verification timestamp avoids a second request when the fragment is
    first registered immediately after the normal full-page authentication.
    """
    if not st.session_state.get("auth_token"):
        return
    _expire_if_needed()
    age = monotonic() - st.session_state.get("auth_verified_at", float("-inf"))
    if 0 <= age < 60:
        return
    user = request_api("GET", "/auth/me", timeout=3)
    if not _valid_identity(user):
        st.rerun(scope="app")
        return
    _accept_identity(user)


def _sign_out() -> None:
    """Try to revoke the server session, then always clear this browser's state."""
    revoked = request_api("POST", "/auth/logout")
    notice = (
        "Signed out."
        if revoked is True
        else "Signed out of this browser. The server could not confirm session revocation."
    )
    clear_session(notice)
    st.rerun(scope="app")


def _show_login() -> None:
    """Collect credentials without retaining a submitted password in widget state."""
    st.subheader("Sign in")
    with st.form("login", clear_on_submit=True):
        username = st.text_input("Username", max_chars=64, key="login_username")
        password = st.text_input(
            "Password", type="password", max_chars=1024, key="login_password"
        )
        submitted = st.form_submit_button("Sign in", icon=":material/login:")
    if not submitted:
        return
    if not username.strip() or not password:
        st.error("Enter your username and password.")
        return
    result = request_api(
        "POST", "/auth/login", payload={"username": username, "password": password}
    )
    if result is None:
        return
    if not (
        isinstance(result, dict)
        and isinstance(result.get("access_token"), str)
        and result["access_token"]
        and isinstance(result.get("expires_at"), str)
        and isinstance(result.get("user"), dict)
        and result["user"].get("user_id")
        and result["user"].get("role") in ("user", "admin")
    ):
        st.error("The report server returned an invalid login response.")
        return
    clear_session()
    st.session_state.update(
        auth_token=result["access_token"],
        auth_expires_at=result["expires_at"],
        auth_user=result["user"],
    )
    _expire_if_needed()
    st.rerun()


def require_login() -> bool:
    """Verify identity on every full rerun before rendering any report content.

    A backend outage keeps credentials for retry, but does not render reports.
    A 401 clears them in request_api. Role changes clear cached report state.
    """
    if notice := st.session_state.pop("auth_notice", None):
        st.info(notice)
    if not st.session_state.get("auth_token"):
        _show_login()
        return False
    with st.sidebar:
        st.html("""
            <style>
            .st-key-sign_out button {
                background-color: #b42318;
                border-color: #b42318;
                color: #ffffff;
            }
            .st-key-sign_out button:hover,
            .st-key-sign_out button:focus-visible {
                background-color: #912018;
                border-color: #912018;
                color: #ffffff;
            }
            </style>
        """)
        if st.button("Sign out", key="sign_out", icon=":material/logout:"):
            _sign_out()
    _expire_if_needed()
    user = request_api("GET", "/auth/me", timeout=3)
    if not _valid_identity(user):
        st.warning(
            "Your session could not be verified. Check the backend and try again."
        )
        if st.button("Retry sign in status", key="retry_session"):
            st.rerun()
        return False
    _accept_identity(user)
    with st.sidebar:
        st.caption(
            f"Signed in as {user.get('display_name', user['username'])} · {user['role']}"
        )
    check_session_expiry()
    return True
