"""Loopback controller server, native file dialogs, and portable entry point."""

import argparse
import contextlib
import json
import os
import queue
import secrets
import subprocess
import sys
import threading
import time
import webbrowser
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from urllib.parse import urlsplit

from .game import Game
from .theme import DEFAULT_THEME, validate_theme
from .twitch import Twitch, TwitchError, normalize_channel

MARKER = "<!-- STREAM-VS-CHAT-OVERLAY v1 -->"


def asset(name: str) -> str:
    return files("vtuber_tictactoe").joinpath("assets", name).read_text(encoding="utf-8")


def default_config_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local")))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    return base / "techdaddy-tictactoe"


@dataclass
class Settings:
    file: Path
    overlay_token: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    overlay_path: str = ""
    client_id: str = ""
    channel: str = ""
    port: int = 18765
    theme: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_THEME))
    visible: bool = True

    @classmethod
    def load(cls, folder: Path) -> "Settings":
        settings = cls(folder / "settings.json")
        if settings.file.exists():
            data = json.loads(settings.file.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("Settings file is not a JSON object.")
            for key in ("overlay_path", "client_id", "channel"):
                value = data.get(key)
                if isinstance(value, str):
                    setattr(settings, key, value)
            token = data.get("overlay_token")
            if (
                isinstance(token, str)
                and len(token) >= 32
                and token.replace("-", "").replace("_", "").isalnum()
            ):
                settings.overlay_token = token
            port = data.get("port")
            if isinstance(port, int) and 1024 <= port <= 65535:
                settings.port = port
            if isinstance(data.get("visible"), bool):
                settings.visible = data["visible"]
            if "theme" in data:
                with contextlib.suppress(ValueError):
                    settings.theme = validate_theme(data["theme"])
        # Publishers may ship their public application ID; never a client secret.
        packaged_id = (
            files("vtuber_tictactoe").joinpath("assets", "twitch-client-id.txt").read_text().strip()
        )
        if packaged_id:
            settings.client_id = packaged_id
        return settings

    def save(self) -> None:
        self.file.parent.mkdir(parents=True, exist_ok=True)
        data = {
            key: getattr(self, key)
            for key in (
                "overlay_token",
                "overlay_path",
                "client_id",
                "channel",
                "port",
                "theme",
                "visible",
            )
        }
        temporary = self.file.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
        temporary.chmod(0o600)
        temporary.replace(self.file)


@dataclass
class DialogRequest:
    save: bool
    done: threading.Event = field(default_factory=threading.Event)
    result: str = ""
    error: str = ""


def native_dialog(save: bool) -> str:
    if sys.platform == "win32":
        kind = "SaveFileDialog" if save else "OpenFileDialog"
        script = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            f"$dialog = New-Object System.Windows.Forms.{kind}; "
            "$dialog.Filter='HTML overlay (*.html)|*.html'; "
            "$dialog.FileName='tic-tac-toe.html'; "
            "$dialog.Title='Choose the TechDaddy Tic-Tac-Toe HTML item'; "
            "if ($dialog.ShowDialog() -eq 'OK') { "
            "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
            "[Console]::Write($dialog.FileName) }"
        )
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-STA", "-Command", script],
            capture_output=True,
            check=True,
            creationflags=0x08000000,
        )
        return result.stdout.decode("utf-8-sig").strip()
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        if save:
            return str(
                filedialog.asksaveasfilename(
                    title="Choose the TechDaddy Tic-Tac-Toe HTML item",
                    filetypes=[("HTML overlay", "*.html")],
                    defaultextension=".html",
                    initialfile="tic-tac-toe.html",
                )
            )
        return str(
            filedialog.askopenfilename(
                title="Choose the TechDaddy Tic-Tac-Toe HTML item",
                filetypes=[("HTML overlay", "*.html")],
            )
        )
    finally:
        root.destroy()


class Application:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.lock = threading.RLock()
        self.game = Game(visible=settings.visible)
        self.control_token = secrets.token_urlsafe(32)
        self.stopping = threading.Event()
        self.dialogs: queue.Queue[DialogRequest] = queue.Queue()
        self.practice = False
        self.connected = False
        self.login = ""
        self.chat_status = "Disconnected"
        self.chat_messages_received = 0
        self.overlay_seen = 0.0
        self.twitch = Twitch(self.on_vote, self.on_status)

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.settings.port}"

    @property
    def overlay_url(self) -> str:
        return f"{self.base}/overlay/{self.settings.overlay_token}"

    def on_vote(self, user: str, text: str, sent_at: float | None) -> None:
        with self.lock:
            if self.connected and not self.practice:
                self.chat_messages_received += 1
                self.game.vote(user, text, time.monotonic(), sent_at)

    def on_status(self, status: str, login: str, connected: bool) -> None:
        with self.lock:
            self.chat_status, self.login, self.connected = status, login, connected
            if connected and self.twitch.channel:
                self.settings.channel = self.twitch.channel
                self.settings.save()
            if not connected and not self.practice:
                self.game.pause(time.monotonic())

    def write_overlay(self, path: Path, *, existing: bool) -> None:
        path = path.expanduser().absolute()
        if path.suffix.lower() != ".html":
            raise ValueError("Choose an .html file.")
        if (existing or path.exists()) and MARKER not in path.read_text(encoding="utf-8"):
            raise ValueError(
                "That file is not a Stream vs Chat overlay. Use Install HTML to create one."
            )
        content = asset("overlay.html").replace("__STATE_URL__", self.overlay_url + "/state")
        temporary = path.with_suffix(".html.tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)
        self.settings.overlay_path = str(path)
        self.settings.save()

    def state(self) -> dict[str, object]:
        with self.lock:
            now = time.monotonic()
            return {
                **self.game.state(now),
                "practice": self.practice,
                "connected": self.connected,
                "chat_status": self.chat_status,
                "login": self.login,
                "chat_messages_received": self.chat_messages_received,
                "channel": self.settings.channel,
                "overlay_path": self.settings.overlay_path,
                "overlay_connected": now - self.overlay_seen < 3,
                "overlay_url": self.overlay_url,
                "theme": dict(self.settings.theme),
            }

    def require_chat(self) -> None:
        if not self.practice and not self.connected:
            raise ValueError("Connect Twitch first, or enable Test mode.")

    def action(self, action: str, data: dict[str, object]) -> dict[str, object]:
        # Blocking network requests and native dialogs must not hold the game lock.
        if action == "connect":
            if self.practice:
                raise ValueError("Turn off Test mode before connecting Twitch.")
            client_id = self.settings.client_id
            if not client_id:
                raise ValueError(
                    "This build is missing its Twitch app configuration. Use the official release."
                )
            channel = normalize_channel(str(data.get("channel", "")), allow_empty=True)
            with self.lock:
                if self.game.phase not in ("ready", "over") and channel != self.settings.channel:
                    raise ValueError("Reset the game before logging into a different channel.")
            result = self.twitch.connect(client_id, channel)
            with self.lock:
                self.settings.client_id, self.settings.channel = client_id, channel
                self.settings.save()
            return result
        if action == "search_channels":
            return {"channels": self.twitch.search(str(data.get("query", "")))}
        if action == "watch_channel":
            channel = normalize_channel(str(data.get("channel", "")))
            with self.lock:
                if self.game.phase not in ("ready", "over"):
                    raise ValueError("Reset the game before changing channels.")
            self.twitch.watch(channel)
            with self.lock:
                self.settings.channel = channel
                self.settings.save()
            return {"channel": channel}
        if action == "disconnect":
            self.twitch.stop()
            return {}
        if action in ("install", "browse"):
            request = DialogRequest(save=action == "install")
            self.dialogs.put(request)
            if not request.done.wait(300):
                raise ValueError("File dialog timed out. Try again.")
            if request.error:
                raise ValueError(request.error)
            return {"path": request.result}
        with self.lock:
            now, wall = time.monotonic(), time.time()
            self.game.tick(now)
            if action == "start":
                self.require_chat()
                self.game.start(str(data.get("first", "random")), now, wall)
            elif action == "select":
                cell = data.get("cell")
                if not isinstance(cell, int) or isinstance(cell, bool):
                    raise ValueError("Select a numbered square.")
                self.game.select(cell)
            elif action == "confirm":
                self.require_chat()
                self.game.confirm(now, wall)
            elif action == "retry":
                self.require_chat()
                if self.game.phase != "no_votes":
                    raise ValueError("There is no empty vote to retry.")
                self.game.start_vote(now, wall)
            elif action == "pause":
                self.game.pause(now)
            elif action == "resume":
                self.require_chat()
                self.game.resume(now, wall)
            elif action == "visibility":
                self.game.visible = not self.game.visible
                self.settings.visible = self.game.visible
                self.settings.save()
            elif action == "reset":
                self.game.reset()
            elif action == "clear_scores":
                self.game.scores = {"X": 0, "O": 0, "draw": 0}
            elif action == "theme":
                self.settings.theme = validate_theme(data.get("theme"))
                self.settings.save()
            elif action == "reset_theme":
                self.settings.theme = dict(DEFAULT_THEME)
                self.settings.save()
            elif action == "practice":
                if self.connected or (
                    self.twitch.thread is not None and self.twitch.thread.is_alive()
                ):
                    raise ValueError("Disconnect Twitch before switching Test mode.")
                if self.game.phase not in ("ready", "over"):
                    raise ValueError("Reset this game before switching Test mode.")
                self.practice = not self.practice
                self.game.reset()
            elif action == "test_vote":
                if not self.practice:
                    raise ValueError("Test votes are only available in Test mode.")
                if not self.game.vote(
                    str(data.get("user", "demo")), str(data.get("text", "")), now
                ):
                    raise ValueError(
                        "Vote ignored: voting is closed, paused, or that square is occupied."
                    )
            elif action == "finish_test_vote":
                if not self.practice:
                    raise ValueError("Only Test mode can finish voting early.")
                if self.game.phase != "chat" or self.game.paused:
                    raise ValueError("Start or resume a test chat vote first.")
                self.game.tick(self.game.deadline)
            elif action == "quit":
                self.stopping.set()
            else:
                raise ValueError("Unknown controller action.")
        return {}


def make_handler(app: Application) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            pass  # Avoid logging control URLs or any credentials.

        def reply(
            self, status: int, payload: object, *, html: bool = False, overlay: bool = False
        ) -> None:
            content = str(payload).encode() if html else json.dumps(payload).encode()
            self.send_response(status)
            self.send_header(
                "Content-Type", "text/html; charset=utf-8" if html else "application/json"
            )
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            if overlay:
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Private-Network", "true")
                self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            self.end_headers()
            with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                self.wfile.write(content)

        def local_host(self) -> bool:
            return self.headers.get("Host") == f"127.0.0.1:{app.settings.port}"

        def authorized(self) -> bool:
            return (
                self.local_host()
                and secrets.compare_digest(
                    self.headers.get("Authorization", ""),
                    "Bearer " + app.control_token,
                )
                and self.headers.get("Origin", app.base) == app.base
            )

        def do_OPTIONS(self) -> None:
            path = urlsplit(self.path).path
            if self.local_host() and path == urlsplit(app.overlay_url).path + "/state":
                self.reply(200, {}, overlay=True)
            else:
                self.reply(403, {"error": "Forbidden"})

        def do_GET(self) -> None:
            path = urlsplit(self.path).path
            if not self.local_host():
                self.reply(403, {"error": "Use the controller's local address."})
            elif path == "/" or path == "/controller":
                self.reply(200, asset("controller.html"), html=True)
            elif path == urlsplit(app.overlay_url).path:
                self.reply(
                    200,
                    asset("overlay.html").replace("__STATE_URL__", app.overlay_url + "/state"),
                    html=True,
                )
            elif path == urlsplit(app.overlay_url).path + "/state":
                with app.lock:
                    app.overlay_seen = time.monotonic()
                    state = app.game.state(time.monotonic())
                    state["theme"] = dict(app.settings.theme)
                self.reply(200, state, overlay=True)
            elif path == "/api/state" and self.authorized():
                self.reply(200, app.state())
            else:
                self.reply(
                    404,
                    {
                        "error": "Not found or unauthorized. Reopen the controller from the executable."
                    },
                )

        def do_POST(self) -> None:
            if urlsplit(self.path).path != "/api/action" or not self.authorized():
                self.reply(403, {"error": "Forbidden"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if (
                    length < 1
                    or length > 8192
                    or self.headers.get("Content-Type") != "application/json"
                ):
                    raise ValueError("Expected a small JSON request.")
                self.connection.settimeout(10)
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict) or not isinstance(data.get("action"), str):
                    raise ValueError("Invalid action.")
                result = app.action(data["action"], data)
                self.reply(200, result)
            except (ValueError, OSError, TwitchError) as exc:
                message = (
                    "Twitch request failed. Check your Client ID and internet connection."
                    if isinstance(exc, TwitchError)
                    else str(exc)
                )
                self.reply(400, {"error": message})

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description="TechDaddy's Tic-Tac-Toe with Chat")
    parser.add_argument(
        "--no-browser", action="store_true", help="Do not open the controller automatically"
    )
    parser.add_argument("--config-dir", type=Path, default=default_config_dir())
    parser.add_argument("--port", type=int)
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Check embedded resources and game rules, then exit",
    )
    args = parser.parse_args()
    if args.self_test:
        game = Game()
        game.start("streamer", 0, 0)
        game.select(5)
        game.confirm(1, 1)
        assert game.vote("viewer", "1", 2)
        game.tick(31)
        assert game.board[0] == "O" and game.board[4] == "X"
        assert MARKER in asset("overlay.html") and "TechDaddy" in asset("controller.html")
        print("TechDaddy Tic-Tac-Toe self-test passed.")
        return
    settings = Settings.load(args.config_dir)
    if args.port is not None:
        if not 1024 <= args.port <= 65535:
            parser.error("Port must be between 1024 and 65535.")
        settings.port = args.port
    app = Application(settings)
    try:
        server = ThreadingHTTPServer(("127.0.0.1", settings.port), make_handler(app))
    except OSError as exc:
        raise SystemExit(
            f"Cannot start controller on port {settings.port}. Close the other instance or use --port. {exc}"
        ) from None
    server.daemon_threads = True
    settings.save()
    if settings.overlay_path:
        try:
            app.write_overlay(Path(settings.overlay_path), existing=True)
        except (OSError, ValueError):
            app.game.message = (
                "Saved HTML item could not be updated. Browse for it or install a new copy."
            )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = app.base + "/controller#" + app.control_token
    if not args.no_browser:
        webbrowser.open(url)
    if sys.stdout is not None:
        print(
            "TechDaddy Tic-Tac-Toe is running. Use Quit controller in its browser tab to exit.",
            flush=True,
        )
        if args.no_browser:
            print(url, flush=True)
    try:
        while not app.stopping.wait(0.1):
            with app.lock:
                app.game.tick(time.monotonic())
            try:
                request = app.dialogs.get_nowait()
            except queue.Empty:
                continue
            try:
                request.result = native_dialog(request.save)
                if request.result:
                    with app.lock:
                        app.write_overlay(Path(request.result), existing=not request.save)
            except Exception:
                request.error = (
                    "Could not save or locate the overlay. Choose a writable HTML item path."
                )
            finally:
                request.done.set()
    except KeyboardInterrupt:
        pass
    finally:
        app.twitch.stop()
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
