"""Exercise idle session checks with Streamlit state and real backend revocation."""

import pytest
from streamlit.testing.v1 import AppTest

from documentation_assistant.backend.db.users import (
    create_user,
    rename_user,
    reset_user_password,
    set_user_active,
    set_user_role,
)
from tests.integration.test_user_management_api import PASSWORD, encoded_password

HEARTBEAT_PAGE = """
import streamlit as st
from documentation_assistant.frontend.auth import _verify_idle_session
_verify_idle_session()
if 'report' in st.session_state:
    st.text_area('Cached report', st.session_state['report']['notes'])
else:
    st.caption('Sign in to view reports.')
"""


@pytest.mark.parametrize(
    "reason", ["logout", "deactivate", "password_reset", "rename", "role_change"]
)
def test_idle_heartbeat_clears_revoked_session_without_report_action(
    backend_for_ui, reason
):
    """The idle callback itself detects 401 and removes cached reports and credentials."""
    path = backend_for_ui.app.state.database_path
    user = create_user(
        path,
        username="heartbeat-user",
        display_name="Synthetic User",
        password_hash=encoded_password(),
    )
    login = backend_for_ui.post(
        "/auth/login", json={"username": user.username, "password": PASSWORD}
    ).json()
    headers = {"Authorization": f"Bearer {login['access_token']}"}
    app = AppTest.from_string(HEARTBEAT_PAGE, default_timeout=15)
    for key, value in {
        "auth_token": login["access_token"],
        "auth_expires_at": login["expires_at"],
        "auth_user": login["user"],
        "auth_verified_at": 0,
        "report": {"notes": "Synthetic cached report."},
        "prepared_pdf": b"synthetic",
    }.items():
        app.session_state[key] = value
    app.run()
    assert not app.exception, app.exception
    assert app.text_area[0].value == "Synthetic cached report."
    if reason == "logout":
        backend_for_ui.post("/auth/logout", headers=headers).raise_for_status()
    elif reason == "deactivate":
        set_user_active(path, user.user_id, is_active=False)
    elif reason == "password_reset":
        reset_user_password(path, user.user_id, password_hash=encoded_password())
    elif reason == "rename":
        rename_user(path, user.user_id, username="renamed-user")
    else:
        set_user_role(path, user.user_id, role="admin")
    app.session_state["auth_verified_at"] = 0
    app.run()
    assert not app.exception, app.exception
    assert not app.text_area
    assert "auth_token" not in app.session_state
    assert "report" not in app.session_state
    assert "prepared_pdf" not in app.session_state
