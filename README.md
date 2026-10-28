# TechDaddy's Tic-Tac-Toe with Chat

A portable Windows/Linux Twitch chat game with a numbered, transparent VTube Studio HTML item.

**[Download the latest release](https://github.com/TechDaddyKB/TechDaddys-Tic-Tac-Toe-with-Chat/releases/latest)** — no Python or package installs required.

## Quick start

1. Extract the entire release archive.
2. Windows: double-click `TechDaddyTicTacToe.exe`.
   Linux x86_64: run `./TechDaddyTicTacToe` (mark it executable in Properties if needed).
3. A native desktop window opens with **Game**, **Twitch**, **Appearance**, and **Overlay Setup** tabs.
   No Python, Node, pip, or package installs are needed. Keep the executable beside its `_internal` folder.
4. Click **Test mode**, then **Randomize who starts** to try it without Twitch.
5. In **Overlay Setup**, click **Install HTML…** and save the item in VTube Studio's Items folder.
   Alternatively copy the included `tic-tac-toe.html` there, then **Browse existing…** to link it.
6. In VTube Studio, add a **Web Item**, allow local file access in its settings,
   and use the HTML's full path as its URL. You can also drag the HTML into VTube Studio.
   Use approximately 900 × 1024 pixels, a transparent background, then move and pin it to the model.
7. The Game tab's **Show board / Hide board** button changes visibility without unloading the item.
   Visibility does not pause voting. Use **Pause voting** separately.
8. Turn Test mode off before logging into Twitch.

Close the desktop window to quit the controller. The browser is used only for Twitch authorization.
The overlay hides automatically after about 2.5 seconds if the controller stops responding.
Reload the HTML in VTube Studio after changing its linked path or controller port.

## Twitch setup (one-time registration, then normal browser login)

This build includes the public Client ID supplied for this application. Streamers can
use **Log in with Twitch** immediately; they do not need to register an app or install
any developer tools. The developer setup below is only for replacing that registration.

For developers replacing the bundled app registration:

1. Register an app at https://dev.twitch.tv/console/apps using a verified Twitch account with 2FA.
2. Set the application's **Client Type to Public**, and choose a suitable category such as Chat Bot.
   If a redirect URI is required, use `http://localhost`; this app's device login does not use redirects.
3. Put the public **Client ID** in `src/vtuber_tictactoe/assets/twitch-client-id.txt` and rebuild. Do not distribute a client secret. The controller has no Client ID field.
4. Enter the Twitch channel name or its `https://twitch.tv/channel` link, then click **Log in with Twitch**.
   Leave it blank to use the signed-in account's own channel.
5. Open the displayed Twitch authorization link, sign in, and enter the displayed device code if asked.
6. Wait until **Chat connected** appears. The signed-in account must be allowed to read the channel.

Once logged in, **Search channels** lets you search Twitch by name. Choose a result, then
click **Watch selected channel**. You can also paste a link directly. Reset an active game before
switching channels so votes from different audiences cannot be combined. Twitch's search
includes channels that have streamed in the last six months; direct name/link entry still
works when an account is missing from search results. Search requires no additional scope.

Only `chat:read` is requested. The application never sends chat messages.
Tokens are held in memory and are not saved to disk; login is required each launch.
Tokens are validated on connection and at least hourly, and refreshed in memory when expired.
The public Client ID, selected channel, overlay path, board visibility, six color choices,
and local overlay connection key are saved in
`%LOCALAPPDATA%/techdaddy-tictactoe/settings.json` on Windows, or
`~/.config/techdaddy-tictactoe/settings.json` on Linux (honoring `XDG_CONFIG_HOME`).

For distribution, put your registered app's public Client ID in
`src/vtuber_tictactoe/assets/twitch-client-id.txt` before building. It is included automatically in both native builds.
The Client ID is public, but must belong to this application, not another developer's app.

## Test mode (no Twitch account needed)

Turn on **Test mode** in the Game tab while Twitch is disconnected. Use **Streamer first**
or **Chat first** to choose a starting side, or randomize it. Cast a simulated vote using the
viewer-name and number fields. Each simulated viewer still gets one vote; change the viewer name to
simulate another person. **Finish test vote now** resolves the votes immediately without waiting
30 seconds. That shortcut is unavailable in normal connected play.

To test the real Twitch connection, turn Test mode off, log in, and send a number in your own channel
while the board says it is chat's turn. Your channel can be offline. Your own account's messages count.
The controller shows received chat messages and unique votes so you can see the connection working.
Sending `1` several times from the same account counts as **one** vote for square 1.

## Playing

- **Randomize who starts** gives either side the first turn. Streamer is always X; chat is O.
- On the streamer's turn, click an empty square in the controller. Click another to change your
  selection. **Confirm move & give chat 30 seconds** commits it and opens chat voting.
- Chat votes by sending exactly one number, `1` through `9`, for an empty square.
  Spaces around the digit are allowed. Messages such as `vote 5`, `!5`, or `1 2` are ignored.
- Each viewer has one vote per chat turn. Their latest valid vote replaces their previous vote.
  Repeated messages from the same person do not add extra votes.
- The channel owner's own messages count too, so you can test through your own offline channel.
  Messages originating from other shared-chat rooms are ignored.
- At 30 seconds, the highest count wins. Ties are chosen randomly among tied leaders.
- If nobody votes, no mark is placed. Use **Reopen voting** for another 30 seconds.
- Pause preserves the current votes and remaining time. Disconnects automatically pause a chat
  turn. After reconnecting, click **Resume voting** yourself.
- A win or draw stops play. Start a rematch or reset the game. Scores last for this controller session.
- Hiding the board affects only the HTML item. The controller's board stays available.
- While chat votes, a board-width **CHAT: VOTE** banner pulses below the grid.
  Pausing changes it to a static **VOTING PAUSED** banner; other turns hide it.
- The **Appearance** tab customizes grid lines, numbers, X, O, banner background and banner text.
  A live sample preview shows both marks and the banner. Changes save automatically and
  apply to the loaded item without reloading it. The HTML item honors browser/OS reduced-motion settings.

## Compatibility and current validation

- Windows release: x86_64, Windows 10/11. GitHub Actions builds a native standalone `.exe`
  on Windows and tests the frozen native GUI, file pickers, bundled resources, and local overlay service.
- Linux release: x86_64 desktop, built on Ubuntu 22.04 (glibc 2.35). Targets Ubuntu 22.04,
  Debian 12, and newer compatible desktops. Python and Qt are bundled; a display server and ordinary OS desktop libraries are expected.
  Twitch authorization uses the default browser. Tk is not included. ARM Linux is not covered.
- VTube Studio officially documents Web Items for **Windows and macOS**. The Linux controller works
  independently, but VTube Studio's Linux/Wine behavior has not been verified. OBS browser sources
  can also use **Copy browser-source URL** in Overlay Setup.
- The included HTML is a template. Install or browse it once so the controller writes its local
  connection address into the file. Keep the controller and Web Item on the same machine.
- A browser preview counts as an active HTML item. The status does not prove that VTube Studio itself is connected.
- No actual Twitch account was authorized and no VTube Studio installation was available during
  development. Automated tests use fake Twitch responses. Live OAuth/chat and VTS pinning still need testing.
- HTTP is bound only to 127.0.0.1. Control actions require a per-launch key. The overlay has a separate,
  persistent read-only key and receives game state only. The desktop window controls the game directly.

## Version 0.2.0 fixes

The controller now uses native Qt tabs. It removes Tk and pins a newer Python runtime without
embedded Tk/Xlib, addressing the crash path reported on Arch/Hyprland. CI audits the packaged runtime
and repeatedly opens menus and file dialogs; this is not a claim of testing that exact user desktop.
Twitch HTTPS and IRC connections explicitly require TLS 1.2 or newer, while keeping hostname and
certificate verification enabled (CodeQL `py/insecure-protocol`). Existing saved settings are reused.

## Troubleshooting

- **Another instance/port in use:** quit the previous controller. Advanced users can run
  `TechDaddyTicTacToe --port 18766`, then reload the linked HTML item.
- **Blank overlay:** make sure the controller is running, the board is visible, and you installed
  or browsed the file in this controller. Enable local file access and reload the item in VTube Studio.
  Try the copied browser-source URL to distinguish controller problems from VTS local-file settings.
- **No file dialog on Linux:** a graphical desktop is required. Both builds use Qt-owned file dialogs. If a Linux Qt platform-plugin error appears,
  ensure your desktop provides its X11/XCB or Wayland libraries (including `libxcb-cursor0` on Ubuntu).
- **Connection error after login:** check that the app is Public, the Client ID is correct, and
  outbound HTTPS plus IRC TLS on port 6697 are allowed. Disconnect and reconnect for a fresh login.
- **Unexpected browser security prompt for local network access:** allow the HTML item to reach
  the local controller. No remote overlay hosting is used.
- **Stream delay:** chat gets 30 real seconds starting when you confirm, independent of Twitch video
  latency. Low-latency streaming gives viewers more useful voting time.

## Development and reproducible builds

Python 3.12+, uv, and an ordinary platform toolchain are needed only by developers.

```
uv sync --locked
make check
make format-check
make tests
uv run vtuber-tictactoe
make build-linux
make build-windows
```

Both native releases use PyInstaller folder packaging on their respective operating systems.
Keep the executable and `_internal` folder together after extracting the ZIP. Qt libraries remain
separate shared libraries and can be replaced with compatible versions.
Each archive includes its executable, HTML template, instructions, license notices, and build metadata.
SHA256 checksums are uploaded alongside the ZIPs. Build tools are only needed by developers.
`TechDaddyTicTacToe --self-test` checks embedded resources and a basic game sequence.

GitHub Actions runs lint, both type checkers, formatting, unit/HTTP/transport tests, browser checks,
and native Windows/Linux builds. Publishing a GitHub release runs the pipeline for that exact tag
and attaches both platform ZIPs only after all checks pass. A release tag must match the version in
`pyproject.toml` (for example, `v0.2.0`). Ordinary pushes and pull requests also run the checks/builds.

The project is a tested first release, not a claim of completed platform acceptance testing.
Game rules and color validation have full branch coverage. OAuth, network and controller boundaries have
additional deterministic tests; the initial overall coverage gate is 75%, with live platform
checks listed above rather than represented as mocked production evidence.

The included browser verification script exercises real local HTML loading,
banner width/animation, transparent backgrounds, live color persistence,
pause/visibility behavior and automatic hiding when the controller stops.
The separate `--gui-self-test` diagnostic exercises actual Qt widgets, test voting, all tabs,
menus and repeated open/save/cancel dialogs. CI runs it against the packaged executable on Windows
and under Xvfb/XCB on Linux; an offscreen run alone does not establish compositor compatibility.
Run `uv run playwright install chromium` and `uv run python scripts/verify_ui.py` to repeat it;
`--chromium /path/to/chromium` can select an existing browser executable.

## Official references

- VTube Studio Web Items: https://github.com/DenchiSoft/VTubeStudio/wiki/Web-Items
- Twitch public-client device login: https://dev.twitch.tv/docs/authentication/getting-tokens-oauth/
- Twitch IRC and scopes: https://dev.twitch.tv/docs/chat/irc/
- Token validation: https://dev.twitch.tv/docs/authentication/validate-tokens/

MIT licensed application. Third-party runtimes and libraries retain their own licenses.
