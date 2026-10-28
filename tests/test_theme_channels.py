import io
import json
from pathlib import Path

import pytest

from vtuber_tictactoe import twitch
from vtuber_tictactoe.app import Application, Settings
from vtuber_tictactoe.theme import DEFAULT_THEME, validate_theme
from vtuber_tictactoe.twitch import Twitch, normalize_channel


@pytest.mark.parametrize(
    "value",
    [
        "Example_Name",
        "#example_name",
        "https://www.twitch.tv/Example_Name",
        "twitch.tv/example_name",
        "https://twitch.tv/example_name/videos?sort=time",
        "m.twitch.tv/example_name/",
    ],
)
def test_channel_names_links_and_channel_subpages(value: str) -> None:
    assert normalize_channel(value) == "example_name"


@pytest.mark.parametrize(
    "value",
    [
        "",
        "https://evil.example/name",
        "https://twitch.tv.evil.example/name",
        "https://twitch.tv/directory",
        "bad name",
        "x" * 26,
        "https://twitch.tv/",
    ],
)
def test_invalid_channel_links_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        normalize_channel(value)
    assert normalize_channel("", allow_empty=True) == ""


def test_theme_save_reload_and_reset(tmp_path: Path) -> None:
    settings = Settings(tmp_path / "settings.json")
    app = Application(settings)
    theme = {**DEFAULT_THEME, "banner_bg": "#ABCDEF", "grid": "#123456"}
    app.action("theme", {"theme": theme})
    loaded = Settings.load(tmp_path)
    assert loaded.theme["banner_bg"] == "#abcdef" and loaded.theme["grid"] == "#123456"
    assert app.state()["theme"] == loaded.theme
    app.action("reset_theme", {})
    assert app.settings.theme == DEFAULT_THEME


@pytest.mark.parametrize(
    "value",
    [
        None,
        {},
        {**DEFAULT_THEME, "grid": "red"},
        {**DEFAULT_THEME, "banner_text": "#123456;display:none"},
    ],
)
def test_theme_rejects_incomplete_values_and_css_injection(value) -> None:
    with pytest.raises(ValueError):
        validate_theme(value)


def test_corrupt_saved_theme_uses_defaults(tmp_path: Path) -> None:
    (tmp_path / "settings.json").write_text('{"theme":{"grid":"bad"}}')
    assert Settings.load(tmp_path).theme == DEFAULT_THEME


def test_search_requires_login_and_uses_read_only_helix(monkeypatch: pytest.MonkeyPatch) -> None:
    reader = Twitch(lambda *_: None, lambda *_: None)
    with pytest.raises(ValueError, match="Log in"):
        reader.search("stream")
    reader.tokens = {"access_token": "test"}
    reader.client_id = "client"
    requests = []

    def fake_open(request, **kwargs):
        requests.append(request)
        return io.BytesIO(
            json.dumps(
                {"data": [{"broadcaster_login": "stream", "display_name": "Stream"}]}
            ).encode()
        )

    monkeypatch.setattr(twitch, "urlopen", fake_open)
    assert reader.search("str eam") == [{"login": "stream", "name": "Stream"}]
    assert "query=str+eam" in requests[0].full_url
    assert requests[0].get_header("Authorization") == "Bearer test"
    assert requests[0].get_header("Client-id") == "client"
    with pytest.raises(ValueError, match="two characters"):
        reader.search("a")


def test_search_and_channel_selection_actions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = Application(Settings(tmp_path / "settings.json"))
    monkeypatch.setattr(app.twitch, "search", lambda query: [{"login": "found", "name": query}])
    assert app.action("search_channels", {"query": "Found"}) == {
        "channels": [{"login": "found", "name": "Found"}]
    }
    watched = []
    monkeypatch.setattr(app.twitch, "watch", watched.append)
    app.action("watch_channel", {"channel": "https://twitch.tv/found"})
    assert watched == ["found"]
    assert Settings.load(tmp_path).channel == "found"
    app.game.start("chat", 0, 0)
    with pytest.raises(ValueError, match="Reset"):
        app.action("watch_channel", {"channel": "other"})
