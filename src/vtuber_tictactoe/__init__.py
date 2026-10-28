"""Stream vs Chat: a local, read-only Twitch tic-tac-toe controller."""

__version__ = "0.2.1"


def main() -> None:
    from .app import main as run

    run()
