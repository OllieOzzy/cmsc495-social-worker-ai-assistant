"""Exercise real password verification and SQLite sessions through FastAPI."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from documentation_assistant.backend.auth import service
from documentation_assistant.backend.auth.passwords import hash_password
from documentation_assistant.backend.db.connection import connect, initialize_database
from documentation_assistant.backend.db.sessions import reserve_login_attempt
from documentation_assistant.backend.db.users import create_user
from documentation_assistant.backend.main import create_app

PASSWORD = "A sufficiently long test password!"


@pytest.fixture
def auth_database(monkeypatch, tmp_path):
    """Provision accounts in an isolated database and use a controllable clock."""
    path = tmp_path / "auth.db"
    monkeypatch.setenv("DAP_DB_PATH", str(path))
    initialize_database(path)
    encoded_hash = hash_password(PASSWORD)
    for username, role in (("user", "user"), ("admin", "admin")):
        create_user(
            path,
            username=username,
            display_name=username.title(),
            password_hash=encoded_hash,
            role=role,
        )
    clock = [1_800_000_000]
    monkeypatch.setattr(service, "time", lambda: clock[0])
    return path, clock


@pytest.fixture
def client(auth_database):
    """Run application startup and shutdown without a separate HTTP server."""
    with TestClient(create_app()) as opened:
        yield opened


def sign_in(client, username="user", password=PASSWORD):
    """Send synthetic credentials to the real login endpoint."""
    return client.post("/auth/login", json={"username": username, "password": password})


def authorization(token):
    """Attach a token to one request rather than modifying shared client headers."""
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.parametrize("username, role", [(" USER ", "user"), ("admin", "admin")])
def test_login_returns_public_identity_and_stores_only_hashed_token(
    client,
    auth_database,
    username,
    role,
):
    """Tokens are unique secrets; account hashes never appear in API responses."""
    path, clock = auth_database
    response = sign_in(client, username)
    assert response.status_code == 200, response.text
    body = response.json()
    token = body["access_token"]
    assert len(token) == 43
    assert body["token_type"] == "bearer"
    assert body["user"]["role"] == role
    assert "password_hash" not in response.text
    assert PASSWORD not in response.text
    assert response.headers["cache-control"] == "no-store"
    identity = client.get("/auth/me", headers=authorization(token))
    assert identity.status_code == 200
    assert identity.json() == body["user"]
    assert identity.headers["cache-control"] == "no-store"
    with connect(path) as connection:
        saved = connection.execute(
            "SELECT token_hash, created_at, expires_at FROM user_sessions"
        ).fetchone()
        assert saved == (
            service.token_digest(token),
            clock[0],
            clock[0] + 8 * 3600,
        )
        assert token not in str(
            connection.execute("SELECT * FROM user_sessions").fetchall()
        )
        assert (
            connection.execute("SELECT count(*) FROM login_attempts").fetchone()[0] == 0
        )


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Basic abc"},
        {"Authorization": "Bearer short"},
        {"Authorization": "Bearer " + "a" * 43},
    ],
)
def test_missing_invalid_or_unknown_tokens_are_unauthorized(client, headers):
    """A public account endpoint must not accept missing or fabricated sessions."""
    for route in ("/auth/me", "/auth/logout"):
        response = (
            client.get(route, headers=headers)
            if route.endswith("me")
            else client.post(route, headers=headers)
        )
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"


def test_logout_revokes_only_the_supplied_session(client):
    """Logging out blocks replay while preserving another browser's session."""
    first = sign_in(client).json()["access_token"]
    second = sign_in(client).json()["access_token"]
    assert first != second
    response = client.post("/auth/logout", headers=authorization(first))
    assert response.status_code == 204
    assert response.content == b""
    assert client.get("/auth/me", headers=authorization(first)).status_code == 401
    assert client.get("/auth/me", headers=authorization(second)).status_code == 200


def test_expiry_boundary_and_pruning_expired_sessions(client, auth_database):
    """Eight hours is an absolute lifetime; using a token never extends it."""
    path, clock = auth_database
    token = sign_in(client).json()["access_token"]
    clock[0] += service.SESSION_LIFETIME_SECONDS - 1
    assert client.get("/auth/me", headers=authorization(token)).status_code == 200
    clock[0] += 1
    assert client.get("/auth/me", headers=authorization(token)).status_code == 401
    fresh = sign_in(client).json()["access_token"]
    with connect(path) as connection:
        assert connection.execute(
            "SELECT token_hash FROM user_sessions"
        ).fetchall() == [(service.token_digest(fresh),)]


def test_sessions_survive_restart_and_read_current_roles(client, auth_database):
    """Session identity comes from SQLite, not process memory or token claims."""
    path, _ = auth_database
    token = sign_in(client).json()["access_token"]
    with connect(path) as connection:
        connection.execute("UPDATE users SET role = 'admin' WHERE username = 'user'")
    with TestClient(create_app()) as restarted:
        response = restarted.get("/auth/me", headers=authorization(token))
        assert response.status_code == 200
        assert response.json()["role"] == "admin"


def test_disabled_accounts_cannot_login_or_use_existing_sessions(client, auth_database):
    """Disabling an account takes effect on the next authenticated request."""
    path, _ = auth_database
    token = sign_in(client).json()["access_token"]
    with connect(path) as connection:
        connection.execute("UPDATE users SET is_active = 0 WHERE username = 'user'")
    assert sign_in(client).status_code == 401
    assert client.get("/auth/me", headers=authorization(token)).status_code == 401


@pytest.mark.parametrize("username", ["user", "unknown"])
def test_bad_credentials_are_generic_and_throttled_across_restart(
    client,
    auth_database,
    username,
):
    """Unknown and real usernames share errors, limits, and persisted counters."""
    _, clock = auth_database
    for _ in range(5):
        response = sign_in(client, username.upper(), "incorrect")
        assert response.status_code == 401
        assert response.json() == {"detail": "Invalid username or password."}
    with TestClient(create_app()) as restarted:
        limited = sign_in(restarted, username)
        assert limited.status_code == 429
        assert limited.headers["retry-after"] == "300"
    clock[0] += 300
    response = sign_in(client, username)
    assert response.status_code == (200 if username == "user" else 401)


def test_success_resets_failed_attempts(client):
    """A successful login clears earlier failures for that normalized username."""
    for _ in range(4):
        assert sign_in(client, password="incorrect").status_code == 401
    assert sign_in(client).status_code == 200
    assert sign_in(client, password="incorrect").status_code == 401


def test_passwords_keep_case_and_whitespace_and_are_not_echoed(client):
    """Reject invalid passwords without exposing them in validation errors."""
    for password in (PASSWORD.lower(), " " + PASSWORD, "", "a" * 1025):
        response = sign_in(client, password=password)
        assert response.status_code == 401
        assert response.json() == {"detail": "Invalid username or password."}


def test_attempt_reservations_are_atomic(auth_database):
    """Parallel login attempts must not bypass the per-username limit."""
    path, clock = auth_database
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(
            pool.map(
                lambda _: reserve_login_attempt(path, "user", clock[0]),
                range(8),
            )
        )
    assert results.count(0) == 5
    assert results.count(300) == 3


def test_session_foreign_key_rejects_unknown_users_and_cascades_deletion(
    client,
    auth_database,
):
    """Sessions cannot outlive deleted accounts or refer to missing identities."""
    import sqlite3

    path, _ = auth_database
    token = sign_in(client).json()["access_token"]
    with pytest.raises(sqlite3.IntegrityError), connect(path) as connection:
        connection.execute(
            "INSERT INTO user_sessions VALUES ('fake-hash', 'missing-user', 1, 2)"
        )
    with connect(path) as connection:
        connection.execute("DELETE FROM users WHERE username = 'user'")
        assert (
            connection.execute("SELECT count(*) FROM user_sessions").fetchone()[0] == 0
        )
    assert client.get("/auth/me", headers=authorization(token)).status_code == 401


def test_health_remains_public_and_auth_is_documented(client):
    """Keep launcher health checks available while exposing bearer auth in Swagger."""
    assert client.get("/health").json() == {"status": "ok"}
    schema = client.get("/openapi.json").json()
    assert schema["paths"]["/auth/me"]["get"]["security"] == [{"HTTPBearer": []}]
    assert "/auth/login" in schema["paths"]


@pytest.mark.parametrize(
    "payload",
    [
        {"password": PASSWORD},
        {"username": "bad username", "password": PASSWORD},
        {"username": "user", "password": PASSWORD, "unexpected": True},
        {"username": "user"},
    ],
)
def test_invalid_login_bodies_do_not_echo_credentials(client, payload):
    """Default validation errors can contain input bodies; auth errors must not."""
    response = client.post("/auth/login", json=payload)
    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid authentication request."}
    assert PASSWORD not in response.text
    assert response.headers["cache-control"] == "no-store"
