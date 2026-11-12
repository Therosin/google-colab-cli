# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from unittest.mock import patch
import pytest
from typer.testing import CliRunner
from colab_cli.cli import app
from colab_cli.commands.automation import show_drive_auth_url
from colab_cli.state import SessionState

runner = CliRunner()


@pytest.fixture
def mock_session():
    return SessionState(
        name="test-session",
        token="test-token",
        url="https://test.url",
        endpoint="e1",
    )


@patch("colab_cli.commands.automation.ColabRuntime")
@patch("colab_cli.common.state")
def test_cli_auth(mock_state, mock_runtime_class, mock_session):
    mock_state.get_session.return_value = mock_session
    mock_state.resolve_session.return_value = "test-session"

    mock_runtime = mock_runtime_class.return_value
    mock_runtime.execute_code.return_value = [{"text": "Success"}]

    result = runner.invoke(app, ["auth", "-s", "test-session"])
    assert result.exit_code == 0

    assert mock_session.last_execution[0] == "automation:auth"
    assert mock_session.last_execution[1] is None
    assert mock_session.last_execution[2] is not None
    mock_state.store.add.assert_called_with(mock_session)

    # Verify ColabRuntime was invoked with the correct code
    mock_runtime.execute_code.assert_called_once()
    called_code = mock_runtime.execute_code.call_args[0][0]

    assert "os.environ['USE_AUTH_EPHEM'] = '0'" in called_code
    assert "auth.authenticate_user()" in called_code


@patch("colab_cli.commands.automation.ColabRuntime")
@patch("colab_cli.common.state")
def test_cli_install(mock_state, mock_runtime_class, mock_session):
    mock_state.get_session.return_value = mock_session
    mock_state.resolve_session.return_value = "test-session"

    mock_runtime = mock_runtime_class.return_value
    mock_runtime.execute_code.return_value = [{"text": "Installed"}]

    result = runner.invoke(app, ["install", "-s", "test-session", "pandas", "numpy"])
    assert result.exit_code == 0
    assert mock_session.last_execution[0] == "automation:install"
    assert mock_session.last_execution[2] is not None
    mock_state.store.add.assert_called_with(mock_session)

    mock_runtime.execute_code.assert_called_once()
    called_code = mock_runtime.execute_code.call_args[0][0]

    assert "subprocess" in called_code
    assert "pip" in called_code
    assert "pandas" in called_code
    assert "numpy" in called_code


@patch("colab_cli.commands.automation.ColabRuntime")
@patch("colab_cli.common.state")
def test_cli_drivemount(mock_state, mock_runtime_class, mock_session):
    mock_state.get_session.return_value = mock_session
    mock_state.resolve_session.return_value = "test-session"

    mock_runtime = mock_runtime_class.return_value
    mock_runtime.execute_code.return_value = [{"text": "Mounted"}]

    result = runner.invoke(app, ["drivemount", "-s", "test-session", "/foo/bar"])
    assert result.exit_code == 0

    # Verify ColabRuntime was invoked with the correct code
    mock_runtime.execute_code.assert_called_once()
    called_code = mock_runtime.execute_code.call_args[0][0]

    assert "drive.mount('/foo/bar')" in called_code
    assert mock_runtime.colab_request_hook is not None
    # Drivemount waits for the user to OAuth in their browser; the kernel
    # goes silent during that wait and the default 10s execute() timeout
    # would raise TimeoutError mid-flow. Insist on a generous timeout
    # (>= 5 minutes) being forwarded to runtime.execute_code.
    _, kwargs = mock_runtime.execute_code.call_args
    assert kwargs.get("timeout") is not None and kwargs["timeout"] >= 300


@patch("colab_cli.commands.automation.ColabRuntime")
@patch("colab_cli.common.state")
def test_cli_auth_uses_long_timeout(mock_state, mock_runtime_class, mock_session):
    """`colab auth` walks the user through a paste-the-code flow that
    routinely takes >10s, so it must pass a generous timeout to
    runtime.execute_code or the call will TimeoutError mid-flow."""
    mock_state.get_session.return_value = mock_session
    mock_state.resolve_session.return_value = "test-session"

    mock_runtime = mock_runtime_class.return_value
    mock_runtime.execute_code.return_value = [{"text": "Authenticated"}]

    result = runner.invoke(app, ["auth", "-s", "test-session"])
    assert result.exit_code == 0

    _, kwargs = mock_runtime.execute_code.call_args
    assert kwargs.get("timeout") is not None and kwargs["timeout"] >= 300


@patch("colab_cli.commands.automation.open_url_in_browser", return_value=True)
def test_show_drive_auth_url_opens_browser(mock_open, capsys):
    """The consent URL is printed and handed to the browser opener."""
    url = "https://accounts.google.com/o/oauth2/v2/auth?state=abc"
    assert show_drive_auth_url(url) is True

    mock_open.assert_called_once_with(url)
    out = capsys.readouterr().out
    assert url in out
    assert "Opened the authorization page" in out


@patch("colab_cli.commands.automation.open_url_in_browser", return_value=False)
def test_show_drive_auth_url_headless_still_prints(mock_open, capsys):
    """With no browser opener the URL must stay on screen for manual use."""
    url = "https://accounts.google.com/o/oauth2/v2/auth?state=abc"
    assert show_drive_auth_url(url) is False

    mock_open.assert_called_once_with(url)
    out = capsys.readouterr().out
    assert url in out
    assert "Opened the authorization page" not in out


@pytest.mark.parametrize("platform, terminal", [("win32", "CONIN$"), ("linux", "/dev/tty")])
@pytest.mark.parametrize("failure", [None, "open", "read", "stdin"])
def test_drive_auth_reads_controlling_terminal_before_stdin(
    mocker, mock_common_state, mock_session, platform, terminal, failure
):
    import json
    from colab_cli.commands import automation

    mock_common_state.store.get.return_value = mock_session
    runtime = mocker.patch.object(automation, "ColabRuntime").return_value
    runtime.execute_code.return_value = []
    creds = mocker.patch.object(automation, "get_credentials").return_value
    creds.request.side_effect = [
        mocker.Mock(response=None, status_code=200, text=json.dumps({"token": "test-token"})),
        mocker.Mock(response=None, status_code=200, text=json.dumps({
            "success": False, "unauthorized_redirect_uri": "https://example.test/auth"
        })),
        mocker.Mock(response=None, status_code=200, text="{}"),
    ]
    show_url = mocker.patch.object(automation, "show_drive_auth_url")
    automation.run_automation("test-session", "drivemount", "drive.mount()")
    mocker.patch.object(automation.sys, "platform", platform)
    opened = mocker.patch("builtins.open", mocker.mock_open(read_data="\n"))
    stdin = mocker.patch.object(automation.sys, "stdin")
    fallback_input = mocker.patch("builtins.input", return_value="")
    if failure in ("open", "stdin"):
        opened.side_effect = OSError("no terminal")
    elif failure == "read":
        opened.return_value.readline.side_effect = OSError("terminal disconnected")
    if failure == "stdin":
        stdin.readline.side_effect = OSError("stdin unavailable")
    wsclient = mocker.Mock()
    wsclient.session.msg.return_value = {}
    message = {
        "content": {"request": {"authType": "dfs_ephemeral"}},
        "metadata": {"colab_msg_id": "msg-1"},
        "header": {"msg_id": "parent-1"},
    }
    assert runtime.colab_request_hook(message, wsclient) is True
    opened.assert_called_once_with(terminal)
    show_url.assert_called_once_with("https://example.test/auth")
    if failure is None:
        opened.return_value.readline.assert_called_once_with()
        stdin.readline.assert_not_called()
    else:
        stdin.readline.assert_called_once_with()
    if failure == "stdin":
        fallback_input.assert_called_once_with()
    else:
        fallback_input.assert_not_called()
    assert creds.request.call_count == 3
    wsclient.session.msg.assert_called_once_with(
        "input_reply", {"value": {"type": "colab_reply", "colab_msg_id": "msg-1"}}
    )
    wsclient.stdin_channel.send.assert_called_once_with(wsclient.session.msg.return_value)
