"""2D grid, movement, distance, and line-of-sight logic for Tendrils Server."""

from __future__ import annotations

from typing import TYPE_CHECKING

from config import SQUARE_SIZE_FT
from models.game_state import GridCell

if TYPE_CHECKING:
    from models.characters import Character
    from models.game_state import GameState


def create_grid(width: int, height: int) -> list[list[GridCell]]:
    """Initialize an empty grid of GridCells.

    Args:
        width: Number of columns.
        height: Number of rows.

    Returns:
        A 2D list indexed as grid[y][x].
    """
    return [
        [GridCell(x=x, y=y) for x in range(width)]
        for y in range(height)
    ]


def distance(pos1: tuple[int, int], pos2: tuple[int, int]) -> int:
    """Calculate distance in feet between two grid positions.

    Uses 5e grid rules where diagonal movement costs 5ft (Chebyshev distance).

    Args:
        pos1: (x, y) of first position.
        pos2: (x, y) of second position.

    Returns:
        Distance in feet.
    """
    dx = abs(pos1[0] - pos2[0])
    dy = abs(pos1[1] - pos2[1])
    return max(dx, dy) * SQUARE_SIZE_FT


def is_adjacent(pos1: tuple[int, int], pos2: tuple[int, int]) -> bool:
    """Check if two positions are adjacent (within 5ft, including diagonals).

    Args:
        pos1: (x, y) of first position.
        pos2: (x, y) of second position.

    Returns:
        True if adjacent.
    """
    return distance(pos1, pos2) <= SQUARE_SIZE_FT


def _in_bounds(x: int, y: int, grid: list[list[GridCell]]) -> bool:
    """Check if coordinates are within grid bounds."""
    if not grid:
        return False
    return 0 <= y < len(grid) and 0 <= x < len(grid[0])


def get_valid_moves(
    character: Character,
    grid: list[list[GridCell]],
    extra_speed: int = 0,
) -> list[tuple[int, int]]:
    """Get all positions a character can move to given their speed.

    Uses BFS to find all reachable positions within movement budget.
    Walls block movement. Difficult terrain costs double. Occupied squares block.

    Args:
        character: The character moving.
        grid: The game grid.
        extra_speed: Additional speed (e.g. from Dash).

    Returns:
        List of (x, y) positions the character can reach.
    """
    if character.position is None:
        return []

    total_speed = character.speed + extra_speed
    max_squares = total_speed // SQUARE_SIZE_FT

    start = character.position
    # BFS with movement cost tracking
    visited: dict[tuple[int, int], int] = {start: 0}
    queue: list[tuple[tuple[int, int], int]] = [(start, 0)]

    while queue:
        (cx, cy), cost = queue.pop(0)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                nx, ny = cx + dx, cy + dy
                if not _in_bounds(nx, ny, grid):
                    continue
                cell = grid[ny][nx]
                if cell.terrain == "wall":
                    continue
                if cell.occupant_id is not None and (nx, ny) != start:
                    continue
                move_cost = 2 if cell.terrain == "difficult" else 1
                new_cost = cost + move_cost
                if new_cost > max_squares:
                    continue
                if (nx, ny) not in visited or visited[(nx, ny)] > new_cost:
                    visited[(nx, ny)] = new_cost
                    queue.append(((nx, ny), new_cost))

    # Remove starting position from valid moves
    valid = [pos for pos in visited if pos != start]
    return valid


def move_character(
    character_id: str,
    target_pos: tuple[int, int],
    game_state: GameState,
) -> list[tuple[int, int]]:
    """Move a character to a target position on the grid.

    Validates that the target is reachable, updates grid occupancy and
    character position.

    Args:
        character_id: ID of the character to move.
        target_pos: Destination (x, y).
        game_state: Current game state (mutated in place).

    Returns:
        The movement path taken (start to end).

    Raises:
        ValueError: If the move is invalid.
    """
    character = game_state.characters[character_id]
    if character.position is None:
        raise ValueError("Character has no position on the grid")

    start = character.position
    tx, ty = target_pos

    if not _in_bounds(tx, ty, game_state.grid):
        raise ValueError(f"Target position ({tx}, {ty}) is out of bounds")

    target_cell = game_state.grid[ty][tx]
    if target_cell.terrain == "wall":
        raise ValueError("Cannot move into a wall")
    if target_cell.occupant_id is not None:
        raise ValueError("Target square is occupied")

    # Check movement budget — use remaining speed if tracked, else full speed
    remaining = getattr(character, "_remaining_movement", character.speed)
    dist = distance(start, target_pos)
    if dist > remaining:
        raise ValueError(
            f"Not enough movement: need {dist}ft, have {remaining}ft remaining"
        )

    # Update grid
    sx, sy = start
    game_state.grid[sy][sx].occupant_id = None
    game_state.grid[ty][tx].occupant_id = character_id

    # Update character
    character.position = target_pos

    path = [start, target_pos]
    return path


def line_of_sight(
    pos1: tuple[int, int],
    pos2: tuple[int, int],
    grid: list[list[GridCell]],
) -> bool:
    """Check if pos1 can see pos2 (simple: blocked only by walls).

    Uses Bresenham's line algorithm to trace between positions.

    Args:
        pos1: (x, y) of observer.
        pos2: (x, y) of target.
        grid: The game grid.

    Returns:
        True if line of sight is clear.
    """
    x0, y0 = pos1
    x1, y1 = pos2

    dx = abs(x1 - x0)
    dy = abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy

    while True:
        if (x0, y0) != pos1 and (x0, y0) != pos2:
            if _in_bounds(x0, y0, grid) and grid[y0][x0].terrain == "wall":
                return False
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x0 += sx
        if e2 < dx:
            err += dx
            y0 += sy

    return True
