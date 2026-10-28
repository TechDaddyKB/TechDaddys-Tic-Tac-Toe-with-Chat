# Development

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
and attaches both platform ZIPs only after all checks pass.
The explicit main-branch commit `Release v1.0.0: community showdown` also publishes this
release directly from CI after verifying security alert #1 is fixed; ordinary pushes do not publish. A release tag must match the version in
`pyproject.toml` (for example, `v1.0.0`). Ordinary pushes and pull requests also run the checks/builds.

Automated checks cover rules, transport boundaries, the overlay and packaged desktop widgets.
Live Twitch authorization and VTube Studio model pinning still need user acceptance checks.
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

Version 1.0 adds numbered-square/concession voting, a separate Practice tab, and native GUI screenshots. Run frozen GUI checks on Windows and Linux before publishing.
