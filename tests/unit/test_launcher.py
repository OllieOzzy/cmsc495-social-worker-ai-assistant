"""Verify account-command dispatch without starting local server processes."""

from unittest.mock import Mock

import pytest

from documentation_assistant import launcher


def test_no_arguments_keep_normal_server_startup(monkeypatch):
    """The existing dap-assistant command still delegates to the server supervisor."""
    start = Mock(return_value=0)
    monkeypatch.setattr(launcher, "_run_servers", start)

    assert launcher.main([]) == 0
    start.assert_called_once_with()


@pytest.mark.parametrize(
    "arguments", [["init-demo-users"], ["create-user", "--username", "robert"]]
)
def test_account_commands_do_not_start_servers(monkeypatch, arguments):
    """Account setup must complete without binding the app's HTTP ports."""
    setup = Mock(return_value=0)
    start = Mock()
    monkeypatch.setattr(launcher, "run_account_command", setup)
    monkeypatch.setattr(launcher, "_run_servers", start)

    assert launcher.main(arguments) == 0
    assert setup.call_args.args[0].command == arguments[0]
    start.assert_not_called()


@pytest.mark.parametrize(
    "arguments",
    [["create-user", "--role", "superuser"], ["create-user", "--password", "secret"]],
)
def test_invalid_roles_and_command_line_passwords_are_rejected(arguments):
    """Do not accept unsupported roles or expose passwords through process arguments."""
    with pytest.raises(SystemExit) as stopped:
        launcher.main(arguments)
    assert stopped.value.code == 2


def test_help_describes_setup_commands_without_starting_servers(capsys):
    """Account setup is discoverable through the standard command help."""
    with pytest.raises(SystemExit) as stopped:
        launcher.main(["--help"])
    assert stopped.value.code == 0
    output = capsys.readouterr().out
    assert "create-user" in output
    assert "init-demo-users" in output
