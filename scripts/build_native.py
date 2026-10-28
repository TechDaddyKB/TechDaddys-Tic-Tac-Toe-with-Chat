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
            [str(executable), "--no-browser", "--port", str(port), "--config-dir", folder],
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


def collect_licenses(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for package in ("certifi", "pyinstaller"):
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
        "--onefile",
        "--name",
        NAME,
        "--collect-data",
        "vtuber_tictactoe",
        "--collect-data",
        "certifi",
    ]
    if sys.platform == "win32":
        command.append("--windowed")
    else:
        command.extend(["--hidden-import", "tkinter", "--hidden-import", "tkinter.filedialog"])
    command.append(str(ROOT / "scripts/launch.py"))
    subprocess.run(command, cwd=ROOT, check=True)
    executable = ROOT / "dist" / (NAME + (".exe" if sys.platform == "win32" else ""))
    smoke_test(executable)
    stage = ROOT / "build" / f"{NAME}-{target}"
    stage.mkdir(parents=True, exist_ok=True)
    shutil.copy2(executable, stage / executable.name)
    for source, name in [
        ("README.md", "START-HERE.txt"),
        ("LICENSE", "LICENSE.txt"),
        ("THIRD-PARTY-NOTICES.txt", "THIRD-PARTY-NOTICES.txt"),
    ]:
        shutil.copy2(ROOT / source, stage / name)
    shutil.copy2(ROOT / "src/vtuber_tictactoe/assets/overlay.html", stage / "tic-tac-toe.html")
    collect_licenses(stage / "licenses")
    (stage / "BUILD-INFO.json").write_text(
        json.dumps(
            {
                "version": version,
                "target": target,
                "python": platform.python_version(),
                "platform": platform.platform(),
                "commit": os.environ.get("GITHUB_SHA", "local"),
                "self_test": "passed",
                "http_smoke_test": "passed",
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
