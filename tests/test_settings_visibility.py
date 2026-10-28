from pathlib import Path

from vtuber_tictactoe.app import Application, Settings


def test_visibility_is_saved_and_restored(tmp_path: Path) -> None:
    app = Application(Settings(tmp_path / "settings.json"))
    assert app.game.visible
    app.action("visibility", {})
    restored = Application(Settings.load(tmp_path))
    assert not restored.game.visible
    restored.action("visibility", {})
    assert Settings.load(tmp_path).visible
