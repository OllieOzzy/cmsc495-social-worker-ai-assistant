"""Render administrator account management without retaining password form data."""

import streamlit as st

from .api_client import request_api
from .audit import show_audit_history
from .auth_state import clear_session, is_admin

_PAGE_SIZE = 25


def show_admin_navigation() -> bool:
    """Toggle an admin-only screen while keeping the selected saved report."""
    if not is_admin():
        st.session_state.pop("app_view", None)
        return False
    selected = st.session_state.get("app_view") == "users"
    with st.sidebar:
        if st.button(
            "Back to reports" if selected else "Manage users",
            key="manage_users",
            icon=":material/manage_accounts:",
        ):
            st.session_state["app_view"] = "reports" if selected else "users"
            st.rerun()
    return selected


def _reset_user_search() -> None:
    """Start at the first result and discard selection from the previous search."""
    st.session_state["users_offset"] = 0
    st.session_state.pop("managed_user_id", None)


def _clear_user_search() -> None:
    """Clear the search widget before the next render and restore all accounts."""
    st.session_state["users_search"] = ""
    _reset_user_search()


def show_user_management() -> None:
    """List a bounded page of accounts, create accounts, and change activation."""
    if not is_admin():
        st.error("Administrator access required.")
        return
    st.header("Manage users")
    st.toggle("Show audit history", key="show_user_audit")
    if st.session_state.get("show_user_audit", False):
        show_audit_history()
        return
    if notice := st.session_state.pop("user_management_notice", None):
        st.success(notice)
    st.text_input(
        "Search accounts",
        key="users_search",
        max_chars=200,
        placeholder="Username or display name",
        on_change=_reset_user_search,
    )
    search = st.session_state.get("users_search", "").strip()
    st.button("Clear search", disabled=not search, on_click=_clear_user_search)
    offset = st.session_state.get("users_offset", 0)
    params = {"limit": _PAGE_SIZE + 1, "offset": offset}
    if search:
        params["search"] = search
    users = request_api("GET", "/users", params=params)
    if users is None:
        if st.button("Refresh users"):
            st.rerun()
        return
    visible = users[:_PAGE_SIZE]
    if not visible:
        st.info("No matching accounts." if search else "No accounts found.")
    st.dataframe(
        [
            {
                "Username": user["username"],
                "Display name": user["display_name"],
                "Role": user["role"],
                "Status": "Active" if user["is_active"] else "Inactive",
            }
            for user in visible
        ],
        hide_index=True,
    )
    with st.container(horizontal=True):
        previous = st.button("Previous users", disabled=offset == 0)
        next_page = st.button("Next users", disabled=len(users) <= _PAGE_SIZE)
    if previous or next_page:
        st.session_state["users_offset"] = (
            max(0, offset - _PAGE_SIZE) if previous else offset + _PAGE_SIZE
        )
        st.rerun()
    _create_account_form()
    if visible:
        _account_status_form(visible)


def _create_account_form() -> None:
    """Submit a password once; ordinary accounts use the CLI's 15-character policy."""
    with st.expander("Create account"), st.form("create_account", clear_on_submit=True):
        username = st.text_input("Username", max_chars=64, key="new_username")
        display_name = st.text_input(
            "Display name", max_chars=200, key="new_display_name"
        )
        role = st.selectbox("Role", ("user", "admin"), key="new_user_role")
        password = st.text_input(
            "Password", type="password", max_chars=1024, key="new_password"
        )
        confirmation = st.text_input(
            "Confirm password",
            type="password",
            max_chars=1024,
            key="new_password_confirmation",
        )
        st.caption(
            "Passwords: 15–1,024 characters. Usernames: 3–64 characters, starting with a letter or number; periods, hyphens, and underscores are allowed."
        )
        create = st.form_submit_button("Create account", icon=":material/person_add:")
    if not create:
        return
    st.session_state.pop("new_password", None)
    st.session_state.pop("new_password_confirmation", None)
    if not username.strip() or not display_name.strip():
        st.error("Enter a username and display name.")
        return
    if password != confirmation:
        st.error("Passwords do not match.")
        return
    if not 15 <= len(password) <= 1024:
        st.error("New account passwords must contain 15 to 1024 characters.")
        return
    created = request_api(
        "POST",
        "/users",
        payload={
            "username": username,
            "display_name": display_name,
            "role": role,
            "password": password,
        },
    )
    if created is not None:
        st.session_state["users_offset"] = 0
        st.session_state["user_management_notice"] = (
            f"Created account: {created['username']}."
        )
        st.rerun()


def _account_status_form(users: list[dict]) -> None:
    """Select outside the form so its active checkbox follows the chosen account."""
    st.subheader("Account status")
    choices = {user["user_id"]: user for user in users}
    selected = st.selectbox(
        "Account",
        list(choices),
        format_func=lambda user_id: choices[user_id]["username"],
        key="managed_user_id",
    )
    account = choices[selected]
    own_account = selected == st.session_state["auth_user"]["user_id"]
    with st.form(f"status_{selected}_{account['is_active']}"):
        active = st.checkbox(
            "Account active", value=account["is_active"], disabled=own_account
        )
        st.caption(
            "Deactivation signs the user out and preserves their reports. Reactivation requires a new sign-in."
        )
        if own_account:
            st.caption("You cannot deactivate your own account.")
        change = st.form_submit_button("Save account status", disabled=own_account)
    if change:
        updated = request_api(
            "PATCH", f"/users/{selected}", payload={"is_active": active}
        )
        if updated is not None:
            st.session_state["user_management_notice"] = (
                f"Updated account: {updated['username']}."
            )
            st.rerun()
    _role_change_form(account)
    _rename_account_form(account)
    _password_reset_form(account)


def _role_change_form(account: dict) -> None:
    """Confirm permission changes and clear the current session after self-demotion."""
    user_id = account["user_id"]
    roles = ("user", "admin")
    with st.expander("Change role"), st.form(f"role_{user_id}_{account['role']}"):
        role = st.selectbox("New role", roles, index=roles.index(account["role"]))
        acknowledged = st.checkbox(
            "I understand this changes permissions and signs the user out of all sessions"
        )
        st.caption(
            "Admins can view all reports and approve or reopen them. The last active admin cannot be demoted. Changing a role does not activate an inactive account."
        )
        saved = st.form_submit_button(
            "Save role", icon=":material/admin_panel_settings:"
        )
    if not saved:
        return
    if role == account["role"]:
        st.info("No role change selected.")
        return
    if not acknowledged:
        st.error("Confirm the permission change and sign-out of all sessions.")
        return
    updated = request_api("PATCH", f"/users/{user_id}/role", payload={"role": role})
    if updated is not None:
        if user_id == st.session_state["auth_user"]["user_id"]:
            clear_session("Role updated. Please sign in again.")
        else:
            st.session_state["user_management_notice"] = (
                f"Updated role for {updated['username']}: {updated['role']}. Existing sessions were signed out."
            )
        st.rerun(scope="app")


def _rename_account_form(account: dict) -> None:
    """Confirm session revocation only when the normalized username changes."""
    user_id = account["user_id"]
    # Saved names are part of the form identity, so external changes reset it.
    form_key = f"rename_{user_id}_{account['username']}_{account['display_name']}"
    with st.expander("Rename account"), st.form(form_key):
        username = st.text_input(
            "New username", value=account["username"], max_chars=64
        )
        display_name = st.text_input(
            "New display name", value=account["display_name"], max_chars=200
        )
        acknowledged = st.checkbox(
            "I understand a username change signs the user out of all sessions"
        )
        st.caption(
            "Usernames must be unique. Display-name changes keep sessions active. Reports and historical approver names are preserved."
        )
        saved = st.form_submit_button("Save account names", icon=":material/edit:")
    if not saved:
        return
    if not username.strip() or not display_name.strip():
        st.error("Enter a username and display name.")
        return
    username_changed = username.strip().lower() != account["username"]
    if username_changed and not acknowledged:
        st.error("Confirm that a username change signs out all sessions.")
        return
    changes = {}
    if username_changed:
        changes["username"] = username
    if display_name.strip() != account["display_name"]:
        changes["display_name"] = display_name
    if not changes:
        st.info("No account details changed.")
        return
    updated = request_api("PATCH", f"/users/{user_id}/profile", payload=changes)
    if updated is not None:
        own_account = user_id == st.session_state["auth_user"]["user_id"]
        if own_account and username_changed:
            clear_session("Username updated. Please sign in with your new username.")
        else:
            if own_account:
                st.session_state["auth_user"] = updated
            st.session_state["users_offset"] = 0
            st.session_state["user_management_notice"] = (
                f"Updated account names: {updated['username']}."
            )
        st.rerun(scope="app")


def _password_reset_form(account: dict) -> None:
    """Require a confirmed replacement password and acknowledgement of session revocation."""
    user_id = account["user_id"]
    password_key = f"reset_password_{user_id}"
    confirmation_key = f"reset_password_confirmation_{user_id}"
    with (
        st.expander("Reset password"),
        st.form(f"reset_password_form_{user_id}", clear_on_submit=True),
    ):
        password = st.text_input(
            "New password", type="password", max_chars=1024, key=password_key
        )
        confirmation = st.text_input(
            "Confirm new password",
            type="password",
            max_chars=1024,
            key=confirmation_key,
        )
        acknowledged = st.checkbox(
            "I understand this signs the user out of all sessions"
        )
        st.caption(
            "Use 15–1,024 characters. This does not change the account's role or activation status."
        )
        if user_id == st.session_state["auth_user"]["user_id"]:
            st.caption("Resetting your own password will sign you out too.")
        submitted = st.form_submit_button(
            "Reset password", icon=":material/lock_reset:"
        )
    if not submitted:
        return
    st.session_state.pop(password_key, None)
    st.session_state.pop(confirmation_key, None)
    if not acknowledged:
        st.error("Confirm that you understand all sessions will be signed out.")
        return
    if password != confirmation:
        st.error("Passwords do not match.")
        return
    if not 15 <= len(password) <= 1024:
        st.error("New account passwords must contain 15 to 1024 characters.")
        return
    updated = request_api(
        "POST", f"/users/{user_id}/reset-password", payload={"password": password}
    )
    if updated is not None:
        if user_id == st.session_state["auth_user"]["user_id"]:
            clear_session("Password reset. Please sign in with your new password.")
        else:
            st.session_state["user_management_notice"] = (
                f"Password reset for {updated['username']}. Existing sessions were signed out."
            )
        st.rerun(scope="app")
