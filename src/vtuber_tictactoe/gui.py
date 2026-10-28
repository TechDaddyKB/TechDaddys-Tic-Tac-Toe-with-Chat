"""Native Qt desktop controller. Qt widgets are touched only by the GUI thread."""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from math import ceil, sin
from pathlib import Path

from PySide6.QtCore import QLineF, QObject, QRectF, QRunnable, Qt, QThreadPool, QTimer, Signal, Slot
from PySide6.QtGui import QCloseEvent, QColor, QFont, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .app import Application
from .theme import DEFAULT_THEME

STYLE = """
QWidget { background:#15151c; color:#eeeaf4; font-family:'Segoe UI',sans-serif; font-size:13px; }
QMainWindow { background:#15151c; }
QLabel#title { font-size:23px; font-weight:700; color:#dcc5ff; }
QLabel#turn { font-size:18px; font-weight:600; color:#c8aff0; }
QTabWidget::pane { border:1px solid #373440; border-radius:8px; }
QTabBar::tab { padding:12px 22px; background:#202029; border-bottom:3px solid transparent; }
QTabBar::tab:selected { background:#2c2538; border-bottom:3px solid #c8aff0; }
QPushButton { padding:10px 14px; background:#2c2935; border:1px solid #4a405b; border-radius:7px; }
QPushButton:hover { background:#3c334b; border-color:#ccb3ef; }
QPushButton:disabled { color:#77727f; border-color:#302d37; background:#211f27; }
QPushButton#primary { background:#c6a6eb; color:#22182f; font-weight:700; }
QPushButton#primary:disabled { background:#554862; color:#a09aa7; }
QLineEdit,QListWidget { padding:10px; background:#101016; border:1px solid #393440; border-radius:7px; }
QGroupBox { border:1px solid #393440; border-radius:8px; margin-top:12px; padding-top:15px; }
QGroupBox::title { subcontrol-origin:margin; left:12px; padding:0 7px; color:#c8aff0; }
QCheckBox { spacing:9px; padding:7px 0; }
QStatusBar { color:#aaa2b8; }
"""


@dataclass
class BoardView:
    board: list[str] = field(default_factory=lambda: [""] * 9)
    phase: str = "ready"
    counts: list[int] = field(default_factory=lambda: [0] * 9)
    pending: int | None = None
    winning_line: tuple[int, ...] = ()
    seconds: int = 0
    voters: int = 0
    paused: bool = False


class BoardWidget(QWidget):
    square_selected = Signal(int)

    def __init__(self, *, sample: bool = False) -> None:
        super().__init__()
        self.sample = sample
        self.theme = dict(DEFAULT_THEME)
        self.view = BoardView()
        self.board_rect = QRectF()
        self.setMinimumSize(330, 370)
        self.setAccessibleName("Live board preview" if sample else "Tic-tac-toe board")

    def update_from(self, app: Application) -> None:
        with app.lock:
            game = app.game
            self.theme = dict(app.settings.theme)
            self.view = BoardView(
                board=list(game.board),
                phase=game.phase,
                counts=game.tally(),
                pending=game.pending,
                winning_line=game.winning_line,
                seconds=ceil(
                    game.remaining if game.paused else max(0, game.deadline - time.monotonic())
                ),
                voters=len(game.votes),
                paused=game.paused,
            )
        if self.sample:
            self.view = BoardView(
                board=["X", "", "O", "", "X", "", "", "", ""],
                phase="chat",
                seconds=app.settings.vote_seconds,
            )
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        side = min(self.width() - 32.0, self.height() - 86.0)
        left, top = (self.width() - side) / 2, 12.0
        self.board_rect = QRectF(left, top, side, side)
        if self.sample:
            painter.save()
            painter.setClipRect(self.rect())
            for y in range(0, self.height(), 16):
                for x in range(0, self.width(), 16):
                    painter.fillRect(
                        x, y, 16, 16, QColor("#24212c" if (x // 16 + y // 16) % 2 else "#1c1923")
                    )
            painter.restore()
        unit = side / 3
        for index, mark in enumerate(self.view.board):
            x, y = left + (index % 3) * unit, top + (index // 3) * unit
            cell = QRectF(x + 7, y + 7, unit - 14, unit - 14)
            if index in self.view.winning_line:
                painter.fillRect(cell, QColor("#294238"))
            if self.view.pending == index + 1 and not mark:
                painter.fillRect(cell, QColor("#3c2d40"))
            color = QColor(self.theme["numbers"])
            painter.setPen(color)
            painter.setFont(QFont("Sans Serif", max(10, int(unit * 0.12 if mark else unit * 0.31))))
            painter.drawText(
                cell,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
                if mark
                else Qt.AlignmentFlag.AlignCenter,
                str(index + 1),
            )
            shown = mark or ("X" if self.view.pending == index + 1 else "")
            if shown:
                painter.setPen(
                    QPen(
                        QColor(self.theme["streamer" if shown == "X" else "chat"]),
                        max(3.0, unit * 0.055),
                        Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap,
                    )
                )
                inset = unit * 0.28
                bounds = QRectF(x + inset, y + inset, unit - inset * 2, unit - inset * 2)
                if shown == "O":
                    painter.drawEllipse(bounds)
                else:
                    painter.drawLine(bounds.topLeft(), bounds.bottomRight())
                    painter.drawLine(bounds.topRight(), bounds.bottomLeft())
            if self.view.phase == "chat" and self.view.counts[index]:
                painter.setPen(QColor(self.theme["chat"]))
                painter.setFont(QFont("Sans Serif", max(8, int(unit * 0.09))))
                painter.drawText(
                    cell.adjusted(3, 3, -3, -3),
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom,
                    f"{self.view.counts[index]} vote(s)",
                )
        painter.setPen(
            QPen(QColor(self.theme["grid"]), 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        )
        for n in (1, 2):
            painter.drawLine(QLineF(left + unit * n, top + 3, left + unit * n, top + side - 3))
            painter.drawLine(QLineF(left + 3, top + unit * n, left + side - 3, top + unit * n))
        if self.view.phase == "chat":
            banner = QRectF(left, top + side + 18, side, 42)
            alpha = 0.7 if self.view.paused else 0.7 + 0.3 * sin(time.monotonic() * 5)
            painter.setOpacity(alpha)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(self.theme["banner_bg"]))
            painter.drawRoundedRect(banner, 8, 8)
            painter.setPen(QColor(self.theme["banner_text"]))
            painter.setFont(QFont("Sans Serif", 13, QFont.Weight.Bold))
            text = "VOTING PAUSED" if self.view.paused else f"CHAT: VOTE · {self.view.seconds}s"
            painter.drawText(banner, Qt.AlignmentFlag.AlignCenter, text)
        painter.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if (
            self.sample
            or self.view.phase != "streamer"
            or not self.board_rect.contains(event.position())
        ):
            return
        unit = self.board_rect.width() / 3
        col = int((event.position().x() - self.board_rect.left()) / unit)
        row = int((event.position().y() - self.board_rect.top()) / unit)
        index = row * 3 + col
        if index in range(9) and not self.view.board[index]:
            self.square_selected.emit(index + 1)


class WorkerSignals(QObject):
    succeeded = Signal(object)
    failed = Signal(str)


class Worker(QRunnable):
    def __init__(self, operation: Callable[[], dict[str, object]]) -> None:
        super().__init__()
        self.operation = operation
        self.signals = WorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            result = self.operation()
        except Exception as error:
            self.signals.failed.emit(str(error))
        else:
            self.signals.succeeded.emit(result)


class MainWindow(QMainWindow):
    def __init__(self, app: Application) -> None:
        super().__init__()
        self.app = app
        self.pool = QThreadPool(self)
        self.network_busy = False
        self.setWindowTitle("TechDaddy's Tic-Tac-Toe with Chat")
        self.resize(1100, 740)
        self.setMinimumSize(820, 700)
        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(22, 18, 22, 18)
        title = QLabel("TechDaddy’s Tic-Tac-Toe with Chat")
        title.setObjectName("title")
        outer.addWidget(title)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("functionTabs")
        outer.addWidget(self.tabs)
        self.build_game()
        self.build_twitch()
        self.build_appearance()
        self.build_overlay()
        self.setCentralWidget(central)
        self.statusBar().showMessage("Ready · X = streamer · O = chat")
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(150)
        self.refresh()

    def button(
        self, text: str, callback: Callable[[], object], *, primary: bool = False
    ) -> QPushButton:
        button = QPushButton(text)
        if primary:
            button.setObjectName("primary")
        button.clicked.connect(lambda _checked=False: callback())
        return button

    def invoke(self, action: str, **data: object) -> None:
        try:
            self.app.action(action, data)
        except (ValueError, OSError) as error:
            self.statusBar().showMessage(str(error), 12000)
        self.refresh()

    def network(
        self,
        action: str,
        callback: Callable[[dict[str, object]], None] | None = None,
        **data: object,
    ) -> None:
        if self.network_busy:
            return
        self.network_busy = True
        worker = Worker(lambda: self.app.action(action, data))

        self.network_callback = callback
        worker.signals.succeeded.connect(self.network_succeeded, Qt.ConnectionType.QueuedConnection)
        worker.signals.failed.connect(self.network_failed, Qt.ConnectionType.QueuedConnection)
        self.pool.start(worker)
        self.refresh()

    @Slot(object)
    def network_succeeded(self, value: dict[str, object]) -> None:
        self.network_busy = False
        if self.network_callback is not None and not self.app.stopping.is_set():
            self.network_callback(value)
        self.network_callback = None
        self.refresh()

    @Slot(str)
    def network_failed(self, message: str) -> None:
        self.network_busy = False
        self.network_callback = None
        self.statusBar().showMessage(message, 15000)
        self.refresh()

    def build_game(self) -> None:
        page = QWidget()
        columns = QHBoxLayout(page)
        board_column = QVBoxLayout()
        columns.addLayout(board_column, 1)
        layout = QVBoxLayout()
        columns.addLayout(layout, 1)
        self.turn = QLabel()
        self.turn.setWordWrap(True)
        self.turn.setObjectName("turn")
        board_column.addWidget(self.turn)
        self.board = BoardWidget()
        self.board.square_selected.connect(lambda cell: self.invoke("select", cell=cell))
        board_column.addWidget(self.board, 1)
        self.message = QLabel()
        self.message.setWordWrap(True)
        board_column.addWidget(self.message)
        self.vote_summary = QLabel()
        layout.addWidget(self.vote_summary)
        duration_row = QFormLayout()
        self.vote_duration = QSpinBox()
        self.vote_duration.setRange(1, 600)
        self.vote_duration.setSuffix(" seconds")
        self.vote_duration.setValue(self.app.settings.vote_seconds)
        self.vote_duration.setAccessibleName("Chat vote time")
        self.vote_duration.setToolTip("Saved automatically. Applies to the next chat turn.")
        self.vote_duration.valueChanged.connect(
            lambda seconds: self.invoke("vote_duration", seconds=seconds)
        )
        duration_row.addRow("Chat vote time", self.vote_duration)
        layout.addLayout(duration_row)
        duration_hint = QLabel("Applies to the next chat turn · saved automatically")
        duration_hint.setWordWrap(True)
        layout.addWidget(duration_hint)
        self.confirm = self.button(
            "Confirm move & give chat 30 seconds", lambda: self.invoke("confirm"), primary=True
        )
        layout.addWidget(self.confirm)
        row = QHBoxLayout()
        self.start = self.button(
            "Randomize who starts", lambda: self.invoke("start", first="random")
        )
        row.addWidget(self.start)
        row.addWidget(self.button("Reset round", self.reset_round))
        self.visibility = self.button("Hide board", lambda: self.invoke("visibility"))
        layout.addLayout(row)
        layout.addWidget(self.visibility)
        row = QHBoxLayout()
        self.pause = self.button("Pause voting", lambda: self.invoke("pause"))
        row.addWidget(self.pause)
        self.resume = self.button("Resume voting", lambda: self.invoke("resume"))
        row.addWidget(self.resume)
        self.retry = self.button("Reopen voting · 30 seconds", lambda: self.invoke("retry"))
        row.addWidget(self.retry)
        layout.addLayout(row)
        self.practice = QCheckBox("Test mode — simulated viewers, no Twitch login needed")
        self.practice.clicked.connect(lambda: self.invoke("practice"))
        layout.addWidget(self.practice)
        self.test_group = QGroupBox("Test controls")
        test = QVBoxLayout(self.test_group)
        row = QHBoxLayout()
        self.streamer_first = self.button(
            "Streamer first", lambda: self.invoke("start", first="streamer")
        )
        row.addWidget(self.streamer_first)
        self.chat_first = self.button("Chat first", lambda: self.invoke("start", first="chat"))
        row.addWidget(self.chat_first)
        self.finish_vote = self.button(
            "Finish test vote now", lambda: self.invoke("finish_test_vote")
        )
        test.addLayout(row)
        test.addWidget(self.finish_vote)
        row = QHBoxLayout()
        self.test_user = QLineEdit("viewer-one")
        self.test_user.setPlaceholderText("Simulated viewer name")
        row.addWidget(self.test_user)
        self.test_number = QLineEdit()
        self.test_number.setPlaceholderText("Vote 1–9")
        self.test_number.setMaxLength(1)
        self.test_number.setMaximumWidth(100)
        row.addWidget(self.test_number)
        self.test_cast = self.button(
            "Cast test vote",
            lambda: self.invoke(
                "test_vote", user=self.test_user.text(), text=self.test_number.text()
            ),
        )
        row.addWidget(self.test_cast)
        test.addLayout(row)
        layout.addWidget(self.test_group)
        self.scores = QLabel()
        layout.addWidget(self.scores)
        layout.addStretch()
        self.tabs.addTab(page, "Game")

    def reset_round(self) -> None:
        with self.app.lock:
            active = self.app.game.phase not in ("ready", "over")
        if (
            not active
            or QMessageBox.question(
                self, "Reset round?", "Reset the current round? Session scores are kept."
            )
            == QMessageBox.StandardButton.Yes
        ):
            self.invoke("reset")

    def build_twitch(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        help_text = QLabel(
            "Read-only Twitch chat. Your channel can be offline, and your own account can vote.\nLeave the channel blank to watch the signed-in account’s own channel."
        )
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        self.channel = QLineEdit(self.app.settings.channel)
        self.channel.setPlaceholderText("Channel name or https://twitch.tv/your_channel")
        layout.addWidget(self.channel)
        row = QHBoxLayout()
        self.login_button = self.button(
            "Log in with Twitch",
            lambda: self.network("connect", self.show_authorization, channel=self.channel.text()),
            primary=True,
        )
        row.addWidget(self.login_button)
        self.disconnect_button = self.button(
            "Disconnect / cancel login", lambda: self.invoke("disconnect")
        )
        row.addWidget(self.disconnect_button)
        layout.addLayout(row)
        self.authorization = QGroupBox("Authorize in your browser")
        auth = QVBoxLayout(self.authorization)
        self.auth_code = QLabel()
        auth.addWidget(self.auth_code)
        self.auth_url = QLineEdit()
        self.auth_url.setReadOnly(True)
        auth.addWidget(self.auth_url)
        auth.addWidget(self.button("Open Twitch authorization", self.open_authorization))
        layout.addWidget(self.authorization)
        self.authorization.hide()
        self.chat_status = QLabel()
        self.chat_status.setWordWrap(True)
        layout.addWidget(self.chat_status)
        row = QHBoxLayout()
        self.search = self.button(
            "Search channels",
            lambda: self.network("search_channels", self.show_channels, query=self.channel.text()),
        )
        row.addWidget(self.search)
        self.watch = self.button(
            "Watch selected channel",
            lambda: self.network("watch_channel", channel=self.channel.text()),
        )
        row.addWidget(self.watch)
        layout.addLayout(row)
        self.results = QListWidget()
        self.results.itemClicked.connect(
            lambda item: self.channel.setText(str(item.data(Qt.ItemDataRole.UserRole)))
        )
        layout.addWidget(self.results, 1)
        hint = QLabel(
            "Only chat:read permission is requested. Tokens remain in memory; log in each launch.\nRepeated votes from one viewer count once. Turn Test mode off to test through real Twitch chat."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.tabs.addTab(page, "Twitch")

    def show_authorization(self, result: dict[str, object]) -> None:
        self.auth_code.setText("Twitch code: " + str(result["user_code"]))
        self.auth_url.setText(str(result["verification_uri"]))
        self.authorization.show()
        self.open_authorization()

    def open_authorization(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        QDesktopServices.openUrl(QUrl(self.auth_url.text()))

    def show_channels(self, result: dict[str, object]) -> None:
        self.results.clear()
        items = result.get("channels", [])
        if isinstance(items, list):
            for entry in items:
                if isinstance(entry, dict):
                    self.results.addItem(str(entry["name"]) + " · @" + str(entry["login"]))
                    self.results.item(self.results.count() - 1).setData(
                        Qt.ItemDataRole.UserRole, str(entry["login"])
                    )
        if not self.results.count():
            self.statusBar().showMessage(
                "No matching channels. You can still enter the channel’s link directly.", 10000
            )

    def build_appearance(self) -> None:
        page = QWidget()
        layout = QHBoxLayout(page)
        self.preview = BoardWidget(sample=True)
        layout.addWidget(self.preview, 1)
        controls = QVBoxLayout()
        form = QFormLayout()
        self.color_buttons: dict[str, QPushButton] = {}
        for key, label in (
            ("grid", "Grid lines"),
            ("numbers", "Numbers"),
            ("streamer", "Streamer X"),
            ("chat", "Chat O"),
            ("banner_bg", "Banner background"),
            ("banner_text", "Banner text"),
        ):
            button = self.button("", lambda key=key: self.choose_color(key))
            self.color_buttons[key] = button
            form.addRow(label, button)
        controls.addLayout(form)
        controls.addWidget(self.button("Reset colors", lambda: self.invoke("reset_theme")))
        controls.addWidget(
            QLabel(
                "Colors save automatically.\nThe sample preview always shows a chat turn.\nThe HTML item updates immediately."
            )
        )
        controls.addStretch()
        layout.addLayout(controls)
        self.tabs.addTab(page, "Appearance")

    def choose_color(self, key: str) -> None:
        color = QColorDialog.getColor(
            QColor(self.app.settings.theme[key]),
            self,
            "Choose overlay color",
            QColorDialog.ColorDialogOption.DontUseNativeDialog,
        )
        if color.isValid():
            self.invoke("theme", theme={**self.app.settings.theme, key: color.name()})

    def build_overlay(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        info = QLabel(
            "Install the transparent HTML board in VTube Studio’s Items folder, or browse for an existing copy.\nThe controller remembers the file path and links it automatically."
        )
        info.setWordWrap(True)
        layout.addWidget(info)
        self.overlay_path = QLineEdit()
        self.overlay_path.setReadOnly(True)
        layout.addWidget(self.overlay_path)
        row = QHBoxLayout()
        self.install = self.button("Install HTML…", lambda: self.pick_overlay(True), primary=True)
        row.addWidget(self.install)
        self.browse = self.button("Browse existing…", lambda: self.pick_overlay(False))
        row.addWidget(self.browse)
        row.addWidget(
            self.button(
                "Copy file path",
                lambda: QApplication.clipboard().setText(self.app.settings.overlay_path),
            )
        )
        layout.addLayout(row)
        self.overlay_status = QLabel()
        layout.addWidget(self.overlay_status)
        guide = QLabel(
            "VTube Studio setup\n\n1. Add a Web Item and enable local-file access.\n2. Use the HTML file’s full path as its URL, or drag the file into VTube Studio.\n3. Use roughly 900 × 1024 pixels with a transparent background.\n4. Position and pin the item to your model.\n\nShow/hide keeps the item loaded. It does not pause voting.\nClosing this controller automatically hides the item.\n\nVTube Studio Web Items officially support Windows/macOS. Linux/Wine pinning remains unverified."
        )
        guide.setWordWrap(True)
        layout.addWidget(guide)
        layout.addWidget(self.button("Show / hide board", lambda: self.invoke("visibility")))
        layout.addWidget(
            self.button(
                "Copy browser-source URL",
                lambda: QApplication.clipboard().setText(self.app.overlay_url),
            )
        )
        layout.addStretch()
        self.tabs.addTab(page, "Overlay Setup")

    def pick_overlay(self, save: bool) -> None:
        dialog = QFileDialog(self, "Install HTML item" if save else "Choose existing HTML item")
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        dialog.setNameFilter("HTML items (*.html)")
        dialog.setDefaultSuffix("html")
        if self.app.settings.overlay_path:
            dialog.setDirectory(str(Path(self.app.settings.overlay_path).parent))
        if save:
            dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
            dialog.setFileMode(QFileDialog.FileMode.AnyFile)
            dialog.selectFile("tic-tac-toe.html")
        else:
            dialog.setFileMode(QFileDialog.FileMode.ExistingFile)
        if dialog.exec() == QFileDialog.DialogCode.Accepted:
            try:
                with self.app.lock:
                    self.app.write_overlay(Path(dialog.selectedFiles()[0]), existing=not save)
                self.statusBar().showMessage(
                    "HTML item linked. Load or reload it in VTube Studio.", 10000
                )
            except (OSError, ValueError) as error:
                self.statusBar().showMessage(str(error), 15000)
        dialog.deleteLater()
        self.refresh()

    def refresh(self) -> None:
        with self.app.lock:
            game = self.app.game
            self.board.update_from(self.app)
            self.preview.update_from(self.app)
            seconds = str(game.state(time.monotonic())["seconds"])
            self.turn.setText(
                ("TEST MODE · " if self.app.practice else "")
                + {
                    "ready": "Ready to play",
                    "streamer": "Streamer’s turn · select an empty square",
                    "chat": "Voting paused" if game.paused else "Chat is voting · " + seconds + "s",
                    "no_votes": "No votes · reopen voting",
                    "over": "Round complete",
                }[game.phase]
            )
            self.message.setText(game.message)
            self.vote_summary.setText(
                f"{len(game.votes)} unique vote(s) this turn · one current vote per viewer"
            )
            duration = self.app.settings.vote_seconds
            self.vote_duration.blockSignals(True)
            self.vote_duration.setValue(duration)
            self.vote_duration.blockSignals(False)
            self.confirm.setText(f"Confirm move & give chat {duration} seconds")
            self.retry.setText(f"Reopen voting · {duration} seconds")
            available = self.app.connected or self.app.practice
            self.start.setEnabled(available and game.phase in ("ready", "over"))
            self.confirm.setEnabled(
                available and game.phase == "streamer" and game.pending is not None
            )
            self.pause.setVisible(game.phase == "chat" and not game.paused)
            self.resume.setVisible(game.phase == "chat" and game.paused)
            self.resume.setEnabled(available)
            self.retry.setVisible(game.phase == "no_votes")
            self.retry.setEnabled(available)
            self.visibility.setText("Hide board" if game.visible else "Show board")
            self.practice.setChecked(self.app.practice)
            self.test_group.setVisible(self.app.practice)
            self.streamer_first.setEnabled(game.phase in ("ready", "over"))
            self.chat_first.setEnabled(game.phase in ("ready", "over"))
            self.finish_vote.setEnabled(game.phase == "chat" and not game.paused)
            self.test_cast.setEnabled(game.phase == "chat" and not game.paused)
            self.scores.setText(
                f"Streamer {game.scores['X']}     Draws {game.scores['draw']}     Chat {game.scores['O']}"
            )
            self.chat_status.setText(
                self.app.chat_status + f" · {self.app.chat_messages_received} messages received"
            )
            self.login_button.setEnabled(
                not self.app.practice and not self.app.connected and not self.network_busy
            )
            self.disconnect_button.setEnabled(not self.network_busy)
            self.search.setEnabled(self.app.connected and not self.network_busy)
            self.watch.setEnabled(
                self.app.connected and not self.network_busy and game.phase in ("ready", "over")
            )
            if self.app.connected or self.app.practice:
                self.authorization.hide()
            self.overlay_path.setText(self.app.settings.overlay_path)
            self.overlay_status.setText(
                "HTML item responding"
                if time.monotonic() - self.app.overlay_seen < 3
                else "HTML item offline · load it in VTube Studio"
            )
            for key, button in self.color_buttons.items():
                color = self.app.settings.theme[key]
                button.setText(color)
                foreground = "#15151c" if QColor(color).lightness() > 128 else "#ffffff"
                button.setStyleSheet(f"background:{color};color:{foreground};font-weight:700;")

    def closeEvent(self, event: QCloseEvent) -> None:
        self.app.stopping.set()
        self.pool.clear()
        event.accept()


def run_desktop(app: Application, *, self_test: bool = False) -> None:
    instance = QApplication.instance()
    qt = instance if isinstance(instance, QApplication) else QApplication([])
    qt.setStyle("Fusion")
    qt.setStyleSheet(STYLE)
    window = MainWindow(app)
    window.show()
    errors: list[str] = []
    if self_test:

        def verify() -> None:
            try:
                from .gui_checks import check_desktop

                check_desktop(window)
                result = {"gui_self_test": "passed"}
            except Exception as error:
                import traceback

                traceback.print_exc()
                errors.append(repr(error))
                result = {"gui_self_test": "failed", "error": str(error)}
            import json

            (app.settings.file.parent / "gui-self-test.json").write_text(
                json.dumps(result), encoding="utf-8"
            )
            window.close()
            qt.quit()

        QTimer.singleShot(0, verify)
    qt.exec()
    if errors:
        raise RuntimeError("Native GUI check failed: " + errors[0])
