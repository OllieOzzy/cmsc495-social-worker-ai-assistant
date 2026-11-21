"""Sign in legacy workflow tests through the real authentication API.

Permission-boundary tests use plain TestClient with explicit per-user tokens.
This helper supplies one administrator to existing report/PDF/AI workflows;
it does not override production dependencies or disable permission checks.
"""

from functools import cache

from fastapi.testclient import TestClient

from documentation_assistant.backend.auth.passwords import hash_password
from documentation_assistant.backend.db.users import create_user, get_user_by_username

_PASSWORD = "Synthetic workflow account password!"


@cache
def _password_hash():
    """Reuse a synthetic account hash to keep unrelated workflow tests fast."""
    return hash_password(_PASSWORD)


class AuthenticatedTestClient(TestClient):
    """Run startup, provision one test admin if needed, and perform a real login."""

    def __enter__(self):
        super().__enter__()
        try:
            path = self.app.state.database_path
            self.account = get_user_by_username(path, "workflow-admin")
            if self.account is None:
                self.account = create_user(
                    path,
                    username="workflow-admin",
                    display_name="Taylor Example",
                    password_hash=_password_hash(),
                    role="admin",
                )
            response = self.post(
                "/auth/login",
                json={"username": self.account.username, "password": _PASSWORD},
            )
            response.raise_for_status()
            self.headers["Authorization"] = f"Bearer {response.json()['access_token']}"
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise
