"""Exercise the real controller and file:// overlay in a local Chromium browser."""

import argparse
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
                page = browser.new_page(viewport={"width": 1280, "height": 1100})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(app.base + "/controller#" + app.control_token)
                expect(page.locator("#board button")).to_have_count(9)
                page.locator("#practice").click()
                expect(page.locator("#practiceFields")).to_be_visible()
                page.locator("#start").click()
                expect(page.locator("#start")).to_be_disabled()
                with app.lock:
                    app.game.reset()
                    app.game.start("streamer", time.monotonic(), time.time())
                page.locator("#board button").nth(4).click()
                expect(page.locator("#board button").nth(4)).to_have_class("cell selected")
                page.locator("#confirm").click()
                expect(page.locator("#phase")).to_contain_text("chat")
                page.locator("#testText").fill("1")
                page.locator("#testVote").click()
                expect(page.locator(".votecount")).to_have_text("1 vote")

                overlay = browser.new_page(viewport={"width": 900, "height": 1100})
                overlay.on("pageerror", lambda error: errors.append(str(error)))
                overlay.goto(overlay_file.as_uri())
                overlay.wait_for_function(
                    "getComputedStyle(document.getElementById('item')).opacity==='1'"
                )
                expect(overlay.locator("#voteBanner")).to_contain_text("CHAT: VOTE")
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
                page.locator("#color-grid").evaluate(
                    "el => {el.value='#112233';el.dispatchEvent(new Event('input',{bubbles:true}))}"
                )
                overlay.wait_for_function(
                    "getComputedStyle(document.querySelector('.grid path')).stroke==='rgb(17, 34, 51)'"
                )
                assert Settings.load(Path(folder)).theme["grid"] == "#112233"
                preview = page.frame_locator("#themePreview")
                expect(preview.locator("#voteBanner")).to_contain_text("CHAT: VOTE")

                Path("build/qa").mkdir(parents=True, exist_ok=True)
                page.screenshot(path="build/qa/controller.png", full_page=True)
                overlay.screenshot(path="build/qa/overlay.png", omit_background=True)
                page.locator("#pause").click()
                expect(overlay.locator("#voteBanner")).to_have_text("VOTING PAUSED")
                page.locator("#visibility").click()
                overlay.wait_for_function(
                    "getComputedStyle(document.getElementById('item')).opacity==='0'"
                )
                page.locator("#visibility").click()
                overlay.wait_for_function(
                    "getComputedStyle(document.getElementById('item')).opacity==='1'"
                )
                with app.lock:
                    app.game.resume(time.monotonic(), time.time())
                    app.game.tick(app.game.deadline)
                overlay.wait_for_function(
                    "getComputedStyle(document.getElementById('voteBanner')).visibility==='hidden'"
                )
                assert app.game.board[0] == "O"

                page.set_viewport_size({"width": 390, "height": 844})
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                server.shutdown()
                overlay.wait_for_function(
                    "getComputedStyle(document.getElementById('item')).opacity==='0'", timeout=6000
                )
                assert not errors, errors
                browser.close()
                print(
                    "UI verified: moves, chat votes, transparent file overlay, equal-width pulsing banner, saved live colors, pause/hide, mobile layout, and fail-closed visibility."
                )
        finally:
            server.shutdown()
            server.server_close()
            worker.join(2)


if __name__ == "__main__":
    main()
