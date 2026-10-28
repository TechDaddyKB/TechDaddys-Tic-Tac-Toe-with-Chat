"""Deterministic game rules; time and randomness are supplied at the boundary."""

import re
from dataclasses import dataclass, field
from math import ceil
from random import SystemRandom
from typing import Literal

Phase = Literal["ready", "streamer", "chat", "no_votes", "over"]
LINES = (
    (0, 1, 2),
    (3, 4, 5),
    (6, 7, 8),
    (0, 3, 6),
    (1, 4, 7),
    (2, 5, 8),
    (0, 4, 8),
    (2, 4, 6),
)


@dataclass
class Game:
    board: list[str] = field(default_factory=lambda: [""] * 9)
    phase: Phase = "ready"
    visible: bool = True
    paused: bool = False
    pending: int | None = None
    votes: dict[str, int] = field(default_factory=dict)
    deadline: float = 0.0
    accept_after: float = 0.0
    remaining: float = 30.0
    winner: str = ""
    winning_line: tuple[int, ...] = ()
    message: str = "Ready when you are. Randomize who starts."
    scores: dict[str, int] = field(default_factory=lambda: {"X": 0, "O": 0, "draw": 0})
    rng: SystemRandom = field(default_factory=SystemRandom, repr=False)

    def reset(self) -> None:
        self.board = [""] * 9
        self.phase = "ready"
        self.paused = False
        self.pending = None
        self.votes.clear()
        self.winner = ""
        self.winning_line = ()
        self.remaining = 30.0
        self.message = "Ready when you are. Randomize who starts."

    def start(self, first: str, now: float, wall: float) -> None:
        if self.phase not in ("ready", "over"):
            raise ValueError("Reset the current game before starting another.")
        self.reset()
        if first == "random":
            first = self.rng.choice(("streamer", "chat"))
        if first == "chat":
            self.start_vote(now, wall)
            self.message = "Chat starts! Type a free square's number."
        elif first == "streamer":
            self.phase = "streamer"
            self.message = "Streamer starts! Select a square, then confirm."
        else:
            raise ValueError("Choose streamer, chat, or random.")

    def start_vote(self, now: float, wall: float) -> None:
        self.phase = "chat"
        self.paused = False
        self.votes.clear()
        self.deadline = now + 30.0
        self.accept_after = wall
        self.remaining = 30.0
        self.message = "Chat's turn! Type a free square's number (1–9)."

    def select(self, cell: int) -> None:
        if self.phase != "streamer":
            raise ValueError("Wait for the streamer's turn.")
        if cell not in range(1, 10) or self.board[cell - 1]:
            raise ValueError("Select an empty square from 1 to 9.")
        self.pending = cell

    def confirm(self, now: float, wall: float) -> None:
        if self.phase != "streamer" or self.pending is None:
            raise ValueError("Select an empty square first.")
        self.board[self.pending - 1] = "X"
        self.pending = None
        if not self.finish():
            self.start_vote(now, wall)

    def vote(self, user: str, text: str, now: float, sent_at: float | None = None) -> bool:
        if self.phase != "chat" or self.paused or now >= self.deadline:
            return False
        if sent_at is not None and sent_at < self.accept_after:
            return False
        text = text.strip()
        if not user or re.fullmatch(r"[1-9]", text) is None:
            return False
        cell = int(text)
        if self.board[cell - 1] or (len(self.votes) >= 100_000 and user not in self.votes):
            return False
        self.votes[user] = cell
        return True

    def tally(self) -> list[int]:
        counts = [0] * 9
        for cell in self.votes.values():
            counts[cell - 1] += 1
        return counts

    def tick(self, now: float) -> None:
        if self.phase != "chat" or self.paused or now < self.deadline:
            return
        counts = self.tally()
        if not self.votes:
            self.phase = "no_votes"
            self.message = "No votes received. Reopen chat voting for another 30 seconds."
            return
        best = max(counts)
        leaders = [i for i, count in enumerate(counts) if count == best]
        chosen = self.rng.choice(leaders)
        self.board[chosen] = "O"
        if not self.finish():
            self.phase = "streamer"
            tied = " (random tiebreak)" if len(leaders) > 1 else ""
            self.message = f"Chat chose {chosen + 1} with {best} votes{tied}. Streamer's turn!"

    def finish(self) -> bool:
        for line in LINES:
            value = self.board[line[0]]
            if value and all(self.board[i] == value for i in line):
                self.winner = value
                self.winning_line = line
                break
        else:
            if all(self.board):
                self.winner = "draw"
        if not self.winner:
            return False
        self.phase = "over"
        self.scores[self.winner] += 1
        self.message = {
            "X": "Streamer wins!",
            "O": "Chat wins!",
            "draw": "It's a draw! Rematch?",
        }[self.winner]
        return True

    def pause(self, now: float) -> None:
        if self.phase == "chat" and not self.paused:
            self.remaining = max(0.0, self.deadline - now)
            self.paused = True
            self.message = "Chat voting paused. Votes are preserved."

    def resume(self, now: float, wall: float) -> None:
        if self.phase != "chat" or not self.paused:
            raise ValueError("No paused chat vote to resume.")
        self.deadline = now + self.remaining
        self.accept_after = wall
        self.paused = False
        self.message = "Chat voting resumed."

    def state(self, now: float) -> dict[str, object]:
        seconds = 0
        if self.phase == "chat":
            seconds = ceil(self.remaining if self.paused else max(0.0, self.deadline - now))
        return {
            "board": list(self.board),
            "phase": self.phase,
            "visible": self.visible,
            "paused": self.paused,
            "pending": self.pending,
            "counts": self.tally(),
            "voters": len(self.votes),
            "seconds": seconds,
            "winner": self.winner,
            "winning_line": list(self.winning_line),
            "message": self.message,
            "scores": dict(self.scores),
        }
