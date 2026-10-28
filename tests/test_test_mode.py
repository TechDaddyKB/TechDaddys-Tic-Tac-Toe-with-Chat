from pathlib import Path

import pytest

from vtuber_tictactoe.app import Application, Settings, asset


def test_simulated_votes_and_quick_resolution_need_no_twitch_login(tmp_path: Path) -> None:
    app = Application(Settings(tmp_path / "settings.json"))
    app.action("practice", {})
    app.action("start", {"first": "chat"})
    app.action("test_vote", {"user": "viewer-one", "text": "1"})
    app.action("test_vote", {"user": "viewer-one", "text": "1"})
    app.action("test_vote", {"user": "viewer-two", "text": "1"})
    assert app.state()["voters"] == 2
    app.action("finish_test_vote", {})
    assert app.game.board[0] == "O" and app.game.phase == "streamer"
    assert not app.connected


def test_early_finish_is_impossible_during_real_twitch_play(tmp_path: Path) -> None:
    app = Application(Settings(tmp_path / "settings.json"))
    app.connected = True
    app.action("start", {"first": "chat"})
    with pytest.raises(ValueError, match="Only Practice mode"):
        app.action("finish_test_vote", {})
    assert app.game.board == [""] * 9 and app.game.phase == "chat"


def test_early_finish_requires_a_running_unpaused_test_vote(tmp_path: Path) -> None:
    app = Application(Settings(tmp_path / "settings.json"))
    app.action("practice", {})
    with pytest.raises(ValueError, match="Start or resume"):
        app.action("finish_test_vote", {})
    app.action("start", {"first": "chat"})
    app.action("pause", {})
    with pytest.raises(ValueError, match="Start or resume"):
        app.action("finish_test_vote", {})
    app.action("resume", {})
    app.action("finish_test_vote", {})
    assert app.game.phase == "no_votes" and app.game.board == [""] * 9


def test_twitch_login_uses_bundled_id_without_a_browser_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = Application(Settings.load(tmp_path))
    calls = []

    def connect(client_id: str, channel: str):
        calls.append((client_id, channel))
        return {"user_code": "CODE"}

    monkeypatch.setattr(app.twitch, "connect", connect)
    assert app.action("connect", {"channel": "https://twitch.tv/stream"}) == {"user_code": "CODE"}
    assert calls == [(asset("twitch-client-id.txt").strip(), "stream")]
    assert "client_id" not in app.state()


def test_missing_app_configuration_has_an_actionable_error(tmp_path: Path) -> None:
    app = Application(Settings(tmp_path / "settings.json"))
    with pytest.raises(ValueError, match="official release"):
        app.action("connect", {"channel": "stream"})
