import json
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from vtuber_tictactoe.app import MARKER, Application, Settings, asset, make_handler


@pytest.fixture
def app(tmp_path: Path) -> Application:
    return Application(Settings(tmp_path / "settings.json"))


def test_settings_roundtrip_and_no_oauth_secrets(tmp_path: Path) -> None:
    settings = Settings.load(tmp_path)
    settings.client_id = "public-client"
    settings.channel = "channel"
    settings.save()
    copy = Settings.load(tmp_path)
    assert copy.overlay_token == settings.overlay_token
    assert copy.channel == "channel"
    assert copy.client_id == asset("twitch-client-id.txt").strip()
    assert "access_token" not in copy.file.read_text()
    settings.file.write_text('{"overlay_token":"bad/", "port":80,"channel":7}')
    copy = Settings.load(tmp_path)
    assert copy.port == 18765 and copy.channel == "" and len(copy.overlay_token) >= 32
    settings.file.write_text("[]")
    with pytest.raises(ValueError, match="not a JSON object"):
        Settings.load(tmp_path)


def test_overlay_install_relink_and_protect_unrelated_html(
    app: Application, tmp_path: Path
) -> None:
    path = tmp_path / "item.html"
    app.write_overlay(path, existing=False)
    assert MARKER in path.read_text() and app.overlay_url in path.read_text()
    assert "__STATE_URL__" not in path.read_text()
    app.write_overlay(path, existing=True)
    assert app.settings.overlay_path == str(path)
    path.write_text("<html>user file</html>")
    with pytest.raises(ValueError, match="not a Stream"):
        app.write_overlay(path, existing=False)
    assert path.read_text() == "<html>user file</html>"
    with pytest.raises(ValueError, match=".html"):
        app.write_overlay(tmp_path / "file.txt", existing=False)


def test_game_actions_and_practice_isolation(app: Application) -> None:
    with pytest.raises(ValueError, match="Connect Twitch"):
        app.action("start", {})
    with pytest.raises(ValueError, match="only available"):
        app.action("test_vote", {})
    app.action("practice", {})
    app.action("start", {"first": "streamer"})
    app.action("select", {"cell": 5})
    app.action("confirm", {})
    app.action("test_vote", {"user": "a", "text": "1"})
    assert app.game.votes == {"a": 1}
    app.action("pause", {})
    app.action("resume", {})
    app.action("visibility", {})
    assert not app.state()["visible"]
    with pytest.raises(ValueError, match="Reset"):
        app.action("practice", {})
    app.action("reset", {})
    app.action("clear_scores", {})
    app.action("practice", {})
    app.action("quit", {})
    assert app.stopping.is_set()


def test_retries_and_rejected_actions(app: Application) -> None:
    app.practice = True
    with pytest.raises(ValueError, match="no empty vote"):
        app.action("retry", {})
    with pytest.raises(ValueError, match="numbered"):
        app.action("select", {"cell": True})
    with pytest.raises(ValueError, match="Unknown"):
        app.action("oops", {})
    with pytest.raises(ValueError, match="ignored"):
        app.action("test_vote", {"text": "1"})
    with pytest.raises(ValueError, match="Turn off"):
        app.action("connect", {})
    app.action("start", {"first": "chat"})
    app.game.tick(app.game.deadline)
    assert app.game.phase == "no_votes"
    app.action("retry", {})
    assert app.game.phase == "chat"


def test_disconnect_auto_pauses_but_reconnection_needs_manual_resume(app: Application) -> None:
    app.connected = True
    app.game.start("chat", time.monotonic(), time.time())
    app.on_vote("a", "3", time.time())
    app.on_status("interrupted", "", False)
    assert app.game.paused and app.game.votes == {"a": 3}
    app.on_status("Reading #channel", "reader", True)
    assert app.game.paused
    app.action("resume", {})
    assert not app.game.paused
    app.practice = True
    app.on_vote("b", "4", time.time())
    assert "b" not in app.game.votes
    app.action("disconnect", {})
    assert not app.connected


def test_connect_saves_only_public_settings(
    app: Application, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app.twitch, "connect", lambda *a: {"user_code": "CODE"})
    app.settings.client_id = "client"
    result = app.action("connect", {"channel": "#CHANNEL"})
    assert result == {"user_code": "CODE"}
    assert app.settings.channel == "channel"
    assert "access_token" not in app.settings.file.read_text()
    app.connected = True
    with pytest.raises(ValueError, match="Disconnect"):
        app.action("practice", {})


@pytest.fixture
def server(app: Application):
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    app.settings.port = server.server_port
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    yield app
    server.shutdown()
    server.server_close()
    worker.join(2)


def request(app: Application, path: str, data=None, *, token=True, headers=None, method=None):
    request_headers = {"Content-Type": "application/json"}
    if token:
        request_headers["Authorization"] = "Bearer " + app.control_token
    request_headers.update(headers or {})
    req = Request(
        app.base + path,
        data=json.dumps(data).encode() if data is not None else None,
        headers=request_headers,
        method=method,
    )
    try:
        result = urlopen(req, timeout=2)
    except HTTPError as exc:
        result = exc
    with result:
        return result.status, result.headers, result.read()


def test_http_controller_auth_cors_and_public_state(server: Application) -> None:
    assert request(server, "/")[0] == 200
    assert request(server, "/api/state", token=False)[0] == 404
    assert request(server, "/api/state")[0] == 200
    assert request(server, "/api/state", headers={"Origin": "https://evil.example"})[0] == 404
    assert request(server, "/api/state", headers={"Host": "evil.example"})[0] == 403
    path = "/overlay/" + server.settings.overlay_token
    assert request(server, path, token=False)[0] == 200
    status, headers, body = request(server, path + "/state", token=False)
    assert status == 200 and headers["Access-Control-Allow-Origin"] == "*"
    assert headers["Cache-Control"] == "no-store"
    assert "client_id" not in json.loads(body) and "login" not in json.loads(body)
    assert server.state()["overlay_connected"]
    assert request(server, path + "/state", method="OPTIONS")[0] == 200
    assert request(server, "/api/action", method="OPTIONS")[0] == 403
    assert request(server, "/overlay/wrong/state", token=False)[0] == 404


def test_http_mutations_reject_csrf_and_invalid_input(server: Application) -> None:
    assert request(server, "/api/action", {"action": "practice"}, token=False)[0] == 403
    assert (
        request(server, "/api/action", {"action": "practice"}, headers={"Origin": "null"})[0] == 403
    )
    assert request(server, "/api/action", {"action": "practice"})[0] == 200
    assert request(server, "/api/action", {"action": "start", "first": "streamer"})[0] == 200
    assert request(server, "/api/action", {"action": "select", "cell": 1})[0] == 200
    assert request(server, "/api/action", {"action": "confirm"})[0] == 200
    assert request(server, "/api/action", {"action": "select", "cell": 2})[0] == 400
    assert request(server, "/api/action", [1])[0] == 400
    assert (
        request(server, "/api/action", {"action": "reset"}, headers={"Content-Type": "text/plain"})[
            0
        ]
        == 400
    )
    assert request(server, "/api/action", {"action": "x" * 9000})[0] == 400
