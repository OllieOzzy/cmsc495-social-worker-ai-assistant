"""Test the health handler directly."""

from documentation_assistant.backend.api.health import health


def test_health_returns_ok():
    """Verify the health handler reports that the API is up."""
    assert health().status == "ok"
