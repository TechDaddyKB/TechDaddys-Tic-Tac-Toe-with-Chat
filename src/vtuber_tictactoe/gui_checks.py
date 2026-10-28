"""Acceptance checks shared by source and frozen native desktop builds."""

import tempfile
from pathlib import Path

from PySide6.QtCore import QEventLoop, Qt, QThread, QTimer
from PySide6.QtGui import QColor, QCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QColorDialog, QFileDialog, QLineEdit, QMenu

from .gui import MainWindow


def check_desktop(window: MainWindow) -> None:
    assert [window.tabs.tabText(i) for i in range(window.tabs.count())] == [
        "Game",
        "Twitch",
        "Appearance",
        "Overlay Setup",
    ]
    assert not window.app.practice
    window.practice.click()
    window.chat_first.click()
    window.test_number.setText("1")
    window.test_cast.click()
    window.test_cast.click()
    assert window.app.game.tally()[0] == 1
    window.finish_vote.click()
    assert window.app.game.board[0] == "O" and window.app.game.phase == "streamer"
    QApplication.processEvents()
    QTest.mouseClick(
        window.board, Qt.MouseButton.LeftButton, pos=window.board.board_rect.center().toPoint()
    )
    window.confirm.click()
    assert window.app.game.board[4] == "X" and window.app.game.phase == "chat"
    window.pause.click()
    assert window.app.game.paused
    window.resume.click()
    assert not window.app.game.paused
    original = window.app.game.visible
    window.visibility.click()
    assert window.app.game.visible != original
    window.visibility.click()
    assert window.app.game.visible == original
    old_theme = dict(window.app.settings.theme)

    def color_picker() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QColorDialog)
        dialog.setCurrentColor(QColor("#112233"))
        dialog.accept()

    QTimer.singleShot(100, color_picker)
    window.choose_color("grid")
    assert window.preview.theme["grid"] == "#112233"
    finished = []
    loop = QEventLoop()

    def completed(result: dict[str, object]) -> None:
        assert QThread.currentThread() == window.thread()
        finished.append(True)
        loop.quit()

    window.network("theme", completed, theme=old_theme)
    QTimer.singleShot(3000, loop.quit)
    loop.exec()
    assert finished and not window.network_busy, "Background completion did not reach GUI thread"
    for index in range(window.tabs.count()):
        window.tabs.setCurrentIndex(index)
        QApplication.processEvents()
    for _ in range(20):
        menu = QMenu(window)
        menu.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        menu.addAction("HTML item")
        menu.popup(window.mapToGlobal(window.rect().center()))
        QApplication.processEvents()
        menu.close()
        menu.deleteLater()
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "item.html"
        errors: list[str] = []

        def dismiss(*, choose: bool) -> None:
            dialog = QApplication.activeModalWidget()
            if not isinstance(dialog, QFileDialog):
                errors.append("Expected an active Qt file picker")
                return
            if choose:
                dialog.setDirectory(str(path.parent))
                field = dialog.findChild(QLineEdit, "fileNameEdit")
                assert field is not None
                field.setText(path.name)
                dialog.accept()
            else:
                dialog.reject()

        for _ in range(3):
            for save in (True, False):
                QTimer.singleShot(100, lambda: dismiss(choose=False))
                before = window.app.settings.overlay_path
                window.pick_overlay(save)
                assert window.app.settings.overlay_path == before
            if path.exists():
                path.unlink()
            QTimer.singleShot(100, lambda: dismiss(choose=True))
            window.pick_overlay(True)
            assert path.is_file() and "STREAM-VS-CHAT-OVERLAY" in path.read_text(), (
                window.statusBar().currentMessage()
            )
            QTimer.singleShot(100, lambda: dismiss(choose=True))
            window.pick_overlay(False)
            assert Path(window.app.settings.overlay_path).samefile(path), (
                window.app.settings.overlay_path,
                str(path),
            )
        assert not errors, errors
    window.app.settings.overlay_path = ""
    window.app.settings.save()
    window.tabs.setCurrentIndex(0)
    QApplication.processEvents()
    if not window.grab().save(str(window.app.settings.file.parent / "desktop-preview.png")):
        raise RuntimeError("Could not capture desktop acceptance preview.")
