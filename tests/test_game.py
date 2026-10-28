import pytest

from vtuber_tictactoe.game import LINES, Game


def chat_game() -> Game:
    game = Game()
    game.start("chat", 100, 1000)
    return game


def test_latest_valid_vote_per_user_and_deadline() -> None:
    game = chat_game()
    assert game.vote("a", "1", 101, 1001)
    assert game.vote("a", " 2 ", 102, 1002)
    assert game.vote("b", "2", 103, 1003)
    assert not game.vote("a", "3", 130, 1030)
    assert game.tally() == [0, 2, 0, 0, 0, 0, 0, 0, 0]
    game.tick(129.999)
    assert not any(game.board)
    game.tick(130)
    assert game.board[1] == "O" and game.phase == "streamer"


@pytest.mark.parametrize("text", ["0", "10", "!vote 5", "I vote 5", "1 2", "５", "", "-1", "2.0"])
def test_only_single_ascii_digits_count(text: str) -> None:
    assert not chat_game().vote("viewer", text, 101)


def test_reject_old_messages_and_occupied_cells() -> None:
    game = chat_game()
    game.board[3] = "X"
    assert not game.vote("a", "4", 101)
    assert not game.vote("a", "5", 101, 999.999)
    assert not game.vote("", "5", 101)
    assert game.vote("a", "5", 101, 1000)


def test_pause_preserves_votes_and_remaining_time() -> None:
    game = chat_game()
    game.vote("a", "5", 105)
    game.pause(110)
    assert game.state(1000)["seconds"] == 20
    game.pause(300)
    game.tick(1000)
    assert game.phase == "chat" and not any(game.board)
    assert not game.vote("b", "2", 1000)
    game.resume(1000, 2000)
    assert game.deadline == 1020
    assert not game.vote("b", "2", 1001, 1999)
    game.tick(1020)
    assert game.board[4] == "O"
    with pytest.raises(ValueError, match="No paused"):
        game.resume(1021, 2021)


def test_no_votes_requires_a_retry_and_does_not_place_a_mark() -> None:
    game = chat_game()
    game.tick(130)
    assert game.phase == "no_votes" and game.board == [""] * 9
    game.tick(160)
    assert game.phase == "no_votes"
    game.start_vote(200, 2000)
    assert game.state(200)["seconds"] == 30
    assert game.votes == {}


def test_tied_vote_selects_one_of_the_leaders() -> None:
    game = chat_game()
    game.vote("a", "2", 101)
    game.vote("b", "9", 101)
    game.tick(130)
    assert game.board.count("O") == 1
    assert game.board[1] == "O" or game.board[8] == "O"
    assert "tiebreak" in game.message


def test_select_confirm_and_prevent_duplicate_moves() -> None:
    game = Game()
    game.start("streamer", 0, 0)
    with pytest.raises(ValueError, match="Select an empty"):
        game.confirm(1, 1)
    for cell in (0, 10):
        with pytest.raises(ValueError, match="empty square"):
            game.select(cell)
    game.select(1)
    game.select(5)
    assert not any(game.board)
    game.confirm(1, 1)
    assert game.board[4] == "X" and game.pending is None
    assert game.phase == "chat" and game.deadline == 31
    with pytest.raises(ValueError, match="Wait"):
        game.select(2)
    with pytest.raises(ValueError, match="Reset"):
        game.start("chat", 3, 3)


@pytest.mark.parametrize("line", LINES)
@pytest.mark.parametrize("mark", ["X", "O"])
def test_every_winning_line(line: tuple[int, ...], mark: str) -> None:
    game = Game()
    for cell in line:
        game.board[cell] = mark
    assert game.finish()
    assert game.phase == "over" and game.winner == mark
    assert game.winning_line == line and game.scores[mark] == 1


def test_draw_reset_visibility_and_score_retention() -> None:
    game = Game(board=list("XOXXOOOXX"), visible=False)
    assert game.finish() and game.winner == "draw"
    game.reset()
    assert game.scores == {"X": 0, "O": 0, "draw": 1}
    assert game.visible is False and game.phase == "ready"


def test_streamer_winning_move_does_not_open_vote() -> None:
    game = Game(board=["X", "X", "", "O", "O", "", "", "", ""], phase="streamer")
    game.select(3)
    game.confirm(0, 0)
    assert game.winner == "X" and game.phase == "over"


def test_chat_winning_move_does_not_return_to_streamer() -> None:
    game = chat_game()
    game.board = ["O", "O", "", "X", "X", "", "", "", ""]
    game.vote("a", "3", 101)
    game.tick(130)
    assert game.winner == "O" and game.scores["O"] == 1


def test_random_first_player_and_invalid_input() -> None:
    phases = set()
    for _ in range(50):
        game = Game()
        game.start("random", 0, 0)
        phases.add(game.phase)
    assert phases <= {"streamer", "chat"}
    with pytest.raises(ValueError, match="Choose"):
        Game().start("unknown", 0, 0)


def test_snapshot_does_not_mutate_game() -> None:
    game = chat_game()
    state = game.state(101)
    assert state["seconds"] == 29
    board = state["board"]
    assert isinstance(board, list)
    board[0] = "X"
    assert game.board[0] == ""


def test_full_game_rejects_occupied_move_and_non_chat_votes() -> None:
    game = Game()
    game.start("streamer", 0, 0)
    assert not game.vote("v", "1", 0)
    game.board[0] = "O"
    with pytest.raises(ValueError, match="empty"):
        game.select(1)


def test_voter_limit_allows_existing_viewer_updates() -> None:
    game = chat_game()
    game.votes = {str(i): 1 for i in range(100_000)}
    assert not game.vote("new", "2", 101)
    assert game.vote("0", "2", 101)
