"""Exercise the transparent file:// item against the controller’s real HTTP service."""

import argparse
import re
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from vtuber_tictactoe.app import Application, Settings, make_handler


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chromium", type=str)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as folder:
        app = Application(Settings(Path(folder) / "settings.json"))
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
        app.settings.port = server.server_port
        server.daemon_threads = True
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        overlay_file = Path(folder) / "board.html"
        app.write_overlay(overlay_file, existing=False)
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(
                    executable_path=args.chromium,
                    args=["--no-sandbox"],
                )
                errors = []
                app.action("vote_duration", {"seconds": 75})
                app.action("practice", {})
                app.action("start", {"first": "streamer"})
                app.action("select", {"cell": 5})
                app.action("confirm", {})
                app.action("test_vote", {"user": "viewer-one", "text": "1"})

                overlay = browser.new_page(viewport={"width": 900, "height": 1100})
                overlay.on("pageerror", lambda error: errors.append(str(error)))
                overlay.goto(overlay_file.as_uri())
                overlay.wait_for_function(
                    "getComputedStyle(document.getElementById('item')).opacity==='1'"
                )
                expect(overlay.locator("#voteBanner")).to_contain_text("CHAT: VOTE")
                expect(overlay.locator("#voteBanner")).not_to_contain_text("1–9")
                expect(overlay.locator("#voteBanner")).to_have_text(
                    re.compile(r"CHAT: VOTE · [0-9]+s")
                )
                assert Settings.load(Path(folder)).vote_seconds == 75
                assert int(overlay.locator("#voteBanner").inner_text().split(" · ")[1][:-1]) > 30
                metrics = overlay.evaluate("""() => ({
                    background:getComputedStyle(document.body).backgroundColor,
                    board:document.getElementById('board').getBoundingClientRect().width,
                    banner:document.getElementById('voteBanner').getBoundingClientRect().width,
                    animation:getComputedStyle(document.getElementById('voteBanner')).animationName,
                    bannerVisible:getComputedStyle(document.getElementById('voteBanner')).visibility
                })""")
                assert metrics["background"] == "rgba(0, 0, 0, 0)"
                assert abs(metrics["board"] - metrics["banner"]) < 1
                assert metrics["animation"] == "votePulse" and metrics["bannerVisible"] == "visible"
                app.action("theme", {"theme": {**app.settings.theme, "grid": "#112233"}})
                overlay.wait_for_function(
                    "getComputedStyle(document.querySelector('.grid path')).stroke==='rgb(17, 34, 51)'"
                )
                assert Settings.load(Path(folder)).theme["grid"] == "#112233"
                Path("build/qa").mkdir(parents=True, exist_ok=True)
                overlay.screenshot(path="build/qa/overlay.png", omit_background=True)
                app.action("pause", {})
                expect(overlay.locator("#voteBanner")).to_have_text("VOTING PAUSED")
                app.action("visibility", {})
                overlay.wait_for_function(
                    "getComputedStyle(document.getElementById('item')).opacity==='0'"
                )
                app.action("visibility", {})
                overlay.wait_for_function(
                    "getComputedStyle(document.getElementById('item')).opacity==='1'"
                )
                with app.lock:
                    app.game.resume(time.monotonic(), time.time())
                app.action("finish_test_vote", {})
                overlay.wait_for_function(
                    "getComputedStyle(document.getElementById('voteBanner')).visibility==='hidden'"
                )
                assert app.game.board[0] == "O"

                server.shutdown()
                overlay.wait_for_function(
                    "getComputedStyle(document.getElementById('item')).opacity==='0'", timeout=6000
                )
                assert not errors, errors
                browser.close()
                print(
                    "UI verified: moves, chat votes, transparent file overlay, equal-width pulsing banner, saved live colors, pause/hide and fail-closed visibility."
                )
        finally:
            server.shutdown()
            server.server_close()
            worker.join(2)


if __name__ == "__main__":
    main()
