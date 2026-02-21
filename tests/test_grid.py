"""Tests for grid, movement, distance, and line-of-sight logic."""

import pytest

from config import SQUARE_SIZE_FT
from engine.grid import (
    create_grid,
    distance,
    get_valid_moves,
    is_adjacent,
    line_of_sight,
    move_character,
)
from models.characters import AbilityScores, Attack, Character
from models.game_state import GameState, GridCell


def _make_character(char_id: str = "c1", position: tuple[int, int] | None = None) -> Character:
    """Helper to create a test character."""
    return Character(
        id=char_id,
        name="Test",
        owner_id="owner1",
        max_hp=20,
        current_hp=20,
        armor_class=15,
        speed=30,
        position=position,
        attacks=[
            Attack(
                name="Sword",
                attack_bonus=5,
                damage_dice="1d8",
                damage_bonus=3,
                damage_type="slashing",
            )
        ],
    )


def _make_game_state(width: int = 10, height: int = 10) -> GameState:
    """Helper to create a test game state."""
    grid = create_grid(width, height)
    return GameState(game_id="test", grid=grid)


class TestCreateGrid:
    """Tests for create_grid()."""

    def test_dimensions(self):
        grid = create_grid(5, 3)
        assert len(grid) == 3      # height (rows)
        assert len(grid[0]) == 5   # width (cols)

    def test_cells_are_open(self):
        grid = create_grid(3, 3)
        for row in grid:
            for cell in row:
                assert cell.terrain == "open"
                assert cell.occupant_id is None

    def test_coordinates_correct(self):
        grid = create_grid(4, 4)
        assert grid[2][3].x == 3
        assert grid[2][3].y == 2


class TestDistance:
    """Tests for distance()."""

    def test_same_position(self):
        assert distance((0, 0), (0, 0)) == 0

    def test_cardinal_distance(self):
        assert distance((0, 0), (3, 0)) == 15  # 3 squares * 5ft
        assert distance((0, 0), (0, 4)) == 20  # 4 squares * 5ft

    def test_diagonal_distance(self):
        """Diagonal uses Chebyshev distance (max of dx, dy)."""
        assert distance((0, 0), (3, 3)) == 15  # max(3,3) * 5 = 15
        assert distance((0, 0), (2, 4)) == 20  # max(2,4) * 5 = 20

    def test_symmetric(self):
        assert distance((1, 2), (4, 6)) == distance((4, 6), (1, 2))


class TestIsAdjacent:
    """Tests for is_adjacent()."""

    def test_same_position_adjacent(self):
        assert is_adjacent((5, 5), (5, 5))

    def test_cardinal_adjacent(self):
        assert is_adjacent((5, 5), (6, 5))
        assert is_adjacent((5, 5), (5, 6))

    def test_diagonal_adjacent(self):
        assert is_adjacent((5, 5), (6, 6))
        assert is_adjacent((5, 5), (4, 4))

    def test_not_adjacent(self):
        assert not is_adjacent((0, 0), (2, 0))
        assert not is_adjacent((0, 0), (0, 2))


class TestGetValidMoves:
    """Tests for get_valid_moves()."""

    def test_center_movement(self):
        """Character in center of open grid can reach many squares."""
        game_state = _make_game_state(10, 10)
        char = _make_character(position=(5, 5))
        moves = get_valid_moves(char, game_state.grid)
        assert len(moves) > 0
        # With speed 30 (6 squares), should reach up to 6 squares away
        assert (5, 0) in moves  # 5 squares up
        assert (5, 5) not in moves  # Current position excluded

    def test_wall_blocks_movement(self):
        """Walls block pathfinding."""
        game_state = _make_game_state(5, 5)
        # Build a wall across row 2
        for x in range(5):
            game_state.grid[2][x].terrain = "wall"
        char = _make_character(position=(2, 0))
        moves = get_valid_moves(char, game_state.grid)
        # Should not be able to reach anything below the wall
        for pos in moves:
            assert pos[1] < 2

    def test_no_position_returns_empty(self):
        """Character with no position gets no valid moves."""
        game_state = _make_game_state()
        char = _make_character(position=None)
        moves = get_valid_moves(char, game_state.grid)
        assert moves == []

    def test_occupied_squares_blocked(self):
        """Can't move through occupied squares."""
        game_state = _make_game_state(5, 5)
        game_state.grid[1][2].occupant_id = "blocker"
        char = _make_character(position=(2, 0))
        moves = get_valid_moves(char, game_state.grid)
        assert (2, 1) not in moves


class TestMoveCharacter:
    """Tests for move_character()."""

    def test_basic_move(self):
        """Move a character to an adjacent square."""
        game_state = _make_game_state(5, 5)
        char = _make_character(char_id="c1", position=(2, 2))
        game_state.characters["c1"] = char
        game_state.grid[2][2].occupant_id = "c1"

        path = move_character("c1", (3, 2), game_state)
        assert char.position == (3, 2)
        assert game_state.grid[2][2].occupant_id is None
        assert game_state.grid[2][3].occupant_id == "c1"
        assert path == [(2, 2), (3, 2)]

    def test_move_to_wall_fails(self):
        """Moving into a wall raises ValueError."""
        game_state = _make_game_state(5, 5)
        game_state.grid[3][3].terrain = "wall"
        char = _make_character(char_id="c1", position=(2, 3))
        game_state.characters["c1"] = char
        game_state.grid[3][2].occupant_id = "c1"

        with pytest.raises(ValueError, match="wall"):
            move_character("c1", (3, 3), game_state)

    def test_move_out_of_bounds_fails(self):
        """Moving out of bounds raises ValueError."""
        game_state = _make_game_state(5, 5)
        char = _make_character(char_id="c1", position=(4, 4))
        game_state.characters["c1"] = char
        game_state.grid[4][4].occupant_id = "c1"

        with pytest.raises(ValueError, match="out of bounds"):
            move_character("c1", (5, 5), game_state)


class TestLineOfSight:
    """Tests for line_of_sight()."""

    def test_clear_los(self):
        """Clear line of sight on open grid."""
        grid = create_grid(10, 10)
        assert line_of_sight((0, 0), (9, 9), grid)

    def test_wall_blocks_los(self):
        """Wall between two points blocks LoS."""
        grid = create_grid(10, 10)
        # Place a wall at (5, 5)
        grid[5][5].terrain = "wall"
        assert not line_of_sight((0, 0), (9, 9), grid)

    def test_adjacent_always_visible(self):
        """Adjacent squares always have LoS."""
        grid = create_grid(5, 5)
        assert line_of_sight((2, 2), (3, 3), grid)

    def test_same_position(self):
        """Same position has LoS."""
        grid = create_grid(5, 5)
        assert line_of_sight((2, 2), (2, 2), grid)
