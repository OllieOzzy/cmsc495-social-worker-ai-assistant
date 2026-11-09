from documentation_assistant.backend.api.health import health


def test_health_returns_ok():
    assert health().status == "ok"
