"""Build and smoke-test a native, self-contained Windows or Linux release."""

import hashlib
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import tomllib
import zipfile
from importlib.metadata import distribution
from importlib.metadata import version as package_version
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
NAME = "TechDaddyTicTacToe"


def smoke_test(executable: Path) -> None:
    subprocess.run([str(executable), "--self-test"], check=True, timeout=60)
    # Test the actual frozen server, not just an import of source code.
    with tempfile.TemporaryDirectory() as folder:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        process = subprocess.Popen(
            [str(executable), "--no-gui", "--port", str(port), "--config-dir", folder],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError("Frozen controller exited during startup.")
                settings = Path(folder) / "settings.json"
                if settings.exists():
                    try:
                        config = json.loads(settings.read_text())
                        url = f"http://127.0.0.1:{port}/overlay/{config['overlay_token']}/state"
                        with urlopen(url, timeout=2) as response:
                            state = json.load(response)
                        if len(state["board"]) == 9 and "theme" in state:
                            print("Frozen controller HTTP smoke test passed.")
                            return
                    except OSError:
                        pass
                time.sleep(0.1)
            raise RuntimeError("Frozen controller did not become ready within 30 seconds.")
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def audit_runtime(bundle: Path) -> None:
    files = [file.name.lower() for file in bundle.rglob("*") if file.is_file()]
    forbidden = [name for name in files if name.startswith(("_tkinter", "libtk", "libtcl"))]
    if forbidden:
        raise RuntimeError(f"Tk runtime unexpectedly included: {forbidden}")
    if not any("qt6widgets" in name for name in files):
        raise RuntimeError("Native Qt widgets runtime was not bundled.")
    if sys.platform == "linux":
        runtime = next(bundle.rglob("libpython3.12.so.1.0"))
        symbols = subprocess.check_output(["nm", "-D", "--defined-only", str(runtime)], text=True)
        if any(symbol in symbols for symbol in ("Tk_MenuObjCmd", "XOpenDisplay", "_XSend")):
            raise RuntimeError("Python runtime embeds the legacy Tk/Xlib implementation.")
    print("Runtime audit passed: Qt included; Tk absent.")


def gui_smoke_test(executable: Path) -> None:
    with tempfile.TemporaryDirectory() as folder:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        result = subprocess.run(
            [str(executable), "--gui-self-test", "--config-dir", folder, "--port", str(port)],
            capture_output=True,
            text=True,
            timeout=90,
        )
        qa = ROOT / "build" / "qa"
        qa.mkdir(parents=True, exist_ok=True)
        (qa / "native-gui.log").write_text(result.stdout + result.stderr, encoding="utf-8")
        report = Path(folder) / "gui-self-test.json"
        if result.returncode or not report.exists():
            raise RuntimeError("Frozen GUI check failed: " + result.stdout + result.stderr)
        content = json.loads(report.read_text())
        if content.get("gui_self_test") != "passed":
            raise RuntimeError(f"Frozen GUI check failed: {content}")
        shutil.copy2(report, qa / report.name)
        shutil.copy2(Path(folder) / "desktop-preview.png", qa / "desktop-preview.png")
        print("Frozen GUI passed: moves, votes, tabs, menus and file pickers.")


def collect_licenses(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for file in (ROOT / "licenses").glob("*.txt"):
        shutil.copy2(file, destination / file.name)
    for package in ("certifi", "pyinstaller", "PySide6-Essentials", "shiboken6"):
        dist = distribution(package)
        for file in dist.files or []:
            if (
                any(word in str(file).lower() for word in ("license", "copying"))
                and dist.locate_file(file).is_file()
            ):
                filename = package + "-" + str(file).replace("/", "_")
                shutil.copy2(dist.locate_file(file), destination / filename)
    candidates = [
        Path(sys.base_prefix) / "LICENSE.txt",
        Path(sys.base_prefix) / "lib/python3.12/LICENSE.txt",
    ]
    for candidate in candidates:
        if candidate.is_file():
            shutil.copy2(candidate, destination / "PYTHON-LICENSE.txt")
            break


def main() -> None:
    if sys.platform not in ("win32", "linux"):
        raise SystemExit("Release builds currently support Windows and Linux x86_64.")
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    if (
        os.environ.get("GITHUB_REF_TYPE") == "tag"
        and os.environ["GITHUB_REF_NAME"] != "v" + version
    ):
        raise SystemExit("The release tag must match the version in pyproject.toml.")
    target = "Windows-x64" if sys.platform == "win32" else "Linux-x64"
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--name",
        NAME,
        "--collect-data",
        "vtuber_tictactoe",
        "--collect-data",
        "certifi",
    ]
    if sys.platform == "win32":
        command.append("--windowed")
    command.extend(["--exclude-module", "tkinter", "--exclude-module", "_tkinter"])
    command.append(str(ROOT / "scripts/launch.py"))
    subprocess.run(command, cwd=ROOT, check=True)
    bundle = ROOT / "dist" / NAME
    executable = bundle / (NAME + (".exe" if sys.platform == "win32" else ""))
    audit_runtime(bundle)
    smoke_test(executable)
    gui_smoke_test(executable)
    stage = ROOT / "build" / f"{NAME}-{target}"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True, exist_ok=True)
    shutil.copytree(bundle, stage, dirs_exist_ok=True)
    for source, name in [
        ("README.md", "START-HERE.txt"),
        ("LICENSE", "LICENSE.txt"),
        ("THIRD-PARTY-NOTICES.txt", "THIRD-PARTY-NOTICES.txt"),
    ]:
        shutil.copy2(ROOT / source, stage / name)
    shutil.copy2(ROOT / "src/vtuber_tictactoe/assets/overlay.html", stage / "tic-tac-toe.html")
    shutil.copytree(ROOT / "docs", stage / "docs", dirs_exist_ok=True)
    shutil.copy2(ROOT / "README.md", stage / "README.md")
    collect_licenses(stage / "licenses")
    (stage / "BUILD-INFO.json").write_text(
        json.dumps(
            {
                "version": version,
                "target": target,
                "python": platform.python_version(),
                "pyside6": package_version("PySide6-Essentials"),
                "shiboken6": package_version("shiboken6"),
                "platform": platform.platform(),
                "commit": os.environ.get("GITHUB_SHA", "local"),
                "self_test": "passed",
                "http_smoke_test": "passed",
                "native_gui_test": "passed",
                "tk_free_runtime_audit": "passed",
            },
            indent=2,
        )
    )
    output = ROOT / "release" / f"{NAME}-v{version}-{target}.zip"
    output.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file in sorted(stage.rglob("*")):
            if file.is_file():
                archive.write(file, Path(stage.name) / file.relative_to(stage))
    checksum = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(".zip.sha256").write_text(f"{checksum}  {output.name}\n")
    print(output)


if __name__ == "__main__":
    main()
