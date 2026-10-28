The controller now opens as a native desktop application with **Game**, **Twitch**, **Appearance**, and **Overlay Setup** tabs. The transparent VTube Studio board remains an HTML Web Item.

- Play and test rounds from the desktop window, manage Twitch login/channel search, preview and save colors, and install or browse for the HTML item.
- Retains broadcaster votes, simulated test votes, a live countdown banner, saved settings, and show/hide controls.
- Removes Tk and the embedded Tk/Xlib runtime involved in the reported Linux crash. Uses Qt-owned menus and file dialogs and Python 3.12.14.
- Requires TLS 1.2 or newer for Twitch HTTPS/IRC connections, keeping certificate and hostname checks enabled (security alert #1).
- CI tests the packaged GUI, repeated file dialogs, game controls, and overlay service on Windows and Linux.

Download the ZIP for your platform and extract the **entire folder**. Keep the executable beside its `_internal` folder; no Python installation is needed. Windows: run `TechDaddyTicTacToe.exe`. Linux: run `./TechDaddyTicTacToe`. Existing saved settings are reused.

Windows/Linux x86_64 packages and SHA256 checksums are attached by CI after checks pass. The exact reported Hyprland desktop, live Twitch authorization, and VTube Studio pinning still require real-user testing.
