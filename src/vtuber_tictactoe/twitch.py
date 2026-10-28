"""Read-only IRC over TLS and public-client Twitch device authorization.

Tokens live only in memory. No chat sending API is exposed.
"""

import contextlib
import json
import re
import socket
import ssl
import threading
import time
from collections.abc import Callable
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

import certifi

Json = dict[str, object]


def create_tls_context() -> ssl.SSLContext:
    """Configure a context completely before publishing it to worker threads."""
    context = ssl.create_default_context(cafile=certifi.where())
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


TLS = create_tls_context()


def normalize_channel(value: str, *, allow_empty: bool = False) -> str:
    value = value.strip().lower().lstrip("#")
    if not value and allow_empty:
        return ""
    if value.startswith(("twitch.tv/", "www.twitch.tv/", "m.twitch.tv/")):
        value = "https://" + value
    if "://" in value:
        url = urlsplit(value)
        if url.scheme not in ("http", "https") or url.netloc not in (
            "twitch.tv",
            "www.twitch.tv",
            "m.twitch.tv",
        ):
            raise ValueError("Use a channel name or a twitch.tv channel link.")
        value = url.path.strip("/").split("/")[0]
    if re.fullmatch(r"[a-z0-9_]{1,25}", value) is None or value in (
        "directory",
        "search",
        "settings",
        "downloads",
        "login",
        "signup",
        "videos",
        "subscriptions",
    ):
        raise ValueError("Enter a channel name or its Twitch channel link.")
    return value


class TwitchError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def api(path: str, data: dict[str, str] | None = None, token: str = "") -> Json:
    headers = {"User-Agent": "StreamVsChat/0.1"}
    if token:
        headers["Authorization"] = "OAuth " + token
    body = urlencode(data).encode() if data is not None else None
    request = Request("https://id.twitch.tv/oauth2/" + path, body, headers)
    try:
        with urlopen(request, timeout=15, context=TLS) as response:
            result = json.load(response)
    except HTTPError as exc:
        try:
            message = json.loads(exc.read()).get("message", "Twitch request failed")
        except (ValueError, AttributeError):
            message = "Twitch request failed"
        raise TwitchError(exc.code, str(message)) from None
    if not isinstance(result, dict):
        raise ValueError("Unexpected response from Twitch.")
    return result


def parse_message(line: str, channel: str) -> tuple[str, str, float | None] | None:
    """Accept only PRIVMSG in the joined room; use stable user IDs and server time."""
    tags: dict[str, str] = {}
    if line.startswith("@"):
        raw_tags, _, line = line.partition(" ")
        for tag in raw_tags[1:].split(";"):
            key, _, value = tag.partition("=")
            tags[key] = value
    match = re.fullmatch(r":([^! ]+)![^ ]+ PRIVMSG #([^ ]+) :(.*)", line)
    if match is None or match[2].lower() != channel:
        return None
    # Shared-chat messages originating in other rooms must not vote here.
    source_room, room = tags.get("source-room-id"), tags.get("room-id")
    if source_room and room and source_room != room:
        return None
    timestamp = tags.get("tmi-sent-ts", "")
    sent_at = int(timestamp) / 1000 if timestamp.isdigit() else None
    return tags.get("user-id") or match[1].lower(), match[3], sent_at


class Twitch:
    def __init__(
        self,
        on_vote: Callable[[str, str, float | None], None],
        on_status: Callable[[str, str, bool], None],
    ) -> None:
        self.on_vote = on_vote
        self.on_status = on_status
        self.cancel = threading.Event()
        self.thread: threading.Thread | None = None
        self.connection: ssl.SSLSocket | None = None
        self.channel = ""
        self.client_id = ""
        self.tokens: Json | None = None
        self.credentials_lock = threading.RLock()

    def stop(self, *, clear_tokens: bool = True) -> None:
        self.cancel.set()
        connection = self.connection
        if connection is not None:
            with contextlib.suppress(OSError):
                connection.shutdown(socket.SHUT_RDWR)
            connection.close()
        self.on_status("Disconnected", "", False)
        if clear_tokens:
            with self.credentials_lock:
                self.tokens = None

    def connect(self, client_id: str, channel: str) -> Json:
        if self.thread is not None and self.thread.is_alive():
            raise ValueError("Disconnect or cancel the current login before connecting again.")
        if re.fullmatch(r"[A-Za-z0-9]{5,100}", client_id) is None:
            raise ValueError("Enter the public Client ID of your registered Twitch app.")
        channel = normalize_channel(channel, allow_empty=True)
        result = api("device", {"client_id": client_id, "scopes": "chat:read"})
        self.cancel = threading.Event()
        self.client_id, self.channel = client_id, channel
        self.on_status("Waiting for Twitch authorization", "", False)
        self.thread = threading.Thread(
            target=self.authorize,
            args=(client_id, channel, result),
            daemon=True,
        )
        self.thread.start()
        return {key: result[key] for key in ("user_code", "verification_uri", "expires_in")}

    def search(self, query: str) -> list[dict[str, str]]:
        query = query.strip()
        if not 2 <= len(query) <= 100:
            raise ValueError("Enter at least two characters of the channel name.")
        with self.credentials_lock:
            if not self.tokens or self.cancel.is_set():
                raise ValueError(
                    "Log in with Twitch before searching channels. A blank channel uses your own account."
                )
            token = str(self.tokens["access_token"])
        url = "https://api.twitch.tv/helix/search/channels?" + urlencode(
            {"query": query, "first": 8}
        )
        request = Request(
            url, headers={"Authorization": "Bearer " + token, "Client-Id": self.client_id}
        )
        with urlopen(request, timeout=15, context=TLS) as response:
            result = json.load(response)
        channels = result.get("data", []) if isinstance(result, dict) else []
        if not isinstance(channels, list):
            raise ValueError("Unexpected channel search response.")
        return [
            {
                "login": str(item["broadcaster_login"]),
                "name": str(item.get("display_name", item["broadcaster_login"])),
            }
            for item in channels
            if isinstance(item, dict) and "broadcaster_login" in item
        ]

    def watch(self, channel: str) -> None:
        channel = normalize_channel(channel)
        with self.credentials_lock:
            tokens = self.tokens
        if tokens is None or self.cancel.is_set():
            raise ValueError("Log in with Twitch before choosing a channel.")
        self.stop(clear_tokens=False)
        if self.thread is not None:
            self.thread.join(timeout=20)
            if self.thread.is_alive():
                raise ValueError("Previous chat connection is closing. Try again in a moment.")
        self.cancel = threading.Event()
        self.channel = channel
        self.on_status(f"Connecting to #{channel}", "", False)
        self.thread = threading.Thread(
            target=self.listen, args=(self.client_id, channel, tokens), daemon=True
        )
        self.thread.start()

    def authorize(self, client_id: str, channel: str, device: Json) -> None:
        try:
            deadline = time.monotonic() + float(str(device["expires_in"]))
            interval = max(1.0, float(str(device.get("interval", 5))))
            while not self.cancel.wait(interval):
                if time.monotonic() >= deadline:
                    raise ValueError("Login code expired. Connect again for a new code.")
                try:
                    tokens = api(
                        "token",
                        {
                            "client_id": client_id,
                            "scopes": "chat:read",
                            "device_code": str(device["device_code"]),
                            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                        },
                    )
                except TwitchError as exc:
                    if str(exc) == "authorization_pending":
                        continue
                    if str(exc) == "slow_down":
                        interval += 5
                        continue
                    raise
                if not self.cancel.is_set():
                    self.listen(client_id, channel, tokens)
                return
        except (OSError, ValueError, TwitchError, KeyError):
            if not self.cancel.is_set():
                self.on_status(
                    "Twitch login failed or expired. Check Client ID and reconnect.", "", False
                )

    def validate(self, client_id: str, tokens: Json) -> tuple[Json, Json]:
        try:
            identity = api("validate", token=str(tokens["access_token"]))
        except TwitchError as exc:
            if exc.status != 401:
                raise
            tokens = api(
                "token",
                {
                    "client_id": client_id,
                    "grant_type": "refresh_token",
                    "refresh_token": str(tokens["refresh_token"]),
                },
            )
            identity = api("validate", token=str(tokens["access_token"]))
        scopes = identity.get("scopes", [])
        if (
            identity.get("client_id") != client_id
            or not isinstance(scopes, list)
            or "chat:read" not in scopes
        ):
            raise ValueError("Wrong Twitch app or missing read-chat permission.")
        return tokens, identity

    def listen(self, client_id: str, channel: str, tokens: Json) -> None:
        delay = 1.0
        while not self.cancel.is_set():
            try:
                tokens, identity = self.validate(client_id, tokens)
                login = str(identity["login"])
                channel = channel or login
                self.channel = channel
                if self.cancel.is_set():
                    return
                with self.credentials_lock:
                    self.tokens = tokens
                expires = float(str(identity.get("expires_in", 3600)))
                validate_at = time.monotonic() + min(3300.0, max(15.0, expires))
                with (
                    socket.create_connection(("irc.chat.twitch.tv", 6697), timeout=15) as raw,
                    TLS.wrap_socket(raw, server_hostname="irc.chat.twitch.tv") as stream,
                ):
                    self.connection = stream
                    stream.settimeout(2)
                    commands = (
                        "CAP REQ :twitch.tv/tags twitch.tv/commands\r\n"
                        f"PASS oauth:{tokens['access_token']}\r\nNICK {login}\r\n"
                        f"JOIN #{channel}\r\n"
                    )
                    stream.sendall(commands.encode())
                    buffer = b""
                    last_received = time.monotonic()
                    while not self.cancel.is_set():
                        if time.monotonic() >= validate_at:
                            self.on_status("Revalidating Twitch login. Voting paused.", "", False)
                            break  # Revalidate/refresh before reconnecting, at least hourly.
                        try:
                            chunk = stream.recv(16384)
                        except TimeoutError:
                            if time.monotonic() - last_received > 360:
                                raise OSError("Chat keepalive timed out.") from None
                            continue
                        if not chunk:
                            raise OSError("Chat connection closed.")
                        last_received = time.monotonic()
                        buffer += chunk
                        if len(buffer) > 1_048_576:
                            raise OSError("Invalid chat frame.")
                        while b"\r\n" in buffer:
                            line_bytes, buffer = buffer.split(b"\r\n", 1)
                            line = line_bytes.decode("utf-8", errors="replace")
                            if line.startswith("PING "):
                                stream.sendall(("PONG " + line[5:] + "\r\n").encode())
                            elif " RECONNECT" in line:
                                raise OSError("Twitch requested a reconnect.")
                            elif " NOTICE " in line and any(
                                value in line.lower()
                                for value in (
                                    "authentication failed",
                                    "improperly formatted auth",
                                )
                            ):
                                raise ValueError("Twitch rejected this login. Reconnect.")
                            elif f" ROOMSTATE #{channel}" in line:
                                delay = 1.0
                                self.on_status(f"Reading #{channel}", login, True)
                            elif " PRIVMSG " in line:
                                parsed = parse_message(line, channel)
                                if parsed is not None:
                                    self.on_vote(*parsed)
            except (ValueError, TwitchError, KeyError):
                with self.credentials_lock:
                    self.tokens = None
                if not self.cancel.is_set():
                    self.on_status(
                        "Twitch authorization lost. Disconnect and log in again.", "", False
                    )
                return
            except OSError:
                if not self.cancel.is_set():
                    self.on_status("Chat interrupted. Voting paused; reconnecting…", "", False)
                    if self.cancel.wait(delay):
                        return
                    delay = min(30.0, delay * 2)
            finally:
                self.connection = None
