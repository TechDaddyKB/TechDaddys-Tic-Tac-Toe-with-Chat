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


DEFAULT_CONCEDE_PHRASES = ("concede", "give up", "rigged")


def validate_concede_phrases(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > 50:
        raise ValueError("Use up to 50 concede phrases, one per line.")
    phrases: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError("Concede phrases must be text.")
        phrase = " ".join(item.split()).casefold()
        if not phrase:
            continue
        if len(phrase) > 80 or phrase.isdecimal():
            raise ValueError("Each phrase must be 1–80 characters and cannot be just a number.")
        if phrase not in phrases:
            phrases.append(phrase)
    return tuple(phrases)


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
    concede_phrases: tuple[str, ...] = DEFAULT_CONCEDE_PHRASES
    active_concede_phrases: tuple[str, ...] = DEFAULT_CONCEDE_PHRASES
    conceded_by: str = ""
    vote_seconds: int = 30
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
        self.conceded_by = ""
        self.winning_line = ()
        self.remaining = float(self.vote_seconds)
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
        self.active_concede_phrases = self.concede_phrases
        self.deadline = now + self.vote_seconds
        self.accept_after = wall
        self.remaining = float(self.vote_seconds)
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
        text = " ".join(text.split()).casefold()
        if not user:
            return False
        if text in self.active_concede_phrases:
            cell = 0  # All concession phrases vote for the same choice.
        elif re.fullmatch(r"[1-9]", text) is not None:
            cell = int(text)
            if self.board[cell - 1]:
                return False
        else:
            return False
        if len(self.votes) >= 100_000 and user not in self.votes:
            return False
        self.votes[user] = cell
        return True

    def concession_votes(self) -> int:
        return sum(cell == 0 for cell in self.votes.values())

    def concede(self, side: str) -> None:
        if side not in ("X", "O") or self.phase != ("streamer" if side == "X" else "chat"):
            raise ValueError("You can only concede during your own turn.")
        self.conceded_by = side
        self.winner = "O" if side == "X" else "X"
        self.phase = "over"
        self.pending = None
        self.paused = False
        self.scores[self.winner] += 1
        self.message = (
            "Streamer conceded. Chat wins!" if side == "X" else "Chat conceded. Streamer wins!"
        )

    def begin_streamer_turn(self, message: str) -> None:
        self.phase = "streamer"
        self.message = message
        empty = [i for i, mark in enumerate(self.board) if not mark]
        if len(empty) == 1:
            self.board[empty[0]] = "X"
            self.pending = None
            self.finish()
            self.message = (
                f"Streamer’s last square ({empty[0] + 1}) filled automatically. " + self.message
            )

    def tally(self) -> list[int]:
        counts = [0] * 9
        for cell in self.votes.values():
            if cell:
                counts[cell - 1] += 1
        return counts

    def tick(self, now: float) -> None:
        if self.phase != "chat" or self.paused or now < self.deadline:
            return
        counts = self.tally()
        if not self.votes:
            self.phase = "no_votes"
            self.message = "No votes received. Reopen chat voting to try again."
            return
        counts.append(self.concession_votes())
        best = max(counts)
        leaders = [i for i, count in enumerate(counts) if count == best]
        chosen = self.rng.choice(leaders)
        if chosen == 9:
            self.concede("O")
            return
        self.board[chosen] = "O"
        if not self.finish():
            tied = " (random tiebreak)" if len(leaders) > 1 else ""
            self.begin_streamer_turn(
                f"Chat chose {chosen + 1} with {best} votes{tied}. Streamer's turn!"
            )

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
            "conceded_by": self.conceded_by,
            "concession_votes": self.concession_votes(),
            "winning_line": list(self.winning_line),
            "message": self.message,
            "scores": dict(self.scores),
        }
