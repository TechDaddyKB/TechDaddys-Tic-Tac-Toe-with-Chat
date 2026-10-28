import time
from pathlib import Path

import pytest

from vtuber_tictactoe import twitch
from vtuber_tictactoe.app import Application, Settings
from vtuber_tictactoe.twitch import Twitch, TwitchError


def test_authorization_pending_slowdown_then_success(monkeypatch: pytest.MonkeyPatch) -> None:
    statuses, sessions, intervals = [], [], []
    reader = Twitch(lambda *_: None, lambda *s: statuses.append(s))
    responses = [
        TwitchError(400, "authorization_pending"),
        TwitchError(400, "slow_down"),
        {"access_token": "test"},
    ]

    def fake_api(path, data=None, token=""):
        result = responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(twitch, "api", fake_api)
    monkeypatch.setattr(reader.cancel, "wait", lambda seconds: intervals.append(seconds) or False)
    monkeypatch.setattr(reader, "listen", lambda *args: sessions.append(args))
    reader.authorize("client", "stream", {"device_code": "device", "expires_in": 60, "interval": 1})
    assert intervals == [1, 1, 6]
    assert sessions == [("client", "stream", {"access_token": "test"})]


@pytest.mark.parametrize(
    "expires, error",
    [(-1, None), (60, TwitchError(400, "access_denied")), (60, OSError("offline"))],
)
def test_authorization_errors_are_reported_without_secrets(
    monkeypatch: pytest.MonkeyPatch, expires: int, error
) -> None:
    statuses = []
    reader = Twitch(lambda *_: None, lambda *s: statuses.append(s))
    monkeypatch.setattr(reader.cancel, "wait", lambda *_: False)

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(twitch, "api", fail)
    reader.authorize("client", "stream", {"device_code": "secret", "expires_in": expires})
    assert len(statuses) == 1
    assert "failed or expired" in statuses[0][0] and "secret" not in str(statuses)


def test_cancelled_authorization_does_not_report_error() -> None:
    statuses = []
    reader = Twitch(lambda *_: None, lambda *s: statuses.append(s))
    reader.cancel.set()
    reader.authorize("client", "stream", {"expires_in": 60})
    assert not statuses


class FakeStream:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.sent = []
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def settimeout(self, value):
        pass

    def sendall(self, data):
        self.sent.append(data)

    def recv(self, length):
        item = self.chunks.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def shutdown(self, how):
        raise OSError("already closed")

    def close(self):
        self.closed = True


def setup_transport(monkeypatch, reader, stream):
    monkeypatch.setattr(twitch.socket, "create_connection", lambda *a, **kw: stream)
    monkeypatch.setattr(twitch.TLS, "wrap_socket", lambda *a, **kw: stream)
    monkeypatch.setattr(
        reader,
        "validate",
        lambda *args: ({"access_token": "test"}, {"login": "reader", "expires_in": 3600}),
    )


def test_transport_handles_split_frames_ping_and_read_only_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    statuses, votes = [], []
    reader = Twitch(lambda *v: votes.append(v), lambda *s: statuses.append(s))
    stream = FakeStream(
        [
            b"PING :tmi.twitch.tv\r\n@room-id=1 :tmi.twitch.tv ROOMSTATE #stream\r\n@user-",
            b"id=99;tmi-sent-ts=1234000 :viewer!v@h PRIVMSG #stream :5\r\n",
            b":tmi.twitch.tv NOTICE * :Login authentication failed\r\n",
        ]
    )
    setup_transport(monkeypatch, reader, stream)
    reader.listen("client", "stream", {"access_token": "test"})
    assert votes == [("99", "5", 1234.0)]
    assert statuses[0] == ("Reading #stream", "reader", True)
    assert statuses[-1][2] is False and "authorization lost" in statuses[-1][0]
    outgoing = b"".join(stream.sent)
    assert b"PASS oauth:test\r\nNICK reader\r\nJOIN #stream\r\n" in outgoing
    assert b"PONG :tmi.twitch.tv\r\n" in outgoing
    assert b"PRIVMSG" not in outgoing
    assert reader.connection is None


@pytest.mark.parametrize(
    "chunks", [[b""], [OSError("offline")], [b":tmi.twitch.tv RECONNECT\r\n"], [b"x" * 1_048_577]]
)
def test_transport_reconnect_pauses_instead_of_accepting_votes(
    monkeypatch: pytest.MonkeyPatch, chunks
) -> None:
    statuses = []
    reader = Twitch(lambda *_: None, lambda *s: statuses.append(s))
    setup_transport(monkeypatch, reader, FakeStream(chunks))
    monkeypatch.setattr(reader.cancel, "wait", lambda *_: True)
    reader.listen("client", "stream", {"access_token": "test"})
    assert statuses[-1] == ("Chat interrupted. Voting paused; reconnecting…", "", False)


def test_stop_shuts_down_socket_and_signals_cancel() -> None:
    statuses = []
    reader = Twitch(lambda *_: None, lambda *s: statuses.append(s))
    stream = FakeStream([])
    reader.connection = stream
    reader.stop()
    assert stream.closed and reader.cancel.is_set()
    assert statuses[-1] == ("Disconnected", "", False)


def test_offline_room_broadcaster_messages_reach_game_and_deduplicate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = Application(Settings(tmp_path / "settings.json"))
    app.game.start("chat", time.monotonic(), 1000)
    message = (
        b"@badges=broadcaster/1;room-id=42;user-id=42;tmi-sent-ts=1234000 "
        b":stream!stream@host PRIVMSG #stream :1\r\n"
    )
    stream = FakeStream(
        [
            b"@room-id=42;emote-only=0 :tmi.twitch.tv ROOMSTATE #stream\r\n",
            message,
            message,
            b":tmi.twitch.tv NOTICE * :Login authentication failed\r\n",
        ]
    )
    setup_transport(monkeypatch, app.twitch, stream)
    app.twitch.listen("client", "stream", {"access_token": "test"})
    assert app.state()["chat_messages_received"] == 2
    assert app.state()["voters"] == 1 and app.game.tally()[0] == 1
    app.game.resume(time.monotonic(), time.time())
    app.game.tick(app.game.deadline)
    assert app.game.board[0] == "O" and app.game.phase == "streamer"
