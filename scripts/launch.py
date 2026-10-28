"""Packaged entry point (PyInstaller or embedded Windows CPython)."""

import sys
import traceback

if __name__ == "__main__":
    try:
        from vtuber_tictactoe.app import main

        main()
    except (Exception, SystemExit) as error:
        # pythonw has no console; surface actionable startup failures natively.
        if isinstance(error, SystemExit) and error.code in (None, 0):
            raise
        if sys.platform == "win32" and not any(
            arg in sys.argv for arg in ("--self-test", "--gui-self-test")
        ):
            import ctypes

            ctypes.windll.user32.MessageBoxW(
                None,
                str(error),
                "TechDaddy Tic-Tac-Toe could not start",
                0x10,
            )
        else:
            traceback.print_exc()
        raise SystemExit(1) from None
