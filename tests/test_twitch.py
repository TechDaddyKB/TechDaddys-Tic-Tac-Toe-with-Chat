import io
from urllib.error import HTTPError

import pytest

from vtuber_tictactoe import twitch
from vtuber_tictactoe.twitch import Twitch, TwitchError, parse_message


def test_tagged_message_with_stable_identity_and_timestamp() -> None:
    assert parse_message(
        "@user-id=42;tmi-sent-ts=1234500;room-id=1 :alice!alice@host PRIVMSG #stream : 5 ",
        "stream",
    ) == ("42", " 5 ", 1234.5)


@pytest.mark.parametrize(
    "line",
    [
        ":alice!a@host PRIVMSG #elsewhere :1",
        "PING :tmi.twitch.tv",
        ":alice!a@host JOIN #stream",
        "@user-id=2;room-id=1;source-room-id=9 :alice!a@host PRIVMSG #stream :1",
    ],
)
def test_non_vote_events_and_other_rooms_are_rejected(line: str) -> None:
    assert parse_message(line, "stream") is None


def test_broadcaster_can_vote_in_their_own_chat() -> None:
    assert parse_message(
        "@badges=broadcaster/1;user-id=42;room-id=42;tmi-sent-ts=1234000 :stream!stream@host PRIVMSG #stream :1",
        "stream",
    ) == ("42", "1", 1234.0)


def test_login_fallback_and_malformed_timestamp() -> None:
    assert parse_message("@tmi-sent-ts=no :Alice!a@h PRIVMSG #stream :2", "stream") == (
        "alice",
        "2",
        None,
    )


def client() -> Twitch:
    return Twitch(lambda *_: None, lambda *_: None)


def test_validation_and_token_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def fake_api(path: str, data=None, token=""):
        calls.append((path, data, token))
        if path == "validate" and token == "old":
            raise TwitchError(401, "invalid access token")
        if path == "token":
            return {"access_token": "new", "refresh_token": "next"}
        return {"client_id": "client", "scopes": ["chat:read"], "login": "reader"}

    monkeypatch.setattr(twitch, "api", fake_api)
    tokens, identity = client().validate(
        "client", {"access_token": "old", "refresh_token": "refresh"}
    )
    assert tokens["access_token"] == "new" and identity["login"] == "reader"
    assert calls[1][1] == {
        "client_id": "client",
        "grant_type": "refresh_token",
        "refresh_token": "refresh",
    }


def test_missing_scope_or_wrong_app_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(twitch, "api", lambda *a, **kw: {"client_id": "wrong", "scopes": []})
    with pytest.raises(ValueError, match="Wrong Twitch"):
        client().validate("right", {"access_token": "a"})


def test_non_auth_error_is_not_refreshed(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args, **kwargs):
        raise TwitchError(500, "temporary")

    monkeypatch.setattr(twitch, "api", fail)
    with pytest.raises(TwitchError) as error:
        client().validate("id", {"access_token": "a"})
    assert error.value.status == 500


def test_connect_validates_channel_and_never_requests_chat_edit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader = client()
    with pytest.raises(ValueError, match="Client ID"):
        reader.connect("", "stream")
    with pytest.raises(ValueError, match="channel"):
        reader.connect("clientid", "https://example.com/name")
    seen = []

    def fake_api(path, data=None, token=""):
        seen.append(data)
        return {
            "user_code": "CODE",
            "device_code": "secret",
            "verification_uri": "https://www.twitch.tv/activate",
            "expires_in": 60,
        }

    monkeypatch.setattr(twitch, "api", fake_api)
    monkeypatch.setattr(reader, "authorize", lambda *_: None)
    result = reader.connect("clientid", "stream")
    assert seen == [{"client_id": "clientid", "scopes": "chat:read"}]
    assert "device_code" not in result and result["user_code"] == "CODE"
    assert reader.thread is not None
    reader.thread.join(1)
    reader.stop()


def test_http_encoding_validation_and_error_sanitizing(monkeypatch: pytest.MonkeyPatch) -> None:
    requests = []

    def open_request(request, **kwargs):
        requests.append(request)
        return io.BytesIO(b'{"client_id":"abc"}')

    monkeypatch.setattr(twitch, "urlopen", open_request)
    assert twitch.api("validate", token="test")["client_id"] == "abc"
    assert requests[0].get_header("Authorization") == "OAuth test"
    twitch.api("token", {"refresh_token": "a&b+"})
    assert requests[1].data == b"refresh_token=a%26b%2B"

    def fail(request, **kwargs):
        raise HTTPError("url", 400, "Bad", {}, io.BytesIO(b'{"message":"authorization_pending"}'))

    monkeypatch.setattr(twitch, "urlopen", fail)
    with pytest.raises(TwitchError, match="authorization_pending"):
        twitch.api("token", {})


def test_invalid_http_responses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(twitch, "urlopen", lambda *a, **kw: io.BytesIO(b"[]"))
    with pytest.raises(ValueError, match="Unexpected"):
        twitch.api("token")

    def fail(*args, **kwargs):
        raise HTTPError("url", 500, "Bad", {}, io.BytesIO(b"not-json"))

    monkeypatch.setattr(twitch, "urlopen", fail)
    with pytest.raises(TwitchError, match="Twitch request failed"):
        twitch.api("token")
